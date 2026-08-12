from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
import struct
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Protocol

from ..db import Database, utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _pack(points: list[int]) -> bytes:
    return struct.pack(f"<{len(points)}H", *points)


def _unpack(blob: bytes, count: int) -> list[int]:
    if len(blob) != count * 2:
        raise MercuryError("mercury_frame_invalid", "stored mercury frame length is inconsistent", status_code=409)
    return list(struct.unpack(f"<{count}H", blob))


class MercuryError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class MercuryAdapter(Protocol):
    session_id: str | None

    def start(self, *, correlation_id: str) -> dict[str, Any]: ...

    def frame(self, *, frame_index: int, phase: str, correlation_id: str) -> dict[str, Any]: ...

    def close(self, *, correlation_id: str) -> dict[str, Any]: ...


class MercurySpectrumSimulatorAdapter:
    """Synthetic spectral source; it never represents a physical lamp switch."""

    def __init__(
        self,
        *,
        layout: dict[str, Any],
        lines: list[dict[str, Any]],
        active_offset: float,
        physical_offset: float,
        seed: int,
        fault: str,
    ) -> None:
        self.layout = layout
        self.lines = lines
        self.active_offset = active_offset
        self.physical_offset = physical_offset
        self.seed = seed
        self.fault = fault
        self.session_id: str | None = None
        self.running = False

    def start(self, *, correlation_id: str) -> dict[str, Any]:
        if self.fault == "switch_failure":
            raise MercuryError("mercury_simulation_start_failed", "synthetic mercury spectrum source failed to start", status_code=409)
        self.session_id = f"mercury-sim-{uuid.uuid4().hex}"
        self.running = True
        return {
            "event_type": "simulation_spectrum_started",
            "session_id": self.session_id,
            "correlation_id": correlation_id,
            "physical_lamp_command": False,
            "physical_lamp_state": "not_controlled",
        }

    def frame(self, *, frame_index: int, phase: str, correlation_id: str) -> dict[str, Any]:
        if not self.running:
            raise MercuryError("mercury_session_not_running", "synthetic spectrum session is not active", status_code=409)
        if self.fault == "stability_failure" and phase == "stabilization":
            raise MercuryError("mercury_stability_failed", "synthetic mercury peak did not stabilize", status_code=409)
        if self.fault == "capture_failure" and phase == "measurement":
            raise MercuryError("mercury_capture_failed", "synthetic mercury spectrum capture failed", status_code=409)

        points_per_ccd = int(self.layout["points_per_ccd"])
        indices = [int(value) for value in self.layout["ccd_indices"]]
        rng = random.Random(self.seed + frame_index * 1009 + (0 if phase == "stabilization" else 100_003))
        spectra = {index: [rng.randint(35, 65) for _ in range(points_per_ccd)] for index in indices}
        for line in self.lines:
            ccd_index = int(line["expected_ccd_index"])
            if ccd_index not in spectra:
                continue
            # expected_position includes the active correction. Recover the
            # nominal instrument position before applying the simulated offset.
            nominal = float(line["expected_position"]) + self.active_offset
            center = int(round(nominal + self.physical_offset))
            amplitude = min(60_000, 4_000 + int(line["relative_intensity"]) * 45)
            for position in range(max(0, center - 10), min(points_per_ccd, center + 11)):
                gaussian = amplitude * math.exp(-0.5 * ((position - center) / 2.0) ** 2)
                spectra[ccd_index][position] = min(65_535, spectra[ccd_index][position] + int(round(gaussian)))
        ccds = []
        hashes = []
        for ccd_index in indices:
            packed = _pack(spectra[ccd_index])
            digest = _sha(packed)
            hashes.append(digest)
            ccds.append({"ccd_index": ccd_index, "points": spectra[ccd_index], "points_sha256": digest})
        return {
            "event_type": "simulated_mercury_frame",
            "session_id": self.session_id,
            "phase": phase,
            "frame_index": frame_index,
            "virtual_time_ms": float(frame_index * 1000),
            "frame_sha256": _sha("".join(hashes)),
            "ccds": ccds,
            "correlation_id": correlation_id,
            "physical_lamp_command": False,
        }

    def close(self, *, correlation_id: str) -> dict[str, Any]:
        self.running = False
        previous = self.session_id
        self.session_id = None
        return {
            "event_type": "simulation_spectrum_stopped",
            "session_id": previous,
            "correlation_id": correlation_id,
            "physical_lamp_command": False,
            "physical_lamp_state": "not_controlled",
        }


