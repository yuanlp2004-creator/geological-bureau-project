from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import zlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..db import Database, utc_now
from .devices import AcqSimulatorAdapter, AcquisitionState, DeviceError


def _pack_points(points: list[int]) -> bytes:
    if not points or any(isinstance(point, bool) or point < 0 or point > 65535 for point in points):
        raise DispersionError("dispersion_points_invalid", "色散帧不是有效的 uint16 点数组")
    return struct.pack(f"<{len(points)}H", *points)


def _unpack_points(blob: bytes | bytearray | memoryview, points_count: int, expected_sha256: str, compression: str) -> list[int]:
    try:
        raw = zlib.decompress(bytes(blob)) if compression == "zlib" else b""
    except zlib.error as exc:
        raise DispersionError("dispersion_frame_integrity_failed", "色散帧压缩 BLOB 无法解码") from exc
    if points_count <= 0 or len(raw) != points_count * 2 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DispersionError(
            "dispersion_frame_integrity_failed",
            "色散帧长度或 SHA-256 校验失败",
            details={"points_count": points_count, "byte_length": len(raw)},
        )
    return list(struct.unpack(f"<{points_count}H", raw))


class DispersionState(str, Enum):
    DRAFT = "draft"
    PRE_EXCITATION = "pre_excitation"
    BURN = "burn"
    DARK = "dark"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class DispersionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _finite(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DispersionError("dispersion_value_invalid", f"{field} must be numeric", details={"field": field}) from exc
    if not math.isfinite(result):
        raise DispersionError("dispersion_value_invalid", f"{field} must be finite", details={"field": field})
    return result


def _gaussian_solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise DispersionError("calibration_singular", "定位点不能形成可逆的校准拟合", details={"column": column})
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) < 1e-15:
                continue
            augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[column])]
    return [augmented[index][-1] for index in range(size)]


def _fit_polynomial(x_values: list[float], y_values: list[float], degree: int) -> list[float]:
    if len(x_values) != len(y_values) or len(x_values) < degree + 1:
        raise DispersionError(
            "calibration_points_insufficient",
            "校准定位点数量不足",
            details={"required": degree + 1, "actual": len(x_values), "degree": degree},
        )
    center = sum(x_values) / len(x_values)
    scale = max(max(abs(value - center) for value in x_values), 1.0)
    normalized = [(value - center) / scale for value in x_values]
    matrix: list[list[float]] = []
    vector: list[float] = []
    for row_power in range(degree + 1):
        matrix.append([sum(x ** (row_power + column_power) for x in normalized) for column_power in range(degree + 1)])
        vector.append(sum((x ** row_power) * y for x, y in zip(normalized, y_values)))
    normalized_coefficients = _gaussian_solve(matrix, vector)
    ascending = [0.0] * (degree + 1)
    for power, coefficient in enumerate(normalized_coefficients):
        for raw_power in range(power + 1):
            ascending[raw_power] += coefficient * math.comb(power, raw_power) * ((-center) ** (power - raw_power)) / (scale**power)
    if degree == 1:
        return [0.0, ascending[1], ascending[0]]
    return list(reversed(ascending))


def _evaluate(coefficients: list[float], value: float) -> float:
    result = 0.0
    for coefficient in coefficients:
        result = result * value + coefficient
    return result


def _calibration_position(wavelength: float, coefficients: list[float]) -> float:
    return _evaluate(coefficients, wavelength)


@dataclass
class _TaskContext:
    task: sqlite3.Row
    layout: sqlite3.Row
    profile: sqlite3.Row


