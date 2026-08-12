from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import uuid
from enum import Enum
from typing import Any

from ..db import Database, utc_now
from .devices import AcqSimulatorAdapter, AcquisitionState as DeviceAcquisitionState, DeviceError
from .sample_queues import SampleQueueError, SampleQueueService, normalize_name


LOW_AVERAGE = 0.1


class AcquisitionState(str, Enum):
    DRAFT = "draft"
    COUNTDOWN = "countdown"
    PRE_EXCITATION = "pre_excitation"
    BURN = "burn"
    DARK = "dark"
    BETWEEN_REPEATS = "between_repeats"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AcquisitionError(ValueError):
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


_SAMPLE_KINDS = {"evaporation", "blank", "normal", "standard", "test", "preheat"}
_STORAGE_MODES = {"averaged", "full_interval"}
_TASK_KINDS = {"evaporation", "sample"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _finite(value: Any, field: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AcquisitionError("acquisition_condition_invalid", f"{field} 必须是数字", details={"field": field}) from exc
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise AcquisitionError("acquisition_condition_invalid", f"{field} 超出范围", details={"field": field})
    return result


def _pack_uint16(points: list[int]) -> bytes:
    if not points:
        return b""
    if any(point < 0 or point > 65535 for point in points):
        raise AcquisitionError("acquisition_points_invalid", "CCD 点值超出 uint16 范围")
    return struct.pack(f"<{len(points)}H", *points)


def _unpack_uint16(blob: bytes | bytearray | memoryview | None, points_count: int) -> list[int]:
    if blob is None or points_count == 0:
        return []
    expected = points_count * 2
    if len(blob) != expected:
        raise AcquisitionError("acquisition_blob_invalid", "原始 CCD BLOB 长度不匹配", details={"expected": expected, "actual": len(blob)})
    return list(struct.unpack(f"<{points_count}H", blob))


def _pack_float32(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _unpack_float32(blob: bytes, points_count: int) -> list[float]:
    expected = points_count * 4
    if len(blob) != expected:
        raise AcquisitionError("acquisition_blob_invalid", "均值 BLOB 长度不匹配", details={"expected": expected, "actual": len(blob)})
    return list(struct.unpack(f"<{points_count}f", blob))


def average_points(
    burn_blobs: list[bytes],
    dark_blobs: list[bytes],
    points_count: int,
    *,
    burn_cycle_seconds: float = 1.0,
    dark_cycle_seconds: float = 1.0,
) -> bytes:
    """Match TCcdBand.CalAllAvgs: burn mean minus dark mean, floored at LowAvg=0.1."""

    if not burn_blobs:
        raise AcquisitionError("acquisition_burn_missing", "没有可用于均值计算的燃烧帧")
    burns = [_unpack_uint16(blob, points_count) for blob in burn_blobs]
    darks = [_unpack_uint16(blob, points_count) for blob in dark_blobs]
    values: list[float] = []
    for point_index in range(points_count):
        burn = sum(frame[point_index] for frame in burns) / (len(burns) * burn_cycle_seconds)
        dark = sum(frame[point_index] for frame in darks) / (len(darks) * dark_cycle_seconds) if darks else 0.0
        values.append(max(LOW_AVERAGE, burn - dark))
    return _pack_float32(values)


def _sample_kind(name: str) -> str:
    if not name:
        return "blank"
    if re.fullmatch(r"S(?:[0-9]|1[0-5])", name.upper()):
        return "standard"
    return "normal"


class AcquisitionService:
    """S13 evaporation and sample acquisition application service."""

    def __init__(self, database: Database):
        self.database = database
        self.sample_queues = SampleQueueService(database)
        self._adapters: dict[int, AcqSimulatorAdapter] = {}

    @staticmethod
    def _layout_indices(row: sqlite3.Row | dict[str, Any]) -> list[int]:
        return [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]

    @staticmethod
    def _profile_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["ccd_indices"] = [int(value) for value in json.loads(result.pop("ccd_indices_json") or "[]")]
        result["mirror"] = bool(result.get("mirror"))
        result["enabled"] = bool(result.get("enabled", True))
        return result

    def _context(self, task_id: int, db: sqlite3.Connection | None = None) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
        if db is None:
            with self.database.read() as connection:
                return self._context(task_id, connection)
        task = db.execute("SELECT * FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise AcquisitionError("acquisition_task_not_found", "采集任务不存在", details={"task_id": task_id}, status_code=404)
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()
        profile = db.execute("SELECT * FROM device_profiles WHERE id=?", (task["device_profile_id"],)).fetchone()
        if layout is None or profile is None:
            raise AcquisitionError("acquisition_configuration_missing", "采集任务引用的设备或 CCD 布局不存在", status_code=409)
        return task, layout, profile

    @staticmethod
    def _sample_dict(row: sqlite3.Row | dict[str, Any], db: sqlite3.Connection) -> dict[str, Any]:
        result = dict(row)
        result["finalized"] = bool(result["finalized"])
        result["bands"] = [
            {
                "id": band["id"],
                "ccd_index": band["ccd_index"],
                "storage_mode": band["storage_mode"],
                "points_count": band["points_count"],
                "burn_frame_count": band["burn_frame_count"],
                "dark_frame_count": band["dark_frame_count"],
                "mean_sha256": band["mean_sha256"],
                "burn_sha256": band["burn_sha256"],
                "dark_sha256": band["dark_sha256"],
            }
            for band in db.execute("SELECT * FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index", (row["id"],)).fetchall()
        ]
        return result

    def _task_dict(self, task_id: int, db: sqlite3.Connection | None = None, *, include_points: bool = False) -> dict[str, Any]:
        if db is None:
            with self.database.read() as connection:
                return self._task_dict(task_id, connection, include_points=include_points)
        task, layout, profile = self._context(task_id, db)
        result = dict(task)
        for field in ("ccd_indices_json", "excitation_condition_json", "evaporation_condition_json", "simulator_json", "last_event_json"):
            raw = result.pop(field, None)
            result[field.removesuffix("_json")] = json.loads(raw) if raw else ([] if field == "ccd_indices_json" else (None if field == "last_event_json" else {}))
        result["status"] = str(result["status"])
        result["progress"] = round(
            min(100.0, ((int(task["completed_repeats"]) * (int(task["burn_frame_count"]) + int(task["dark_frame_count"]))) + int(task["burn_frames_captured"]) + int(task["dark_frames_captured"])) / max(1, int(task["repeat_count"]) * (int(task["burn_frame_count"]) + int(task["dark_frame_count"]))) * 100),
            2,
        )
        result["layout"] = {
            "id": layout["id"],
            "name": layout["name"],
            "points_per_ccd": layout["points_per_ccd"],
            "ccd_indices": self._layout_indices(layout),
        }
        result["profile"] = {
            "id": profile["id"],
            "name": profile["name"],
            "transport": profile["transport"],
            "mirror": bool(profile["mirror"]),
        }
        samples = [self._sample_dict(row, db) for row in db.execute("SELECT * FROM acquisition_samples WHERE task_id=? ORDER BY repeat_index", (task_id,)).fetchall()]
        result["samples"] = samples
        result["messages"] = [
            dict(row) | {"details": json.loads(row["details_json"] or "{}")}
            for row in db.execute("SELECT * FROM acquisition_messages WHERE task_id=? ORDER BY id DESC LIMIT 40", (task_id,)).fetchall()
        ][::-1]
        result["intervals"] = [
            dict(row)
            for row in db.execute("SELECT * FROM acquisition_intervals WHERE task_id=? ORDER BY repeat_index, start_frame_index", (task_id,)).fetchall()
        ]
        if not include_points and result.get("last_event"):
            event = dict(result["last_event"])
            event["ccds"] = [
                {key: value for key, value in ccd.items() if key != "points"}
                for ccd in event.get("ccds", [])
            ]
            result["last_event"] = event
        return result

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM acquisition_tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]
        return [self._task_dict(task_id) for task_id in ids]

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            profiles = [
                {"id": row["id"], "name": row["name"], "transport": row["transport"], "ccd_indices": json.loads(row["ccd_indices_json"] or "[]"), "points_per_ccd": row["points_per_ccd"]}
                for row in db.execute("SELECT id, name, transport, ccd_indices_json, points_per_ccd FROM device_profiles WHERE enabled=1 ORDER BY id").fetchall()
            ]
            layouts = [
                {"id": row["id"], "name": row["name"], "frame_count": row["frame_count"], "ccds_per_frame": row["ccds_per_frame"], "points_per_ccd": row["points_per_ccd"], "ccd_indices": self._layout_indices(row)}
                for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall()
            ]
            methods = [
                {"method_id": row["method_id"], "method_version": row["version"], "name": row["name"]}
                for row in db.execute("SELECT m.id AS method_id, m.name, v.version FROM methods m JOIN method_versions v ON v.method_id=m.id WHERE v.state='published' ORDER BY m.id, v.version DESC").fetchall()
            ]
        return {"task_kinds": sorted(_TASK_KINDS), "sample_kinds": sorted(_SAMPLE_KINDS), "storage_modes": sorted(_STORAGE_MODES), "states": [state.value for state in AcquisitionState], "profiles": profiles, "layouts": layouts, "methods": methods, "queues": self.sample_queues.list()}

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        task_kind = str(payload.get("task_kind", "sample")).lower()
        if task_kind not in _TASK_KINDS:
            raise AcquisitionError("acquisition_task_kind_invalid", "采集类型必须是 evaporation 或 sample")
        storage_mode = str(payload.get("storage_mode", "averaged")).lower()
        if storage_mode not in _STORAGE_MODES:
            raise AcquisitionError("acquisition_storage_mode_invalid", "保存模式必须是 averaged 或 full_interval")
        queue_id = payload.get("queue_id")
        queue_item_id = payload.get("queue_item_id")
        queue_item: dict[str, Any] | None = None
        if task_kind == "evaporation" and (queue_id is not None or queue_item_id is not None):
            raise AcquisitionError("evaporation_queue_invalid", "蒸发任务不能绑定样品队列")
        if queue_id is not None or queue_item_id is not None:
            if queue_id is None or queue_item_id is None:
                raise AcquisitionError("queue_reference_incomplete", "队列和队列项必须同时提供")
            queue_item = self.sample_queues.get_item(int(queue_id), int(queue_item_id))
            if queue_item["spectrum_hash"]:
                raise AcquisitionError("queue_item_already_acquired", "队列项已经完成采集", status_code=409)
        sample_name = str(payload.get("sample_name", "")).strip()
        naming_mode = str(payload.get("naming_mode", "temporary"))
        if queue_item is not None:
            sample_name = str(queue_item["post_name"] or queue_item["pre_name"] or "")
            naming_mode = "pre_recorded" if sample_name else "post"
            repeat_count = int(queue_item["repeats"] or 1)
            sample_kind = _sample_kind(sample_name)
        elif task_kind == "evaporation":
            repeat_count = 1
            sample_kind = "evaporation"
            sample_name = str(payload.get("sample_name", "")).strip()
            naming_mode = "post" if not sample_name else naming_mode
            storage_mode = "full_interval"
        else:
            repeat_count = int(payload.get("repeat_count", 1))
            if not 1 <= repeat_count <= 10:
                raise AcquisitionError("repeat_invalid", "重复次数必须在 1 到 10 之间")
            sample_kind = str(payload.get("sample_kind", "test")).lower()
            if sample_kind not in _SAMPLE_KINDS - {"evaporation"}:
                raise AcquisitionError("sample_kind_invalid", "样品类型无效")
            if sample_kind == "preheat":
                naming_mode = "temporary"
        task_name = str(payload.get("name", "S13 样品采集" if task_kind == "sample" else "S13 蒸发采集")).strip() or "S13 采集"
        with self.database.write() as db:
            profile_id = int(payload.get("device_profile_id", 1))
            profile = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
            if profile is None:
                raise AcquisitionError("device_profile_not_found", "设备档案不存在", status_code=404)
            if profile["transport"] != "simulator":
                raise AcquisitionError("device_transport_unavailable", "真实串口采集留待 S14", status_code=409)
            layout_key = payload.get("ccd_layout_id", "default")
            layout = db.execute("SELECT * FROM ccd_layouts WHERE id=? OR name=?", (layout_key if str(layout_key).isdigit() else -1, str(layout_key))).fetchone()
            if layout is None:
                raise AcquisitionError("ccd_layout_not_found", "CCD 布局不存在", status_code=404)
            allowed = self._layout_indices(layout)
            selected = [int(value) for value in (payload.get("ccd_indices") or allowed)]
            if not selected or len(selected) != len(set(selected)) or any(value not in allowed for value in selected):
                raise AcquisitionError("ccd_indices_invalid", "CCD 选择必须是当前布局的唯一子集", details={"allowed": allowed})
            if int(profile["points_per_ccd"]) != int(layout["points_per_ccd"]):
                raise AcquisitionError("ccd_layout_profile_mismatch", "设备档案与 CCD 布局点数不一致", status_code=409)
            method_id = payload.get("method_id")
            method_version = payload.get("method_version")
            method_version_id = None
            if method_id is not None:
                query = "SELECT v.id, v.version FROM method_versions v WHERE v.method_id=? AND v.state='published'"
                args: list[Any] = [int(method_id)]
                if method_version is not None:
                    query += " AND v.version=?"
                    args.append(int(method_version))
                query += " ORDER BY v.version DESC LIMIT 1"
                method = db.execute(query, args).fetchone()
                if method is None:
                    raise AcquisitionError("method_revision_not_found", "未找到已发布方法修订", status_code=404)
                method_version_id, method_version = int(method["id"]), int(method["version"])
            burn_count = int(payload.get("burn_frame_count", payload.get("frame_count", 3)))
            dark_count = int(payload.get("dark_frame_count", 1))
            if not 1 <= burn_count <= 255 or not 0 <= dark_count <= 20:
                raise AcquisitionError("acquisition_condition_invalid", "燃烧/暗帧数量超出范围")
            countdown = _finite(payload.get("countdown_seconds", 0), "countdown_seconds", maximum=600)
            pre = _finite(payload.get("pre_excitation_seconds", 1), "pre_excitation_seconds", maximum=600)
            period = _finite(payload.get("sampling_period_seconds", 1), "sampling_period_seconds", minimum=0.001, maximum=60)
            burn_cycle = _finite(payload.get("burn_cycle_seconds", 1), "burn_cycle_seconds", minimum=0.001, maximum=60)
            dark_cycle = _finite(payload.get("dark_cycle_seconds", burn_cycle), "dark_cycle_seconds", minimum=0.001, maximum=60)
            now = utc_now()
            excitation = dict(payload.get("excitation_conditions") or {})
            evaporation = dict(payload.get("evaporation_conditions") or {})
            simulator = {"sample": str(payload.get("simulator_sample", "280-288.acq")), "seed": int(payload.get("seed", 0)), "fault_frame": payload.get("fault_frame")}
            cursor = db.execute(
                "INSERT INTO acquisition_tasks(task_kind, name, status, device_profile_id, ccd_layout_id, method_version_id, method_id, method_version, queue_id, queue_item_id, sample_name, sample_kind, naming_mode, storage_mode, repeat_count, burn_frame_count, dark_frame_count, countdown_seconds, countdown_remaining, pre_excitation_seconds, sampling_period_seconds, burn_cycle_seconds, dark_cycle_seconds, ccd_indices_json, excitation_condition_json, evaporation_condition_json, simulator_json, created_by, created_at, updated_at) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_kind, task_name, profile["id"], layout["id"], method_version_id, method_id, method_version, queue_id, queue_item_id, sample_name, sample_kind, naming_mode, storage_mode, repeat_count, burn_count, dark_count, countdown, countdown, pre, period, burn_cycle, dark_cycle, _json(selected), _json(excitation), _json(evaporation), _json(simulator), actor_user_id, now, now),
            )
            task_id = int(cursor.lastrowid)
            self._message(db, task_id, "info", "task.created", "采集任务已创建", {"task_kind": task_kind, "sample_kind": sample_kind})
            self._audit(db, actor_user_id, "acquisition.task.create", task_id, {"task_kind": task_kind, "queue_item_id": queue_item_id, "repeat_count": repeat_count, "storage_mode": storage_mode})
        return self._task_dict(task_id)

    def _adapter(self, task_id: int, profile: sqlite3.Row) -> AcqSimulatorAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = AcqSimulatorAdapter()
            self._adapters[task_id] = adapter
        if adapter.state == DeviceAcquisitionState.IDLE:
            adapter.connect(self._profile_dict(profile), correlation_id=f"acquisition-{task_id}")
        return adapter

    def _start_adapter(self, task_id: int, task: sqlite3.Row, profile: sqlite3.Row) -> tuple[AcqSimulatorAdapter, Any]:
        adapter = self._adapter(task_id, profile)
        simulator = json.loads(task["simulator_json"] or "{}")
        try:
            event = adapter.start_debug(sample=str(simulator.get("sample", "280-288.acq")), seed=int(simulator.get("seed", 0)) + int(task["current_repeat_index"]), fault_frame=simulator.get("fault_frame"), correlation_id=f"acquisition-{task_id}")
        except DeviceError as exc:
            raise AcquisitionError("acquisition_start_failed", exc.message, details=exc.detail(), status_code=exc.status_code) from exc
        return adapter, event

    def start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self._context(task_id)
        status = str(task["status"])
        if status in {state.value for state in (AcquisitionState.COUNTDOWN, AcquisitionState.PRE_EXCITATION, AcquisitionState.BURN, AcquisitionState.DARK, AcquisitionState.BETWEEN_REPEATS, AcquisitionState.PAUSED)}:
            return self._task_dict(task_id)
        if status != AcquisitionState.DRAFT.value:
            raise AcquisitionError("acquisition_task_not_startable", "当前任务状态不能开始采集", details={"status": status}, status_code=409)
        try:
            adapter, event = self._start_adapter(task_id, task, profile)
        except AcquisitionError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise
        now = utc_now()
        next_state = AcquisitionState.COUNTDOWN.value if float(task["countdown_seconds"]) > 0 else AcquisitionState.PRE_EXCITATION.value
        with self.database.write() as db:
            sample_id = self._create_sample(db, task)
            db.execute("UPDATE acquisition_tasks SET status=?, adapter_session_id=?, countdown_remaining=?, last_event_json=?, last_message=?, started_at=?, updated_at=? WHERE id=?", (next_state, adapter.session_id, task["countdown_seconds"], _json(event.to_dict()), "预激发已准备" if next_state == "pre_excitation" else "倒计时开始", now, now, task_id))
            self._message(db, task_id, "info", "task.start", "采集已开始", {"state": next_state, "sample_id": sample_id})
            self._audit(db, actor_user_id, "acquisition.task.start", task_id, {"state": next_state, "correlation_id": event.correlation_id})
        return self._task_dict(task_id)

    @staticmethod
    def _create_sample(db: sqlite3.Connection, task: sqlite3.Row) -> int:
        cursor = db.execute(
            "INSERT INTO acquisition_samples(task_id, queue_item_id, repeat_index, sample_name_original, sample_name, sample_kind, storage_mode, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'collecting', ?, ?)",
            (task["id"], task["queue_item_id"], task["current_repeat_index"], task["sample_name"], task["sample_name"], task["sample_kind"], task["storage_mode"], utc_now(), utc_now()),
        )
        return int(cursor.lastrowid)

    def _current_sample(self, db: sqlite3.Connection, task_id: int, repeat_index: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM acquisition_samples WHERE task_id=? AND repeat_index=?", (task_id, repeat_index)).fetchone()
        if row is None:
            raise AcquisitionError("acquisition_sample_missing", "当前重复次序缺少样品记录", status_code=409)
        return row

    @staticmethod
    def _message(db: sqlite3.Connection, task_id: int, level: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO acquisition_messages(task_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (task_id, level, code, message, _json(details or {}), utc_now()))

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: int | None, action: str, target_id: int, details: dict[str, Any]) -> None:
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'acquisition', ?, ?, ?)", (actor, action, target_id, _json(details), utc_now()))

    def _store_event(self, db: sqlite3.Connection, task: sqlite3.Row, sample: sqlite3.Row, phase: str, frame_index: int, event: Any, virtual_time_ms: float, *, damaged: bool = False, damage_code: str | None = None, damage_message: str | None = None) -> None:
        selected = [int(value) for value in json.loads(task["ccd_indices_json"] or "[]")]
        by_index = {int(ccd["ccd_index"]): ccd for ccd in (event.ccds or [])}
        details = event.details or {}
        for ccd_index in selected:
            ccd = by_index.get(ccd_index)
            points = [] if damaged or ccd is None else [int(value) for value in ccd.get("points", [])]
            blob = None if damaged or ccd is None else _pack_uint16(points)
            points_sha = hashlib.sha256(blob).hexdigest() if blob is not None else None
            db.execute(
                "INSERT INTO acquisition_frames(task_id, sample_id, repeat_index, phase, frame_index, ccd_index, points_blob, points_count, points_sha256, raw_transfer_sha256, raw_byte_length, headers_json, virtual_time_ms, peak_value, peak_position, integral_value, damaged, damage_code, damage_message, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task["id"], sample["id"], sample["repeat_index"], phase, frame_index, ccd_index, blob, len(points), points_sha, details.get("sha256"), int(details.get("byte_length", 0)), _json(details.get("headers", [])), virtual_time_ms, max(points) if points else None, points.index(max(points)) if points else None, float(sum(points)) if points else None, int(damaged or ccd is None), damage_code, damage_message, utc_now()),
            )

    def _store_damaged(self, db: sqlite3.Connection, task: sqlite3.Row, sample: sqlite3.Row, phase: str, frame_index: int, event: Any) -> None:
        details = event.details or {}
        self._store_event(db, task, sample, phase, frame_index, event, self._virtual_time(task, sample["repeat_index"], phase, frame_index), damaged=True, damage_code=str(details.get("code", "device_fault")), damage_message=event.message or "CCD 帧损坏")

    @staticmethod
    def _virtual_time(task: sqlite3.Row, repeat_index: int, phase: str, frame_index: int) -> float:
        per_repeat = float(task["pre_excitation_seconds"]) + (int(task["burn_frame_count"]) + int(task["dark_frame_count"])) * float(task["sampling_period_seconds"])
        offset = float(task["countdown_seconds"]) + repeat_index * per_repeat + float(task["pre_excitation_seconds"])
        if phase == "dark":
            offset += int(task["burn_frame_count"]) * float(task["sampling_period_seconds"])
        return (offset + frame_index * float(task["sampling_period_seconds"])) * 1000

    def _finalize_sample(self, db: sqlite3.Connection, task: sqlite3.Row, sample: sqlite3.Row, actor_user_id: int | None) -> tuple[bool, str]:
        selected = [int(value) for value in json.loads(task["ccd_indices_json"] or "[]")]
        burn_expected = int(task["burn_frame_count"])
        dark_expected = int(task["dark_frame_count"])
        frames = db.execute("SELECT * FROM acquisition_frames WHERE sample_id=? ORDER BY phase, frame_index, ccd_index", (sample["id"],)).fetchall()
        if any(frame["damaged"] for frame in frames) or len(frames) != len(selected) * (burn_expected + dark_expected):
            raise AcquisitionError("acquisition_frames_incomplete", "当前重复存在损坏或不完整帧，不能完成收尾")
        by_key = {(row["phase"], int(row["frame_index"]), int(row["ccd_index"])): row for row in frames}
        if sample["sample_kind"] == "preheat":
            result_hash = hashlib.sha256("|".join(row["points_sha256"] or "" for row in frames).encode("ascii")).hexdigest()
            db.execute("UPDATE acquisition_samples SET status='completed', finalized=1, result_sha256=?, completed_at=?, updated_at=? WHERE id=?", (result_hash, utc_now(), utc_now(), sample["id"]))
            self._message(db, task["id"], "success", "sample.preheat.completed", "预热采集完成，未写入正式样品谱带", {"sample_id": sample["id"], "result_sha256": result_hash})
            return True, result_hash
        points_count = int(db.execute("SELECT points_per_ccd FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()[0])
        band_hashes: list[str] = []
        for ccd_index in selected:
            burn_rows = [by_key[("burn", index, ccd_index)] for index in range(burn_expected)]
            dark_rows = [by_key[("dark", index, ccd_index)] for index in range(dark_expected)]
            burn_blobs = [bytes(row["points_blob"]) for row in burn_rows]
            dark_blobs = [bytes(row["points_blob"]) for row in dark_rows]
            mean_blob = average_points(burn_blobs, dark_blobs, points_count, burn_cycle_seconds=float(task["burn_cycle_seconds"]), dark_cycle_seconds=float(task["dark_cycle_seconds"]))
            mean_hash = hashlib.sha256(mean_blob).hexdigest()
            burn_blob = b"".join(burn_blobs) if sample["storage_mode"] == "full_interval" else None
            dark_blob = b"".join(dark_blobs) if sample["storage_mode"] == "full_interval" else None
            burn_hash = hashlib.sha256(burn_blob).hexdigest() if burn_blob is not None else None
            dark_hash = hashlib.sha256(dark_blob).hexdigest() if dark_blob is not None else None
            band_hashes.extend(value for value in (mean_hash, burn_hash, dark_hash) if value)
            db.execute("INSERT INTO acquisition_sample_bands(sample_id, ccd_index, storage_mode, points_count, burn_frame_count, dark_frame_count, mean_blob, mean_sha256, burn_frames_blob, burn_sha256, dark_frames_blob, dark_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (sample["id"], ccd_index, sample["storage_mode"], len(mean_blob) // 4, burn_expected, dark_expected, mean_blob, mean_hash, burn_blob, burn_hash, dark_blob, dark_hash, utc_now()))
        result_hash = hashlib.sha256("|".join(band_hashes).encode("ascii")).hexdigest()
        db.execute("UPDATE acquisition_samples SET status='completed', finalized=1, result_sha256=?, completed_at=?, updated_at=? WHERE id=?", (result_hash, utc_now(), utc_now(), sample["id"]))
        self._message(db, task["id"], "success", "sample.completed", "当前重复采集完成", {"sample_id": sample["id"], "repeat_index": sample["repeat_index"], "result_sha256": result_hash})
        return True, result_hash

    def _close_adapter(self, task_id: int) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            try:
                adapter.stop_debug(correlation_id=f"acquisition-{task_id}")
                adapter.disconnect(correlation_id=f"acquisition-{task_id}")
            except DeviceError:
                pass

    def _begin_next_repeat(self, task_id: int, actor_user_id: int | None = None) -> None:
        task, _, profile = self._context(task_id)
        adapter, event = self._start_adapter(task_id, task, profile)
        with self.database.write() as db:
            current = self._context(task_id, db)[0]
            sample_id = self._create_sample(db, current)
            db.execute("UPDATE acquisition_tasks SET status='pre_excitation', adapter_session_id=?, burn_frames_captured=0, dark_frames_captured=0, last_event_json=?, last_message=?, updated_at=? WHERE id=?", (adapter.session_id, _json(event.to_dict()), "下一次重复预激发已开始", utc_now(), task_id))
            self._message(db, task_id, "info", "sample.repeat.start", "下一次重复采集已开始", {"repeat_index": current["current_repeat_index"], "sample_id": sample_id})
            self._audit(db, actor_user_id, "acquisition.repeat.start", task_id, {"repeat_index": current["current_repeat_index"]})

    def _fail_task(self, task_id: int, code: str, message: str, actor_user_id: int | None = None, *, event: Any | None = None) -> None:
        with self.database.write() as db:
            task = db.execute("SELECT * FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task["status"] in {"completed", "failed", "stopped"}:
                return
            sample = db.execute("SELECT * FROM acquisition_samples WHERE task_id=? AND status='collecting' ORDER BY repeat_index DESC LIMIT 1", (task_id,)).fetchone()
            if sample is not None:
                db.execute("UPDATE acquisition_samples SET status='failed', failure_code=?, failure_message=?, updated_at=? WHERE id=?", (code, message, utc_now(), sample["id"]))
            db.execute("UPDATE acquisition_tasks SET status='failed', failure_code=?, failure_message=?, last_message=?, last_event_json=COALESCE(?, last_event_json), completed_at=?, updated_at=? WHERE id=?", (code, message, message, _json(event.to_dict()) if event is not None else None, utc_now(), utc_now(), task_id))
            self._message(db, task_id, "error", code, message, {})
            self._audit(db, actor_user_id, "acquisition.task.failed", task_id, {"code": code, "message": message})
        self._close_adapter(task_id)

    def step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self._context(task_id)
        status = str(task["status"])
        if status == AcquisitionState.COUNTDOWN.value:
            remaining = max(0.0, float(task["countdown_remaining"]) - float(task["sampling_period_seconds"]))
            next_state = AcquisitionState.PRE_EXCITATION.value if remaining <= 0 else status
            with self.database.write() as db:
                db.execute("UPDATE acquisition_tasks SET status=?, countdown_remaining=?, last_message=?, updated_at=? WHERE id=?", (next_state, remaining, "预激发准备" if next_state == "pre_excitation" else f"倒计时 {remaining:.3f} 秒", utc_now(), task_id))
                self._message(db, task_id, "info", "task.countdown", "倒计时推进", {"remaining_seconds": remaining})
            return self._task_dict(task_id)
        if status == AcquisitionState.BETWEEN_REPEATS.value:
            self._begin_next_repeat(task_id, actor_user_id)
            return self._task_dict(task_id)
        if status not in {AcquisitionState.PRE_EXCITATION.value, AcquisitionState.BURN.value, AcquisitionState.DARK.value}:
            raise AcquisitionError("acquisition_task_not_running", "当前任务未处于可采集状态", details={"status": status}, status_code=409)
        task, _, profile = self._context(task_id)
        with self.database.read() as db:
            sample = self._current_sample(db, task_id, int(task["current_repeat_index"]))
        adapter = self._adapters.get(task_id)
        if status == AcquisitionState.PRE_EXCITATION.value and float(task["pre_excitation_seconds"]) > 0:
            with self.database.write() as db:
                db.execute(
                    "UPDATE acquisition_tasks SET status='burn', last_message=?, updated_at=? WHERE id=?",
                    ("预激发完成，开始正式燃烧采集", utc_now(), task_id),
                )
                self._message(db, task_id, "info", "task.pre_excitation.complete", "预激发完成，开始正式燃烧采集", {"seconds": float(task["pre_excitation_seconds"]), "sample_id": sample["id"]})
            return self._task_dict(task_id)
        try:
            if status == AcquisitionState.PRE_EXCITATION.value:
                event = json.loads(task["last_event_json"] or "{}")

                class StoredEvent:
                    pass

                stored = StoredEvent()
                stored.ccds = event.get("ccds", [])
                stored.details = event.get("details", {})
                stored.message = event.get("message", "")
                stored.to_dict = lambda: event
                phase, frame_index = "burn", 0
            else:
                if adapter is None:
                    raise AcquisitionError("acquisition_session_lost", "采集会话已丢失，已收帧不会被替换", status_code=409)
                event = adapter.step_debug(correlation_id=f"acquisition-{task_id}")
                if event.event_type == "fault":
                    with self.database.write() as db:
                        live = self._context(task_id, db)[0]
                        current_sample = self._current_sample(db, task_id, int(live["current_repeat_index"]))
                        phase = "burn" if status == "burn" else "dark"
                        frame_index = int(live["burn_frames_captured"] if phase == "burn" else live["dark_frames_captured"])
                        self._store_damaged(db, live, current_sample, phase, frame_index, event)
                    self._fail_task(task_id, str(event.details.get("code", "device_fault")), event.message or "CCD 帧损坏", actor_user_id, event=event)
                    return self._task_dict(task_id, include_points=True)
                phase = "burn" if status == "burn" else "dark"
                frame_index = int(task["burn_frames_captured"] if phase == "burn" else task["dark_frames_captured"])
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise AcquisitionError("acquisition_frame_failed", exc.message, details=exc.detail(), status_code=exc.status_code) from exc
        except AcquisitionError:
            raise
        completed = False
        final_hash = ""
        next_state = status
        with self.database.write() as db:
            live = self._context(task_id, db)[0]
            current_sample = self._current_sample(db, task_id, int(live["current_repeat_index"]))
            self._store_event(db, live, current_sample, phase, frame_index, stored if status == "pre_excitation" else event, self._virtual_time(live, int(current_sample["repeat_index"]), phase, frame_index))
            burn_captured = int(live["burn_frames_captured"]) + (1 if phase == "burn" else 0)
            dark_captured = int(live["dark_frames_captured"]) + (1 if phase == "dark" else 0)
            if phase == "burn" and burn_captured >= int(live["burn_frame_count"]):
                next_state = "dark" if int(live["dark_frame_count"]) > 0 else "completed"
            elif phase == "dark" and dark_captured >= int(live["dark_frame_count"]):
                next_state = "completed"
            else:
                next_state = phase
            db.execute("UPDATE acquisition_tasks SET status=?, burn_frames_captured=?, dark_frames_captured=?, last_event_json=?, last_message=?, updated_at=? WHERE id=?", (next_state, burn_captured, dark_captured, _json((stored if status == "pre_excitation" else event).to_dict()), f"{phase} 第 {frame_index + 1} 帧已保存", utc_now(), task_id))
            self._message(db, task_id, "info", "frame.capture", f"{phase} 第 {frame_index + 1} 帧已保存", {"phase": phase, "frame_index": frame_index, "repeat_index": current_sample["repeat_index"]})
            self._audit(db, actor_user_id, "acquisition.frame.capture", task_id, {"phase": phase, "frame_index": frame_index, "repeat_index": current_sample["repeat_index"], "sha256": (stored if status == "pre_excitation" else event).details.get("sha256", "")})
            if next_state == "completed":
                completed, final_hash = self._finalize_sample(db, live, current_sample, actor_user_id)
                completed_repeats = int(live["completed_repeats"]) + 1
                if completed_repeats < int(live["repeat_count"]):
                    next_state = "between_repeats"
                    db.execute("UPDATE acquisition_tasks SET status=?, current_repeat_index=?, completed_repeats=?, burn_frames_captured=0, dark_frames_captured=0, last_message=?, updated_at=? WHERE id=?", (next_state, int(live["current_repeat_index"]) + 1, completed_repeats, "当前重复已完成，等待下一次采集", utc_now(), task_id))
                else:
                    db.execute("UPDATE acquisition_tasks SET status='completed', completed_repeats=?, result_sha256=?, completed_at=?, last_message=?, updated_at=? WHERE id=?", (completed_repeats, hashlib.sha256("|".join(row["result_sha256"] or "" for row in db.execute("SELECT result_sha256 FROM acquisition_samples WHERE task_id=? ORDER BY repeat_index", (task_id,)).fetchall()).encode("ascii")).hexdigest(), utc_now(), "全部采集完成", utc_now(), task_id))
                    if live["queue_id"] is not None and live["queue_item_id"] is not None and live["sample_kind"] != "preheat":
                        queue_hash = db.execute("SELECT result_sha256 FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()[0]
                        self.sample_queues.attach_acquisition(int(live["queue_id"]), int(live["queue_item_id"]), str(queue_hash), actor_user_id, connection=db)
                    self._message(db, task_id, "success", "task.completed", "全部采集完成", {"result_sha256": hashlib.sha256("|".join(row["result_sha256"] or "" for row in db.execute("SELECT result_sha256 FROM acquisition_samples WHERE task_id=? ORDER BY repeat_index", (task_id,)).fetchall()).encode("ascii")).hexdigest()})
                    self._audit(db, actor_user_id, "acquisition.task.completed", task_id, {"repeat_count": completed_repeats})
        if next_state in {"between_repeats", "completed"}:
            self._close_adapter(task_id)
        return self._task_dict(task_id, include_points=True)

    def pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self._context(task_id)
        status = str(task["status"])
        if status == "paused":
            return self._task_dict(task_id)
        if status not in {"countdown", "pre_excitation", "burn", "dark"}:
            raise AcquisitionError("acquisition_task_not_pauseable", "当前任务不能暂停", details={"status": status}, status_code=409)
        with self.database.write() as db:
            db.execute("UPDATE acquisition_tasks SET status='paused', paused_from=?, last_message=?, updated_at=? WHERE id=?", (status, "采集已暂停", utc_now(), task_id))
            self._message(db, task_id, "warning", "task.pause", "采集已暂停", {"from": status})
            self._audit(db, actor_user_id, "acquisition.task.pause", task_id, {"from": status})
        return self._task_dict(task_id)

    def resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self._context(task_id)
        status = str(task["status"])
        if status != "paused":
            if status in {"countdown", "pre_excitation", "burn", "dark"}:
                return self._task_dict(task_id)
            raise AcquisitionError("acquisition_task_not_resumable", "当前任务未暂停", details={"status": status}, status_code=409)
        target = task["paused_from"] or "burn"
        with self.database.write() as db:
            db.execute("UPDATE acquisition_tasks SET status=?, paused_from=NULL, last_message=?, updated_at=? WHERE id=?", (target, "采集已继续", utc_now(), task_id))
            self._message(db, task_id, "info", "task.resume", "采集已继续", {"to": target})
            self._audit(db, actor_user_id, "acquisition.task.resume", task_id, {"to": target})
        return self._task_dict(task_id)

    def stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self._context(task_id)
        status = str(task["status"])
        if status in {"completed", "failed", "stopped"}:
            return self._task_dict(task_id)
        with self.database.write() as db:
            db.execute("UPDATE acquisition_tasks SET status='stopping', last_message=?, updated_at=? WHERE id=?", ("正在停止采集", utc_now(), task_id))
            current = db.execute("SELECT id FROM acquisition_samples WHERE task_id=? AND status='collecting' ORDER BY repeat_index DESC LIMIT 1", (task_id,)).fetchone()
            if current is not None:
                db.execute("UPDATE acquisition_samples SET status='stopped', failure_code='stopped', failure_message='用户停止采集', updated_at=? WHERE id=?", (utc_now(), current["id"]))
            db.execute("UPDATE acquisition_tasks SET status='stopped', completed_at=?, last_message=?, updated_at=? WHERE id=?", (utc_now(), "采集已停止，已收帧保留", utc_now(), task_id))
            self._message(db, task_id, "warning", "task.stop", "采集已停止，已收帧保留", {})
            self._audit(db, actor_user_id, "acquisition.task.stop", task_id, {"from": status})
        self._close_adapter(task_id)
        return self._task_dict(task_id)

    def frames(self, task_id: int, *, repeat_index: int | None = None, phase: str | None = None, ccd_index: int | None = None, include_points: bool = False) -> list[dict[str, Any]]:
        self._context(task_id)
        where = ["task_id=?"]
        args: list[Any] = [task_id]
        if repeat_index is not None:
            where.append("repeat_index=?")
            args.append(int(repeat_index))
        if phase is not None:
            if phase not in {"burn", "dark"}:
                raise AcquisitionError("acquisition_phase_invalid", "阶段必须是 burn 或 dark")
            where.append("phase=?")
            args.append(phase)
        if ccd_index is not None:
            where.append("ccd_index=?")
            args.append(int(ccd_index))
        with self.database.read() as db:
            rows = db.execute(f"SELECT * FROM acquisition_frames WHERE {' AND '.join(where)} ORDER BY repeat_index, phase, frame_index, ccd_index", args).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                if include_points and row["points_blob"] is not None:
                    item["points"] = _unpack_uint16(row["points_blob"], int(row["points_count"]))
                item.pop("points_blob", None)
                result.append(item)
            return result

    def analysis(self, task_id: int, repeat_index: int | None = None) -> dict[str, Any]:
        self._context(task_id)
        with self.database.read() as db:
            task = db.execute("SELECT * FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()
            repeat = int(task["current_repeat_index"] if repeat_index is None else repeat_index)
            points_count = int(db.execute("SELECT points_per_ccd FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()[0])
            frames = db.execute("SELECT * FROM acquisition_frames WHERE task_id=? AND repeat_index=? ORDER BY phase, frame_index, ccd_index", (task_id, repeat)).fetchall()
            curves = []
            for row in frames:
                curve = dict(row)
                blob = curve.pop("points_blob", None)
                if blob is not None:
                    curve["points"] = _unpack_uint16(blob, int(row["points_count"]))
                curve["headers"] = json.loads(curve.pop("headers_json") or "[]")
                curve["damaged"] = bool(curve["damaged"])
                curves.append(curve)
            intervals = []
            for interval in db.execute("SELECT * FROM acquisition_intervals WHERE task_id=? AND repeat_index=? ORDER BY start_frame_index", (task_id, repeat)).fetchall():
                stats = []
                for ccd in json.loads(task["ccd_indices_json"] or "[]"):
                    selected = [row for row in frames if row["phase"] == "burn" and int(row["frame_index"]) in range(interval["start_frame_index"], interval["end_frame_index"] + 1) and int(row["ccd_index"]) == int(ccd) and not row["damaged"] and row["points_blob"] is not None]
                    point_mean: list[float] = []
                    if selected:
                        values = [_unpack_uint16(row["points_blob"], points_count) for row in selected]
                        point_mean = [sum(frame[index] for frame in values) / len(values) for index in range(points_count)]
                    stats.append({"ccd_index": ccd, "frame_count": len(selected), "damaged_count": (interval["end_frame_index"] - interval["start_frame_index"] + 1) - len(selected), "point_mean": point_mean, "point_mean_sha256": hashlib.sha256(_pack_float32(point_mean)).hexdigest() if point_mean else None, "peak_mean": sum(row["peak_value"] or 0 for row in selected) / len(selected) if selected else None, "integral_mean": sum(row["integral_value"] or 0 for row in selected) / len(selected) if selected else None})
                intervals.append(dict(interval) | {"stats": stats})
            return {"task_id": task_id, "repeat_index": repeat, "points_per_ccd": points_count, "curves": curves, "intervals": intervals}

    def mark_interval(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        repeat = int(payload.get("repeat_index", 0))
        label = str(payload.get("label", "")).strip()
        start = int(payload.get("start_frame_index", -1))
        end = int(payload.get("end_frame_index", -1))
        if not label or len(label) > 50 or start < 0 or end < start:
            raise AcquisitionError("acquisition_interval_invalid", "区间名称或帧范围无效")
        with self.database.write() as db:
            task = db.execute("SELECT * FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise AcquisitionError("acquisition_task_not_found", "采集任务不存在", status_code=404)
            expected = set(range(start, end + 1))
            actual = {int(row[0]) for row in db.execute("SELECT DISTINCT frame_index FROM acquisition_frames WHERE task_id=? AND repeat_index=? AND phase='burn'", (task_id, repeat)).fetchall()}
            if not expected.issubset(actual):
                raise AcquisitionError("acquisition_interval_not_captured", "区间包含尚未采集的燃烧帧", details={"missing": sorted(expected - actual)}, status_code=409)
            overlap = db.execute("SELECT frame_index FROM acquisition_frames WHERE task_id=? AND repeat_index=? AND phase='burn' AND frame_index BETWEEN ? AND ? AND interval_label IS NOT NULL AND interval_label<>? LIMIT 1", (task_id, repeat, start, end, label)).fetchone()
            if overlap is not None:
                raise AcquisitionError("acquisition_interval_overlap", "区间与已有标记重叠", status_code=409)
            db.execute("UPDATE acquisition_frames SET interval_label=NULL WHERE task_id=? AND repeat_index=? AND phase='burn' AND interval_label=?", (task_id, repeat, label))
            db.execute("UPDATE acquisition_frames SET interval_label=? WHERE task_id=? AND repeat_index=? AND phase='burn' AND frame_index BETWEEN ? AND ?", (label, task_id, repeat, start, end))
            db.execute("INSERT INTO acquisition_intervals(task_id, repeat_index, label, start_frame_index, end_frame_index, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(task_id, repeat_index, label) DO UPDATE SET start_frame_index=excluded.start_frame_index, end_frame_index=excluded.end_frame_index, created_by=excluded.created_by, created_at=excluded.created_at", (task_id, repeat, label, start, end, actor_user_id, utc_now()))
            self._message(db, task_id, "info", "interval.mark", "蒸发区间已标记", {"repeat_index": repeat, "label": label, "start": start, "end": end})
            self._audit(db, actor_user_id, "acquisition.interval.mark", task_id, {"repeat_index": repeat, "label": label, "start": start, "end": end})
        return self.analysis(task_id, repeat)

    def rename(self, task_id: int, sample_id: int, post_name: str, actor_user_id: int | None = None) -> dict[str, Any]:
        name, _ = normalize_name(post_name)
        if not name:
            raise AcquisitionError("sample_name_invalid", "采集后名称不能为空")
        with self.database.write() as db:
            task = db.execute("SELECT * FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()
            sample = db.execute("SELECT * FROM acquisition_samples WHERE id=? AND task_id=?", (sample_id, task_id)).fetchone()
            if task is None or sample is None:
                raise AcquisitionError("acquisition_sample_not_found", "采集样品不存在", status_code=404)
            if task["status"] != "completed" or sample["status"] != "completed" or not sample["finalized"]:
                raise AcquisitionError("sample_not_completed", "只有完整采集样品可以后命名", status_code=409)
            hashes_before = [row[0] for row in db.execute("SELECT mean_sha256 FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index", (sample_id,)).fetchall()]
            db.execute("UPDATE acquisition_samples SET sample_name=?, updated_at=? WHERE task_id=?", (name, utc_now(), task_id))
            db.execute("UPDATE acquisition_tasks SET sample_name=?, naming_mode='post', updated_at=? WHERE id=?", (name, utc_now(), task_id))
            if task["queue_id"] is not None and task["queue_item_id"] is not None:
                try:
                    self.sample_queues.rename_linked_item(int(task["queue_id"]), int(task["queue_item_id"]), name, actor_user_id, connection=db)
                except SampleQueueError as exc:
                    raise AcquisitionError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
            self._message(db, task_id, "success", "sample.rename", "采集后样品名称已保存", {"sample_id": sample_id, "name": name, "mean_hashes": hashes_before})
            self._audit(db, actor_user_id, "acquisition.sample.rename", sample_id, {"task_id": task_id, "name": name, "mean_hashes": hashes_before})
        return self._task_dict(task_id)

    def band(self, sample_id: int, ccd_index: int | None = None, include_points: bool = False) -> list[dict[str, Any]]:
        with self.database.read() as db:
            where = ["sample_id=?"]
            args: list[Any] = [sample_id]
            if ccd_index is not None:
                where.append("ccd_index=?")
                args.append(int(ccd_index))
            rows = db.execute(f"SELECT * FROM acquisition_sample_bands WHERE {' AND '.join(where)} ORDER BY ccd_index", args).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                for field, count, unpack in (("mean_blob", int(row["points_count"]), _unpack_float32),):
                    blob = row[field]
                    if include_points and blob is not None:
                        item["mean_points"] = unpack(blob, count)
                item.pop("mean_blob", None)
                item.pop("burn_frames_blob", None)
                item.pop("dark_frames_blob", None)
                result.append(item)
            return result
