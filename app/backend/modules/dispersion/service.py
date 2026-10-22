from __future__ import annotations
import json
import sqlite3
import threading
from typing import Any
from ...db import Database, utc_now
from ..devices import AcqSimulatorAdapter, AcquisitionState, DeviceError
from .calibration import CalibrationService
from .repository import DispersionRepository
from .values import DispersionError, DispersionState, _finite, _json, _task_command


class DispersionService:
    def open_legacy_record(self, identifier: int, actor_user_id: int | None = None) -> dict:
        from .legacy_open import open_record
        return open_record(self, identifier, actor_user_id)

    def __init__(self, database: Database):
        self.database = database
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._adapters: dict[int, AcqSimulatorAdapter] = {}
        self.repository = DispersionRepository(database)
        self.calibrations = CalibrationService(database)

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
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

    def _adapter(self, task_id: int, profile: sqlite3.Row) -> AcqSimulatorAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = AcqSimulatorAdapter()
            self._adapters[task_id] = adapter
        if adapter.state == AcquisitionState.IDLE:
            adapter.connect(self.repository._profile_dict(profile), correlation_id=f"dispersion-{task_id}")
        return adapter

    @_task_command
    def start_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
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
        try:
            adapter = self._adapter(task_id, context.profile)
            event = adapter.start_debug(
                sample=json.loads(context.task["condition_json"] or "{}").get("sample", "280-288.acq"),
                seed=int(json.loads(context.task["condition_json"] or "{}").get("seed", 0)),
                fault_frame=None,
                correlation_id=f"dispersion-{task_id}",
            )
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
                {"correlation_id": event.correlation_id, "state": "pre_excitation"},
            )
        return self.repository._task_dict(task_id)

    def _advance_once(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
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
            if new_state == "completed":
                self._close_adapter(task_id)
            return self.repository._task_dict(task_id)
        if status not in {DispersionState.BURN.value, DispersionState.DARK.value}:
            raise DispersionError(
                "dispersion_task_not_running", "当前任务未处于可采集状态", details={"status": status}, status_code=409
            )
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = self._adapter(task_id, context.profile)
        try:
            event = adapter.step_debug(correlation_id=f"dispersion-{task_id}")
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise DispersionError(
                "dispersion_frame_failed", exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        if event.event_type == "fault":
            self._fail_task(task_id, str(event.details.get("code", "device_fault")), event.message, actor_user_id)
            return self.repository._task_dict(task_id)
        phase = "burn" if status == DispersionState.BURN.value else "dark"
        burn_count = int(context.task["burn_frames_captured"])
        dark_count = int(context.task["dark_frames_captured"])
        phase_index = burn_count if phase == "burn" else dark_count
        with self.database.write() as db:
            virtual_time_ms = (
                float(context.task["pre_excitation_seconds"])
                + (phase_index if phase == "burn" else int(context.task["frame_count"]) + phase_index)
                * float(context.task["sampling_period_seconds"])
            ) * 1000
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
                {"phase": phase, "frame_index": phase_index, "sha256": event.details.get("sha256")},
            )
        if new_state == "completed":
            self._close_adapter(task_id)
        return self.repository._task_dict(task_id)

    @_task_command
    def step_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._advance_once(task_id, actor_user_id)

    @_task_command
    def pause_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
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

    def _close_adapter(self, task_id: int) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            try:
                adapter.stop_debug(correlation_id=f"dispersion-{task_id}")
                adapter.disconnect(correlation_id=f"dispersion-{task_id}")
            except DeviceError:
                pass

    @_task_command
    def stop_task(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        status = str(context.task["status"])
        if status in {DispersionState.COMPLETED.value, DispersionState.FAILED.value, DispersionState.STOPPED.value}:
            return self.repository._task_dict(task_id)
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
            db.execute(
                (
                    "UPDATE dispersion_tasks SET status='failed', failure_code=?, failure_message=?, "
                    "updated_at=?, completed_at=? WHERE id=?"
                ),
                (code, message, utc_now(), utc_now(), task_id),
            )
            self.repository._audit(db, actor_user_id, "dispersion.task.failed", task_id, {"code": code, "message": message})
        self._close_adapter(task_id)

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.repository.list_tasks(limit)

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    def frames(self, task_id: int, *, phase: str | None = None, ccd_index: int | None = None) -> list[dict[str, Any]]:
        return self.repository.frames(task_id, phase=phase, ccd_index=ccd_index)

    def add_line(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.add_line(task_id, payload, actor_user_id)

    @_task_command
    def update_gap(self, task_id: int, gap_index: int, gap_um: float, actor=None) -> dict[str, Any]:
        return self.calibrations.update_gap(task_id, gap_index, gap_um, actor)

    def update_line_wavelength(self, task_id: int, line_id: int, wavelength: float, actor=None) -> dict[str, Any]:
        return self.calibrations.update_line_wavelength(task_id, line_id, wavelength, actor)

    def delete_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.delete_line(task_id, line_id, actor_user_id)

    def locate_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.locate_line(task_id, line_id, actor_user_id)

    def locate_all(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.locate_all(task_id, actor_user_id)

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

    def restore_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.restore_line_position(task_id, line_id, actor_user_id)

    def fit_calibration(
        self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.calibrations.fit_calibration(task_id, payload, actor_user_id)

    def publish_calibration(self, calibration_version_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.calibrations.publish_calibration(calibration_version_id, actor_user_id)

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