class SerialMercuryAdapter:
    """Hard protocol gate. It cannot construct or transmit command bytes."""

    session_id: str | None = None

    def start(self, *, correlation_id: str) -> dict[str, Any]:
        raise MercuryError(
            "mercury_protocol_unavailable",
            "real mercury lamp protocol documentation or capture is unavailable",
            details={"correlation_id": correlation_id, "commands_sent": False},
            status_code=409,
        )

    def frame(self, *, frame_index: int, phase: str, correlation_id: str) -> dict[str, Any]:
        raise MercuryError("mercury_protocol_unavailable", "real mercury lamp protocol is unavailable", status_code=409)

    def close(self, *, correlation_id: str) -> dict[str, Any]:
        return {
            "event_type": "serial_close_skipped",
            "correlation_id": correlation_id,
            "reason": "protocol_unavailable",
            "commands_sent": False,
        }


class MercuryCalibrationService:
    """S15 mercury-line optical alignment without mutating S12 calibration data."""

    def __init__(self, database: Database):
        self.database = database
        self._adapters: dict[int, MercuryAdapter] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @contextmanager
    def _control_scope(self, session_id: int):
        with self._locks_guard:
            lock = self._locks.setdefault(session_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise MercuryError("mercury_session_busy", "another mercury control operation is in progress", status_code=409)
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def _layout(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["ccd_indices"] = [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]
        result["gap_points"] = json.loads(row["gap_points_json"] or "[]")
        return result

    @staticmethod
    def _expected_position(layout: dict[str, Any], wavelength_nm: float, active_offset: float) -> tuple[int, float]:
        low = float(layout["wavelength_min"])
        high = float(layout["wavelength_max"])
        indices = layout["ccd_indices"]
        points = int(layout["points_per_ccd"])
        if not low <= wavelength_nm <= high:
            raise MercuryError(
                "mercury_line_outside_layout",
                "selected mercury line is outside the CCD layout wavelength range",
                details={"wavelength_nm": wavelength_nm, "wavelength_min": low, "wavelength_max": high},
            )
        global_position = (wavelength_nm - low) / (high - low) * (len(indices) * points - 1)
        ordinal = min(len(indices) - 1, int(global_position // points))
        nominal = global_position - ordinal * points
        return int(indices[ordinal]), nominal - active_offset

    @staticmethod
    def _trace(db: sqlite3.Connection, session_id: int, direction: str, kind: str, name: str, payload: dict[str, Any], correlation_id: str, safe_state: str) -> None:
        sequence = int(db.execute("SELECT COALESCE(MAX(sequence_no), -1) + 1 FROM mercury_traces WHERE session_id=?", (session_id,)).fetchone()[0])
        payload_json = _json(payload)
        db.execute(
            "INSERT INTO mercury_traces(session_id, sequence_no, direction, kind, name, payload_json, payload_sha256, correlation_id, safe_state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, sequence, direction, kind, name, payload_json, _sha(payload_json), correlation_id, safe_state, utc_now()),
        )

    @staticmethod
    def _message(db: sqlite3.Connection, session_id: int, level: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        db.execute(
            "INSERT INTO mercury_messages(session_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, level, code, message, _json(details or {}), utc_now()),
        )

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: int | None, action: str, target_id: int, details: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'mercury_calibration', ?, ?, ?)",
            (actor, action, target_id, _json(details), utc_now()),
        )

    def _ensure_active(self, db: sqlite3.Connection, profile_id: int, layout_id: int, actor: int | None) -> sqlite3.Row:
        active = db.execute(
            "SELECT v.* FROM mercury_active_alignments a JOIN mercury_alignment_versions v ON v.id=a.version_id WHERE a.device_profile_id=? AND a.ccd_layout_id=?",
            (profile_id, layout_id),
        ).fetchone()
        if active is not None:
            return active
        now = utc_now()
        snapshot = {"kind": "baseline", "device_profile_id": profile_id, "ccd_layout_id": layout_id, "version": 1, "offset_points": 0.0}
        snapshot_json = _json(snapshot)
        cursor = db.execute(
            "INSERT INTO mercury_alignment_versions(device_profile_id, ccd_layout_id, version, source_session_id, parent_version_id, offset_points, before_rms, after_rms, max_before_offset, max_after_offset, point_count, snapshot_json, snapshot_sha256, created_by, created_at) VALUES (?, ?, 1, NULL, NULL, 0, 0, 0, 0, 0, 0, ?, ?, ?, ?)",
            (profile_id, layout_id, snapshot_json, _sha(snapshot_json), actor, now),
        )
        version_id = int(cursor.lastrowid)
        db.execute(
            "INSERT INTO mercury_active_alignments(device_profile_id, ccd_layout_id, version_id, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)",
            (profile_id, layout_id, version_id, actor, now),
        )
        return db.execute("SELECT * FROM mercury_alignment_versions WHERE id=?", (version_id,)).fetchone()

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            lines = [dict(row) | {"enabled": bool(row["enabled"])} for row in db.execute("SELECT * FROM mercury_reference_lines WHERE enabled=1 ORDER BY wavelength_nm").fetchall()]
            profiles = [dict(row) for row in db.execute("SELECT id, name, transport, port, baud_rate, points_per_ccd, ccd_indices_json FROM device_profiles WHERE enabled=1 ORDER BY id").fetchall()]
            for profile in profiles:
                profile["ccd_indices"] = json.loads(profile.pop("ccd_indices_json") or "[]")
                profile["mercury_protocol_available"] = profile["transport"] == "simulator"
                profile["protocol_status"] = "synthetic_spectrum_only" if profile["transport"] == "simulator" else "deferred_external"
            layouts = [self._layout(row) for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall()]
            active = [dict(row) for row in db.execute("SELECT a.device_profile_id, a.ccd_layout_id, a.version_id, v.version, v.offset_points, v.snapshot_sha256, a.updated_at FROM mercury_active_alignments a JOIN mercury_alignment_versions v ON v.id=a.version_id ORDER BY a.device_profile_id, a.ccd_layout_id").fetchall()]
        return {
            "reference_lines": lines,
            "profiles": profiles,
            "layouts": layouts,
            "active_alignments": active,
            "faults": ["none", "switch_failure", "stability_failure", "capture_failure"],
            "real_protocol_available": False,
            "protocol_notice": "真实汞灯协议与抓包缺失；串口入口不发送任何命令。",
        }

    def create_session(self, payload: dict[str, Any], actor: int | None = None) -> dict[str, Any]:
        line_ids = [int(value) for value in payload.get("line_ids") or []]
        if len(line_ids) < 2 or len(line_ids) != len(set(line_ids)):
            raise MercuryError("mercury_line_selection_invalid", "select at least two distinct mercury lines")
        fault = str(payload.get("simulator_fault", "none"))
        if fault not in {"none", "switch_failure", "stability_failure", "capture_failure"}:
            raise MercuryError("mercury_simulator_fault_invalid", "unknown mercury simulator fault")
        with self.database.write() as db:
            profile_id = int(payload.get("device_profile_id", 1))
            profile = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
            if profile is None:
                raise MercuryError("device_profile_not_found", "device profile was not found", status_code=404)
            layout_key = payload.get("ccd_layout_id", "default")
            layout_row = db.execute("SELECT * FROM ccd_layouts WHERE id=? OR name=?", (layout_key if str(layout_key).isdigit() else -1, str(layout_key))).fetchone()
            if layout_row is None:
                raise MercuryError("ccd_layout_not_found", "CCD layout was not found", status_code=404)
            if int(profile["points_per_ccd"]) != int(layout_row["points_per_ccd"]):
                raise MercuryError("ccd_layout_profile_mismatch", "device profile and CCD layout point counts differ", status_code=409)
            placeholders = ",".join("?" for _ in line_ids)
            references = db.execute(f"SELECT * FROM mercury_reference_lines WHERE enabled=1 AND id IN ({placeholders}) ORDER BY wavelength_nm", line_ids).fetchall()
            if len(references) != len(line_ids):
                raise MercuryError("mercury_reference_line_not_found", "one or more selected mercury lines were not found", status_code=404)
            active = self._ensure_active(db, int(profile["id"]), int(layout_row["id"]), actor)
            layout = self._layout(layout_row)
            now = utc_now()
            simulator = {
                "offset_points": float(payload.get("simulator_offset_points", 6.0)),
                "seed": int(payload.get("simulator_seed", 0)),
                "fault": fault,
            }
            cursor = db.execute(
                "INSERT INTO mercury_sessions(name, status, device_profile_id, ccd_layout_id, transport, stabilization_frames, tolerance_points, search_radius_points, correction_limit_points, simulator_json, before_version_id, safe_off, created_by, created_at, updated_at) VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    str(payload.get("name", "S15 汞灯调试与光学校准")).strip(),
                    profile["id"], layout_row["id"], profile["transport"],
                    int(payload.get("stabilization_frames", 2)), float(payload.get("tolerance_points", 1.0)),
                    int(payload.get("search_radius_points", 40)), float(payload.get("correction_limit_points", 25.0)),
                    _json(simulator), active["id"], actor, now, now,
                ),
            )
            session_id = int(cursor.lastrowid)
            for reference in references:
                ccd_index, expected = self._expected_position(layout, float(reference["wavelength_nm"]), float(active["offset_points"]))
                db.execute(
                    "INSERT INTO mercury_session_lines(session_id, reference_line_id, wavelength_nm, expected_ccd_index, expected_position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, reference["id"], reference["wavelength_nm"], ccd_index, expected, now),
                )
            self._message(db, session_id, "info", "session.created", "mercury calibration session created", {"line_count": len(references), "transport": profile["transport"]})
            self._audit(db, actor, "mercury.session.create", session_id, {"line_ids": line_ids, "before_version_id": active["id"], "transport": profile["transport"]})
        return self.session(session_id)

    def _context(self, session_id: int, db: sqlite3.Connection | None = None) -> tuple[sqlite3.Row, sqlite3.Row, dict[str, Any]]:
        if db is None:
            with self.database.read() as connection:
                return self._context(session_id, connection)
        session = db.execute("SELECT * FROM mercury_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None:
            raise MercuryError("mercury_session_not_found", "mercury calibration session was not found", details={"session_id": session_id}, status_code=404)
        profile = db.execute("SELECT * FROM device_profiles WHERE id=?", (session["device_profile_id"],)).fetchone()
        layout_row = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (session["ccd_layout_id"],)).fetchone()
        if profile is None or layout_row is None:
            raise MercuryError("mercury_configuration_missing", "mercury session references missing device or layout", status_code=409)
        return session, profile, self._layout(layout_row)

    def _lines(self, db: sqlite3.Connection, session_id: int) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT l.*, r.label, r.relative_intensity, r.source_name, r.source_url FROM mercury_session_lines l JOIN mercury_reference_lines r ON r.id=l.reference_line_id WHERE l.session_id=? ORDER BY l.wavelength_nm",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _version_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json") or "{}")
        return result

    def session(self, session_id: int, *, include_points: bool = False) -> dict[str, Any]:
        with self.database.read() as db:
            row, profile, layout = self._context(session_id, db)
            result = dict(row)
            for field, default in (("simulator_json", {}), ("analysis_json", None), ("last_event_json", None)):
                raw = result.pop(field, None)
                result[field.removesuffix("_json")] = json.loads(raw) if raw else default
            result["safe_off"] = bool(result["safe_off"])
            result["profile"] = {"id": profile["id"], "name": profile["name"], "transport": profile["transport"], "port": profile["port"], "baud_rate": profile["baud_rate"]}
            result["layout"] = {key: layout[key] for key in ("id", "name", "points_per_ccd", "ccd_indices", "wavelength_min", "wavelength_max")}
            result["lines"] = self._lines(db, session_id)
            result["messages"] = []
            for message in db.execute("SELECT * FROM mercury_messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall():
                item = dict(message)
                item["details"] = json.loads(item.pop("details_json") or "{}")
                result["messages"].append(item)
            result["traces"] = []
            for trace in db.execute("SELECT * FROM mercury_traces WHERE session_id=? ORDER BY sequence_no", (session_id,)).fetchall():
                item = dict(trace)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                result["traces"].append(item)
            result["frames"] = []
            for frame in db.execute("SELECT * FROM mercury_frames WHERE session_id=? ORDER BY phase, frame_index, ccd_index", (session_id,)).fetchall():
                item = dict(frame)
                blob = item.pop("points_blob")
                if include_points:
                    item["points"] = _unpack(blob, int(item["points_count"]))
                result["frames"].append(item)
            before = db.execute("SELECT * FROM mercury_alignment_versions WHERE id=?", (row["before_version_id"],)).fetchone()
            candidate = db.execute("SELECT * FROM mercury_alignment_versions WHERE id=?", (row["candidate_version_id"],)).fetchone() if row["candidate_version_id"] else None
            active = db.execute(
                "SELECT v.* FROM mercury_active_alignments a JOIN mercury_alignment_versions v ON v.id=a.version_id WHERE a.device_profile_id=? AND a.ccd_layout_id=?",
                (row["device_profile_id"], row["ccd_layout_id"]),
            ).fetchone()
            result["before_version"] = self._version_dict(before)
            result["candidate_version"] = self._version_dict(candidate)
            result["active_version"] = self._version_dict(active)
            result["progress"] = round(min(100.0, int(row["stabilized_frames"]) / max(1, int(row["stabilization_frames"])) * 60.0 + (40.0 if row["candidate_version_id"] else 0.0)), 2)
            if not include_points and result["last_event"] and "ccds" in result["last_event"]:
                compact = dict(result["last_event"])
                compact["ccds"] = [{key: value for key, value in ccd.items() if key != "points"} for ccd in compact["ccds"]]
                result["last_event"] = compact
        return result

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [int(row[0]) for row in db.execute("SELECT id FROM mercury_sessions ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]
        return [self.session(session_id) for session_id in ids]

    def _build_adapter(self, session_id: int, profile: sqlite3.Row, layout: dict[str, Any], session: sqlite3.Row, db: sqlite3.Connection) -> MercuryAdapter:
        if profile["transport"] == "serial":
            return SerialMercuryAdapter()
        config = json.loads(session["simulator_json"] or "{}")
        before = db.execute("SELECT * FROM mercury_alignment_versions WHERE id=?", (session["before_version_id"],)).fetchone()
        if before is None:
            raise MercuryError("mercury_alignment_missing", "before alignment version was not found", status_code=409)
        return MercurySpectrumSimulatorAdapter(
            layout=layout,
            lines=self._lines(db, session_id),
            active_offset=float(before["offset_points"]),
            physical_offset=float(config.get("offset_points", 6.0)),
            seed=int(config.get("seed", 0)),
            fault=str(config.get("fault", "none")),
        )

    def start(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, profile, layout = self._context(session_id)
            if session["status"] != "draft":
                if session["status"] in {"stabilizing", "acquiring", "ready"}:
                    return self.session(session_id, include_points=True)
                raise MercuryError("mercury_session_not_startable", "mercury session is not startable", details={"status": session["status"]}, status_code=409)
            correlation_id = f"mercury-{session_id}-{uuid.uuid4().hex[:10]}"
            if profile["transport"] == "serial":
                with self.database.write() as db:
                    self._trace(db, session_id, "internal", "event", "protocol.deferred", {"reason": "missing_mercury_protocol", "commands_sent": False}, correlation_id, "safe_off")
                    now = utc_now()
                    db.execute("UPDATE mercury_sessions SET status='deferred_external', safe_off=1, failure_code='mercury_protocol_unavailable', failure_message=?, last_message=?, completed_at=?, updated_at=? WHERE id=?", ("real mercury lamp protocol documentation or capture is unavailable", "真实汞灯协议缺失，未发送命令", now, now, session_id))
                    self._message(db, session_id, "warning", "session.deferred_external", "real mercury protocol is unavailable; no command bytes were sent", {"commands_sent": False})
                    self._audit(db, actor, "mercury.session.deferred", session_id, {"reason": "missing_mercury_protocol", "commands_sent": False})
                return self.session(session_id)
            with self.database.read() as db:
                adapter = self._build_adapter(session_id, profile, layout, session, db)
            try:
                event = adapter.start(correlation_id=correlation_id)
            except MercuryError as exc:
                self._safe_off(session_id, exc, correlation_id, actor, adapter=adapter)
                return self.session(session_id)
            self._adapters[session_id] = adapter
            now = utc_now()
            with self.database.write() as db:
                db.execute("UPDATE mercury_sessions SET status='stabilizing', safe_off=0, adapter_session_id=?, last_event_json=?, last_message=?, started_at=?, updated_at=? WHERE id=?", (adapter.session_id, _json(event), "模拟汞谱源已启动，等待稳定", now, now, session_id))
                self._trace(db, session_id, "internal", "event", "simulation.spectrum.started", event, correlation_id, "simulation_active")
                self._message(db, session_id, "info", "session.started", "synthetic mercury spectrum started; no physical lamp command was issued", {"physical_lamp_command": False})
                self._audit(db, actor, "mercury.session.start", session_id, {"source": "synthetic_spectrum", "physical_lamp_command": False})
            return self.session(session_id, include_points=True)

    def _safe_off(self, session_id: int, exc: MercuryError, correlation_id: str, actor: int | None, *, adapter: MercuryAdapter | None = None) -> None:
        current = adapter or self._adapters.get(session_id)
        close_event = current.close(correlation_id=f"{correlation_id}-close") if current is not None else {"event_type": "close_not_required", "commands_sent": False}
        self._adapters.pop(session_id, None)
        now = utc_now()
        with self.database.write() as db:
            self._trace(db, session_id, "internal", "safety", "safe_off", {"code": exc.code, "message": exc.message, "close": close_event}, correlation_id, "safe_off")
            db.execute("UPDATE mercury_sessions SET status='safe_off', safe_off=1, adapter_session_id=NULL, failure_code=?, failure_message=?, last_event_json=?, last_message=?, completed_at=?, updated_at=? WHERE id=?", (exc.code, exc.message, _json(close_event), exc.message, now, now, session_id))
            self._message(db, session_id, "error", "session.safe_off", exc.message, {"code": exc.code, "close": close_event})
            self._audit(db, actor, "mercury.session.safe_off", session_id, {"code": exc.code, "close": close_event})

    @staticmethod
    def _store_frame(db: sqlite3.Connection, session_id: int, event: dict[str, Any]) -> None:
        for ccd in event["ccds"]:
            points = [int(value) for value in ccd["points"]]
            blob = _pack(points)
            db.execute(
                "INSERT INTO mercury_frames(session_id, phase, frame_index, ccd_index, points_blob, points_count, points_sha256, frame_sha256, virtual_time_ms, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, event["phase"], event["frame_index"], ccd["ccd_index"], blob, len(points), _sha(blob), event["frame_sha256"], event["virtual_time_ms"], utc_now()),
            )

    @staticmethod
    def _locate(points: list[int], expected: float, radius: int) -> tuple[int, int] | None:
        start = max(0, int(math.floor(expected)) - radius)
        end = min(len(points) - 1, int(math.ceil(expected)) + radius)
        if start > end:
            return None
        peak_position = max(range(start, end + 1), key=lambda position: (points[position], -position))
        peak_value = int(points[peak_position])
        if peak_value < 500:
            return None
        return peak_position, peak_value

    def _analyze(self, db: sqlite3.Connection, session: sqlite3.Row, event: dict[str, Any], actor: int | None) -> dict[str, Any]:
        by_ccd = {int(item["ccd_index"]): item["points"] for item in event["ccds"]}
        offsets: list[float] = []
        located: list[dict[str, Any]] = []
        for line in self._lines(db, int(session["id"])):
            points = by_ccd.get(int(line["expected_ccd_index"]), [])
            peak = self._locate(points, float(line["expected_position"]), int(session["search_radius_points"]))
            if peak is None:
                db.execute("UPDATE mercury_session_lines SET state='not_found' WHERE id=?", (line["id"],))
                continue
            position, value = peak
            offset = float(position) - float(line["expected_position"])
            offsets.append(offset)
            located.append({"line_id": line["id"], "wavelength_nm": line["wavelength_nm"], "expected_position": line["expected_position"], "observed_position": position, "offset_points": offset})
            db.execute("UPDATE mercury_session_lines SET observed_ccd_index=?, observed_position=?, peak_value=?, offset_points=?, state='located' WHERE id=?", (line["expected_ccd_index"], position, value, offset, line["id"]))
        total = int(db.execute("SELECT COUNT(*) FROM mercury_session_lines WHERE session_id=?", (session["id"],)).fetchone()[0])
        if len(offsets) != total:
            raise MercuryError("mercury_peak_not_found", "one or more selected mercury peaks were not located", details={"located": len(offsets), "selected": total}, status_code=409)
        ordered = sorted(offsets)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
        suggestion = -median
        before_rms = math.sqrt(sum(value * value for value in offsets) / len(offsets))
        after_offsets = [value + suggestion for value in offsets]
        after_rms = math.sqrt(sum(value * value for value in after_offsets) / len(after_offsets))
        maximum_before = max(abs(value) for value in offsets)
        maximum_after = max(abs(value) for value in after_offsets)
        if abs(suggestion) > float(session["correction_limit_points"]):
            raise MercuryError("mercury_correction_limit_exceeded", "calibration suggestion exceeds the configured correction limit", details={"suggestion_points": suggestion, "limit_points": session["correction_limit_points"]}, status_code=409)
        before = db.execute("SELECT * FROM mercury_alignment_versions WHERE id=?", (session["before_version_id"],)).fetchone()
        if before is None:
            raise MercuryError("mercury_alignment_missing", "before alignment version was not found", status_code=409)
        candidate_offset = float(before["offset_points"]) + suggestion
        next_version = int(db.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM mercury_alignment_versions WHERE device_profile_id=? AND ccd_layout_id=?", (session["device_profile_id"], session["ccd_layout_id"])).fetchone()[0])
        snapshot = {
            "kind": "mercury_optical_alignment",
            "session_id": session["id"],
            "parent_version_id": before["id"],
            "offset_points": candidate_offset,
            "suggestion_points": suggestion,
            "before_rms": before_rms,
            "after_rms": after_rms,
            "max_before_offset": maximum_before,
            "max_after_offset": maximum_after,
            "lines": located,
        }
        snapshot_json = _json(snapshot)
        cursor = db.execute(
            "INSERT INTO mercury_alignment_versions(device_profile_id, ccd_layout_id, version, source_session_id, parent_version_id, offset_points, before_rms, after_rms, max_before_offset, max_after_offset, point_count, snapshot_json, snapshot_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session["device_profile_id"], session["ccd_layout_id"], next_version, session["id"], before["id"], candidate_offset, before_rms, after_rms, maximum_before, maximum_after, len(offsets), snapshot_json, _sha(snapshot_json), actor, utc_now()),
        )
        candidate_id = int(cursor.lastrowid)
        for item, after_offset in zip(located, after_offsets, strict=True):
            db.execute("UPDATE mercury_session_lines SET after_offset_points=? WHERE id=?", (after_offset, item["line_id"]))
        analysis = {
            "line_count": len(offsets),
            "median_offset_points": median,
            "suggestion_points": suggestion,
            "before_rms": before_rms,
            "after_rms": after_rms,
            "max_before_offset": maximum_before,
            "max_after_offset": maximum_after,
            "within_tolerance": maximum_after <= float(session["tolerance_points"]),
            "candidate_version_id": candidate_id,
        }
        db.execute("UPDATE mercury_sessions SET status='ready', candidate_version_id=?, analysis_json=?, last_message=?, updated_at=? WHERE id=?", (candidate_id, _json(analysis), "峰位分析完成，等待应用或停止", utc_now(), session["id"]))
        self._message(db, int(session["id"]), "success", "calibration.suggested", "mercury peak offset and optical correction suggestion calculated", analysis)
        self._audit(db, actor, "mercury.calibration.suggest", int(session["id"]), analysis)
        return analysis

    def step(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self._context(session_id)
            if session["status"] == "ready":
                return self.session(session_id, include_points=True)
            if session["status"] not in {"stabilizing", "acquiring"}:
                raise MercuryError("mercury_session_not_running", "mercury session is not running", details={"status": session["status"]}, status_code=409)
            adapter = self._adapters.get(session_id)
            if adapter is None:
                exc = MercuryError("mercury_adapter_lost", "mercury adapter session is unavailable; restart with a new session", status_code=409)
                self._safe_off(session_id, exc, f"mercury-{session_id}-adapter-lost", actor)
                return self.session(session_id)
            phase = "stabilization" if session["status"] == "stabilizing" else "measurement"
            frame_index = int(session["stabilized_frames"]) if phase == "stabilization" else 0
            correlation_id = f"mercury-{session_id}-{phase}-{frame_index}-{uuid.uuid4().hex[:8]}"
            try:
                event = adapter.frame(frame_index=frame_index, phase=phase, correlation_id=correlation_id)
            except MercuryError as exc:
                self._safe_off(session_id, exc, correlation_id, actor)
                return self.session(session_id)
            with self.database.write() as db:
                self._store_frame(db, session_id, event)
                self._trace(db, session_id, "inbound", "frame", f"{phase}.frame", {key: value for key, value in event.items() if key != "ccds"} | {"ccd_hashes": [item["points_sha256"] for item in event["ccds"]]}, correlation_id, "simulation_active")
                if phase == "stabilization":
                    stabilized = int(session["stabilized_frames"]) + 1
                    next_state = "acquiring" if stabilized >= int(session["stabilization_frames"]) else "stabilizing"
                    db.execute("UPDATE mercury_sessions SET status=?, stabilized_frames=?, last_event_json=?, last_message=?, updated_at=? WHERE id=?", (next_state, stabilized, _json(event), f"稳定帧 {stabilized}/{session['stabilization_frames']}", utc_now(), session_id))
                    self._message(db, session_id, "info", "stability.frame", "mercury stabilization frame captured", {"stabilized_frames": stabilized, "required": session["stabilization_frames"]})
                    self._audit(db, actor, "mercury.frame.capture", session_id, {"phase": phase, "frame_index": frame_index, "frame_sha256": event["frame_sha256"]})
                else:
                    db.execute("UPDATE mercury_sessions SET last_event_json=?, last_message=?, updated_at=? WHERE id=?", (_json(event), "测量帧已采集，正在计算校准建议", utc_now(), session_id))
                    refreshed = db.execute("SELECT * FROM mercury_sessions WHERE id=?", (session_id,)).fetchone()
                    self._analyze(db, refreshed, event, actor)
                    self._audit(db, actor, "mercury.frame.capture", session_id, {"phase": phase, "frame_index": frame_index, "frame_sha256": event["frame_sha256"]})
            return self.session(session_id, include_points=True)

    def apply(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self._context(session_id)
            if session["status"] == "applied":
                return self.session(session_id)
            if session["status"] != "ready" or session["candidate_version_id"] is None:
                raise MercuryError("mercury_calibration_not_ready", "mercury correction is not ready to apply", details={"status": session["status"]}, status_code=409)
            analysis = json.loads(session["analysis_json"] or "{}")
            if not analysis.get("within_tolerance"):
                raise MercuryError("mercury_calibration_out_of_tolerance", "corrected mercury peaks remain outside tolerance", details=analysis, status_code=409)
            adapter = self._adapters.get(session_id)
            close_event = adapter.close(correlation_id=f"mercury-{session_id}-apply-close") if adapter is not None else {"event_type": "close_not_required", "physical_lamp_command": False}
            self._adapters.pop(session_id, None)
            now = utc_now()
            with self.database.write() as db:
                db.execute(
                    "INSERT INTO mercury_active_alignments(device_profile_id, ccd_layout_id, version_id, updated_by, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(device_profile_id, ccd_layout_id) DO UPDATE SET version_id=excluded.version_id, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                    (session["device_profile_id"], session["ccd_layout_id"], session["candidate_version_id"], actor, now),
                )
                self._trace(db, session_id, "internal", "event", "calibration.applied", {"before_version_id": session["before_version_id"], "candidate_version_id": session["candidate_version_id"], "close": close_event}, f"mercury-{session_id}-apply", "safe_off")
                db.execute("UPDATE mercury_sessions SET status='applied', safe_off=1, adapter_session_id=NULL, last_event_json=?, last_message=?, completed_at=?, updated_at=? WHERE id=?", (_json(close_event), "光学调整版本已应用，模拟谱源已关闭", now, now, session_id))
                self._message(db, session_id, "success", "calibration.applied", "optical alignment version applied and source safely closed", {"version_id": session["candidate_version_id"]})
                self._audit(db, actor, "mercury.calibration.apply", session_id, {"before_version_id": session["before_version_id"], "version_id": session["candidate_version_id"]})
            return self.session(session_id)

    def rollback(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self._context(session_id)
            if session["status"] == "rolled_back":
                return self.session(session_id)
            if session["status"] != "applied":
                raise MercuryError("mercury_calibration_not_applied", "only an applied mercury correction can be rolled back", details={"status": session["status"]}, status_code=409)
            now = utc_now()
            with self.database.write() as db:
                db.execute(
                    "UPDATE mercury_active_alignments SET version_id=?, updated_by=?, updated_at=? WHERE device_profile_id=? AND ccd_layout_id=?",
                    (session["before_version_id"], actor, now, session["device_profile_id"], session["ccd_layout_id"]),
                )
                self._trace(db, session_id, "internal", "event", "calibration.rolled_back", {"from_version_id": session["candidate_version_id"], "to_version_id": session["before_version_id"]}, f"mercury-{session_id}-rollback", "safe_off")
                db.execute("UPDATE mercury_sessions SET status='rolled_back', safe_off=1, last_message=?, updated_at=? WHERE id=?", ("已回滚到校准前光学调整版本", now, session_id))
                self._message(db, session_id, "success", "calibration.rolled_back", "optical alignment restored to the before version", {"version_id": session["before_version_id"]})
                self._audit(db, actor, "mercury.calibration.rollback", session_id, {"from_version_id": session["candidate_version_id"], "to_version_id": session["before_version_id"]})
            return self.session(session_id)

    def stop(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self._context(session_id)
            if session["status"] in {"applied", "rolled_back", "stopped", "safe_off", "deferred_external"}:
                return self.session(session_id)
            adapter = self._adapters.get(session_id)
            close_event = adapter.close(correlation_id=f"mercury-{session_id}-stop") if adapter is not None else {"event_type": "close_not_required", "physical_lamp_command": False}
            self._adapters.pop(session_id, None)
            now = utc_now()
            with self.database.write() as db:
                self._trace(db, session_id, "internal", "safety", "session.stopped", {"close": close_event}, f"mercury-{session_id}-stop", "safe_off")
                db.execute("UPDATE mercury_sessions SET status='stopped', safe_off=1, adapter_session_id=NULL, last_event_json=?, last_message=?, completed_at=?, updated_at=? WHERE id=?", (_json(close_event), "会话已停止并进入安全态", now, now, session_id))
                self._message(db, session_id, "info", "session.stopped", "mercury session stopped in a safe state", {"close": close_event})
                self._audit(db, actor, "mercury.session.stop", session_id, {"previous_status": session["status"], "close": close_event})
            return self.session(session_id)
