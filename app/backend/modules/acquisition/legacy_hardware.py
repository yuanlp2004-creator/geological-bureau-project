"""Historical turn acquisition queries and confirmed sample conversion."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ...db import Database, utc_now
from ..acquisition_import import AcquisitionRecordImporter
from ..methods import MethodService
from ..spectral_lines import canonical_lines, exposure_interval
from .confirmed_import import ConfirmedSpectrum
from .values import AcquisitionError


_STATES = (
    "draft", "connecting", "connected", "pre_excitation", "turning", "collecting", "anomaly",
    "manual_intervention", "paused", "stopping", "completed", "failed", "stopped", "safety_stopped",
    "deferred_external",
)
_ANOMALY_KINDS = ("baseline_high", "baseline_low", "baseline_shift", "frame_fault", "peak_shift", "turn_timeout")

_control_guard = threading.Lock()
_controlled_tasks: set[tuple[Database, int]] = set()


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _unpack_points(blob: bytes, count: int) -> list[int]:
    if len(blob) != count * 2:
        raise AcquisitionError(
            "hardware_frame_invalid",
            "CCD frame payload length is inconsistent",
            details={"expected": count * 2, "actual": len(blob)},
        )
    return list(struct.unpack(f"<{count}H", blob))


# Older one-frame tasks did not store an explicit exposure interval.
def _exposure_config(task: sqlite3.Row, step: sqlite3.Row) -> dict[str, Any]:
    plan = next(item for item in json.loads(task['plan_json']) if item['order_index'] == step['order_index'])
    return {'start_frame': 1, 'end_frame': 1, 'storage_mode': 'averaged',
            'expected_baseline_position': 256, 'search_radius_points': 64, **plan}


def _manual_frames(db: sqlite3.Connection, task_id: int, include_points: bool) -> list[dict[str, Any]]:
    """Latest raw frame per CCD/attempt, including frames in an unfinished dwell."""
    results = []
    for row in db.execute('SELECT e.*, s.last_attempt, s.status FROM hardware_exposure_frames e '
                          'JOIN hardware_plan_steps s ON s.id=e.step_id WHERE e.task_id=? AND e.id IN '
                          '(SELECT MAX(id) FROM hardware_exposure_frames WHERE task_id=? GROUP BY step_id,attempt,ccd_index) '
                          'ORDER BY e.step_id,e.attempt,e.ccd_index', (task_id, task_id)):
        item = dict(row)
        blob = bytes(item.pop('points_blob'))
        if _sha(blob) != item['points_sha256']:
            raise AcquisitionError('hardware_exposure_integrity_failed', '转角原始帧哈希不符')
        item.update(id=-item['id'], damaged=False,
                    confirmed=item.pop('status') == 'confirmed' and item['attempt'] == item.pop('last_attempt'))
        if include_points:
            item['points'] = _unpack_points(blob, item['points_count'])
        results.append(item)
    return results


def _exposure_results(db: sqlite3.Connection, task_id: int, include_points: bool = False) -> list[dict[str, Any]]:
    results = []
    for row in db.execute('SELECT r.*, f.confirmed FROM hardware_exposure_results r JOIN hardware_frames f '
                          'ON f.step_id=r.step_id AND f.attempt=r.attempt AND f.ccd_index=r.ccd_index '
                          'WHERE r.task_id=? ORDER BY r.step_id,r.attempt,r.ccd_index', (task_id,)):
        item = dict(row)
        mean, full = bytes(item.pop('mean_blob')), item.pop('frames_blob')
        if _sha(mean) != row['mean_sha256'] or (full is not None and _sha(full) != row['frames_sha256']):
            raise AcquisitionError('hardware_exposure_integrity_failed', '转角区间结果哈希不符')
        item['confirmed'] = bool(item['confirmed'])
        if include_points:
            item['mean_points'] = list(struct.unpack(f"<{row['points_count']}f", mean))
            item['frames'] = [_unpack_points(full[offset:offset + row['points_count'] * 2], row['points_count'])
                              for offset in range(0, len(full), row['points_count'] * 2)] if full is not None else []
        results.append(item)
    return results


class LegacyHardwareService:
    def __init__(self, database: Database):
        self.database = database

    @contextmanager
    def control_scope(self, task_id: int) -> Iterator[None]:
        key = (self.database, task_id)
        with _control_guard:
            if key in _controlled_tasks:
                raise AcquisitionError(
                    "hardware_task_busy",
                    "another hardware control operation is in progress",
                    details={"task_id": task_id},
                    status_code=409,
                )
            _controlled_tasks.add(key)
        try:
            yield
        finally:
            with _control_guard:
                _controlled_tasks.remove(key)

    def get_task(self, task_id: int, *, include_points: bool = False) -> dict[str, Any]:
        return self._task_dict(task_id, include_points=include_points)

    @staticmethod
    def _layout_indices(row: sqlite3.Row | dict[str, Any]) -> list[int]:
        return [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]

    def _context(
        self, task_id: int, db: sqlite3.Connection | None = None
    ) -> tuple[sqlite3.Row, sqlite3.Row, dict[str, Any]]:
        if db is None:
            with self.database.read() as connection:
                return self._context(task_id, connection)
        task = db.execute("SELECT * FROM hardware_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise AcquisitionError(
                "hardware_task_not_found",
                "hardware acquisition task was not found",
                details={"task_id": task_id},
                status_code=404,
            )
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()
        profile_row = db.execute("SELECT * FROM device_profiles WHERE id=?", (task["device_profile_id"],)).fetchone()
        if layout is None or profile_row is None:
            raise AcquisitionError(
                "hardware_configuration_missing",
                "hardware task references missing device or CCD layout",
                status_code=409,
            )
        profile = dict(profile_row)
        profile["ccd_indices"] = json.loads(profile.pop("ccd_indices_json") or "[]")
        profile["mirror"] = bool(profile.get("mirror"))
        profile["enabled"] = bool(profile.get("enabled", True))
        return task, layout, profile

    @staticmethod
    def _decode_json_field(result: dict[str, Any], field: str, default: Any) -> None:
        raw = result.pop(field, None)
        result[field.removesuffix("_json")] = json.loads(raw) if raw else default

    def _task_dict(
        self, task_id: int, db: sqlite3.Connection | None = None, *, include_points: bool = False
    ) -> dict[str, Any]:
        if db is None:
            with self.database.read() as connection:
                return self._task_dict(task_id, connection, include_points=include_points)
        task, layout, profile = self._context(task_id, db)
        result = dict(task)
        for field, default in (
            ("ccd_indices_json", []),
            ("plan_json", []),
            ("thresholds_json", {}),
            ("simulator_json", {}),
            ("last_event_json", None),
        ):
            self._decode_json_field(result, field, default)
        result["transport"] = str(result["transport"])
        result["profile"] = {
            "id": profile["id"],
            "name": profile["name"],
            "transport": profile["transport"],
            "port": profile["port"],
            "baud_rate": profile["baud_rate"],
            "mirror": profile["mirror"],
        }
        result["layout"] = {
            "id": layout["id"],
            "name": layout["name"],
            "points_per_ccd": layout["points_per_ccd"],
            "ccd_indices": self._layout_indices(layout),
        }
        result["progress"] = round(
            min(100.0, float(result["completed_steps"]) / max(1, int(result["total_steps"])) * 100), 2
        )
        result["steps"] = []
        # 计划项、追踪和决策分别保留顺序，页面可对照每次转角与异常处理。
        for row in db.execute(
            "SELECT * FROM hardware_plan_steps WHERE task_id=? ORDER BY order_index", (task_id,)
        ).fetchall():
            config = _exposure_config(task, row)
            captured_frames = db.execute(
                "SELECT COALESCE(MAX(frame_index),0) FROM hardware_exposure_frames WHERE step_id=? AND attempt=?",
                (row["id"], row["last_attempt"] + 1),
            ).fetchone()[0]
            step = dict(row) | {
                "key_band": bool(row["key_band"]),
                "duration_seconds": config.get("duration_seconds"),
                **{key: config[key] for key in ("storage_mode", "start_frame", "end_frame")},
                "captured_frames": captured_frames,
            }
            if task['execution_mode'] == 'manual':
                duration = config["duration_seconds"]
                event = result.get('last_event') or {}
                step["captured_seconds"] = 0
                if row["status"] == "confirmed":
                    step["captured_seconds"] = duration
                elif row["status"] == "collecting" and row["order_index"] == task["current_step_index"]:
                    step["captured_seconds"] = min(duration, float(event.get("capture_seconds", 0)))
            result["steps"].append(step)
        result["traces"] = []
        for row in db.execute(
            "SELECT * FROM hardware_traces WHERE task_id=? ORDER BY sequence_no DESC LIMIT 60", (task_id,)
        ).fetchall():
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item.pop("raw_payload", None)
            result["traces"].append(item)
        result["traces"].reverse()
        result["decisions"] = [
            dict(row)
            | {
                "observed": json.loads(row["observed_json"] or "{}"),
                "threshold": json.loads(row["threshold_json"] or "{}"),
            }
            for row in db.execute("SELECT * FROM hardware_decisions WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        ]
        result["messages"] = [
            dict(row) | {"details": json.loads(row["details_json"] or "{}")}
            for row in db.execute(
                "SELECT * FROM hardware_messages WHERE task_id=? ORDER BY id DESC LIMIT 60", (task_id,)
            ).fetchall()
        ][::-1]
        # 响应默认只带帧摘要，确需绘图时才解码点值，避免轮询反复传输全部原始数据。
        frames = self._read_frames(db, task_id, include_points=include_points)
        if task["execution_mode"] == "manual":
            frames = _manual_frames(db, task_id, include_points) + [row for row in frames if row["damaged"]]
        result["frames"] = frames
        result['exposures'] = _exposure_results(db, task_id, include_points)
        result['analysis_sample'] = AcquisitionRecordImporter().bind(db).confirmed_source(f'hardware-task:{task_id}')
        result["latest_trace"] = result["traces"][-1] if result["traces"] else None
        result["latest_decision"] = result["decisions"][-1] if result["decisions"] else None
        return result

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            profiles = []
            for row in db.execute(
                "SELECT id, name, transport, port, baud_rate, ccd_indices_json, points_per_ccd FROM device_profiles WHERE enabled=1 ORDER BY id"
            ).fetchall():
                profiles.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "transport": row["transport"],
                        "port": row["port"],
                        "baud_rate": row["baud_rate"],
                        "ccd_indices": json.loads(row["ccd_indices_json"] or "[]"),
                        "points_per_ccd": row["points_per_ccd"],
                    }
                )
            layouts = [
                dict(row) | {"ccd_indices": self._layout_indices(row)}
                for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall()
            ]
            methods = [{'method_id': item.method.id, 'version': item.version, 'name': item.method.name,
                        'ccd_layout_id': item.payload.get('conditions', {}).get('ccd_layout_id', 'default'),
                        'sampling_period_seconds': item.payload.get('conditions', {}).get('sampling_period_seconds', 1),
                        'turns': (item.payload.get('conditions') or {}).get('angle_exposures', []),
                        'turn_angles': [exposure['angle_deg'] for exposure in (item.payload.get('conditions') or {}).get('angle_exposures', [])]}
                       for item in MethodService(self.database).bind_snapshots(db).published()]
        return {
            "states": list(_STATES),
            "strategies": ["key_first", "short_to_long"],
            "anomaly_policies": ["manual", "retry_then_stop"],
            "anomaly_kinds": list(_ANOMALY_KINDS),
            "profiles": profiles,
            "layouts": layouts,
            "methods": methods,
        }

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM hardware_tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)
                ).fetchall()
            ]
        return [self._task_dict(task_id) for task_id in ids]

    @staticmethod
    def _read_frames(
        db: sqlite3.Connection, task_id: int, *, step_id: int | None = None, include_points: bool
    ) -> list[dict[str, Any]]:
        columns = (
            "id, task_id, step_id, attempt, ccd_index, points_count, points_sha256, raw_transfer_sha256, "
            "raw_byte_length, headers_json, baseline_intensity, baseline_position, expected_peak_position, "
            "peak_position, peak_value, virtual_time_ms, damaged, confirmed, anomaly_kind, damage_code, "
            "damage_message, captured_at"
        )
        if include_points:
            columns += ", points_blob"
        query = f"SELECT {columns} FROM hardware_frames WHERE task_id=?"
        args = [task_id]
        if step_id is not None:
            query += " AND step_id=?"
            args.append(step_id)
        query += " ORDER BY step_id, attempt, ccd_index"
        result = []
        for row in db.execute(query, args):
            item = dict(row)
            if include_points:
                blob = item.pop("points_blob")
                if blob is not None:
                    item["points"] = _unpack_points(blob, int(item["points_count"]))
                    if _sha(blob) != item["points_sha256"]:
                        raise AcquisitionError("hardware_frame_invalid", "CCD frame payload hash is inconsistent")
            item["damaged"] = bool(item["damaged"])
            item["confirmed"] = bool(item["confirmed"])
            result.append(item)
        return result

    def frames(self, task_id: int, *, step_id: int | None = None, include_points: bool = False) -> list[dict[str, Any]]:
        task = self._context(task_id)[0]
        with self.database.read() as db:
            result = self._read_frames(db, task_id, step_id=step_id, include_points=include_points)
            if task['execution_mode'] == 'manual':
                live = _manual_frames(db, task_id, include_points)
                return [item for item in live if step_id is None or item['step_id'] == step_id] + [item for item in result if item['damaged']]
            return result

    def traces(self, task_id: int) -> list[dict[str, Any]]:
        task = self._context(task_id)[0]
        with self.database.read() as db:
            result = []
            for row in db.execute(
                "SELECT * FROM hardware_traces WHERE task_id=? ORDER BY sequence_no", (task["id"],)
            ).fetchall():
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                item.pop("raw_payload", None)
                result.append(item)
            return result

    def decisions(self, task_id: int) -> list[dict[str, Any]]:
        task = self._context(task_id)[0]
        with self.database.read() as db:
            return [
                dict(row)
                | {
                    "observed": json.loads(row["observed_json"] or "{}"),
                    "threshold": json.loads(row["threshold_json"] or "{}"),
                }
                for row in db.execute(
                    "SELECT * FROM hardware_decisions WHERE task_id=? ORDER BY id", (task["id"],)
                ).fetchall()
            ]

    def save_analysis_sample(self, task_id: int, payload: dict, actor_user_id: int | None = None) -> dict:
        with self.control_scope(task_id), self.database.write() as db:
            db.execute("BEGIN IMMEDIATE")
            task, layout, _ = self._context(task_id, db)
            if task['status'] != 'completed' or task['completed_steps'] != task['total_steps']:
                raise AcquisitionError('hardware_sample_incomplete', '全部转角采集完成并确认后才能保存分析样品', status_code=409)
            methods = MethodService(self.database)
            method = None
            if task["method_id"] and task["method_version"]:
                snapshots = methods.bind_snapshots(db)
                method = snapshots.for_print(task["method_id"], task["method_version"])
            if method is None or method.state != "published":
                raise AcquisitionError(
                    "hardware_sample_method_missing", "任务须绑定已发布方法后才能生成分析样品", status_code=409
                )
            conditions = method.payload['conditions']
            importer = AcquisitionRecordImporter().bind(db)
            source_id = f"hardware-task:{task_id}"
            existing = importer.confirmed_source(source_id)
            if existing:
                if existing['source_sha256'] != task['result_sha256']:
                    raise AcquisitionError('hardware_sample_source_changed', '已保存转角结果的来源哈希不一致', status_code=409)
                return {**existing, 'already_saved': True}
            geometry = methods.bind_geometry(db, conditions)
            if geometry.layout_id != layout['id']:
                raise AcquisitionError('hardware_sample_layout_mismatch', '任务与已发布方法的 CCD 布局不一致', status_code=409)
            lines = [line for line in canonical_lines(method.payload.get('lines'), conditions) if line.get('enabled')]
            intervals: dict[int, list[tuple[int, int]]] = {}
            method_ccds: set[int] = set()
            for line in lines:
                location = geometry.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm']))
                if location is None:
                    raise AcquisitionError('hardware_sample_line_outside_ccd', '方法谱线超出当前布局')
                method_ccds.add(location.ccd_index)
                interval = exposure_interval(line, conditions)
                if interval:
                    intervals.setdefault(location.ccd_index, []).append(interval)
            steps = {
                row["id"]: row
                for row in db.execute("SELECT * FROM hardware_plan_steps WHERE task_id=?", (task_id,))
            }
            bands, provenance = [], []
            for exposure in _exposure_results(db, task_id):
                if not exposure['confirmed']:
                    continue
                ccd = exposure['ccd_index']
                if any(band['ccd_index'] == ccd for band in bands):
                    raise AcquisitionError('hardware_sample_duplicate_ccd', '同一 CCD 有多个已确认转角结果，不能混合为一个样品')
                config = _exposure_config(task, steps[exposure['step_id']])
                if config.get('method_content_sha256') != method.content_sha256:
                    raise AcquisitionError('hardware_sample_method_changed', '已确认结果的方法快照不一致', status_code=409)
                raw = db.execute(
                    "SELECT * FROM hardware_exposure_frames WHERE task_id=? AND step_id=? AND attempt=? "
                    "AND ccd_index=? AND frame_index<=? ORDER BY frame_index",
                    (task_id, exposure["step_id"], exposure["attempt"], ccd, exposure["end_frame"]),
                ).fetchall()
                if [r["frame_index"] for r in raw] != list(range(1, exposure["end_frame"] + 1)):
                    raise AcquisitionError('hardware_sample_frames_missing', '已确认尝试的原始帧不完整')
                if any(len(r['points_blob']) != exposure['points_count'] * 2
                       or _sha(r['points_blob']) != r['points_sha256'] for r in raw):
                    raise AcquisitionError('hardware_exposure_integrity_failed', '转角原始帧校验失败')
                if any(start < 1 or end > len(raw) for start, end in intervals.get(ccd, [])):
                    raise AcquisitionError('hardware_sample_line_interval_missing', '转角采集范围不足以覆盖方法逐线曝光区间')
                stored = db.execute(
                    "SELECT mean_blob FROM hardware_exposure_results WHERE id=?", (exposure["id"],)
                ).fetchone()
                detail = {
                    key: exposure[key]
                    for key in ("id", "step_id", "attempt", "ccd_index", "start_frame", "end_frame", "mean_sha256")
                }
                detail.update(
                    angle_deg=config["angle_deg"],
                    method_content_sha256=method.content_sha256,
                    frame_sha256=[row["points_sha256"] for row in raw],
                )
                frames = [
                    {
                        "frame_index": row["frame_index"] - 1,
                        "blob": row["points_blob"],
                        "sha256": row["points_sha256"],
                        "evidence": {
                            "hardware_task_id": task_id,
                            **{key: detail[key] for key in ("step_id", "attempt", "angle_deg")},
                            "source_frame_index": row["frame_index"],
                            "source_frame_id": row["id"],
                        },
                    }
                    for row in raw
                ]
                bands.append({
                    **exposure,
                    "mean_blob": stored["mean_blob"],
                    "storage_mode": "full_interval" if intervals.get(ccd) else exposure["storage_mode"],
                    "frames": frames,
                })
                provenance.append(detail)
            expected = set(json.loads(task['ccd_indices_json']))
            if {band['ccd_index'] for band in bands} != expected:
                raise AcquisitionError('hardware_sample_bands_missing', '全部所选 CCD 均须有已确认结果')
            if not method_ccds <= expected:
                raise AcquisitionError('hardware_sample_method_ccds_missing', '采集结果没有覆盖方法全部启用谱线')
            decisions = db.execute("SELECT * FROM hardware_decisions WHERE task_id=? ORDER BY id", (task_id,))
            record = ConfirmedSpectrum(
                source_record_id=source_id,
                source_sha256=task["result_sha256"],
                layout_id=layout["id"],
                device_profile_id=task["device_profile_id"],
                method_id=task["method_id"],
                method_version=task["method_version"],
                method_version_id=method.version_id,
                sample_name=payload.get("sample_name") or task["sample_name"],
                sample_kind=payload.get("sample_kind", "test"),
                name_length=int(payload.get("name_length", 12)),
                sampling_period_seconds=task["sampling_period_seconds"],
                bands=bands,
                evidence={
                    "hardware_task_id": task_id,
                    "method_content_sha256": method.content_sha256,
                    "confirmed_exposures": provenance,
                    "decisions": [dict(row) for row in decisions],
                },
                captured_at=task["completed_at"] or utc_now(),
            )
            try:
                result = importer.import_confirmed(record, actor_user_id)
            except ValueError as exc:
                raise AcquisitionError('hardware_sample_invalid', str(exc)) from exc
            audit_details = {**result, 'method_content_sha256': method.content_sha256, 'exposures': provenance}
            audit_json = json.dumps(audit_details, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            db.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, 'hardware.sample.save', 'hardware', ?, ?, ?)",
                (actor_user_id, task_id, audit_json, utc_now()),
            )
            return result
