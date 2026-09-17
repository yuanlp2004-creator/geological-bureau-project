from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import threading
import uuid
from contextlib import contextmanager
from enum import Enum
from typing import Any

from ..db import Database, utc_now
from .devices import AcqSimulatorAdapter, DeviceError


class HardwareTaskState(str, Enum):
    DRAFT = "draft"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    PRE_EXCITATION = "pre_excitation"
    TURNING = "turning"
    COLLECTING = "collecting"
    ANOMALY = "anomaly"
    MANUAL_INTERVENTION = "manual_intervention"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    SAFETY_STOPPED = "safety_stopped"
    DEFERRED_EXTERNAL = "deferred_external"


class HardwareError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = 422,
        deferred_external: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        self.deferred_external = deferred_external

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


_STRATEGIES = {"short_to_long", "key_first"}
_POLICIES = {"retry_then_stop", "manual"}
_ANOMALIES = {"baseline_low", "baseline_high", "baseline_shift", "peak_shift", "frame_fault", "turn_timeout"}
_DECISION_STATES = {"draft", "connected", "pre_excitation", "turning", "collecting", "anomaly", "manual_intervention", "paused"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _finite(value: Any, field: str, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise HardwareError("hardware_value_invalid", f"{field} must be numeric", details={"field": field}) from exc
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise HardwareError("hardware_value_invalid", f"{field} is outside the supported range", details={"field": field, "minimum": minimum, "maximum": maximum})
    return result


def _pack_points(points: list[int]) -> bytes:
    if any(int(point) < 0 or int(point) > 65535 for point in points):
        raise HardwareError("hardware_points_invalid", "CCD points must fit uint16")
    return struct.pack(f"<{len(points)}H", *[int(point) for point in points])


def _unpack_points(blob: bytes | None, count: int) -> list[int]:
    if blob is None:
        return []
    if len(blob) != count * 2:
        raise HardwareError("hardware_frame_invalid", "CCD frame payload length is inconsistent", details={"expected": count * 2, "actual": len(blob)})
    return list(struct.unpack(f"<{count}H", blob))


class SimulatorTurnAdapter:
    """Turn adapter backed only by the S11 deterministic simulator."""

    def __init__(self) -> None:
        self.acquisition = AcqSimulatorAdapter()
        self.session_id: str | None = None
        self.profile: dict[str, Any] | None = None

    def connect(self, profile: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        try:
            event = self.acquisition.connect(profile, correlation_id=correlation_id)
        except DeviceError as exc:
            raise HardwareError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        self.profile = dict(profile)
        return event.to_dict()

    def pre_excitation(self, *, sample: str, seed: int, correlation_id: str) -> dict[str, Any]:
        try:
            event = self.acquisition.start_debug(sample=sample, seed=seed, fault_frame=None, correlation_id=correlation_id)
        except DeviceError as exc:
            raise HardwareError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        self.session_id = self.acquisition.session_id
        return event.to_dict()

    def turn(self, *, angle_deg: float, correlation_id: str) -> dict[str, Any]:
        if self.acquisition.state.value != "debugging":
            raise HardwareError("hardware_session_not_running", "simulator session is not active", status_code=409)
        return {"event_type": "turn_complete", "angle_deg": angle_deg, "correlation_id": correlation_id, "simulated": True}

    def capture(self, *, correlation_id: str) -> dict[str, Any]:
        try:
            event = self.acquisition.step_debug(correlation_id=correlation_id)
        except DeviceError as exc:
            raise HardwareError(exc.code, exc.message, details=exc.detail(), status_code=exc.status_code) from exc
        return event.to_dict()

    def close(self, correlation_id: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            events.append(self.acquisition.stop_debug(correlation_id=correlation_id).to_dict())
            events.append(self.acquisition.disconnect(correlation_id=correlation_id).to_dict())
        except DeviceError as exc:
            events.append({"event_type": "close_error", "code": exc.code, "message": exc.message})
        self.session_id = None
        return events


class SerialTurnAdapter:
    """Explicit protocol gate. No guessed command bytes are ever emitted."""

    def connect(self, profile: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        raise HardwareError(
            "hardware_protocol_unavailable",
            "real serial/turn protocol documentation or capture is not available",
            details={"transport": "serial", "port": profile.get("port"), "baud_rate": profile.get("baud_rate"), "correlation_id": correlation_id},
            status_code=409,
            deferred_external=True,
        )

    def close(self, correlation_id: str) -> list[dict[str, Any]]:
        return [{"event_type": "serial_close_skipped", "correlation_id": correlation_id, "reason": "protocol_unavailable"}]


class HardwareAcquisitionService:
    """S14 automatic turn plan and anomaly-control application service."""

    def __init__(self, database: Database):
        self.database = database
        self._adapters: dict[int, SimulatorTurnAdapter | SerialTurnAdapter] = {}
        self._task_locks: dict[int, threading.Lock] = {}
        self._task_locks_guard = threading.Lock()

    @contextmanager
    def _control_scope(self, task_id: int):
        with self._task_locks_guard:
            lock = self._task_locks.setdefault(task_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise HardwareError("hardware_task_busy", "another hardware control operation is in progress", details={"task_id": task_id}, status_code=409)
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def _layout_indices(row: sqlite3.Row | dict[str, Any]) -> list[int]:
        return [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]

    def _context(self, task_id: int, db: sqlite3.Connection | None = None) -> tuple[sqlite3.Row, sqlite3.Row, dict[str, Any]]:
        if db is None:
            with self.database.read() as connection:
                return self._context(task_id, connection)
        task = db.execute("SELECT * FROM hardware_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise HardwareError("hardware_task_not_found", "hardware acquisition task was not found", details={"task_id": task_id}, status_code=404)
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()
        profile_row = db.execute("SELECT * FROM device_profiles WHERE id=?", (task["device_profile_id"],)).fetchone()
        if layout is None or profile_row is None:
            raise HardwareError("hardware_configuration_missing", "hardware task references missing device or CCD layout", status_code=409)
        profile = dict(profile_row)
        profile["ccd_indices"] = json.loads(profile.pop("ccd_indices_json") or "[]")
        profile["mirror"] = bool(profile.get("mirror"))
        profile["enabled"] = bool(profile.get("enabled", True))
        return task, layout, profile

    @staticmethod
    def _decode_json_field(result: dict[str, Any], field: str, default: Any) -> None:
        raw = result.pop(field, None)
        result[field.removesuffix("_json")] = json.loads(raw) if raw else default

    def _task_dict(self, task_id: int, db: sqlite3.Connection | None = None, *, include_points: bool = False) -> dict[str, Any]:
        if db is None:
            with self.database.read() as connection:
                return self._task_dict(task_id, connection, include_points=include_points)
        task, layout, profile = self._context(task_id, db)
        result = dict(task)
        for field, default in (("ccd_indices_json", []), ("plan_json", []), ("thresholds_json", {}), ("simulator_json", {}), ("last_event_json", None)):
            self._decode_json_field(result, field, default)
        result["transport"] = str(result["transport"])
        result["profile"] = {"id": profile["id"], "name": profile["name"], "transport": profile["transport"], "port": profile["port"], "baud_rate": profile["baud_rate"], "mirror": profile["mirror"]}
        result["layout"] = {"id": layout["id"], "name": layout["name"], "points_per_ccd": layout["points_per_ccd"], "ccd_indices": self._layout_indices(layout)}
        result["progress"] = round(min(100.0, float(result["completed_steps"]) / max(1, int(result["total_steps"])) * 100), 2)
        result["steps"] = []
        for row in db.execute("SELECT * FROM hardware_plan_steps WHERE task_id=? ORDER BY order_index", (task_id,)).fetchall():
            result["steps"].append(dict(row) | {"key_band": bool(row["key_band"])})
        result["traces"] = []
        for row in db.execute("SELECT * FROM hardware_traces WHERE task_id=? ORDER BY sequence_no DESC LIMIT 60", (task_id,)).fetchall():
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item.pop("raw_payload", None)
            result["traces"].append(item)
        result["traces"].reverse()
        result["decisions"] = [dict(row) | {"observed": json.loads(row["observed_json"] or "{}"), "threshold": json.loads(row["threshold_json"] or "{}")} for row in db.execute("SELECT * FROM hardware_decisions WHERE task_id=? ORDER BY id", (task_id,)).fetchall()]
        result["messages"] = [dict(row) | {"details": json.loads(row["details_json"] or "{}")} for row in db.execute("SELECT * FROM hardware_messages WHERE task_id=? ORDER BY id DESC LIMIT 60", (task_id,)).fetchall()][::-1]
        frames = []
        for row in db.execute("SELECT * FROM hardware_frames WHERE task_id=? ORDER BY step_id, attempt, ccd_index", (task_id,)).fetchall():
            item = dict(row)
            if include_points and row["points_blob"] is not None:
                item["points"] = _unpack_points(row["points_blob"], int(row["points_count"]))
            item.pop("points_blob", None)
            item["damaged"] = bool(item["damaged"])
            item["confirmed"] = bool(item["confirmed"])
            frames.append(item)
        result["frames"] = frames
        result["latest_trace"] = result["traces"][-1] if result["traces"] else None
        result["latest_decision"] = result["decisions"][-1] if result["decisions"] else None
        return result

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM hardware_tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]
        return [self._task_dict(task_id) for task_id in ids]

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            profiles = []
            for row in db.execute("SELECT id, name, transport, port, baud_rate, ccd_indices_json, points_per_ccd FROM device_profiles WHERE enabled=1 ORDER BY id").fetchall():
                profiles.append({"id": row["id"], "name": row["name"], "transport": row["transport"], "port": row["port"], "baud_rate": row["baud_rate"], "ccd_indices": json.loads(row["ccd_indices_json"] or "[]"), "points_per_ccd": row["points_per_ccd"]})
            layouts = [dict(row) | {"ccd_indices": self._layout_indices(row)} for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall()]
        return {"states": [state.value for state in HardwareTaskState], "strategies": sorted(_STRATEGIES), "anomaly_policies": sorted(_POLICIES), "anomaly_kinds": sorted(_ANOMALIES), "profiles": profiles, "layouts": layouts}

    @staticmethod
    def _normalize_plan(turns: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
        if strategy not in _STRATEGIES:
            raise HardwareError("turn_strategy_invalid", "turn strategy is not supported", details={"strategy": strategy})
        normalized: list[dict[str, Any]] = []
        wavelengths: list[float] = []
        angles: list[float] = []
        for source_index, raw in enumerate(turns):
            wavelength = _finite(raw.get("wavelength_nm"), "wavelength_nm", 160, 800)
            angle = _finite(raw.get("angle_deg"), "angle_deg", -360, 360)
            priority = int(raw.get("priority", 0))
            if not 0 <= priority <= 100:
                raise HardwareError("turn_priority_invalid", "turn priority must be between 0 and 100", details={"source_index": source_index})
            if any(abs(wavelength - existing) <= 0.01 for existing in wavelengths):
                raise HardwareError("turn_duplicate_wavelength", "duplicate wavelength bands are not allowed", details={"wavelength_nm": wavelength, "source_index": source_index}, status_code=409)
            if any(abs(angle - existing) <= 0.001 for existing in angles):
                raise HardwareError("turn_duplicate_angle", "duplicate turn angles are not allowed", details={"angle_deg": angle, "source_index": source_index}, status_code=409)
            wavelengths.append(wavelength)
            angles.append(angle)
            normalized.append({"source_index": source_index, "angle_deg": angle, "wavelength_nm": wavelength, "priority": priority, "key_band": bool(raw.get("key_band", False)), "expected_peak_position": _finite(raw.get("expected_peak_position", 1024), "expected_peak_position", 0, 4096)})
        if strategy == "key_first":
            normalized.sort(key=lambda item: (not item["key_band"], -item["priority"], item["wavelength_nm"], item["angle_deg"], item["source_index"]))
        else:
            normalized.sort(key=lambda item: (item["wavelength_nm"], item["angle_deg"], -item["priority"], item["source_index"]))
        for order_index, item in enumerate(normalized):
            item["order_index"] = order_index
        return normalized

    @staticmethod
    def _thresholds(payload: dict[str, Any]) -> dict[str, float]:
        defaults = {"baseline_min": 1.0, "baseline_max": 65535.0, "baseline_position_tolerance": 25.0, "peak_position_tolerance": 25.0}
        for key, value in (payload.get("thresholds") or {}).items():
            if key not in defaults:
                raise HardwareError("threshold_invalid", "unknown hardware anomaly threshold", details={"field": key})
            defaults[key] = _finite(value, key, 0 if key.endswith("tolerance") else 0, 65535)
        if defaults["baseline_min"] > defaults["baseline_max"]:
            raise HardwareError("threshold_invalid", "baseline_min must not exceed baseline_max")
        return defaults

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        strategy = str(payload.get("strategy", "short_to_long"))
        policy = str(payload.get("anomaly_policy", "retry_then_stop"))
        if policy not in _POLICIES:
            raise HardwareError("anomaly_policy_invalid", "anomaly policy is not supported", details={"policy": policy})
        plan = self._normalize_plan(list(payload.get("turns") or []), strategy)
        thresholds = self._thresholds(payload)
        retry_limit = int(payload.get("retry_limit", 1))
        if not 0 <= retry_limit <= 5:
            raise HardwareError("retry_limit_invalid", "retry limit must be between 0 and 5")
        with self.database.write() as db:
            profile_id = int(payload.get("device_profile_id", 1))
            profile = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
            if profile is None:
                raise HardwareError("device_profile_not_found", "device profile was not found", status_code=404)
            layout_key = payload.get("ccd_layout_id", "default")
            layout = db.execute("SELECT * FROM ccd_layouts WHERE id=? OR name=?", (layout_key if str(layout_key).isdigit() else -1, str(layout_key))).fetchone()
            if layout is None:
                raise HardwareError("ccd_layout_not_found", "CCD layout was not found", status_code=404)
            allowed = self._layout_indices(layout)
            selected = [int(value) for value in (payload.get("ccd_indices") or allowed)]
            if not selected or len(selected) != len(set(selected)) or any(value not in allowed for value in selected):
                raise HardwareError("ccd_indices_invalid", "selected CCDs must be a subset of the layout", details={"allowed": allowed})
            if int(profile["points_per_ccd"]) != int(layout["points_per_ccd"]):
                raise HardwareError("ccd_layout_profile_mismatch", "device profile and CCD layout point counts differ", status_code=409)
            method_id = payload.get("method_id")
            method_version = payload.get("method_version")
            if method_id is not None:
                query = "SELECT version FROM method_versions WHERE method_id=? AND state='published'"
                args: list[Any] = [int(method_id)]
                if method_version is not None:
                    query += " AND version=?"
                    args.append(int(method_version))
                query += " ORDER BY version DESC LIMIT 1"
                method_row = db.execute(query, args).fetchone()
                if method_row is None:
                    raise HardwareError("method_revision_not_found", "published method revision was not found", status_code=404)
                method_version = int(method_row["version"])
            pre_seconds = _finite(payload.get("pre_excitation_seconds", 1), "pre_excitation_seconds", 0, 600)
            period = _finite(payload.get("sampling_period_seconds", 1), "sampling_period_seconds", 0.001, 60)
            simulator = {"sample": str(payload.get("simulator_sample", "280-288.acq")), "seed": int(payload.get("seed", 0)), "anomalies": list(payload.get("simulator_anomalies") or [])}
            for item in simulator["anomalies"]:
                step_index = int(item.get("step_index", -1))
                kind = str(item.get("kind", ""))
                count = int(item.get("count", 1))
                if not 0 <= step_index < len(plan) or kind not in _ANOMALIES or not 1 <= count <= 20:
                    raise HardwareError("simulator_anomaly_invalid", "simulator anomaly script is invalid", details={"item": item})
            now = utc_now()
            cursor = db.execute(
                "INSERT INTO hardware_tasks(name, status, device_profile_id, ccd_layout_id, transport, strategy, anomaly_policy, sample_name, method_id, method_version, retry_limit, pre_excitation_seconds, sampling_period_seconds, ccd_indices_json, plan_json, thresholds_json, simulator_json, total_steps, created_by, created_at, updated_at) VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(payload.get("name", "S14 真实设备与自动转角")).strip(), profile["id"], layout["id"], profile["transport"], strategy, policy, str(payload.get("sample_name", "")).strip(), method_id, method_version, retry_limit, pre_seconds, period, _json(selected), _json(plan), _json(thresholds), _json(simulator), len(plan), actor_user_id, now, now),
            )
            task_id = int(cursor.lastrowid)
            for item in plan:
                db.execute("INSERT INTO hardware_plan_steps(task_id, order_index, source_index, angle_deg, wavelength_nm, priority, key_band, expected_peak_position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_id, item["order_index"], item["source_index"], item["angle_deg"], item["wavelength_nm"], item["priority"], int(item["key_band"]), item["expected_peak_position"], now, now))
            self._message(db, task_id, "info", "task.created", "hardware turn task created", {"strategy": strategy, "total_steps": len(plan), "transport": profile["transport"]})
            self._audit(db, actor_user_id, "hardware.task.create", task_id, {"strategy": strategy, "total_steps": len(plan), "transport": profile["transport"]})
        return self._task_dict(task_id)

    def _adapter(self, task_id: int, profile: dict[str, Any]) -> SimulatorTurnAdapter | SerialTurnAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = SimulatorTurnAdapter() if profile["transport"] == "simulator" else SerialTurnAdapter()
            self._adapters[task_id] = adapter
        return adapter

    def _trace(self, db: sqlite3.Connection, task_id: int, direction: str, kind: str, name: str, payload: dict[str, Any], correlation_id: str, safe_state: str, raw_payload: bytes | None = None) -> None:
        sequence = int(db.execute("SELECT COALESCE(MAX(sequence_no), -1) + 1 FROM hardware_traces WHERE task_id=?", (task_id,)).fetchone()[0])
        payload_json = _json(payload)
        db.execute("INSERT INTO hardware_traces(task_id, sequence_no, direction, kind, name, payload_json, payload_sha256, raw_payload, correlation_id, safe_state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_id, sequence, direction, kind, name, payload_json, _sha(payload_json), raw_payload, correlation_id, safe_state, utc_now()))

    @staticmethod
    def _message(db: sqlite3.Connection, task_id: int, level: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO hardware_messages(task_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (task_id, level, code, message, _json(details or {}), utc_now()))

    @staticmethod
    def _audit(db: sqlite3.Connection, actor_user_id: int | None, action: str, target_id: int, details: dict[str, Any]) -> None:
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'hardware', ?, ?, ?)", (actor_user_id, action, target_id, _json(details), utc_now()))

    def _start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self._context(task_id)
        if task["status"] != HardwareTaskState.DRAFT.value:
            if task["status"] in _DECISION_STATES:
                return self._task_dict(task_id)
            raise HardwareError("hardware_task_not_startable", "hardware task is not startable", details={"status": task["status"]}, status_code=409)
        correlation_id = f"hardware-{task_id}-{uuid.uuid4().hex[:10]}"
        adapter = self._adapter(task_id, profile)
        if profile["transport"] == "serial":
            with self.database.write() as db:
                self._trace(db, task_id, "internal", "event", "protocol.deferred", {"reason": "missing_serial_turn_protocol", "transport": "serial"}, correlation_id, HardwareTaskState.DEFERRED_EXTERNAL.value)
                db.execute("UPDATE hardware_tasks SET status='deferred_external', failure_code=?, failure_message=?, completed_at=?, last_message=?, updated_at=? WHERE id=?", ("hardware_protocol_unavailable", "real serial/turn protocol documentation or capture is not available", utc_now(), "真实串口协议缺失，任务延期", utc_now(), task_id))
                self._message(db, task_id, "warning", "task.deferred_external", "real serial/turn protocol is unavailable; no command bytes were sent", {"correlation_id": correlation_id})
                self._audit(db, actor_user_id, "hardware.task.deferred", task_id, {"reason": "missing_serial_turn_protocol", "correlation_id": correlation_id})
            self._adapters.pop(task_id, None)
            return self._task_dict(task_id)
        try:
            connected = adapter.connect(profile, correlation_id)
            pre_event = adapter.pre_excitation(sample=json.loads(task["simulator_json"] or "{}").get("sample", "280-288.acq"), seed=int(json.loads(task["simulator_json"] or "{}").get("seed", 0)), correlation_id=correlation_id)
        except HardwareError as exc:
            with self.database.write() as db:
                self._trace(db, task_id, "internal", "safety", "startup.failed", {"code": exc.code, "message": exc.message, "commands_sent": False}, correlation_id, HardwareTaskState.FAILED.value)
                db.execute("UPDATE hardware_tasks SET status='failed', failure_code=?, failure_message=?, completed_at=?, last_message=?, updated_at=? WHERE id=?", (exc.code, exc.message, utc_now(), exc.message, utc_now(), task_id))
                self._message(db, task_id, "error", "task.failed", exc.message, {"code": exc.code, "correlation_id": correlation_id})
                self._audit(db, actor_user_id, "hardware.task.safety_stop", task_id, {"reason": exc.message, "code": exc.code, "correlation_id": correlation_id})
            adapter.close(correlation_id=f"hardware-close-{task_id}-{uuid.uuid4().hex[:8]}")
            self._adapters.pop(task_id, None)
            raise
        with self.database.write() as db:
            db.execute("UPDATE hardware_tasks SET status='pre_excitation', adapter_session_id=?, last_event_json=?, started_at=?, last_message=?, updated_at=? WHERE id=?", (adapter.session_id if isinstance(adapter, SimulatorTurnAdapter) else None, _json(pre_event), utc_now(), "hardware connected; pre-excitation started", utc_now(), task_id))
            self._trace(db, task_id, "inbound", "connection", "connected", connected, correlation_id, HardwareTaskState.PRE_EXCITATION.value)
            self._trace(db, task_id, "internal", "event", "pre_excitation.started", pre_event, correlation_id, HardwareTaskState.PRE_EXCITATION.value)
            self._message(db, task_id, "info", "task.start", "hardware task started", {"state": "pre_excitation"})
            self._audit(db, actor_user_id, "hardware.task.start", task_id, {"state": "pre_excitation", "correlation_id": correlation_id})
        return self._task_dict(task_id)

    def _current_step(self, db: sqlite3.Connection, task: sqlite3.Row) -> sqlite3.Row:
        row = db.execute("SELECT * FROM hardware_plan_steps WHERE task_id=? AND order_index=?", (task["id"], task["current_step_index"])).fetchone()
        if row is None:
            raise HardwareError("hardware_plan_step_missing", "current turn plan step is missing", status_code=409)
        return row

    def _simulated_anomalies(self, task: sqlite3.Row, step: sqlite3.Row, attempt: int) -> list[str]:
        config = json.loads(task["simulator_json"] or "{}")
        result: list[str] = []
        for item in config.get("anomalies", []):
            if int(item.get("step_index", -1)) == int(step["order_index"]) and attempt < int(item.get("count", 1)):
                result.append(str(item["kind"]))
        return sorted(set(result))

    def _metrics(self, task: sqlite3.Row, step: sqlite3.Row, ccd: dict[str, Any] | None, anomalies: list[str]) -> tuple[list[int], dict[str, Any], bool]:
        points = [int(value) for value in (ccd or {}).get("points", [])]
        thresholds = json.loads(task["thresholds_json"] or "{}")
        expected = float(step["expected_peak_position"])
        raw_peak = max(points) if points else None
        baseline_intensity = float(raw_peak or 0)
        baseline_position = expected
        peak_position = expected
        damaged = ccd is None or not points or bool(set(anomalies).intersection({"frame_fault", "turn_timeout"}))
        if "baseline_low" in anomalies:
            baseline_intensity = float(thresholds["baseline_min"]) - 1
        if "baseline_high" in anomalies:
            baseline_intensity = float(thresholds["baseline_max"]) + 1
        if "baseline_shift" in anomalies:
            baseline_position = expected + float(thresholds["baseline_position_tolerance"]) * 2
        if "peak_shift" in anomalies:
            peak_position = expected + float(thresholds["peak_position_tolerance"]) * 2
        observed = {"baseline_intensity": baseline_intensity, "baseline_position": baseline_position, "expected_peak_position": expected, "peak_position": peak_position, "raw_peak_value": raw_peak, "anomaly_script": anomalies}
        detected: list[str] = []
        if damaged:
            detected.append("frame_fault" if "frame_fault" in anomalies or "turn_timeout" not in anomalies else "turn_timeout")
        if baseline_intensity < float(thresholds["baseline_min"]):
            detected.append("baseline_low")
        if baseline_intensity > float(thresholds["baseline_max"]):
            detected.append("baseline_high")
        if abs(baseline_position - expected) > float(thresholds["baseline_position_tolerance"]):
            detected.append("baseline_shift")
        if abs(peak_position - expected) > float(thresholds["peak_position_tolerance"]):
            detected.append("peak_shift")
        return points, observed, bool(detected)

    def _store_frames(self, db: sqlite3.Connection, task: sqlite3.Row, step: sqlite3.Row, attempt: int, event: dict[str, Any], anomalies: list[str], confirmed: bool) -> tuple[list[dict[str, Any]], str | None]:
        selected = [int(value) for value in json.loads(task["ccd_indices_json"] or "[]")]
        by_ccd = {int(item["ccd_index"]): item for item in event.get("ccds", [])}
        details = event.get("details") or {}
        observed_rows: list[dict[str, Any]] = []
        first_sha: str | None = None
        for ccd_index in selected:
            points, observed, detected = self._metrics(task, step, by_ccd.get(ccd_index), anomalies)
            physical_damage = bool(detected and set(anomalies).intersection({"frame_fault", "turn_timeout"}))
            blob = None if observed["raw_peak_value"] is None or physical_damage else _pack_points(points)
            points_sha = _sha(blob) if blob is not None else None
            if first_sha is None:
                first_sha = points_sha
            anomaly_kind = ",".join(sorted(set(anomalies))) if detected else None
            db.execute("INSERT INTO hardware_frames(task_id, step_id, attempt, ccd_index, points_blob, points_count, points_sha256, raw_transfer_sha256, raw_byte_length, headers_json, baseline_intensity, baseline_position, expected_peak_position, peak_position, peak_value, virtual_time_ms, damaged, confirmed, anomaly_kind, damage_code, damage_message, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task["id"], step["id"], attempt, ccd_index, blob, len(points), points_sha, details.get("sha256"), int(details.get("byte_length", 0)), _json(details.get("headers", [])), observed["baseline_intensity"], observed["baseline_position"], observed["expected_peak_position"], observed["peak_position"], observed["raw_peak_value"], (int(task["current_step_index"]) * float(task["sampling_period_seconds"]) + attempt * float(task["sampling_period_seconds"])) * 1000, int(physical_damage), int(confirmed and not detected), anomaly_kind, "simulated_fault" if physical_damage else None, "simulated hardware anomaly" if detected else None, utc_now()))
            detected_kinds: list[str] = []
            if detected:
                if physical_damage:
                    detected_kinds.append("turn_timeout" if "turn_timeout" in anomalies else "frame_fault")
                thresholds = json.loads(task["thresholds_json"] or "{}")
                if observed["baseline_intensity"] < float(thresholds["baseline_min"]):
                    detected_kinds.append("baseline_low")
                if observed["baseline_intensity"] > float(thresholds["baseline_max"]):
                    detected_kinds.append("baseline_high")
                if abs(observed["baseline_position"] - observed["expected_peak_position"]) > float(thresholds["baseline_position_tolerance"]):
                    detected_kinds.append("baseline_shift")
                if abs(observed["peak_position"] - observed["expected_peak_position"]) > float(thresholds["peak_position_tolerance"]):
                    detected_kinds.append("peak_shift")
            observed_rows.append({"ccd_index": ccd_index, **observed, "detected": sorted(set(detected_kinds))})
        return observed_rows, first_sha

    def _decision(self, db: sqlite3.Connection, task: sqlite3.Row, step: sqlite3.Row, attempt: int, anomaly_kind: str, decision: str, observed: list[dict[str, Any]], actor_user_id: int | None, reason: str) -> None:
        db.execute("INSERT INTO hardware_decisions(task_id, step_id, attempt, anomaly_kind, decision, observed_json, threshold_json, reason, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task["id"], step["id"], attempt, anomaly_kind, decision, _json(observed), task["thresholds_json"], reason, actor_user_id, utc_now()))

    def _safe_stop_db(self, db: sqlite3.Connection, task: sqlite3.Row, actor_user_id: int | None, reason: str, *, state: str = "safety_stopped") -> None:
        correlation_id = f"hardware-safe-{task['id']}-{uuid.uuid4().hex[:10]}"
        self._trace(db, task["id"], "internal", "safety", "safety.stop", {"reason": reason, "commands_sent": False}, correlation_id, state)
        db.execute("UPDATE hardware_tasks SET status=?, failure_code=?, failure_message=?, completed_at=?, last_message=?, updated_at=? WHERE id=?", (state, "safety_stop", reason, utc_now(), reason, utc_now(), task["id"]))
        self._message(db, task["id"], "error", "task.safety_stop", reason, {"correlation_id": correlation_id})
        self._audit(db, actor_user_id, "hardware.task.safety_stop", int(task["id"]), {"reason": reason, "correlation_id": correlation_id})

    def _close_adapter(self, task_id: int) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            adapter.close(correlation_id=f"hardware-close-{task_id}-{uuid.uuid4().hex[:8]}")

    def _complete_step(self, db: sqlite3.Connection, task: sqlite3.Row, step: sqlite3.Row, actor_user_id: int | None) -> bool:
        db.execute("UPDATE hardware_plan_steps SET status='confirmed', updated_at=? WHERE id=?", (utc_now(), step["id"]))
        completed = int(task["completed_steps"]) + 1
        if completed >= int(task["total_steps"]):
            hashes = [row[0] for row in db.execute("SELECT points_sha256 FROM hardware_frames WHERE task_id=? AND confirmed=1 ORDER BY step_id, attempt, ccd_index", (task["id"],)).fetchall()]
            result_sha = _sha("|".join(value or "" for value in hashes))
            db.execute("UPDATE hardware_tasks SET status='completed', completed_steps=?, result_sha256=?, completed_at=?, last_message=?, updated_at=? WHERE id=?", (completed, result_sha, utc_now(), "all turn steps confirmed", utc_now(), task["id"]))
            self._message(db, task["id"], "success", "task.completed", "all turn steps confirmed", {"result_sha256": result_sha})
            self._audit(db, actor_user_id, "hardware.task.completed", int(task["id"]), {"result_sha256": result_sha, "completed_steps": completed})
            return True
        next_index = int(task["current_step_index"]) + 1
        db.execute("UPDATE hardware_tasks SET status='turning', current_step_index=?, current_retry_count=0, completed_steps=?, last_message=?, updated_at=? WHERE id=?", (next_index, completed, "next turn step ready", utc_now(), task["id"]))
        return False

    def _step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self._context(task_id)
        status = str(task["status"])
        if status == HardwareTaskState.PRE_EXCITATION.value:
            with self.database.write() as db:
                current = self._context(task_id, db)[0]
                db.execute("UPDATE hardware_tasks SET status='turning', last_message=?, updated_at=? WHERE id=?", ("pre-excitation complete; turn plan ready", utc_now(), task_id))
                self._trace(db, task_id, "internal", "event", "pre_excitation.complete", {"seconds": current["pre_excitation_seconds"]}, f"hardware-{task_id}", HardwareTaskState.TURNING.value)
                self._message(db, task_id, "info", "pre_excitation.complete", "pre-excitation complete; turn plan ready", {})
            return self._task_dict(task_id)
        if status == HardwareTaskState.TURNING.value:
            with self.database.write() as db:
                current, _, current_profile = self._context(task_id, db)
                step_row = self._current_step(db, current)
                if step_row["status"] not in {"pending", "retry_pending", "turning"}:
                    raise HardwareError("hardware_step_not_pending", "current turn step is not pending", status_code=409)
                correlation_id = f"hardware-turn-{task_id}-{step_row['order_index']}-{uuid.uuid4().hex[:8]}"
                adapter = self._adapter(task_id, current_profile)
                response = adapter.turn(angle_deg=float(step_row["angle_deg"]), correlation_id=correlation_id) if isinstance(adapter, SimulatorTurnAdapter) else {}
                db.execute("UPDATE hardware_plan_steps SET status='collecting', updated_at=? WHERE id=?", (utc_now(), step_row["id"]))
                db.execute("UPDATE hardware_tasks SET status='collecting', last_message=?, updated_at=? WHERE id=?", ("turn complete; collecting CCD frame", utc_now(), task_id))
                self._trace(db, task_id, "outbound", "command", "turn.request", {"angle_deg": step_row["angle_deg"], "order_index": step_row["order_index"], "simulated": isinstance(adapter, SimulatorTurnAdapter)}, correlation_id, HardwareTaskState.COLLECTING.value)
                self._trace(db, task_id, "inbound", "response", "turn.response", response, correlation_id, HardwareTaskState.COLLECTING.value)
                self._audit(db, actor_user_id, "hardware.turn.request", task_id, {"order_index": step_row["order_index"], "angle_deg": step_row["angle_deg"], "correlation_id": correlation_id})
                self._audit(db, actor_user_id, "hardware.turn.response", task_id, {"order_index": step_row["order_index"], "correlation_id": correlation_id})
            return self._task_dict(task_id)
        if status != HardwareTaskState.COLLECTING.value:
            if status == HardwareTaskState.MANUAL_INTERVENTION.value:
                raise HardwareError("hardware_manual_intervention_required", "manual intervention is required before continuing", status_code=409)
            raise HardwareError("hardware_task_not_running", "hardware task is not ready to capture", details={"status": status}, status_code=409)
        adapter = self._adapters.get(task_id)
        if not isinstance(adapter, SimulatorTurnAdapter):
            raise HardwareError("hardware_adapter_unavailable", "no active simulator adapter is available", status_code=409)
        try:
            event = adapter.capture(correlation_id=f"hardware-frame-{task_id}-{uuid.uuid4().hex[:8]}")
        except HardwareError as exc:
            event = {"event_type": "fault", "ccds": [], "details": {"code": exc.code}, "message": exc.message}
        completed_now = False
        should_close = False
        with self.database.write() as db:
            current = self._context(task_id, db)[0]
            step_row = self._current_step(db, current)
            attempt = int(step_row["last_attempt"]) + 1
            forced = self._simulated_anomalies(current, step_row, attempt)
            observed, _ = self._store_frames(db, current, step_row, attempt, event, forced, False)
            anomaly_kinds = sorted({item for row in observed for item in row["detected"]})
            if not anomaly_kinds and event.get("event_type") == "fault":
                anomaly_kinds = ["frame_fault"]
            db.execute("UPDATE hardware_plan_steps SET last_attempt=?, updated_at=? WHERE id=?", (attempt, utc_now(), step_row["id"]))
            self._trace(db, task_id, "inbound", "frame", "frame.capture", {"attempt": attempt, "event_type": event.get("event_type"), "sha256": (event.get("details") or {}).get("sha256"), "anomaly_kinds": anomaly_kinds}, f"hardware-frame-{task_id}", HardwareTaskState.COLLECTING.value)
            self._audit(db, actor_user_id, "hardware.frame.capture", task_id, {"order_index": step_row["order_index"], "attempt": attempt, "anomaly_kinds": anomaly_kinds, "frame_sha256": (event.get("details") or {}).get("sha256")})
            if anomaly_kinds:
                anomaly_text = ",".join(anomaly_kinds)
                db.execute("UPDATE hardware_tasks SET status='anomaly', current_retry_count=?, last_event_json=?, last_message=?, updated_at=? WHERE id=?", (int(step_row["retry_count"]), _json(event), f"anomaly detected: {anomaly_text}", utc_now(), task_id))
                self._message(db, task_id, "warning", "anomaly.detected", f"anomaly detected: {anomaly_text}", {"order_index": step_row["order_index"], "attempt": attempt})
                self._audit(db, actor_user_id, "hardware.anomaly.detected", task_id, {"order_index": step_row["order_index"], "attempt": attempt, "anomaly_kinds": anomaly_kinds})
                retry_count = int(step_row["retry_count"])
                if anomaly_kinds == ["peak_shift"] and retry_count < int(current["retry_limit"]):
                    db.execute("UPDATE hardware_plan_steps SET status='retry_pending', retry_count=retry_count+1, correction_offset=?, updated_at=? WHERE id=?", (float(step_row["expected_peak_position"]) - float(observed[0]["peak_position"]), utc_now(), step_row["id"]))
                    self._decision(db, current, step_row, attempt, anomaly_text, "correct", observed, actor_user_id, "automatic peak-position correction scheduled")
                    self._message(db, task_id, "info", "anomaly.correct", "automatic peak-position correction scheduled", {"order_index": step_row["order_index"]})
                    self._audit(db, actor_user_id, "hardware.decision.correct", task_id, {"order_index": step_row["order_index"], "attempt": attempt})
                    db.execute("UPDATE hardware_tasks SET status='turning', current_retry_count=current_retry_count+1, last_message=?, updated_at=? WHERE id=?", ("retrying after automatic correction", utc_now(), task_id))
                elif retry_count < int(current["retry_limit"]):
                    db.execute("UPDATE hardware_plan_steps SET status='retry_pending', retry_count=retry_count+1, updated_at=? WHERE id=?", (utc_now(), step_row["id"]))
                    self._decision(db, current, step_row, attempt, anomaly_text, "retry", observed, actor_user_id, "retry limit not exhausted")
                    self._message(db, task_id, "info", "anomaly.retry", "retry scheduled after anomaly", {"order_index": step_row["order_index"], "retry_count": retry_count + 1})
                    self._audit(db, actor_user_id, "hardware.decision.retry", task_id, {"order_index": step_row["order_index"], "attempt": attempt, "retry_count": retry_count + 1})
                    db.execute("UPDATE hardware_tasks SET status='turning', current_retry_count=current_retry_count+1, last_message=?, updated_at=? WHERE id=?", ("retry scheduled", utc_now(), task_id))
                elif current["anomaly_policy"] == "manual":
                    db.execute("UPDATE hardware_plan_steps SET status='manual', updated_at=? WHERE id=?", (utc_now(), step_row["id"]))
                    self._decision(db, current, step_row, attempt, anomaly_text, "manual", observed, actor_user_id, "retry limit exhausted; manual takeover required")
                    db.execute("UPDATE hardware_tasks SET status='manual_intervention', last_message=?, updated_at=? WHERE id=?", ("manual intervention required", utc_now(), task_id))
                    self._audit(db, actor_user_id, "hardware.decision.manual", task_id, {"order_index": step_row["order_index"], "attempt": attempt})
                else:
                    self._decision(db, current, step_row, attempt, anomaly_text, "stop", observed, actor_user_id, "retry limit exhausted; safety stop")
                    self._safe_stop_db(db, current, actor_user_id, f"retry limit exhausted at turn {step_row['order_index']}: {anomaly_text}")
                    should_close = True
            else:
                db.execute("UPDATE hardware_frames SET confirmed=1 WHERE task_id=? AND step_id=? AND attempt=?", (task_id, step_row["id"], attempt))
                self._decision(db, current, step_row, attempt, "none", "accept", observed, actor_user_id, "baseline and peak checks passed")
                completed_now = self._complete_step(db, current, step_row, actor_user_id)
                should_close = completed_now
        if should_close:
            self._close_adapter(task_id)
        return self._task_dict(task_id, include_points=True)

    def _pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self._context(task_id)
        if task["status"] == HardwareTaskState.PAUSED.value:
            return self._task_dict(task_id)
        if task["status"] not in {HardwareTaskState.PRE_EXCITATION.value, HardwareTaskState.TURNING.value, HardwareTaskState.COLLECTING.value, HardwareTaskState.ANOMALY.value}:
            raise HardwareError("hardware_task_not_pauseable", "hardware task cannot be paused in its current state", details={"status": task["status"]}, status_code=409)
        with self.database.write() as db:
            db.execute("UPDATE hardware_tasks SET status='paused', paused_from=?, last_message=?, updated_at=? WHERE id=?", (task["status"], "hardware task paused", utc_now(), task_id))
            self._message(db, task_id, "warning", "task.pause", "hardware task paused", {"from": task["status"]})
            self._audit(db, actor_user_id, "hardware.task.pause", task_id, {"from": task["status"]})
        return self._task_dict(task_id)

    def _resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self._context(task_id)
        if task["status"] != HardwareTaskState.PAUSED.value:
            raise HardwareError("hardware_task_not_resumable", "hardware task is not paused", details={"status": task["status"]}, status_code=409)
        target = task["paused_from"] or HardwareTaskState.TURNING.value
        with self.database.write() as db:
            db.execute("UPDATE hardware_tasks SET status=?, paused_from=NULL, last_message=?, updated_at=? WHERE id=?", (target, "hardware task resumed", utc_now(), task_id))
            self._message(db, task_id, "info", "task.resume", "hardware task resumed", {"to": target})
            self._audit(db, actor_user_id, "hardware.task.resume", task_id, {"to": target})
        return self._task_dict(task_id)

    def _intervene(self, task_id: int, action: str, note: str = "", actor_user_id: int | None = None) -> dict[str, Any]:
        if action not in {"accept", "retry", "stop"}:
            raise HardwareError("hardware_intervention_invalid", "intervention action is not supported")
        task, _, _ = self._context(task_id)
        if task["status"] != HardwareTaskState.MANUAL_INTERVENTION.value:
            raise HardwareError("hardware_manual_intervention_not_required", "manual intervention is not currently required", status_code=409)
        should_close = False
        with self.database.write() as db:
            current = self._context(task_id, db)[0]
            step = self._current_step(db, current)
            latest_attempt = int(step["last_attempt"])
            rows = db.execute("SELECT * FROM hardware_frames WHERE task_id=? AND step_id=? AND attempt=?", (task_id, step["id"], latest_attempt)).fetchall()
            observed = [{key: value for key, value in dict(row).items() if key not in {"points_blob", "raw_payload"}} for row in rows]
            if action == "accept":
                if not rows or any(row["damaged"] for row in rows):
                    raise HardwareError("hardware_manual_accept_invalid", "damaged frames cannot be accepted", status_code=409)
                db.execute("UPDATE hardware_frames SET confirmed=1 WHERE task_id=? AND step_id=? AND attempt=?", (task_id, step["id"], latest_attempt))
                anomaly_kind = ",".join(sorted({kind for row in rows for kind in str(row["anomaly_kind"] or "").split(",") if kind})) or "none"
                self._decision(db, current, step, latest_attempt, anomaly_kind, "accept", observed, actor_user_id, note or "manual takeover accepted the latest frame")
                self._audit(db, actor_user_id, "hardware.decision.accept", task_id, {"order_index": step["order_index"], "attempt": latest_attempt, "note": note})
                should_close = self._complete_step(db, current, step, actor_user_id)
            elif action == "retry":
                db.execute("UPDATE hardware_plan_steps SET status='retry_pending', retry_count=retry_count+1, updated_at=? WHERE id=?", (utc_now(), step["id"]))
                self._decision(db, current, step, latest_attempt, step["status"], "retry", observed, actor_user_id, note or "manual takeover requested a retry")
                db.execute("UPDATE hardware_tasks SET status='turning', current_retry_count=current_retry_count+1, last_message=?, updated_at=? WHERE id=?", ("manual retry scheduled", utc_now(), task_id))
                self._audit(db, actor_user_id, "hardware.decision.manual", task_id, {"action": "retry", "order_index": step["order_index"], "note": note})
            else:
                self._decision(db, current, step, latest_attempt, step["status"], "stop", observed, actor_user_id, note or "manual takeover requested a safety stop")
                self._safe_stop_db(db, current, actor_user_id, note or "manual takeover requested a safety stop")
                should_close = True
        if should_close:
            self._close_adapter(task_id)
        return self._task_dict(task_id, include_points=True)

    def _stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self._context(task_id)
        if task["status"] in {HardwareTaskState.COMPLETED.value, HardwareTaskState.FAILED.value, HardwareTaskState.STOPPED.value, HardwareTaskState.SAFETY_STOPPED.value, HardwareTaskState.DEFERRED_EXTERNAL.value}:
            return self._task_dict(task_id)
        with self.database.write() as db:
            db.execute("UPDATE hardware_tasks SET status='stopping', last_message=?, updated_at=? WHERE id=?", ("stopping hardware safely", utc_now(), task_id))
            self._trace(db, task_id, "internal", "safety", "stop.request", {"reason": "user_requested"}, f"hardware-stop-{task_id}", HardwareTaskState.STOPPING.value)
            self._audit(db, actor_user_id, "hardware.task.stop", task_id, {"from": task["status"]})
            db.execute("UPDATE hardware_tasks SET status='stopped', completed_at=?, last_message=?, updated_at=? WHERE id=?", (utc_now(), "hardware task stopped safely", utc_now(), task_id))
            self._message(db, task_id, "warning", "task.stop", "hardware task stopped safely", {})
        self._close_adapter(task_id)
        return self._task_dict(task_id)

    def start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._start(task_id, actor_user_id)

    def step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._step(task_id, actor_user_id)

    def pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._pause(task_id, actor_user_id)

    def resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._resume(task_id, actor_user_id)

    def intervene(self, task_id: int, action: str, note: str = "", actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._intervene(task_id, action, note, actor_user_id)

    def stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._stop(task_id, actor_user_id)

    def frames(self, task_id: int, *, step_id: int | None = None, include_points: bool = False) -> list[dict[str, Any]]:
        self._context(task_id)
        with self.database.read() as db:
            query = "SELECT * FROM hardware_frames WHERE task_id=?"
            args: list[Any] = [task_id]
            if step_id is not None:
                query += " AND step_id=?"
                args.append(step_id)
            query += " ORDER BY step_id, attempt, ccd_index"
            result = []
            for row in db.execute(query, args).fetchall():
                item = dict(row)
                if include_points and row["points_blob"] is not None:
                    item["points"] = _unpack_points(row["points_blob"], int(row["points_count"]))
                item.pop("points_blob", None)
                item["damaged"] = bool(item["damaged"])
                item["confirmed"] = bool(item["confirmed"])
                result.append(item)
            return result

    def traces(self, task_id: int) -> list[dict[str, Any]]:
        task = self._context(task_id)[0]
        with self.database.read() as db:
            result = []
            for row in db.execute("SELECT * FROM hardware_traces WHERE task_id=? ORDER BY sequence_no", (task["id"],)).fetchall():
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                item.pop("raw_payload", None)
                result.append(item)
            return result

    def decisions(self, task_id: int) -> list[dict[str, Any]]:
        task = self._context(task_id)[0]
        with self.database.read() as db:
            return [dict(row) | {"observed": json.loads(row["observed_json"] or "{}"), "threshold": json.loads(row["threshold_json"] or "{}")} for row in db.execute("SELECT * FROM hardware_decisions WHERE task_id=? ORDER BY id", (task["id"],)).fetchall()]