class DispersionService:
    """S12 dispersion acquisition and immutable calibration application service."""

    def __init__(self, database: Database):
        self.database = database
        self._adapters: dict[int, AcqSimulatorAdapter] = {}

    @staticmethod
    def _decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for field in ("ccd_indices_json", "condition_json", "last_event_json"):
            value = result.pop(field, None)
            output = field.removesuffix("_json")
            if value in (None, ""):
                result[output] = None if field == "last_event_json" else ({} if field == "condition_json" else [])
            else:
                result[output] = json.loads(value)
        result["status"] = str(result["status"])
        return result

    @staticmethod
    def _line_decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["position_state"] = str(result["position_state"])
        return result

    @staticmethod
    def _calibration_decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for field in ("coefficients_json", "residuals_json"):
            value = result.pop(field, "[]")
            result[field.removesuffix("_json")] = json.loads(value or "[]")
        result["publishable"] = result["state"] == "published" or result["residual_max"] <= result["residual_limit_points"]
        return result

    def _context(self, task_id: int, db: sqlite3.Connection | None = None) -> _TaskContext:
        if db is None:
            with self.database.read() as connection:
                return self._context(task_id, connection)
        task = db.execute("SELECT * FROM dispersion_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise DispersionError("dispersion_task_not_found", "色散采集任务不存在", details={"task_id": task_id}, status_code=404)
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()
        profile = db.execute("SELECT * FROM device_profiles WHERE id=?", (task["device_profile_id"],)).fetchone()
        if layout is None or profile is None:
            raise DispersionError("dispersion_configuration_missing", "采集任务引用的布局或设备档案不存在", status_code=409)
        return _TaskContext(task, layout, profile)

    @staticmethod
    def _resolve_layout(db: sqlite3.Connection, reference: str | int) -> sqlite3.Row:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            row = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (int(reference),)).fetchone()
        else:
            row = db.execute("SELECT * FROM ccd_layouts WHERE name=?", (str(reference),)).fetchone()
        if row is None:
            raise DispersionError("ccd_layout_not_found", "未找到 CCD 布局", details={"ccd_layout_id": reference}, status_code=404)
        return row

    @staticmethod
    def _profile(db: sqlite3.Connection, profile_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
        if row is None:
            raise DispersionError("device_profile_not_found", "未找到启用的设备档案", details={"profile_id": profile_id}, status_code=404)
        if row["transport"] != "simulator":
            raise DispersionError("dispersion_transport_unavailable", "S12 当前仅支持确定性模拟器", status_code=409)
        return row

    @staticmethod
    def _layout_indices(layout: sqlite3.Row) -> list[int]:
        return [int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")]

    @staticmethod
    def _profile_dict(profile: sqlite3.Row) -> dict[str, Any]:
        result = dict(profile)
        result["ccd_indices"] = json.loads(result.pop("ccd_indices_json") or "[]")
        result["mirror"] = bool(result["mirror"])
        result["enabled"] = bool(result["enabled"])
        return result

    @staticmethod
    def _geometry(layout: sqlite3.Row, ccd_index: int) -> tuple[float, int]:
        indices = DispersionService._layout_indices(layout)
        if ccd_index not in indices:
            raise DispersionError("ccd_index_invalid", "CCD 不在当前布局中", details={"ccd_index": ccd_index, "allowed": indices})
        points = int(layout["points_per_ccd"])
        gaps = [float(value) for value in json.loads(layout["gap_points_json"] or "[]")]
        return ccd_index * points + sum(gaps[:ccd_index]), points

    @staticmethod
    def _default_coefficients(db: sqlite3.Connection, layout_id: int) -> list[float]:
        row = db.execute(
            "SELECT coefficients_json FROM dispersion_calibrations WHERE ccd_layout_id=? AND enabled=1 ORDER BY id LIMIT 1",
            (layout_id,),
        ).fetchone()
        coefficients = json.loads(row[0]) if row else []
        if len(coefficients) >= 3:
            return [float(value) for value in coefficients[:3]]
        layout = db.execute("SELECT wavelength_min, wavelength_max, points_per_ccd, ccd_indices_json FROM ccd_layouts WHERE id=?", (layout_id,)).fetchone()
        if layout is None or layout["wavelength_max"] <= layout["wavelength_min"]:
            raise DispersionError("calibration_reference_missing", "当前布局没有可用的色散参考")
        total = len(json.loads(layout["ccd_indices_json"] or "[]")) * int(layout["points_per_ccd"])
        slope = total / (float(layout["wavelength_max"]) - float(layout["wavelength_min"]))
        return [0.0, slope, -float(layout["wavelength_min"]) * slope]

    def _expected_position(self, db: sqlite3.Connection, layout: sqlite3.Row, wavelength: float, ccd_index: int) -> float | None:
        coefficients = self._default_coefficients(db, int(layout["id"]))
        global_position = _calibration_position(wavelength, coefficients)
        left, points = self._geometry(layout, ccd_index)
        local = global_position - left
        return local if 0 <= local <= points - 1 else None

    def _task_dict(self, task_id: int, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        if db is None:
            with self.database.read() as connection:
                return self._task_dict(task_id, connection)
        context = self._context(task_id, db)
        task = self._decode(context.task)
        task["layout"] = {
            "id": context.layout["id"],
            "name": context.layout["name"],
            "frame_count": context.layout["frame_count"],
            "ccds_per_frame": context.layout["ccds_per_frame"],
            "points_per_ccd": context.layout["points_per_ccd"],
            "ccd_indices": self._layout_indices(context.layout),
        }
        task["profile"] = {"id": context.profile["id"], "name": context.profile["name"], "transport": context.profile["transport"]}
        task["lines"] = [self._line_decode(row) for row in db.execute("SELECT * FROM dispersion_task_lines WHERE task_id=? ORDER BY wavelength_nm, id", (task_id,)).fetchall()]
        task["frame_summary"] = [dict(row) for row in db.execute("SELECT phase, COUNT(DISTINCT frame_index) AS frame_count, MAX(frame_index) AS last_frame_index FROM dispersion_task_frames WHERE task_id=? GROUP BY phase", (task_id,)).fetchall()]
        task["calibrations"] = [self._calibration_decode(row) for row in db.execute("SELECT * FROM dispersion_calibration_versions WHERE source_task_id=? ORDER BY version DESC, id DESC", (task_id,)).fetchall()]
        return task

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [int(row[0]) for row in db.execute("SELECT id FROM dispersion_tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
            return [self._task_dict(task_id, db) for task_id in ids]

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            layouts = []
            for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall():
                layouts.append({
                    "id": row["id"], "name": row["name"], "frame_count": row["frame_count"],
                    "ccds_per_frame": row["ccds_per_frame"], "points_per_ccd": row["points_per_ccd"],
                    "point_width_um": row["point_width"], "ccd_indices": self._layout_indices(row),
                    "wavelength_min": row["wavelength_min"], "wavelength_max": row["wavelength_max"],
                })
            calibrations = [self._calibration_decode(row) for row in db.execute("SELECT * FROM dispersion_calibration_versions WHERE state='published' ORDER BY created_at DESC").fetchall()]
            profiles = [dict(row) | {"ccd_indices": json.loads(row["ccd_indices_json"] or "[]")} for row in db.execute("SELECT id, name, transport, frame_count, ccds_per_frame, points_per_ccd, ccd_indices_json FROM device_profiles WHERE enabled=1 ORDER BY id").fetchall()]
            return {"ccd_layouts": layouts, "calibration_versions": calibrations, "device_profiles": profiles, "states": [state.value for state in DispersionState]}

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            layout = self._resolve_layout(db, payload.get("ccd_layout_id", "default"))
            profile = self._profile(db, int(payload.get("device_profile_id", 1)))
            frame_count = int(payload.get("frame_count", 3))
            dark_count = int(payload.get("dark_frame_count", 0))
            pre_seconds = _finite(payload.get("pre_excitation_seconds", 3), "pre_excitation_seconds")
            period = _finite(payload.get("sampling_period_seconds", 1), "sampling_period_seconds")
            residual_limit = _finite(payload.get("residual_limit_points", 2), "residual_limit_points")
            if frame_count < 1 or frame_count > 255 or dark_count < 0 or dark_count > 20:
                raise DispersionError("dispersion_condition_invalid", "燃烧帧数或暗帧数超出范围")
            if pre_seconds < 0 or pre_seconds > 600 or period <= 0 or period > 60 or residual_limit <= 0:
                raise DispersionError("dispersion_condition_invalid", "采集条件超出范围")
            selected = payload.get("ccd_indices") or self._layout_indices(layout)
            try:
                selected = [int(value) for value in selected]
            except (TypeError, ValueError) as exc:
                raise DispersionError("ccd_indices_invalid", "CCD 索引必须是整数") from exc
            allowed = self._layout_indices(layout)
            if not selected or len(selected) != len(set(selected)) or any(value not in allowed for value in selected):
                raise DispersionError("ccd_indices_invalid", "CCD 选择必须是当前布局的唯一子集", details={"allowed": allowed})
            method_id = payload.get("method_id")
            method_version = payload.get("method_version")
            if method_id is not None:
                query = "SELECT id, version FROM method_versions WHERE method_id=? AND state='published'"
                args: tuple[Any, ...] = (int(method_id),)
                if method_version is not None:
                    query += " AND version=?"
                    args += (int(method_version),)
                query += " ORDER BY version DESC LIMIT 1"
                method_row = db.execute(query, args).fetchone()
                if method_row is None:
                    raise DispersionError("method_revision_not_found", "未找到可绑定的已发布方法修订", status_code=404)
                method_version = int(method_row["version"])
            now = utc_now()
            condition = {key: payload.get(key) for key in ("sample", "seed", "frame_count", "dark_frame_count", "pre_excitation_seconds", "sampling_period_seconds", "residual_limit_points")}
            cursor = db.execute(
                "INSERT INTO dispersion_tasks(name, status, device_profile_id, ccd_layout_id, method_id, method_version, frame_count, dark_frame_count, pre_excitation_seconds, sampling_period_seconds, residual_limit_points, ccd_indices_json, condition_json, created_by, created_at, updated_at) VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(payload.get("name", "S12 色散校准")).strip(), profile["id"], layout["id"], method_id, method_version, frame_count, dark_count, pre_seconds, period, residual_limit, _json(selected), _json(condition), actor_user_id, now, now),
            )
            task_id = int(cursor.lastrowid)
            for line in payload.get("lines", []):
                self._insert_line(db, task_id, layout, line, now)
            self._audit(db, actor_user_id, "dispersion.task.create", task_id, {"ccd_layout_id": layout["id"], "frame_count": frame_count, "dark_frame_count": dark_count})
            return self._task_dict(task_id, db)

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self._task_dict(task_id)

    def _adapter(self, task_id: int, profile: sqlite3.Row) -> AcqSimulatorAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = AcqSimulatorAdapter()
            self._adapters[task_id] = adapter
        if adapter.state == AcquisitionState.IDLE:
            adapter.connect(self._profile_dict(profile), correlation_id=f"dispersion-{task_id}")
        return adapter

    def start_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        status = str(context.task["status"])
        if status in {DispersionState.PRE_EXCITATION.value, DispersionState.BURN.value, DispersionState.DARK.value, DispersionState.PAUSED.value}:
            return self._task_dict(task_id)
        if status != DispersionState.DRAFT.value:
            raise DispersionError("dispersion_task_not_startable", "当前任务状态不能开始采集", details={"status": status}, status_code=409)
        try:
            adapter = self._adapter(task_id, context.profile)
            event = adapter.start_debug(sample=json.loads(context.task["condition_json"] or "{}").get("sample", "280-288.acq"), seed=int(json.loads(context.task["condition_json"] or "{}").get("seed", 0)), fault_frame=None, correlation_id=f"dispersion-{task_id}")
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise DispersionError("dispersion_start_failed", exc.message, details=exc.detail(), status_code=exc.status_code) from exc
        now = utc_now()
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status='pre_excitation', paused_from=NULL, adapter_session_id=?, last_event_json=?, started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?", (adapter.session_id, _json(event.to_dict()), now, now, task_id))
            self._audit(db, actor_user_id, "dispersion.task.start", task_id, {"correlation_id": event.correlation_id, "state": "pre_excitation"})
        return self._task_dict(task_id)

    def _store_event(self, db: sqlite3.Connection, task_id: int, phase: str, phase_index: int, event: Any, selected: list[int], virtual_time_ms: float) -> None:
        details = event.details or {}
        ccd_by_index = {int(item["ccd_index"]): item for item in event.ccds}
        now = utc_now()
        for ccd_index in selected:
            ccd = ccd_by_index.get(ccd_index)
            if ccd is None:
                raise DispersionError("ccd_frame_missing", "采集帧缺少已选择的 CCD", details={"ccd_index": ccd_index, "frame_index": phase_index})
            raw_points = _pack_points(ccd["points"])
            points_blob = zlib.compress(raw_points, level=9)
            db.execute(
                "INSERT INTO dispersion_task_frames(task_id, phase, frame_index, ccd_index, points_blob, points_count, dtype, endianness, compression, points_sha256, raw_transfer_sha256, headers_json, raw_byte_length, virtual_time_ms, captured_at) VALUES (?, ?, ?, ?, ?, ?, 'uint16', 'little', 'zlib', ?, ?, ?, ?, ?, ?)",
                (task_id, phase, phase_index, ccd_index, points_blob, len(ccd["points"]), hashlib.sha256(raw_points).hexdigest(), details.get("sha256", ""), _json(details.get("headers", [])), int(details.get("byte_length", 0)), virtual_time_ms, now),
            )

    def _advance_once(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        status = str(context.task["status"])
        if status == DispersionState.PRE_EXCITATION.value:
            event = json.loads(context.task["last_event_json"] or "{}")
            class StoredEvent:
                pass
            stored = StoredEvent()
            stored.ccds = event.get("ccds", [])
            stored.details = event.get("details", {})
            stored.frame_index = event.get("frame_index")
            stored.correlation_id = event.get("correlation_id", f"dispersion-{task_id}")
            stored.to_dict = lambda: event
            with self.database.write() as db:
                self._store_event(db, task_id, "burn", 0, stored, json.loads(context.task["ccd_indices_json"]), float(context.task["pre_excitation_seconds"]) * 1000)
                burn_count = 1
                new_state = "dark" if burn_count >= int(context.task["frame_count"]) and int(context.task["dark_frame_count"]) > 0 else ("completed" if burn_count >= int(context.task["frame_count"]) else "burn")
                db.execute("UPDATE dispersion_tasks SET status=?, burn_frames_captured=?, dark_frames_captured=0, last_frame_index=?, last_event_json=?, updated_at=?, completed_at=? WHERE id=?", (new_state, burn_count, 0, _json(event), utc_now(), utc_now() if new_state == "completed" else None, task_id))
                self._audit(db, actor_user_id, "dispersion.frame.capture", task_id, {"phase": "burn", "frame_index": 0})
            if new_state == "completed":
                self._close_adapter(task_id)
            return self._task_dict(task_id)
        if status not in {DispersionState.BURN.value, DispersionState.DARK.value}:
            raise DispersionError("dispersion_task_not_running", "当前任务未处于可采集状态", details={"status": status}, status_code=409)
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = self._adapter(task_id, context.profile)
        try:
            event = adapter.step_debug(correlation_id=f"dispersion-{task_id}")
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise DispersionError("dispersion_frame_failed", exc.message, details=exc.detail(), status_code=exc.status_code) from exc
        if event.event_type == "fault":
            self._fail_task(task_id, str(event.details.get("code", "device_fault")), event.message, actor_user_id)
            return self._task_dict(task_id)
        phase = "burn" if status == DispersionState.BURN.value else "dark"
        burn_count = int(context.task["burn_frames_captured"])
        dark_count = int(context.task["dark_frames_captured"])
        phase_index = burn_count if phase == "burn" else dark_count
        with self.database.write() as db:
            virtual_time_ms = (float(context.task["pre_excitation_seconds"]) + (phase_index if phase == "burn" else int(context.task["frame_count"]) + phase_index) * float(context.task["sampling_period_seconds"])) * 1000
            self._store_event(db, task_id, phase, phase_index, event, json.loads(context.task["ccd_indices_json"]), virtual_time_ms)
            burn_count += 1 if phase == "burn" else 0
            dark_count += 1 if phase == "dark" else 0
            completed = burn_count >= int(context.task["frame_count"]) and dark_count >= int(context.task["dark_frame_count"])
            if phase == "burn" and burn_count >= int(context.task["frame_count"]):
                new_state = "dark" if int(context.task["dark_frame_count"]) > 0 else "completed"
            elif phase == "dark" and dark_count >= int(context.task["dark_frame_count"]):
                new_state = "completed"
            else:
                new_state = phase
            db.execute("UPDATE dispersion_tasks SET status=?, burn_frames_captured=?, dark_frames_captured=?, last_frame_index=?, last_event_json=?, updated_at=?, completed_at=? WHERE id=?", (new_state, burn_count, dark_count, event.frame_index, _json(event.to_dict()), utc_now(), utc_now() if completed else None, task_id))
            self._audit(db, actor_user_id, "dispersion.frame.capture", task_id, {"phase": phase, "frame_index": phase_index, "sha256": event.details.get("sha256")})
        if new_state == "completed":
            self._close_adapter(task_id)
        return self._task_dict(task_id)

    def step_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._advance_once(task_id, actor_user_id)

    def pause_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        status = str(context.task["status"])
        if status == DispersionState.PAUSED.value:
            return self._task_dict(task_id)
        if status not in {DispersionState.PRE_EXCITATION.value, DispersionState.BURN.value, DispersionState.DARK.value}:
            raise DispersionError("dispersion_task_not_pauseable", "当前任务不能暂停", details={"status": status}, status_code=409)
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status='paused', paused_from=?, updated_at=? WHERE id=?", (status, utc_now(), task_id))
            self._audit(db, actor_user_id, "dispersion.task.pause", task_id, {"from": status})
        return self._task_dict(task_id)

    def resume_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        status = str(context.task["status"])
        if status != DispersionState.PAUSED.value:
            if status in {DispersionState.PRE_EXCITATION.value, DispersionState.BURN.value, DispersionState.DARK.value}:
                return self._task_dict(task_id)
            raise DispersionError("dispersion_task_not_resumable", "当前任务未暂停", details={"status": status}, status_code=409)
        target = context.task["paused_from"] or "burn"
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status=?, paused_from=NULL, updated_at=? WHERE id=?", (target, utc_now(), task_id))
            self._audit(db, actor_user_id, "dispersion.task.resume", task_id, {"to": target})
        return self._task_dict(task_id)

    def _close_adapter(self, task_id: int) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            try:
                adapter.stop_debug(correlation_id=f"dispersion-{task_id}")
                adapter.disconnect(correlation_id=f"dispersion-{task_id}")
            except DeviceError:
                pass

    def stop_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        status = str(context.task["status"])
        if status in {DispersionState.COMPLETED.value, DispersionState.FAILED.value, DispersionState.STOPPED.value}:
            return self._task_dict(task_id)
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status='stopping', updated_at=? WHERE id=?", (utc_now(), task_id))
            self._audit(db, actor_user_id, "dispersion.task.stop.request", task_id, {"from": status})
        self._close_adapter(task_id)
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status='stopped', completed_at=COALESCE(completed_at, ?), updated_at=? WHERE id=?", (utc_now(), utc_now(), task_id))
            self._audit(db, actor_user_id, "dispersion.task.stop", task_id, {"from": status})
        return self._task_dict(task_id)

    def _fail_task(self, task_id: int, code: str, message: str, actor_user_id: int | None = None) -> None:
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status='failed', failure_code=?, failure_message=?, updated_at=?, completed_at=? WHERE id=?", (code, message, utc_now(), utc_now(), task_id))
            self._audit(db, actor_user_id, "dispersion.task.failed", task_id, {"code": code, "message": message})
        self._close_adapter(task_id)

    def frames(self, task_id: int, *, phase: str | None = None, ccd_index: int | None = None) -> list[dict[str, Any]]:
        self._context(task_id)
        if phase is not None and phase not in {"burn", "dark"}:
            raise DispersionError("dispersion_phase_invalid", "帧阶段必须是 burn 或 dark", details={"phase": phase})
        with self.database.read() as db:
            query = "SELECT * FROM dispersion_task_frames WHERE task_id=?"
            args: list[Any] = [task_id]
            if phase:
                query += " AND phase=?"
                args.append(phase)
            if ccd_index is not None:
                query += " AND ccd_index=?"
                args.append(ccd_index)
            query += " ORDER BY phase, frame_index, ccd_index"
            rows = []
            for row in db.execute(query, args).fetchall():
                item = dict(row)
                item["points"] = _unpack_points(item.pop("points_blob"), int(item["points_count"]), item["points_sha256"], item["compression"])
                item["sha256"] = item["raw_transfer_sha256"]
                item["byte_length"] = item["raw_byte_length"]
                item["headers"] = json.loads(item.pop("headers_json") or "[]")
                rows.append(item)
            return rows

    def _insert_line(self, db: sqlite3.Connection, task_id: int, layout: sqlite3.Row, payload: dict[str, Any], now: str | None = None) -> int:
        element = str(payload.get("element", "")).strip()
        wavelength = _finite(payload.get("wavelength_nm"), "wavelength_nm")
        ccd_index = int(payload.get("ccd_index", 0))
        if not element or not 1 <= len(element) <= 20:
            raise DispersionError("dispersion_line_invalid", "谱线元素不能为空或过长", details={"field": "element"})
        if wavelength < float(layout["wavelength_min"]) or wavelength > float(layout["wavelength_max"]):
            raise DispersionError("line_wavelength_out_of_range", "谱线波长超出当前布局范围", details={"wavelength_nm": wavelength, "minimum": layout["wavelength_min"], "maximum": layout["wavelength_max"]})
        left, points = self._geometry(layout, ccd_index)
        expected = self._expected_position(db, layout, wavelength, ccd_index)
        actual = payload.get("actual_position")
        if actual is not None:
            actual = _finite(actual, "actual_position")
            if actual < 0 or actual > points - 1:
                raise DispersionError("line_position_out_of_range", "实测位置超出 CCD 范围", details={"position": actual, "points": points})
        now = now or utc_now()
        duplicate = db.execute("SELECT id, wavelength_nm FROM dispersion_task_lines WHERE task_id=? AND ccd_index=? AND ABS(wavelength_nm - ?) <= 0.01 LIMIT 1", (task_id, ccd_index, wavelength)).fetchone()
        if duplicate is not None:
            raise DispersionError("dispersion_line_duplicate", "同一 CCD 中 ±0.01 nm 内不能重复添加校准谱线", details={"existing_line_id": duplicate["id"], "existing_wavelength_nm": duplicate["wavelength_nm"]}, status_code=409)
        try:
            cursor = db.execute("INSERT INTO dispersion_task_lines(task_id, element, wavelength_nm, ccd_index, expected_position, located_position, saved_position, position_state, position_source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (task_id, element, wavelength, ccd_index, expected, actual, actual, "saved" if actual is not None else "pending", "manual" if actual is not None else None, now, now))
        except sqlite3.IntegrityError as exc:
            raise DispersionError("dispersion_line_duplicate", "同一任务中不能重复添加相同 CCD 的谱线", status_code=409) from exc
        return int(cursor.lastrowid)

    def add_line(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        with self.database.write() as db:
            line_id = self._insert_line(db, task_id, context.layout, payload)
            self._audit(db, actor_user_id, "dispersion.line.create", line_id, {"task_id": task_id, "wavelength_nm": payload.get("wavelength_nm"), "ccd_index": payload.get("ccd_index", 0)})
            return self._line_decode(db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone())

    def delete_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)).fetchone()
            if row is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            db.execute("DELETE FROM dispersion_task_lines WHERE id=?", (line_id,))
            self._audit(db, actor_user_id, "dispersion.line.delete", line_id, {"task_id": task_id})
            return {"id": line_id, "deleted": True}

    def locate_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        with self.database.write() as db:
            line = db.execute("SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)).fetchone()
            if line is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            expected = line["expected_position"]
            if expected is None:
                raise DispersionError("line_wavelength_out_of_range", "谱线没有落入当前 CCD 的有效范围")
            frame = db.execute("SELECT * FROM dispersion_task_frames WHERE task_id=? AND phase='burn' AND ccd_index=? ORDER BY frame_index DESC LIMIT 1", (task_id, line["ccd_index"])).fetchone()
            if frame is None:
                raise DispersionError("dispersion_frames_missing", "至少采集一帧燃烧帧后才能定位谱线", status_code=409)
            points = _unpack_points(frame["points_blob"], int(frame["points_count"]), frame["points_sha256"], frame["compression"])
            start = max(0, int(round(expected)) - 24)
            end = min(len(points), int(round(expected)) + 25)
            if start >= end:
                raise DispersionError("line_position_out_of_range", "定位窗口超出 CCD 范围")
            peak = max(range(start, end), key=lambda index: points[index])
            adjustment = float(line["adjustment_points"] or 0)
            located = max(0.0, min(len(points) - 1.0, float(peak) + adjustment))
            db.execute("UPDATE dispersion_task_lines SET located_position=?, position_state='located', position_source='frame', position_frame_id=?, updated_at=? WHERE id=?", (located, frame["id"], utc_now(), line_id))
            self._audit(db, actor_user_id, "dispersion.line.locate", line_id, {"task_id": task_id, "frame_id": frame["id"], "position": located})
            return self._line_decode(db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone())

    def locate_all(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        self._context(task_id)
        with self.database.read() as db:
            line_ids = [int(row[0]) for row in db.execute("SELECT id FROM dispersion_task_lines WHERE task_id=? ORDER BY id", (task_id,)).fetchall()]
        located: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for line_id in line_ids:
            try:
                located.append(self.locate_line(task_id, line_id, actor_user_id))
            except DispersionError as exc:
                errors.append({"line_id": line_id, **exc.detail()})
        return {"task_id": task_id, "located": located, "errors": errors, "all_succeeded": not errors}

    def move_line(self, task_id: int, line_id: int, direction: str, steps: float, actor_user_id: int | None = None) -> dict[str, Any]:
        sign = -1.0 if direction == "short" else 1.0 if direction == "long" else 0.0
        if sign == 0:
            raise DispersionError("line_move_invalid", "方向必须是 short 或 long")
        with self.database.write() as db:
            line = db.execute("SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)).fetchone()
            if line is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            current = line["located_position"] if line["located_position"] is not None else line["expected_position"]
            if current is None:
                raise DispersionError("line_position_missing", "谱线尚未定位")
            _, points = self._geometry(self._context(task_id, db).layout, int(line["ccd_index"]))
            position = max(0.0, min(points - 1.0, float(current) + sign * _finite(steps, "steps")))
            adjustment = float(line["adjustment_points"] or 0) + sign * float(steps)
            db.execute("UPDATE dispersion_task_lines SET located_position=?, position_state='located', position_source='manual_adjustment', adjustment_points=?, updated_at=? WHERE id=?", (position, adjustment, utc_now(), line_id))
            self._audit(db, actor_user_id, "dispersion.line.move", line_id, {"task_id": task_id, "direction": direction, "steps": steps, "position": position})
            return self._line_decode(db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone())

    def save_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._save_or_restore_position(task_id, line_id, restore=False, actor_user_id=actor_user_id)

    def restore_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._save_or_restore_position(task_id, line_id, restore=True, actor_user_id=actor_user_id)

    def _save_or_restore_position(self, task_id: int, line_id: int, *, restore: bool, actor_user_id: int | None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)).fetchone()
            if row is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            if restore:
                if row["saved_position"] is None:
                    raise DispersionError("line_saved_position_missing", "该谱线没有可恢复的实测位置", status_code=409)
                position = float(row["saved_position"])
                action = "dispersion.line.position.restore"
            else:
                if row["located_position"] is None:
                    raise DispersionError("line_position_missing", "谱线尚未定位", status_code=409)
                position = float(row["located_position"])
                action = "dispersion.line.position.save"
            if restore:
                db.execute("UPDATE dispersion_task_lines SET located_position=?, position_state='saved', updated_at=? WHERE id=?", (position, utc_now(), line_id))
            else:
                db.execute("UPDATE dispersion_task_lines SET saved_position=?, position_state='saved', updated_at=? WHERE id=?", (position, utc_now(), line_id))
            self._audit(db, actor_user_id, action, line_id, {"task_id": task_id, "position": position})
            return self._line_decode(db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone())

    def fit_calibration(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        context = self._context(task_id)
        degree = int(payload.get("degree", 2))
        with self.database.read() as db:
            rows = db.execute("SELECT * FROM dispersion_task_lines WHERE task_id=? ORDER BY wavelength_nm, id", (task_id,)).fetchall()
            values: list[tuple[sqlite3.Row, float, float]] = []
            seen_wavelengths: list[float] = []
            for row in rows:
                position = row["saved_position"] if row["saved_position"] is not None else row["located_position"]
                if position is None:
                    continue
                wavelength = float(row["wavelength_nm"])
                if any(math.isclose(wavelength, old, abs_tol=0.01) for old in seen_wavelengths):
                    raise DispersionError("calibration_duplicate_wavelength", "校准谱线不能有重复波长", details={"wavelength_nm": wavelength})
                seen_wavelengths.append(wavelength)
                left, _ = self._geometry(context.layout, int(row["ccd_index"]))
                values.append((row, wavelength, left + float(position)))
            coefficients = _fit_polynomial([item[1] for item in values], [item[2] for item in values], degree)
            residuals = []
            errors = []
            for row, wavelength, actual in values:
                predicted = _evaluate(coefficients, wavelength)
                residual = predicted - actual
                residuals.append({"line_id": row["id"], "element": row["element"], "wavelength_nm": wavelength, "ccd_index": row["ccd_index"], "measured_position": actual, "predicted_position": predicted, "residual_points": residual})
                errors.append(residual)
        rms = math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else math.inf
        maximum = max((abs(error) for error in errors), default=math.inf)
        residual_limit = float(payload.get("residual_limit_points") or context.task["residual_limit_points"])
        name = str(payload.get("name") or f"S12 task {task_id}").strip()
        with self.database.write() as db:
            version_row = db.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM dispersion_calibration_versions WHERE name=?", (name,)).fetchone()
            version = int(version_row[0])
            now = utc_now()
            cursor = db.execute("INSERT INTO dispersion_calibration_versions(name, version, state, calibration_id, ccd_layout_id, source_task_id, coefficients_json, residuals_json, wavelength_min, wavelength_max, residual_rms, residual_max, point_count, residual_limit_points, created_by, created_at) VALUES (?, ?, 'draft', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (name, version, context.layout["id"], task_id, _json(coefficients), _json(residuals), min(item[1] for item in values), max(item[1] for item in values), rms, maximum, len(values), residual_limit, actor_user_id, now))
            calibration_id = int(cursor.lastrowid)
            self._audit(db, actor_user_id, "dispersion.calibration.fit", calibration_id, {"task_id": task_id, "degree": degree, "point_count": len(values), "residual_rms": rms, "residual_max": maximum})
            return self._calibration_decode(db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_id,)).fetchone())

    def publish_calibration(self, calibration_version_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_version_id,)).fetchone()
            if row is None:
                raise DispersionError("calibration_version_not_found", "校准版本不存在", status_code=404)
            if row["state"] == "published":
                return self._calibration_decode(row)
            if row["state"] != "draft":
                raise DispersionError("calibration_version_not_publishable", "当前校准版本不能发布", status_code=409)
            if int(row["point_count"]) < 3:
                raise DispersionError("calibration_points_insufficient", "至少需要三个不同定位点才能发布")
            if float(row["residual_max"]) > float(row["residual_limit_points"]):
                raise DispersionError("calibration_residual_exceeded", "校准残差超过发布阈值", details={"residual_max": row["residual_max"], "limit": row["residual_limit_points"]})
            base_name = str(row["name"])
            name = base_name
            if db.execute("SELECT 1 FROM dispersion_calibrations WHERE name=?", (name,)).fetchone():
                name = f"{base_name} · v{row['version']}"
            cursor = db.execute("INSERT INTO dispersion_calibrations(name, ccd_layout_id, wavelength_min, wavelength_max, coefficients_json, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)", (name, row["ccd_layout_id"], row["wavelength_min"], row["wavelength_max"], row["coefficients_json"], utc_now()))
            parent_id = int(cursor.lastrowid)
            db.execute("UPDATE dispersion_calibration_versions SET state='published', calibration_id=? WHERE id=?", (parent_id, calibration_version_id))
            self._audit(db, actor_user_id, "dispersion.calibration.publish", calibration_version_id, {"calibration_id": parent_id, "name": name, "version": row["version"]})
            return self._calibration_decode(db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_version_id,)).fetchone())

    def calibration(self, calibration_version_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_version_id,)).fetchone()
            if row is None:
                raise DispersionError("calibration_version_not_found", "校准版本不存在", status_code=404)
            return self._calibration_decode(row)

    def bind_calibration(self, calibration_version_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        method_id = int(payload["method_id"])
        with self.database.write() as db:
            calibration = db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=? AND state='published'", (calibration_version_id,)).fetchone()
            if calibration is None:
                raise DispersionError("calibration_not_published", "只有已发布校准版本才能绑定方法", status_code=409)
            version = payload.get("method_version")
            if version is None:
                method_row = db.execute("SELECT current_version FROM methods WHERE id=?", (method_id,)).fetchone()
                version = method_row[0] if method_row else None
            if version is None:
                raise DispersionError("method_revision_not_found", "方法没有可绑定的当前修订", status_code=404)
            method_version = db.execute("SELECT * FROM method_versions WHERE method_id=? AND version=? AND state='published'", (method_id, int(version))).fetchone()
            if method_version is None:
                raise DispersionError("method_revision_not_found", "未找到已发布方法修订", status_code=404)
            method_payload = json.loads(method_version["payload_json"] or "{}")
            layout_reference = method_payload.get("conditions", {}).get("ccd_layout_id", "default")
            method_layout = self._resolve_layout(db, layout_reference)
            if int(method_layout["id"]) != int(calibration["ccd_layout_id"]):
                raise DispersionError("method_calibration_layout_mismatch", "方法修订与校准版本的 CCD 布局不一致", details={"method_layout_id": method_layout["id"], "calibration_layout_id": calibration["ccd_layout_id"]})
            existing = db.execute("SELECT * FROM method_calibration_bindings WHERE method_version_id=?", (method_version["id"],)).fetchone()
            if existing is not None:
                if int(existing["calibration_version_id"]) == calibration_version_id:
                    return dict(existing)
                raise DispersionError("method_calibration_already_bound", "方法修订已经绑定其他校准版本", status_code=409)
            now = utc_now()
            cursor = db.execute("INSERT INTO method_calibration_bindings(method_version_id, method_id, method_version, calibration_version_id, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)", (method_version["id"], method_id, int(version), calibration_version_id, actor_user_id, now))
            self._audit(db, actor_user_id, "dispersion.calibration.bind", calibration_version_id, {"method_id": method_id, "method_version": int(version), "binding_id": cursor.lastrowid})
            return dict(db.execute("SELECT * FROM method_calibration_bindings WHERE id=?", (cursor.lastrowid,)).fetchone())

    def bindings(self, method_id: int | None = None) -> list[dict[str, Any]]:
        with self.database.read() as db:
            query = "SELECT b.*, c.name AS calibration_name, c.version AS calibration_version, c.state AS calibration_state FROM method_calibration_bindings b JOIN dispersion_calibration_versions c ON c.id=b.calibration_version_id"
            args: tuple[Any, ...] = ()
            if method_id is not None:
                query += " WHERE b.method_id=?"
                args = (method_id,)
            query += " ORDER BY b.created_at DESC"
            return [dict(row) for row in db.execute(query, args).fetchall()]

    def _audit(self, db: sqlite3.Connection, actor_user_id: int | None, action: str, target_id: int | None, details: dict[str, Any]) -> None:
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'dispersion', ?, ?, ?)", (actor_user_id, action, target_id, _json(details), utc_now()))
