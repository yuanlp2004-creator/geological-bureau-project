from __future__ import annotations
import json
import sqlite3
from typing import Any
from ...db import Database, utc_now
from .codec import _pack_points, _unpack_points
from .rules import _metrics, _normalize_plan, _thresholds
from .values import HardwareError, HardwareTaskState, _ANOMALIES, _POLICIES, _STRATEGIES, _finite, _json, _sha
from ..methods import MethodService
from ..spectral_lines import canonical_lines
from .exposures import exposure_config, exposure_results


class HardwareRepository:
    def __init__(self, database: Database):
        self.database = database

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
            raise HardwareError(
                "hardware_task_not_found",
                "hardware acquisition task was not found",
                details={"task_id": task_id},
                status_code=404,
            )
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()
        profile_row = db.execute("SELECT * FROM device_profiles WHERE id=?", (task["device_profile_id"],)).fetchone()
        if layout is None or profile_row is None:
            raise HardwareError(
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
            config = exposure_config(task, row)
            result["steps"].append(dict(row) | {"key_band": bool(row["key_band"]),
                'storage_mode': config['storage_mode'], 'start_frame': config['start_frame'], 'end_frame': config['end_frame'],
                'captured_frames': db.execute('SELECT COALESCE(MAX(frame_index),0) FROM hardware_exposure_frames '
                                              'WHERE step_id=? AND attempt=?', (row['id'], row['last_attempt'] + 1)).fetchone()[0]})
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
        frames = []
        # 响应默认只带帧摘要，确需绘图时才解码点值，避免轮询反复传输全部原始数据。
        for row in db.execute(
            "SELECT * FROM hardware_frames WHERE task_id=? ORDER BY step_id, attempt, ccd_index", (task_id,)
        ).fetchall():
            item = dict(row)
            if include_points and row["points_blob"] is not None:
                item["points"] = _unpack_points(row["points_blob"], int(row["points_count"]))
            item.pop("points_blob", None)
            item["damaged"] = bool(item["damaged"])
            item["confirmed"] = bool(item["confirmed"])
            frames.append(item)
        result["frames"] = frames
        result['exposures'] = exposure_results(db, task_id, include_points)
        from ..acquisition_import import AcquisitionRecordImporter
        result['analysis_sample'] = AcquisitionRecordImporter().bind(db).confirmed_source(f'hardware-task:{task_id}')
        result["latest_trace"] = result["traces"][-1] if result["traces"] else None
        result["latest_decision"] = result["decisions"][-1] if result["decisions"] else None
        return result

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM hardware_tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)
                ).fetchall()
            ]
        return [self._task_dict(task_id) for task_id in ids]

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
            methods = [{'method_id': item.method.id, 'version': item.version, 'name': item.method.name}
                       for item in MethodService(self.database).bind_snapshots(db).published()]
        return {
            "states": [state.value for state in HardwareTaskState],
            "strategies": sorted(_STRATEGIES),
            "anomaly_policies": sorted(_POLICIES),
            "anomaly_kinds": sorted(_ANOMALIES),
            "profiles": profiles,
            "layouts": layouts,
            "methods": methods,
        }

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        strategy = str(payload.get("strategy", "short_to_long"))
        policy = str(payload.get("anomaly_policy", "retry_then_stop"))
        if policy not in _POLICIES:
            raise HardwareError("anomaly_policy_invalid", "anomaly policy is not supported", details={"policy": policy})
        # 先规范化计划顺序、关键点和异常阈值，计划配置与任务一起固化。
        plan = _normalize_plan(list(payload.get("turns") or []), strategy)
        thresholds = _thresholds(payload)
        retry_limit = int(payload.get("retry_limit", 1))
        if not 0 <= retry_limit <= 5:
            raise HardwareError("retry_limit_invalid", "retry limit must be between 0 and 5")
        with self.database.write() as db:
            profile_id = int(payload.get("device_profile_id", 1))
            profile = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
            if profile is None:
                raise HardwareError("device_profile_not_found", "device profile was not found", status_code=404)
            layout_key = payload.get("ccd_layout_id", "default")
            layout = db.execute(
                "SELECT * FROM ccd_layouts WHERE id=? OR name=?",
                (layout_key if str(layout_key).isdigit() else -1, str(layout_key)),
            ).fetchone()
            if layout is None:
                raise HardwareError("ccd_layout_not_found", "CCD layout was not found", status_code=404)
            allowed = self._layout_indices(layout)
            selected = [int(value) for value in (payload.get("ccd_indices") or allowed)]
            if not selected or len(selected) != len(set(selected)) or any(value not in allowed for value in selected):
                raise HardwareError(
                    "ccd_indices_invalid", "selected CCDs must be a subset of the layout", details={"allowed": allowed}
                )
            if int(profile["points_per_ccd"]) != int(layout["points_per_ccd"]):
                raise HardwareError(
                    "ccd_layout_profile_mismatch", "device profile and CCD layout point counts differ", status_code=409
                )
            # 锁定可选方法发布版本及设备布局，后续帧沿用此任务的上下文。
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
                    raise HardwareError(
                        "method_revision_not_found", "published method revision was not found", status_code=404
                    )
                method_version = int(method_row["version"])
                methods = MethodService(self.database)
                snapshot = methods.bind_snapshots(db).for_print(int(method_id), method_version)
                conditions = snapshot.payload['conditions']
                locator = methods.bind_geometry(db, conditions)
                if locator.layout_id != layout['id']:
                    raise HardwareError('hardware_method_layout_mismatch', '转角任务与方法 CCD 布局不一致')
                if not payload.get('ccd_indices') and conditions.get('selected_ccds'):
                    selected = [int(ccd) for ccd in conditions['selected_ccds']]
                    if not selected or len(selected) != len(set(selected)) or any(ccd not in allowed for ccd in selected):
                        raise HardwareError('hardware_method_ccds_invalid', '方法 CCD 选择不属于当前布局')
                exposures = conditions['angle_exposures']
                if not plan:
                    lines = canonical_lines(snapshot.payload.get('lines'), conditions)
                    turns = []
                    for index, exposure in enumerate(exposures):
                        slot_ccds = [ccd for ccd in selected if ccd // int(layout['ccds_per_frame']) == index]
                        if not slot_ccds:
                            raise HardwareError('hardware_method_ccds_missing', '方法转角没有选中的 CCD，不能遗漏波段')
                        candidates = []
                        for line in lines:
                            location = locator.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm']))
                            if line.get('enabled') and location is not None and location.ccd_index in slot_ccds:
                                candidates.append((line, location))
                        positioning = next((location for line, location in candidates if line['line_type'] == 'positioning'), None)
                        baseline = next((location for line, location in candidates if line['line_type'] == 'baseline'), None)
                        turns.append({**exposure, 'wavelength_nm': locator.wavelength_at(slot_ccds[0], 1024),
                                      'key_band': any(line.get('critical_band', False) for line, _ in candidates),
                                      'priority': max((line.get('priority', 0) for line, _ in candidates), default=0),
                                      'expected_peak_position': positioning.point if positioning else 1024,
                                      'expected_baseline_position': baseline.point if baseline else 256,
                                      'baseline_ccd_index': baseline.ccd_index if baseline else None,
                                      'peak_ccd_index': positioning.ccd_index if positioning else None,
                                      'ccd_indices': slot_ccds})
                    plan = _normalize_plan(turns, strategy)
                    for item in plan:
                        item['ccd_indices'] = turns[item['source_index']]['ccd_indices']
                if {item['angle_deg'] for item in plan} != {item['angle_deg'] for item in exposures}:
                    raise HardwareError('hardware_method_angles_mismatch', '绑定方法必须覆盖其全部转角')
                for item in plan:
                    exposure = next(entry for entry in exposures if entry['angle_deg'] == item['angle_deg'])
                    slot = exposures.index(exposure)
                    item['ccd_indices'] = [ccd for ccd in selected if ccd // int(layout['ccds_per_frame']) == slot]
                    item.update({key: exposure[key] for key in ('storage_mode', 'start_frame', 'end_frame')})
                    item['method_content_sha256'] = snapshot.content_sha256
            if not plan:
                raise HardwareError('hardware_turns_required', '请选择已发布方法或填写转角计划')
            for item in plan:
                if any(item[key] is not None and item[key] not in item.get('ccd_indices', selected)
                       for key in ('baseline_ccd_index', 'peak_ccd_index')):
                    raise HardwareError('hardware_monitor_ccd_invalid', '监测谱线必须位于该转角所选的 CCD')
                if any(item[key] >= layout['points_per_ccd'] for key in ('expected_peak_position', 'expected_baseline_position')):
                    raise HardwareError('hardware_window_outside_ccd', '基线或定位峰的理论位置超出 CCD 点数')
            pre_seconds = _finite(payload.get("pre_excitation_seconds", 1), "pre_excitation_seconds", 0, 600)
            period = _finite(payload.get("sampling_period_seconds", 1), "sampling_period_seconds", 0.001, 60)
            simulator = {
                "sample": str(payload.get("simulator_sample", "280-288.acq")),
                "seed": int(payload.get("seed", 0)),
                "anomalies": list(payload.get("simulator_anomalies") or []),
            }
            for item in simulator["anomalies"]:
                step_index = int(item.get("step_index", -1))
                kind = str(item.get("kind", ""))
                count = int(item.get("count", 1))
                if not 0 <= step_index < len(plan) or kind not in _ANOMALIES or not 1 <= count <= 20:
                    raise HardwareError(
                        "simulator_anomaly_invalid", "simulator anomaly script is invalid", details={"item": item}
                    )
            now = utc_now()
            cursor = db.execute(
                (
                    "INSERT INTO hardware_tasks(name, status, device_profile_id, ccd_layout_id, transport,"
                    " strategy, anomaly_policy, sample_name, method_id, method_version, retry_limit,"
                    " pre_excitation_seconds, sampling_period_seconds, ccd_indices_json, plan_json,"
                    " thresholds_json, simulator_json, total_steps, created_by, created_at, updated_at) "
                    "VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    str(payload.get("name", "S14 真实设备与自动转角")).strip(),
                    profile["id"],
                    layout["id"],
                    profile["transport"],
                    strategy,
                    policy,
                    str(payload.get("sample_name", "")).strip(),
                    method_id,
                    method_version,
                    retry_limit,
                    pre_seconds,
                    period,
                    _json(selected),
                    _json(plan),
                    _json(thresholds),
                    _json(simulator),
                    len(plan),
                    actor_user_id,
                    now,
                    now,
                ),
            )
            task_id = int(cursor.lastrowid)
            # 逐项持久化规范化后的转角计划，原始输入顺序与执行顺序分别保存供追溯。
            for item in plan:
                db.execute(
                    (
                        "INSERT INTO hardware_plan_steps(task_id, order_index, source_index, angle_deg,"
                        " wavelength_nm, priority, key_band, expected_peak_position, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    (
                        task_id,
                        item["order_index"],
                        item["source_index"],
                        item["angle_deg"],
                        item["wavelength_nm"],
                        item["priority"],
                        int(item["key_band"]),
                        item["expected_peak_position"],
                        now,
                        now,
                    ),
                )
            self._message(
                db,
                task_id,
                "info",
                "task.created",
                "hardware turn task created",
                {"strategy": strategy, "total_steps": len(plan), "transport": profile["transport"]},
            )
            self._audit(
                db,
                actor_user_id,
                "hardware.task.create",
                task_id,
                {"strategy": strategy, "total_steps": len(plan), "transport": profile["transport"]},
            )
        return self._task_dict(task_id)

    def _trace(
        self,
        db: sqlite3.Connection,
        task_id: int,
        direction: str,
        kind: str,
        name: str,
        payload: dict[str, Any],
        correlation_id: str,
        safe_state: str,
        raw_payload: bytes | None = None,
    ) -> None:
        sequence = int(
            db.execute(
                "SELECT COALESCE(MAX(sequence_no), -1) + 1 FROM hardware_traces WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        )
        payload_json = _json(payload)
        db.execute(
            (
                "INSERT INTO hardware_traces(task_id, sequence_no, direction, kind, name, "
                "payload_json, payload_sha256, raw_payload, correlation_id, safe_state, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                task_id,
                sequence,
                direction,
                kind,
                name,
                payload_json,
                _sha(payload_json),
                raw_payload,
                correlation_id,
                safe_state,
                utc_now(),
            ),
        )

    @staticmethod
    def _message(
        db: sqlite3.Connection, task_id: int, level: str, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        db.execute(
            "INSERT INTO hardware_messages(task_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, level, code, message, _json(details or {}), utc_now()),
        )

    @staticmethod
    def _audit(
        db: sqlite3.Connection, actor_user_id: int | None, action: str, target_id: int, details: dict[str, Any]
    ) -> None:
        db.execute(
            (
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                "details_json, created_at) VALUES (?, ?, 'hardware', ?, ?, ?)"
            ),
            (actor_user_id, action, target_id, _json(details), utc_now()),
        )

    def _current_step(self, db: sqlite3.Connection, task: sqlite3.Row) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM hardware_plan_steps WHERE task_id=? AND order_index=?",
            (task["id"], task["current_step_index"]),
        ).fetchone()
        if row is None:
            raise HardwareError("hardware_plan_step_missing", "current turn plan step is missing", status_code=409)
        return row

    def _store_frames(
        self,
        db: sqlite3.Connection,
        task: sqlite3.Row,
        step: sqlite3.Row,
        attempt: int,
        event: dict[str, Any],
        anomalies: list[str],
        confirmed: bool,
    ) -> tuple[list[dict[str, Any]], str | None]:
        selected = exposure_config(task, step).get('ccd_indices', json.loads(task['ccd_indices_json']))
        by_ccd = {int(item["ccd_index"]): item for item in event.get("ccds", [])}
        details = event.get("details") or {}
        observed_rows: list[dict[str, Any]] = []
        first_sha: str | None = None
        # 每个所选 CCD 单独保存观测指标、点值和哈希；缺失数据保留损坏标记，默认不确认。
        for ccd_index in selected:
            points, observed, detected = _metrics(dict(task), dict(step), by_ccd.get(ccd_index), anomalies)
            # 转角超时或帧故障标为物理损坏，不保存可用点值；数值阈值异常与物理损坏分开记录。
            physical_damage = ccd_index not in by_ccd or not points or bool(set(anomalies).intersection({"frame_fault", "turn_timeout"}))
            blob = None if observed["raw_peak_value"] is None or physical_damage else _pack_points(points)
            points_sha = _sha(blob) if blob is not None else None
            if first_sha is None:
                first_sha = points_sha
            anomaly_kind = ",".join(observed['detected']) if detected else None
            db.execute(
                (
                    "INSERT INTO hardware_frames(task_id, step_id, attempt, ccd_index, points_blob,"
                    " points_count, points_sha256, raw_transfer_sha256, raw_byte_length, headers_json,"
                    " baseline_intensity, baseline_position, expected_peak_position, peak_position,"
                    " peak_value, virtual_time_ms, damaged, confirmed, anomaly_kind, damage_code,"
                    " damage_message, captured_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    task["id"],
                    step["id"],
                    attempt,
                    ccd_index,
                    blob,
                    len(points),
                    points_sha,
                    details.get("sha256"),
                    int(details.get("byte_length", 0)),
                    _json(details.get("headers", [])),
                    observed["baseline_intensity"],
                    observed["baseline_position"],
                    observed["expected_peak_position"],
                    observed["peak_position"],
                    observed["raw_peak_value"],
                    (
                        int(task["current_step_index"]) * float(task["sampling_period_seconds"])
                        + attempt * float(task["sampling_period_seconds"])
                    )
                    * 1000,
                    int(physical_damage),
                    int(confirmed and not detected),
                    anomaly_kind,
                    "simulated_fault" if physical_damage else None,
                    "simulated hardware anomaly" if detected else None,
                    utc_now(),
                ),
            )
            # 再按阈值展开基线及峰位异常种类，供重试或人工决定使用；未确认帧不能被视为有效结果。
            detected_kinds = observed['detected']
            observed_rows.append({"ccd_index": ccd_index, **observed, "detected": sorted(set(detected_kinds))})
        return observed_rows, first_sha

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

    def _decision(
        self,
        db: sqlite3.Connection,
        task: sqlite3.Row,
        step: sqlite3.Row,
        attempt: int,
        anomaly_kind: str,
        decision: str,
        observed: list[dict[str, Any]],
        actor_user_id: int | None,
        reason: str,
    ) -> None:
        db.execute(
            (
                "INSERT INTO hardware_decisions(task_id, step_id, attempt, anomaly_kind, "
                "decision, observed_json, threshold_json, reason, actor_user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                task["id"],
                step["id"],
                attempt,
                anomaly_kind,
                decision,
                _json(observed),
                task["thresholds_json"],
                reason,
                actor_user_id,
                utc_now(),
            ),
        )
