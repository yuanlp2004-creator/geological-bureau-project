from __future__ import annotations
from contextlib import ExitStack, nullcontext
from functools import partial
import hashlib
import json
import sqlite3
import threading
from typing import Any
from ...db import Database, utc_now
from ..devices import AcqSimulatorAdapter, SerialAcqAdapter, create_device_adapter, monitor_capture, AcquisitionState, DeviceError
from .calibration import CalibrationService
from .repository import DispersionRepository
from .values import DispersionError, DispersionState, _finite, _json, _task_command, _task_scope


class DispersionService:
    def open_legacy_record(self, identifier: int, actor_user_id: int | None = None) -> dict:
        from .legacy_open import open_record
        return open_record(self, identifier, actor_user_id)

    def __init__(self, database: Database, *, exit_gate=None, on_frame_saved=None, on_serial_notice=None):
        self.database = database
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._start_lock = threading.Lock()
        self._adapters: dict[int, AcqSimulatorAdapter | SerialAcqAdapter] = {}
        self.repository = DispersionRepository(database)
        self.calibrations = CalibrationService(database)
        self._exit_gate = exit_gate
        self._on_frame_saved = on_frame_saved
        self._on_serial_notice = on_serial_notice

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None, *, connection=None, capture_turn=None) -> dict[str, Any]:
        with (self.database.write() if connection is None else nullcontext(connection)) as db:
            layout = self.repository._resolve_layout(db, payload.get("ccd_layout_id", "default"))
            profile = self.repository._profile(db, int(payload.get("device_profile_id", 1)))
            frame_count = int(payload.get("frame_count", 3))
            dark_count = int(payload.get("dark_frame_count", 0))
            pre_seconds = _finite(payload.get("pre_excitation_seconds", 3), "pre_excitation_seconds")
            period = _finite(payload.get("sampling_period_seconds", 1), "sampling_period_seconds")
            from ...services import AppService
            gap_error = AppService(self.database).get_settings()['analysis']['dispersion_allow_gap_error_um']
            residual_limit = _finite(payload.get("residual_limit_points") or gap_error / float(layout['point_width']), "residual_limit_points")
            if frame_count < 1 or frame_count > 255 or dark_count < 0 or dark_count > 20:
                raise DispersionError("dispersion_condition_invalid", "燃烧帧数或暗帧数超出范围")
            if pre_seconds < 0 or pre_seconds > 600 or period <= 0 or period > 60 or residual_limit <= 0:
                raise DispersionError("dispersion_condition_invalid", "采集条件超出范围")
            selected = payload.get("ccd_indices") or self.repository._layout_indices(layout)
            try:
                selected = [int(value) for value in selected]
            except (TypeError, ValueError) as exc:
                raise DispersionError("ccd_indices_invalid", "CCD 索引必须是整数") from exc
            allowed = self.repository._layout_indices(layout)
            if not selected or len(selected) != len(set(selected)) or any(value not in allowed for value in selected):
                raise DispersionError(
                    "ccd_indices_invalid", "CCD 选择必须是当前布局的唯一子集", details={"allowed": allowed}
                )
            if profile["transport"] == "serial" and not set(selected).issubset(json.loads(profile["ccd_indices_json"])):
                raise DispersionError("ccd_profile_selection_invalid", "真实采集不能选择设备档案中未安装的CCD")
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
            condition = {
                key: payload.get(key)
                for key in (
                    "sample",
                    "seed",
                    "frame_count",
                    "dark_frame_count",
                    "pre_excitation_seconds",
                    "sampling_period_seconds",
                    "residual_limit_points",
                )
            }
            if payload.get("preheat"):
                condition.update(preheat=True, preheat_source_task_id=payload["preheat_source_task_id"])
            if capture_turn:
                condition['capture_turn'] = capture_turn
                condition['reference_coefficients'] = capture_turn['reference_coefficients']
            cursor = db.execute(
                (
                    "INSERT INTO dispersion_tasks(name, status, device_profile_id, ccd_layout_id, "
                    "method_id, method_version, frame_count, dark_frame_count, "
                    "pre_excitation_seconds, sampling_period_seconds, residual_limit_points, "
                    "ccd_indices_json, condition_json, created_by, created_at, updated_at) VALUES "
                    "(?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    str(payload.get("name", "S12 色散校准")).strip(),
                    profile["id"],
                    layout["id"],
                    method_id,
                    method_version,
                    frame_count,
                    dark_count,
                    pre_seconds,
                    period,
                    residual_limit,
                    _json(selected),
                    _json(condition),
                    actor_user_id,
                    now,
                    now,
                ),
            )
            task_id = int(cursor.lastrowid)
            if payload.get("source_record_id") is not None:
                self.repository._import_wdt(db, task_id, layout, int(payload["source_record_id"]), actor_user_id)
            for line in payload.get("lines", []):
                self.calibrations._insert_line(db, task_id, layout, line, now)
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.task.create",
                task_id,
                {"ccd_layout_id": layout["id"], "frame_count": frame_count, "dark_frame_count": dark_count},
            )
            return self.repository._task_dict(task_id, db)

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self.repository._task_dict(task_id)

    def coordinate(self, task_id: int, wavelength: float) -> dict[str, Any]:
        wavelength = _finite(wavelength, 'wavelength_nm')
        with self.database.read() as db:
            context = self.repository._context(task_id, db)
            for ccd in json.loads(context.task['ccd_indices_json']):
                point = self.repository._expected_position(db, context.layout, wavelength, ccd)
                if point is not None:
                    return {'ccd_index': ccd, 'point_index': round(point)}
        raise DispersionError('line_wavelength_out_of_range', '该波长不在当前任务的 CCD 范围内')

    @_task_command
    def preheat_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        source = self.repository._task_dict(task_id)
        if source["discarded_at"]:
            raise DispersionError("dispersion_task_discarded", "该色散摄谱任务已删除", status_code=409)
        if source["status"] not in {"draft", "completed", "failed", "stopped"}:
            raise DispersionError("dispersion_task_busy", "当前摄谱尚未结束，不能预热", status_code=409)
        payload = {key: source[key] for key in (
            "device_profile_id", "ccd_layout_id", "ccd_indices", "frame_count", "dark_frame_count",
            "pre_excitation_seconds", "sampling_period_seconds", "residual_limit_points", "method_id", "method_version",
        )}
        payload.update(name=f"预热 · {source['name']}"[:120], preheat=True,
                       preheat_source_task_id=source["condition"].get("preheat_source_task_id", task_id),
                       sample=source["condition"].get("sample") or "280-288.acq",
                       seed=source["condition"].get("seed") or 0)
        warmup = self.create_task(payload, actor_user_id, capture_turn=source.get('capture_turn'))
        return self.start_task(warmup["id"], actor_user_id)

    def _adapter(self, task_id: int, profile: sqlite3.Row) -> AcqSimulatorAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            notice = partial(self._on_serial_notice, task_id=task_id) if self._on_serial_notice else None
            adapter = create_device_adapter(dict(profile), exit_gate=self._exit_gate, on_serial_notice=notice)
            self._adapters[task_id] = adapter
        if adapter.state == AcquisitionState.IDLE:
            adapter.connect(self.repository._profile_dict(profile), correlation_id=f"dispersion-{task_id}")
        return adapter

    def active_serial_connections(self) -> list[dict[str, Any]]:
        return [{"task_id": task_id, **adapter.diagnostics()} for task_id, adapter in list(self._adapters.items())
                if isinstance(adapter, SerialAcqAdapter) and adapter.diagnostics()['connected']]

    @_task_command
    def start_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._start_lock:
            return self._start_task(task_id, actor_user_id)

    def _start_task(self, task_id: int, actor_user_id: int | None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        if context.task["discarded_at"]:
            raise DispersionError("dispersion_task_discarded", "该色散摄谱任务已删除", status_code=409)
        status = str(context.task["status"])
        if status in {
            DispersionState.PRE_EXCITATION.value,
            DispersionState.BURN.value,
            DispersionState.DARK.value,
            DispersionState.PAUSED.value,
        }:
            return self.repository._task_dict(task_id)
        if status != DispersionState.DRAFT.value:
            raise DispersionError(
                "dispersion_task_not_startable", "当前任务状态不能开始采集", details={"status": status}, status_code=409
            )
        condition = json.loads(context.task['condition_json'] or '{}')
        turn = condition.get('capture_turn')
        position = None
        if turn:
            if turn['multiple'] and context.profile['transport'] != 'simulator':
                raise DispersionError('hardware_protocol_unavailable', '真实自动转角协议尚未确认，不能执行多转角摄谱', status_code=409)
            with self.database.read() as db:
                members = self.repository.capture_turn_members(db, turn, include_preheat=True)
            if any(row['id'] != task_id and row['status'] not in {'draft', 'completed', 'failed', 'stopped'} for row in members):
                raise DispersionError('dispersion_task_busy', '请先完成或停止正在摄谱的转角', status_code=409)
        try:
            adapter = self._adapter(task_id, context.profile)
            if isinstance(adapter, SerialAcqAdapter):
                event = adapter.prepare_capture(pre_seconds=float(context.task["pre_excitation_seconds"]),
                    burn_seconds=float(context.task["sampling_period_seconds"]), burn_count=int(context.task["frame_count"]),
                    dark_seconds=float(context.task["sampling_period_seconds"]), dark_count=int(context.task["dark_frame_count"]),
                    correlation_id=f"dispersion-{task_id}")
            else:
                correlation_id = f'dispersion-{task_id}'
                args = {'sample': condition.get('sample') or '280-288.acq', 'seed': int(condition.get('seed') or 0),
                        'fault_frame': None, 'correlation_id': correlation_id}
                event = adapter.start_debug(**args)
                if turn and turn['multiple']:
                    from ..hardware_acquisition import confirm_simulated_turn
                    position = confirm_simulated_turn(adapter, turn['angle_deg'], correlation_id)
                    event = adapter.start_debug(**{**args, 'seed': args['seed'] + turn['turn_index'] * 1009})
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise DispersionError(
                "dispersion_start_failed", exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        now = utc_now()
        with self.database.write() as db:
            db.execute(
                (
                    "UPDATE dispersion_tasks SET status='pre_excitation', paused_from=NULL, "
                    "adapter_session_id=?, last_event_json=?, started_at=COALESCE(started_at, ?), "
                    "updated_at=? WHERE id=?"
                ),
                (adapter.session_id, _json(event.to_dict()), now, now, task_id),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.task.start",
                task_id,
                {"correlation_id": event.correlation_id, "state": "pre_excitation", **({'turn': position} if position else {})},
            )
        if isinstance(adapter, SerialAcqAdapter):
            try:
                adapter.begin_capture()
            except DeviceError as exc:
                self._fail_task(task_id, exc.code, exc.message, actor_user_id)
                raise DispersionError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
            monitor_capture(adapter, lambda: self.step_task(task_id, actor_user_id),
                            lambda message: self._fail_task(task_id, "serial_capture_failed", message, actor_user_id))
        return self.repository._task_dict(task_id)

    def _advance_once(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        status = str(context.task["status"])
        real = isinstance(self._adapters.get(task_id), SerialAcqAdapter) or context.profile["transport"] == "serial"
        if real and task_id not in self._adapters and status in {"pre_excitation", "burn", "dark", "paused"}:
            self._fail_task(task_id, "dispersion_session_lost", "真实采集会话已丢失，已收帧保留，请检查仪器后新建任务", actor_user_id)
            raise DispersionError("dispersion_session_lost", "真实采集会话已丢失", status_code=409)
        if not real and status == DispersionState.PRE_EXCITATION.value:
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
                self.repository._store_event(
                    db,
                    task_id,
                    "burn",
                    0,
                    stored,
                    json.loads(context.task["ccd_indices_json"]),
                    float(context.task["pre_excitation_seconds"]) * 1000,
                )
                burn_count = 1
                new_state = (
                    "dark"
                    if burn_count >= int(context.task["frame_count"]) and int(context.task["dark_frame_count"]) > 0
                    else ("completed" if burn_count >= int(context.task["frame_count"]) else "burn")
                )
                db.execute(
                    (
                        "UPDATE dispersion_tasks SET status=?, burn_frames_captured=?, "
                        "dark_frames_captured=0, last_frame_index=?, last_event_json=?, updated_at=?, "
                        "completed_at=? WHERE id=?"
                    ),
                    (
                        new_state,
                        burn_count,
                        0,
                        _json(event),
                        utc_now(),
                        utc_now() if new_state == "completed" else None,
                        task_id,
                    ),
                )
                self.repository._audit(db, actor_user_id, "dispersion.frame.capture", task_id, {"phase": "burn", "frame_index": 0})
            if self._on_frame_saved is not None:
                self._on_frame_saved(task_id, "burn", 0, stored.details)
            if new_state == "completed":
                self._close_adapter(task_id)
            return self.repository._task_dict(task_id)
        if status not in {DispersionState.PRE_EXCITATION.value, DispersionState.BURN.value, DispersionState.DARK.value}:
            raise DispersionError(
                "dispersion_task_not_running", "当前任务未处于可采集状态", details={"status": status}, status_code=409
            )
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = self._adapter(task_id, context.profile)
        try:
            event = adapter.next_capture_event() if real else adapter.step_debug(correlation_id=f"dispersion-{task_id}")
            if event is None:
                return self.repository._task_dict(task_id)
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise DispersionError(
                "dispersion_frame_failed", exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        if event.event_type == "fault":
            self._fail_task(task_id, str(event.details.get("code", "device_fault")), event.message, actor_user_id)
            return self.repository._task_dict(task_id)
        phase = str(event.details["phase"]) if real else ("burn" if status == DispersionState.BURN.value else "dark")
        burn_count = int(context.task["burn_frames_captured"])
        dark_count = int(context.task["dark_frames_captured"])
        phase_index = burn_count if phase == "burn" else dark_count
        if real and int(event.details["phase_index"]) != phase_index:
            self._fail_task(task_id, "serial_frame_sequence_invalid", "真实CCD帧序异常", actor_user_id)
            return self.repository._task_dict(task_id)
        with self.database.write() as db:
            virtual_time_ms = (
                float(context.task["pre_excitation_seconds"])
                + (phase_index if phase == "burn" else int(context.task["frame_count"]) + phase_index)
                * float(context.task["sampling_period_seconds"])
            ) * 1000
            if real:
                virtual_time_ms = event.details["elapsed_ms"]
            self.repository._store_event(
                db, task_id, phase, phase_index, event, json.loads(context.task["ccd_indices_json"]), virtual_time_ms
            )
            burn_count += 1 if phase == "burn" else 0
            dark_count += 1 if phase == "dark" else 0
            completed = burn_count >= int(context.task["frame_count"]) and dark_count >= int(
                context.task["dark_frame_count"]
            )
            if phase == "burn" and burn_count >= int(context.task["frame_count"]):
                new_state = "dark" if int(context.task["dark_frame_count"]) > 0 else "completed"
            elif phase == "dark" and dark_count >= int(context.task["dark_frame_count"]):
                new_state = "completed"
            else:
                new_state = phase
            db.execute(
                (
                    "UPDATE dispersion_tasks SET status=?, burn_frames_captured=?, "
                    "dark_frames_captured=?, last_frame_index=?, last_event_json=?, updated_at=?, "
                    "completed_at=? WHERE id=?"
                ),
                (
                    new_state,
                    burn_count,
                    dark_count,
                    event.frame_index,
                    _json(event.to_dict()),
                    utc_now(),
                    utc_now() if completed else None,
                    task_id,
                ),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.frame.capture",
                task_id,
                {"phase": phase, "frame_index": phase_index, "sha256": event.details.get("sha256"),
                 **({"communication": event.details.get("communication", [])} if real else {})},
            )
        if self._on_frame_saved is not None:
            self._on_frame_saved(task_id, phase, phase_index, event.details)
        if new_state == "completed":
            self._close_adapter(task_id)
        return self.repository._task_dict(task_id)

    @_task_command
    def step_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._advance_once(task_id, actor_user_id)

    @_task_command
    def pause_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        if context.profile["transport"] == "serial":
            raise DispersionError("serial_pause_unsupported", "旧设备协议未提供暂停命令；请使用停止", status_code=409)
        status = str(context.task["status"])
        if status == DispersionState.PAUSED.value:
            return self.repository._task_dict(task_id)
        if status not in {DispersionState.PRE_EXCITATION.value, DispersionState.BURN.value, DispersionState.DARK.value}:
            raise DispersionError(
                "dispersion_task_not_pauseable", "当前任务不能暂停", details={"status": status}, status_code=409
            )
        with self.database.write() as db:
            db.execute(
                "UPDATE dispersion_tasks SET status='paused', paused_from=?, updated_at=? WHERE id=?",
                (status, utc_now(), task_id),
            )
            self.repository._audit(db, actor_user_id, "dispersion.task.pause", task_id, {"from": status})
        return self.repository._task_dict(task_id)

    @_task_command
    def resume_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        status = str(context.task["status"])
        if status != DispersionState.PAUSED.value:
            if status in {DispersionState.PRE_EXCITATION.value, DispersionState.BURN.value, DispersionState.DARK.value}:
                return self.repository._task_dict(task_id)
            raise DispersionError(
                "dispersion_task_not_resumable", "当前任务未暂停", details={"status": status}, status_code=409
            )
        target = context.task["paused_from"] or "burn"
        with self.database.write() as db:
            db.execute(
                "UPDATE dispersion_tasks SET status=?, paused_from=NULL, updated_at=? WHERE id=?",
                (target, utc_now(), task_id),
            )
            self.repository._audit(db, actor_user_id, "dispersion.task.resume", task_id, {"to": target})
        return self.repository._task_dict(task_id)

    def _close_adapter(self, task_id: int, *, strict: bool = False) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            try:
                if not isinstance(adapter, SerialAcqAdapter):
                    adapter.stop_debug(correlation_id=f"dispersion-{task_id}")
                adapter.disconnect(correlation_id=f"dispersion-{task_id}")
            except DeviceError:
                if strict and isinstance(adapter, SerialAcqAdapter):
                    raise

    def shutdown(self) -> list[dict[str, Any]]:
        errors = []
        for task_id in list(self._adapters):
            adapter = self._adapters.get(task_id)
            if isinstance(adapter, SerialAcqAdapter):
                try:
                    adapter.disconnect(correlation_id="application-shutdown")
                except DeviceError as exc:
                    errors.append({"task_id": task_id, **exc.detail()})
                try:
                    with self._locks[task_id]:
                        self._stop_task(task_id)
                except Exception as exc:
                    errors.append({"task_id": task_id, "message": str(exc)})
                    import logging
                    logging.getLogger(__name__).exception("Serial dispersion shutdown was not confirmed")
        return errors

    @_task_command
    def stop_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._stop_task(task_id, actor_user_id)

    def _stop_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        status = str(context.task["status"])
        if status in {DispersionState.COMPLETED.value, DispersionState.FAILED.value, DispersionState.STOPPED.value}:
            return self.repository._task_dict(task_id)
        if context.profile["transport"] == "serial" and task_id not in self._adapters and status in {"pre_excitation", "burn", "dark", "paused"}:
            self._fail_task(task_id, "dispersion_session_lost", "真实采集会话已丢失，无法发送结束指令，请检查仪器状态", actor_user_id)
            raise DispersionError("dispersion_session_lost", "无法确认仪器已停止，请检查仪器状态", status_code=409)
        try:
            adapter = self._adapters.get(task_id)
            if isinstance(adapter, SerialAcqAdapter):
                try:
                    adapter.stop_debug(correlation_id=f"dispersion-{task_id}")
                except DeviceError:
                    pass
                while adapter.pending_frames and task_id in self._adapters:
                    self._advance_once(task_id, actor_user_id)
                if adapter.capture_error:
                    raise adapter.capture_error
                if self.repository._context(task_id).task["status"] == "completed":
                    self._close_adapter(task_id, strict=True)
                    return self.repository._task_dict(task_id)
            self._close_adapter(task_id, strict=True)
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise DispersionError(exc.code, exc.message, details=exc.details, status_code=409) from exc
        with self.database.write() as db:
            db.execute("UPDATE dispersion_tasks SET status='stopping', updated_at=? WHERE id=?", (utc_now(), task_id))
            self.repository._audit(db, actor_user_id, "dispersion.task.stop.request", task_id, {"from": status})
        self._close_adapter(task_id)
        with self.database.write() as db:
            db.execute(
                "UPDATE dispersion_tasks SET status='stopped', completed_at=COALESCE(completed_at, ?), updated_at=? WHERE id=?",
                (utc_now(), utc_now(), task_id),
            )
            self.repository._audit(db, actor_user_id, "dispersion.task.stop", task_id, {"from": status})
        return self.repository._task_dict(task_id)

    def _fail_task(self, task_id: int, code: str, message: str, actor_user_id: int | None = None) -> None:
        with self.database.write() as db:
            current = db.execute("SELECT status FROM dispersion_tasks WHERE id=?", (task_id,)).fetchone()
            if current is None or current["status"] in {"completed", "failed", "stopped"}:
                return
            db.execute(
                (
                    "UPDATE dispersion_tasks SET status='failed', failure_code=?, failure_message=?, "
                    "updated_at=?, completed_at=? WHERE id=?"
                ),
                (code, message, utc_now(), utc_now(), task_id),
            )
            self.repository._audit(db, actor_user_id, "dispersion.task.failed", task_id, {"code": code, "message": message})
        self._close_adapter(task_id)

    def list_tasks(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.repository.list_tasks(limit, offset)

    def discard_task(self, task_id: int, actor_user_id: int) -> None:
        with self.database.read() as db:
            task = self.repository._context(task_id, db).task
            condition = json.loads(task["condition_json"] or "{}")
            turn = condition.get("capture_turn")
            if turn and condition.get("preheat"):
                raise DispersionError("dispersion_task_not_found", "色散摄谱任务不存在", status_code=404)
            members = self.repository.capture_turn_members(db, turn) if turn else [task]
        ids = [member["id"] for member in members]
        idle = {"draft", "completed", "stopped", "failed"}
        with ExitStack() as locks:
            for identifier in ids:
                locks.enter_context(_task_scope(self, identifier))
            with self.database.write() as db:
                db.execute("BEGIN IMMEDIATE")
                tasks = [self.repository._context(identifier, db).task for identifier in ids]
                if any(item["status"] not in idle or self._adapters.get(item["id"]) is not None for item in tasks):
                    raise DispersionError("dispersion_task_busy", "请先完成或停止当前摄谱，再删除任务", status_code=409)
                if db.execute("""SELECT 1 FROM dispersion_tasks
                    WHERE status NOT IN ('draft','completed','stopped','failed')
                    AND json_extract(condition_json, '$.preheat_source_task_id') IN
                      (SELECT value FROM json_each(?)) LIMIT 1""", (_json(ids),)).fetchone():
                    raise DispersionError("dispersion_task_busy", "请先完成或停止当前预热，再删除任务", status_code=409)
                for item in tasks:
                    if item["discarded_at"]:
                        continue
                    db.execute("UPDATE dispersion_tasks SET discarded_at=? WHERE id=?", (utc_now(), item["id"]))
                    self.repository._audit(db, actor_user_id, "dispersion.task.discard", item["id"], {"status": item["status"]})

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    def frames(self, task_id: int, *, phase: str | None = None, ccd_index: int | None = None) -> list[dict[str, Any]]:
        return self.repository.frames(task_id, phase=phase, ccd_index=ccd_index)

    def spectrum_records(self) -> list[dict[str, Any]]:
        return self.repository.spectrum_records()

    def spectrum_snapshot(self, task_id: int, ccd: int) -> dict[str, Any]:
        records = self.repository.spectrum_records(task_id)
        if not records:
            raise DispersionError("dispersion_spectrum_not_found", "色散谱图不存在", status_code=404)
        record = records[0]
        indices = record["ccd_indices"]
        if not 0 <= ccd < len(indices):
            raise DispersionError("dispersion_point_invalid", "CCD 超出当前谱带范围")
        with self.database.read() as db:
            layout = self.repository._context(task_id, db).layout
            geometry = {"ccd_indices": indices, "ccd_count": len(indices), "points_per_ccd": layout["points_per_ccd"],
                        "gap_points": json.loads(layout["gap_points_json"]), "point_width_um": layout["point_width"],
                        "ws_cof": self.repository._reference_coefficients(db, layout)}
        return {"record": record, "layout": geometry, "frames": self.frames(task_id, ccd_index=indices[ccd])}

    def point_details(self, task_id: int, ccd: int, point: int | None) -> dict[str, Any]:
        from base64 import b64encode
        from struct import pack

        task = self.get_task(task_id)
        points_per_ccd = task['layout']['points_per_ccd']
        if ccd not in task['ccd_indices'] or (point is not None and not 0 <= point < points_per_ccd):
            raise DispersionError('dispersion_point_invalid', '点位超出当前 CCD')
        frames = self.frames(task_id, ccd_index=ccd)
        rows = []
        frame_data = bytearray()
        phase_counts = {}
        for phase in ('burn', 'dark'):
            integrations = [frame for frame in frames if frame['phase'] == phase]
            expected = task['frame_count' if phase == 'burn' else 'dark_frame_count'] if task['status'] == 'completed' else len(integrations)
            if [frame['frame_index'] for frame in integrations] != list(range(expected)):
                raise DispersionError('dispersion_point_frames_missing', '当前谱带的分时帧不完整', status_code=409)
            if any(len(frame['points']) != points_per_ccd for frame in integrations):
                raise DispersionError('dispersion_point_layout_invalid', '分时帧与 CCD 布局不符')
            if point is None:
                for frame in integrations:
                    frame_data.extend(pack(f'<{points_per_ccd}H', *frame['points']))
            else:
                rows.extend({'phase': phase, 'integration': frame['frame_index'] + 1, 'value': frame['points'][point]}
                            for frame in integrations)
            phase_counts[phase] = expected
        if not (rows or frame_data):
            raise DispersionError('dispersion_point_frames_missing', '当前谱带没有可读取的分时帧', status_code=409)
        condition = task['condition']
        ignition = condition.get('ignition', {})
        sampling = task['sampling_period_seconds']
        result = {
            'record_id': f'dispersion:{task_id}', 'sample_name': task['name'], 'ccd_index': ccd,
            'source_sha256': condition.get('source_sha256', ''),
            'pre_excitation_seconds': ignition.get('pre_burn', task['pre_excitation_seconds']),
            'burn_cycle_seconds': ignition.get('burn_cyc', sampling), 'dark_cycle_seconds': ignition.get('dark_cyc', sampling),
            'burn_count': phase_counts['burn'], 'dark_count': phase_counts['dark'],
        }
        if point is None:
            return {**result, 'point_count': points_per_ccd, 'frames_base64': b64encode(frame_data).decode('ascii')}
        result.update(point_index=point, wavelength_nm=None, rows=rows)
        result['sha256'] = hashlib.sha256(_json(result).encode('utf-8')).hexdigest()
        return result

    def observation_spectrum(self, task_id: int, ccd: int, start: int, end: int) -> dict:
        task = self.get_task(task_id)
        if ccd not in task['ccd_indices'] or not 1 <= start <= end <= task['frame_count']:
            raise DispersionError('dispersion_observation_range_invalid', '请选择有效的 CCD 和曝光区间')
        frames = [frame for frame in self.frames(task_id, phase='burn', ccd_index=ccd)
                  if start - 1 <= frame['frame_index'] < end]
        if [frame['frame_index'] for frame in frames] != list(range(start - 1, end)):
            raise DispersionError('dispersion_observation_frames_missing', '所选区间的燃烧帧尚未完整保存')
        if any(len(frame['points']) != task['layout']['points_per_ccd'] for frame in frames):
            raise DispersionError('dispersion_observation_points_invalid', '已保存燃烧帧与 CCD 布局不符')
        return {
            'task_id': task_id, 'label': task['name'], 'ccd': ccd, 'exposure': [start, end],
            'points': [sum(values) / len(frames) for values in zip(*(frame['points'] for frame in frames))],
            'frame_sha256': [frame['points_sha256'] for frame in frames],
        }

    def record_observation_print(self, task_id: int, details: dict, actor: int) -> None:
        with self.database.write() as db:
            self.repository._context(task_id, db)
            self.repository._audit(db, actor, 'dispersion.observation.print', task_id, details)

    def record_observation_copy(self, task_id: int, details: dict, actor: int) -> None:
        with self.database.write() as db:
            self.repository._context(task_id, db)
            self.repository._audit(db, actor, 'dispersion.observation.copy', task_id, details)

    def add_line(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.add_line(task_id, payload, actor_user_id)

    @_task_command
    def update_gap(self, task_id: int, gap_index: int, gap_um: float, actor=None, *, legacy_limits: bool = False) -> dict[str, Any]:
        return self.calibrations.update_gap(task_id, gap_index, gap_um, actor, legacy_limits=legacy_limits)

    def update_line_wavelength(self, task_id: int, line_id: int, wavelength: float, actor=None, *, legacy_input: bool = False) -> dict[str, Any]:
        return self.calibrations.update_line_wavelength(task_id, line_id, wavelength, actor, legacy_input=legacy_input)

    def add_point(self, task_id: int, ccd_index: int, point_index: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.add_point(task_id, ccd_index, point_index, actor_user_id)

    def delete_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.delete_line(task_id, line_id, actor_user_id)

    def locate_line(self, task_id: int, line_id: int, actor_user_id: int | None = None, *, legacy_window: bool = False) -> dict[str, Any]:
        return self.calibrations.locate_line(task_id, line_id, actor_user_id, legacy_window=legacy_window)

    def locate_all(self, task_id: int, actor_user_id: int | None = None, *, legacy_window: bool = False) -> dict[str, Any]:
        return self.calibrations.locate_all(task_id, actor_user_id, legacy_window=legacy_window)

    def move_line(
        self, task_id: int, line_id: int, direction: str, steps: float, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.calibrations.move_line(task_id, line_id, direction, steps, actor_user_id)

    def set_line_position(
        self, task_id: int, line_id: int, position: float, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.calibrations.set_line_position(task_id, line_id, position, actor_user_id)

    def save_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.save_line_position(task_id, line_id, actor_user_id)

    def all_positions(self, task_id: int, restore: bool, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.all_positions(task_id, restore, actor_user_id)

    def restore_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.restore_line_position(task_id, line_id, actor_user_id)

    def fit_calibration(
        self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.calibrations.fit_calibration(task_id, payload, actor_user_id)

    def publish_calibration(self, calibration_version_id: int, actor_user_id: int | None = None, *, name: str | None = None) -> dict[str, Any]:
        return self.calibrations.publish_calibration(calibration_version_id, actor_user_id, name=name)

    def calibration(self, calibration_version_id: int) -> dict[str, Any]:
        return self.calibrations.calibration(calibration_version_id)

    def bind_calibration(
        self, calibration_version_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.calibrations.bind_calibration(calibration_version_id, payload, actor_user_id)

    def manage_calibration(self, identifier: int, action: str, name: str | None, actor: int | None) -> dict[str, Any]:
        return self.calibrations.manage_calibration(identifier, action, name, actor)

    def bindings(self, method_id: int | None = None) -> list[dict[str, Any]]:
        return self.calibrations.bindings(method_id)
