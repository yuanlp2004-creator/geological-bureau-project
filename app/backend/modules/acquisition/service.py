from __future__ import annotations
import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any
from ...db import Database, utc_now
from ..devices import AcqSimulatorAdapter, AcquisitionState as DeviceAcquisitionState, DeviceError, DeviceEvent
from ..sample_queues import SampleQueueService
from .repository import AcquisitionRepository
from .simulation import _seeded_acquisition_event
from .values import AcquisitionError, AcquisitionState, _json


class AcquisitionService:
    @staticmethod
    def interval_band(connection, sample_id: int, ccd_index: int, interval: tuple[int, int] | None = None):
        """Detached, hash-checked acquisition values in the caller's transaction."""
        from .codec import average_points, _unpack_float32
        row = connection.execute(
            'SELECT b.*, t.burn_cycle_seconds,t.dark_cycle_seconds FROM acquisition_sample_bands b '
            'JOIN acquisition_samples s ON s.id=b.sample_id JOIN acquisition_tasks t ON t.id=s.task_id '
            'WHERE b.sample_id=? AND b.ccd_index=?', (sample_id, ccd_index),
        ).fetchone()
        if row is None:
            if interval is not None:
                task = connection.execute('SELECT t.* FROM acquisition_tasks t JOIN acquisition_samples s ON s.task_id=t.id WHERE s.id=?', (sample_id,)).fetchone()
                frames = connection.execute('SELECT * FROM acquisition_frames WHERE sample_id=? AND ccd_index=? AND damaged=0 ORDER BY frame_index', (sample_id, ccd_index)).fetchall()
                if task and frames:
                    for frame in frames:
                        blob = bytes(frame['points_blob'] or b'')
                        if len(blob) != int(frame['points_count']) * 2 or hashlib.sha256(blob).hexdigest() != frame['points_sha256']:
                            raise AcquisitionError('analysis_band_integrity_failed', '采集中分时帧校验失败')
                    start, end = interval
                    burn = [bytes(frame['points_blob']) for frame in frames if frame['phase'] == 'burn' and start - 1 <= frame['frame_index'] < end]
                    dark = [bytes(frame['points_blob']) for frame in frames if frame['phase'] == 'dark']
                    if len(burn) == end - start + 1:
                        count = int(frames[0]['points_count'])
                        blob = average_points(burn, dark, count, burn_cycle_seconds=task['burn_cycle_seconds'], dark_cycle_seconds=task['dark_cycle_seconds'])
                        return {'points': _unpack_float32(blob, count), 'interval': interval, 'provisional': True}
                raise AcquisitionError('analysis_interval_waiting', '等待谱线曝光区间的完整燃烧帧')
            raise AcquisitionError('analysis_band_missing', '谱线对应的 CCD 谱带不存在')
        count = int(row['points_count'])
        mean = bytes(row['mean_blob'])
        if len(mean) != count * 4 or hashlib.sha256(mean).hexdigest() != row['mean_sha256']:
            raise AcquisitionError('analysis_band_integrity_failed', '谱带形状或 SHA-256 校验失败')
        if interval is not None:
            burn = bytes(row['burn_frames_blob'] or b'')
            dark = bytes(row['dark_frames_blob'] or b'')
            for blob, frames, digest in ((burn, row['burn_frame_count'], row['burn_sha256']),
                                         (dark, row['dark_frame_count'], row['dark_sha256'])):
                if len(blob) != int(frames) * count * 2 or (blob and hashlib.sha256(blob).hexdigest() != digest):
                    raise AcquisitionError('analysis_interval_frames_missing', '谱线区间需要完整且通过哈希检查的分时帧')
            start, end = interval
            frames = connection.execute('SELECT * FROM acquisition_frames WHERE sample_id=? AND ccd_index=? AND damaged=0 ORDER BY frame_index', (sample_id, ccd_index)).fetchall()
            if frames:
                for frame in frames:
                    blob = bytes(frame['points_blob'] or b'')
                    if len(blob) != count * 2 or hashlib.sha256(blob).hexdigest() != frame['points_sha256']:
                        raise AcquisitionError('analysis_band_integrity_failed', '分时帧校验失败')
                burns = [bytes(frame['points_blob']) for frame in frames if frame['phase'] == 'burn' and start - 1 <= frame['frame_index'] < end]
                darks = [bytes(frame['points_blob']) for frame in frames if frame['phase'] == 'dark']
                if not 1 <= start < end or len(burns) != end - start + 1:
                    raise AcquisitionError('analysis_interval_invalid', '谱线曝光段超出实际完整帧范围')
                mean = average_points(burns, darks, count, burn_cycle_seconds=row['burn_cycle_seconds'], dark_cycle_seconds=row['dark_cycle_seconds'])
                return {'points': _unpack_float32(mean, count), 'mean_sha256': row['mean_sha256'], 'interval': interval}
            if not 1 <= start < end <= int(row['burn_frame_count']):
                raise AcquisitionError('analysis_interval_invalid', '谱线曝光段超出实际燃烧帧范围')
            mean = average_points([burn[i * count * 2:(i + 1) * count * 2] for i in range(start - 1, end)],
                [dark[i * count * 2:(i + 1) * count * 2] for i in range(int(row['dark_frame_count']))], count,
                burn_cycle_seconds=row['burn_cycle_seconds'], dark_cycle_seconds=row['dark_cycle_seconds'])
        return {'points': _unpack_float32(mean, count), 'mean_sha256': row['mean_sha256'], 'interval': interval}

    def __init__(self, database: Database):
        self.database = database
        self.sample_queues = SampleQueueService(database)
        self._adapters: dict[int, AcqSimulatorAdapter] = {}
        self._task_locks: dict[int, threading.Lock] = {}
        self._task_locks_guard = threading.Lock()
        self.repository = AcquisitionRepository(database)

    @contextmanager
    def _control_scope(self, task_id: int):
        with self._task_locks_guard:
            lock = self._task_locks.setdefault(task_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise AcquisitionError(
                "acquisition_task_busy", "当前任务正在执行另一项采集操作", details={"task_id": task_id}, status_code=409
            )
        try:
            yield
        finally:
            lock.release()

    def _adapter(self, task_id: int, profile: sqlite3.Row) -> AcqSimulatorAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = AcqSimulatorAdapter()
            self._adapters[task_id] = adapter
        if adapter.state == DeviceAcquisitionState.IDLE:
            adapter.connect(self.repository._profile_dict(profile), correlation_id=f"acquisition-{task_id}")
        return adapter

    def _start_adapter(self, task_id: int, task: sqlite3.Row, profile: sqlite3.Row) -> tuple[AcqSimulatorAdapter, Any]:
        adapter = self._adapter(task_id, profile)
        simulator = json.loads(task["simulator_json"] or "{}")
        try:
            event = adapter.start_debug(
                sample=str(simulator.get("sample", "280-288.acq")),
                seed=int(simulator.get("seed", 0)) + int(task["current_repeat_index"]),
                fault_frame=simulator.get("fault_frame"),
                correlation_id=f"acquisition-{task_id}",
            )
            event = _seeded_acquisition_event(
                event,
                repeat_index=int(task["current_repeat_index"]),
                phase="burn",
                frame_index=0,
                sample_kind=str(task["sample_kind"]),
            )
        except DeviceError as exc:
            raise AcquisitionError(
                "acquisition_start_failed", exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        return adapter, event

    def start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._start(task_id, actor_user_id)

    def _start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        status = str(task["status"])
        if status in {
            state.value
            for state in (
                AcquisitionState.COUNTDOWN,
                AcquisitionState.PRE_EXCITATION,
                AcquisitionState.BURN,
                AcquisitionState.DARK,
                AcquisitionState.BETWEEN_REPEATS,
                AcquisitionState.PAUSED,
            )
        }:
            return self.repository._task_dict(task_id)
        if status != AcquisitionState.DRAFT.value:
            raise AcquisitionError(
                "acquisition_task_not_startable",
                "当前任务状态不能开始采集",
                details={"status": status},
                status_code=409,
            )
        try:
            adapter, event = self._start_adapter(task_id, task, profile)
        except AcquisitionError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise
        now = utc_now()
        next_state = (
            AcquisitionState.COUNTDOWN.value
            if float(task["countdown_seconds"]) > 0
            else AcquisitionState.PRE_EXCITATION.value
        )
        with self.database.write() as db:
            sample_id = self.repository._create_sample(db, task)
            db.execute(
                (
                    "UPDATE acquisition_tasks SET status=?, adapter_session_id=?, "
                    "countdown_remaining=?, last_event_json=?, last_message=?, started_at=?, "
                    "updated_at=? WHERE id=?"
                ),
                (
                    next_state,
                    adapter.session_id,
                    task["countdown_seconds"],
                    _json(event.to_dict()),
                    "预激发已准备" if next_state == "pre_excitation" else "倒计时开始",
                    now,
                    now,
                    task_id,
                ),
            )
            self.repository._message(
                db, task_id, "info", "task.start", "采集已开始", {"state": next_state, "sample_id": sample_id}
            )
            self.repository._audit(
                db,
                actor_user_id,
                "acquisition.task.start",
                task_id,
                {"state": next_state, "correlation_id": event.correlation_id},
            )
        return self.repository._task_dict(task_id)

    def _finish_repeat(
        self,
        db: sqlite3.Connection,
        task: sqlite3.Row,
        sample: sqlite3.Row,
        actor_user_id: int | None,
    ) -> str:
        """在调用方事务内固化本次重复，并决定等待下一次还是完成任务。"""
        self.repository._finalize_sample(db, task, sample, actor_user_id)
        task_id = int(task["id"])
        completed_repeats = int(task["completed_repeats"]) + 1
        if completed_repeats < int(task["repeat_count"]):
            db.execute(
                "UPDATE acquisition_tasks SET status=?, current_repeat_index=?, completed_repeats=?, "
                "burn_frames_captured=0, dark_frames_captured=0, last_message=?, updated_at=? WHERE id=?",
                (
                    "between_repeats",
                    int(task["current_repeat_index"]) + 1,
                    completed_repeats,
                    "当前重复已完成，等待下一次采集",
                    utc_now(),
                    task_id,
                ),
            )
            return "between_repeats"
        self._complete_task(db, task, completed_repeats, actor_user_id)
        return "completed"

    def _complete_task(
        self,
        db: sqlite3.Connection,
        task: sqlite3.Row,
        completed_repeats: int,
        actor_user_id: int | None,
    ) -> None:
        """在同一事务内保存任务结果、关联队列并记录完成消息与审计。"""
        task_id = int(task["id"])
        sample_hashes = db.execute(
            "SELECT result_sha256 FROM acquisition_samples WHERE task_id=? ORDER BY repeat_index",
            (task_id,),
        ).fetchall()
        task_hash = hashlib.sha256(
            "|".join(row["result_sha256"] or "" for row in sample_hashes).encode("ascii")
        ).hexdigest()
        db.execute(
            "UPDATE acquisition_tasks SET status='completed', completed_repeats=?, result_sha256=?, "
            "completed_at=?, last_message=?, updated_at=? WHERE id=?",
            (completed_repeats, task_hash, utc_now(), "全部采集完成", utc_now(), task_id),
        )
        if task["queue_id"] is not None and task["queue_item_id"] is not None and task["sample_kind"] != "preheat":
            self.sample_queues.attach_acquisition(
                int(task["queue_id"]),
                int(task["queue_item_id"]),
                task_hash,
                actor_user_id,
                connection=db,
            )
        self.repository._message(
            db,
            task_id,
            "success",
            "task.completed",
            "全部采集完成",
            {"result_sha256": task_hash},
        )
        self.repository._audit(db, actor_user_id, "acquisition.task.completed", task_id, {"repeat_count": completed_repeats})

    def _close_adapter(self, task_id: int) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            try:
                adapter.stop_debug(correlation_id=f"acquisition-{task_id}")
                adapter.disconnect(correlation_id=f"acquisition-{task_id}")
            except DeviceError:
                pass

    def _begin_next_repeat(self, task_id: int, actor_user_id: int | None = None) -> None:
        task, _, profile = self.repository._context(task_id)
        adapter, event = self._start_adapter(task_id, task, profile)
        with self.database.write() as db:
            current = self.repository._context(task_id, db)[0]
            sample_id = self.repository._create_sample(db, current)
            db.execute(
                (
                    "UPDATE acquisition_tasks SET status='pre_excitation', adapter_session_id=?, "
                    "burn_frames_captured=0, dark_frames_captured=0, last_event_json=?, "
                    "last_message=?, updated_at=? WHERE id=?"
                ),
                (adapter.session_id, _json(event.to_dict()), "下一次重复预激发已开始", utc_now(), task_id),
            )
            self.repository._message(
                db,
                task_id,
                "info",
                "sample.repeat.start",
                "下一次重复采集已开始",
                {"repeat_index": current["current_repeat_index"], "sample_id": sample_id},
            )
            self.repository._audit(
                db,
                actor_user_id,
                "acquisition.repeat.start",
                task_id,
                {"repeat_index": current["current_repeat_index"]},
            )

    def _fail_task(
        self, task_id: int, code: str, message: str, actor_user_id: int | None = None, *, event: Any | None = None
    ) -> None:
        with self.database.write() as db:
            task = db.execute("SELECT * FROM acquisition_tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task["status"] in {"completed", "failed", "stopped"}:
                return
            sample = db.execute(
                "SELECT * FROM acquisition_samples WHERE task_id=? AND status='collecting' ORDER BY repeat_index DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if sample is not None:
                db.execute(
                    "UPDATE acquisition_samples SET status='failed', failure_code=?, failure_message=?, updated_at=? WHERE id=?",
                    (code, message, utc_now(), sample["id"]),
                )
            db.execute(
                (
                    "UPDATE acquisition_tasks SET status='failed', failure_code=?, "
                    "failure_message=?, last_message=?, last_event_json=COALESCE(?, "
                    "last_event_json), completed_at=?, updated_at=? WHERE id=?"
                ),
                (
                    code,
                    message,
                    message,
                    _json(event.to_dict()) if event is not None else None,
                    utc_now(),
                    utc_now(),
                    task_id,
                ),
            )
            self.repository._message(db, task_id, "error", code, message, {})
            self.repository._audit(db, actor_user_id, "acquisition.task.failed", task_id, {"code": code, "message": message})
        self._close_adapter(task_id)

    def step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._step(task_id, actor_user_id)

    def _step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        status = str(task["status"])
        if status == AcquisitionState.COUNTDOWN.value:
            remaining = max(0.0, float(task["countdown_remaining"]) - float(task["sampling_period_seconds"]))
            next_state = AcquisitionState.PRE_EXCITATION.value if remaining <= 0 else status
            with self.database.write() as db:
                db.execute(
                    "UPDATE acquisition_tasks SET status=?, countdown_remaining=?, last_message=?, updated_at=? WHERE id=?",
                    (
                        next_state,
                        remaining,
                        "预激发准备" if next_state == "pre_excitation" else f"倒计时 {remaining:.3f} 秒",
                        utc_now(),
                        task_id,
                    ),
                )
                self.repository._message(db, task_id, "info", "task.countdown", "倒计时推进", {"remaining_seconds": remaining})
            return self.repository._task_dict(task_id)
        if status == AcquisitionState.BETWEEN_REPEATS.value:
            self._begin_next_repeat(task_id, actor_user_id)
            return self.repository._task_dict(task_id)
        if status not in {
            AcquisitionState.PRE_EXCITATION.value,
            AcquisitionState.BURN.value,
            AcquisitionState.DARK.value,
        }:
            raise AcquisitionError(
                "acquisition_task_not_running", "当前任务未处于可采集状态", details={"status": status}, status_code=409
            )
        task, _, profile = self.repository._context(task_id)
        with self.database.read() as db:
            sample = self.repository._current_sample(db, task_id, int(task["current_repeat_index"]))
        adapter = self._adapters.get(task_id)
        if status == AcquisitionState.PRE_EXCITATION.value and float(task["pre_excitation_seconds"]) > 0:
            with self.database.write() as db:
                db.execute(
                    "UPDATE acquisition_tasks SET status='burn', last_message=?, updated_at=? WHERE id=?",
                    ("预激发完成，开始正式燃烧采集", utc_now(), task_id),
                )
                self.repository._message(
                    db,
                    task_id,
                    "info",
                    "task.pre_excitation.complete",
                    "预激发完成，开始正式燃烧采集",
                    {"seconds": float(task["pre_excitation_seconds"]), "sample_id": sample["id"]},
                )
            return self.repository._task_dict(task_id)
        try:
            if status == AcquisitionState.PRE_EXCITATION.value:
                event = json.loads(task["last_event_json"] or "{}")
                phase, frame_index = "burn", 0
                stored = _seeded_acquisition_event(
                    DeviceEvent(
                        event_type=str(event.get("event_type", "frame")),
                        state=DeviceAcquisitionState(str(event.get("state", DeviceAcquisitionState.DEBUGGING.value))),
                        occurred_at=str(event.get("occurred_at") or utc_now()),
                        correlation_id=str(event.get("correlation_id", f"acquisition-{task_id}")),
                        frame_index=event.get("frame_index"),
                        frame_count=event.get("frame_count"),
                        ccds=list(event.get("ccds") or []),
                        message=str(event.get("message", "")),
                        details=dict(event.get("details") or {}),
                    ),
                    repeat_index=int(task["current_repeat_index"]),
                    phase=phase,
                    frame_index=frame_index,
                    sample_kind=str(task["sample_kind"]),
                )
            else:
                if adapter is None:
                    raise AcquisitionError(
                        "acquisition_session_lost", "采集会话已丢失，已收帧不会被替换", status_code=409
                    )
                event = adapter.step_debug(correlation_id=f"acquisition-{task_id}")
                if event.event_type == "fault":
                    with self.database.write() as db:
                        live = self.repository._context(task_id, db)[0]
                        current_sample = self.repository._current_sample(db, task_id, int(live["current_repeat_index"]))
                        phase = "burn" if status == "burn" else "dark"
                        frame_index = int(
                            live["burn_frames_captured"] if phase == "burn" else live["dark_frames_captured"]
                        )
                        self.repository._store_damaged(db, live, current_sample, phase, frame_index, event)
                    self._fail_task(
                        task_id,
                        str(event.details.get("code", "device_fault")),
                        event.message or "CCD 帧损坏",
                        actor_user_id,
                        event=event,
                    )
                    return self.repository._task_dict(task_id, include_points=True)
                phase = "burn" if status == "burn" else "dark"
                frame_index = int(task["burn_frames_captured"] if phase == "burn" else task["dark_frames_captured"])
                event = _seeded_acquisition_event(
                    event,
                    repeat_index=int(task["current_repeat_index"]),
                    phase=phase,
                    frame_index=frame_index,
                    sample_kind=str(task["sample_kind"]),
                )
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise AcquisitionError(
                "acquisition_frame_failed", exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        except AcquisitionError:
            raise
        next_state = status
        with self.database.write() as db:
            live = self.repository._context(task_id, db)[0]
            current_sample = self.repository._current_sample(db, task_id, int(live["current_repeat_index"]))
            self.repository._store_event(
                db,
                live,
                current_sample,
                phase,
                frame_index,
                stored if status == "pre_excitation" else event,
                self.repository._virtual_time(live, int(current_sample["repeat_index"]), phase, frame_index),
            )
            burn_captured = int(live["burn_frames_captured"]) + (1 if phase == "burn" else 0)
            dark_captured = int(live["dark_frames_captured"]) + (1 if phase == "dark" else 0)
            if phase == "burn" and burn_captured >= int(live["burn_frame_count"]):
                next_state = "dark" if int(live["dark_frame_count"]) > 0 else "completed"
            elif phase == "dark" and dark_captured >= int(live["dark_frame_count"]):
                next_state = "completed"
            else:
                next_state = phase
            db.execute(
                (
                    "UPDATE acquisition_tasks SET status=?, burn_frames_captured=?, "
                    "dark_frames_captured=?, last_event_json=?, last_message=?, updated_at=? WHERE "
                    "id=?"
                ),
                (
                    next_state,
                    burn_captured,
                    dark_captured,
                    _json((stored if status == "pre_excitation" else event).to_dict()),
                    f"{phase} 第 {frame_index + 1} 帧已保存",
                    utc_now(),
                    task_id,
                ),
            )
            self.repository._message(
                db,
                task_id,
                "info",
                "frame.capture",
                f"{phase} 第 {frame_index + 1} 帧已保存",
                {"phase": phase, "frame_index": frame_index, "repeat_index": current_sample["repeat_index"]},
            )
            self.repository._audit(
                db,
                actor_user_id,
                "acquisition.frame.capture",
                task_id,
                {
                    "phase": phase,
                    "frame_index": frame_index,
                    "repeat_index": current_sample["repeat_index"],
                    "sha256": (stored if status == "pre_excitation" else event).details.get("sha256", ""),
                },
            )
            if next_state == "completed":
                next_state = self._finish_repeat(db, live, current_sample, actor_user_id)
        if next_state in {"between_repeats", "completed"}:
            self._close_adapter(task_id)
        return self.repository._task_dict(task_id, include_points=True)

    def pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._pause(task_id, actor_user_id)

    def _pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self.repository._context(task_id)
        status = str(task["status"])
        if status == "paused":
            return self.repository._task_dict(task_id)
        if status not in {"countdown", "pre_excitation", "burn", "dark"}:
            raise AcquisitionError(
                "acquisition_task_not_pauseable", "当前任务不能暂停", details={"status": status}, status_code=409
            )
        with self.database.write() as db:
            db.execute(
                "UPDATE acquisition_tasks SET status='paused', paused_from=?, last_message=?, updated_at=? WHERE id=?",
                (status, "采集已暂停", utc_now(), task_id),
            )
            self.repository._message(db, task_id, "warning", "task.pause", "采集已暂停", {"from": status})
            self.repository._audit(db, actor_user_id, "acquisition.task.pause", task_id, {"from": status})
        return self.repository._task_dict(task_id)

    def resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._resume(task_id, actor_user_id)

    def _resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self.repository._context(task_id)
        status = str(task["status"])
        if status != "paused":
            if status in {"countdown", "pre_excitation", "burn", "dark"}:
                return self.repository._task_dict(task_id)
            raise AcquisitionError(
                "acquisition_task_not_resumable", "当前任务未暂停", details={"status": status}, status_code=409
            )
        target = task["paused_from"] or "burn"
        with self.database.write() as db:
            db.execute(
                "UPDATE acquisition_tasks SET status=?, paused_from=NULL, last_message=?, updated_at=? WHERE id=?",
                (target, "采集已继续", utc_now(), task_id),
            )
            self.repository._message(db, task_id, "info", "task.resume", "采集已继续", {"to": target})
            self.repository._audit(db, actor_user_id, "acquisition.task.resume", task_id, {"to": target})
        return self.repository._task_dict(task_id)

    def stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._stop(task_id, actor_user_id)

    def _stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self.repository._context(task_id)
        status = str(task["status"])
        if status in {"completed", "failed", "stopped"}:
            return self.repository._task_dict(task_id)
        with self.database.write() as db:
            db.execute(
                "UPDATE acquisition_tasks SET status='stopping', last_message=?, updated_at=? WHERE id=?",
                ("正在停止采集", utc_now(), task_id),
            )
            current = db.execute(
                "SELECT id FROM acquisition_samples WHERE task_id=? AND status='collecting' ORDER BY repeat_index DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if current is not None:
                db.execute(
                    (
                        "UPDATE acquisition_samples SET status='stopped', failure_code='stopped', "
                        "failure_message='用户停止采集', updated_at=? WHERE id=?"
                    ),
                    (utc_now(), current["id"]),
                )
            db.execute(
                "UPDATE acquisition_tasks SET status='stopped', completed_at=?, last_message=?, updated_at=? WHERE id=?",
                (utc_now(), "采集已停止，已收帧保留", utc_now(), task_id),
            )
            self.repository._message(db, task_id, "warning", "task.stop", "采集已停止，已收帧保留", {})
            self.repository._audit(db, actor_user_id, "acquisition.task.stop", task_id, {"from": status})
        self._close_adapter(task_id)
        return self.repository._task_dict(task_id)

    def list_tasks(self, limit: int = 50, *, task_kind: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_tasks(limit, task_kind=task_kind)

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        return self.repository.create_task(payload, actor_user_id)

    def frames(
        self,
        task_id: int,
        *,
        repeat_index: int | None = None,
        phase: str | None = None,
        ccd_index: int | None = None,
        include_points: bool = False,
    ) -> list[dict[str, Any]]:
        return self.repository.frames(task_id, repeat_index=repeat_index, phase=phase, ccd_index=ccd_index, include_points=include_points)

    def analysis(self, task_id: int, repeat_index: int | None = None) -> dict[str, Any]:
        return self.repository.analysis(task_id, repeat_index)

    def mark_interval(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        return self.repository.mark_interval(task_id, payload, actor_user_id)

    def rename(
        self, task_id: int, sample_id: int, post_name: str, actor_user_id: int | None = None,
        *, name_length: int | None = None
    ) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self.repository.rename(task_id, sample_id, post_name, actor_user_id, name_length=name_length)

    def band(self, sample_id: int, ccd_index: int | None = None, include_points: bool = False) -> list[dict[str, Any]]:
        return self.repository.band(sample_id, ccd_index, include_points)

    def spectrum_records(self) -> list[dict[str, Any]]:
        return self.repository.spectrum_records()

    def sample_identity(self, sample_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row=db.execute('SELECT id,task_id,sample_name,repeat_index FROM acquisition_samples WHERE id=?',(sample_id,)).fetchone()
            if row is None:
                raise AcquisitionError('acquisition_sample_not_found','采集样品不存在',status_code=404)
            return dict(row)

    def spectrum_snapshot(self, sample_id: int, *, include_frames: bool = False) -> dict[str, Any]:
        from ..devices import DeviceService
        snapshot = self.repository.spectrum_snapshot(sample_id, include_frames=include_frames)
        snapshot['point_width_um'] = DeviceService(self.database).profile(snapshot['sample']['device_profile_id'])['point_width_um']
        return snapshot

    def spectrum_interval(self, sample_id: int, interval: tuple[int, int]) -> dict[int, dict]:
        """Read an exposure view through the acquisition boundary; stored bands remain immutable."""
        snapshot = self.spectrum_snapshot(sample_id)
        with self.database.read() as db:
            return {band["ccd_index"]: self.interval_band(db, sample_id, band["ccd_index"], interval)
                    for band in snapshot["bands"]}

    def get_task(self, task_id: int, *, include_points: bool = False) -> dict[str, Any]:
        return self.repository._task_dict(task_id, include_points=include_points)

    def measurement_snapshot(self, task_id: int) -> dict[str, Any]:
        return self.repository.measurement_snapshot(task_id)

    def discard(self, task_id: int, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            raise AcquisitionError("sample_discard_reason_missing", "删除异常样品必须说明原因")
        with self._control_scope(task_id):
            # 删除标记与队列解绑一起提交，实体和帧保留供审计；已被分析引用的样品会拒绝删除。
            # 在任务控制锁内处置异常样品，删除后的样品不得再改名或用作正式结果。
            with self.database.write() as db:
                task, _, _ = self.repository._context(task_id, db)
                samples = db.execute("SELECT * FROM acquisition_samples WHERE task_id=?", (task_id,)).fetchall()
                if not samples:
                    raise AcquisitionError("sample_discard_empty", "尚未开始摄谱，没有可删除样品", status_code=409)
                for sample in samples:
                    if db.execute("SELECT 1 FROM acquisition_sample_disposals WHERE sample_id=?", (sample["id"],)).fetchone():
                        continue
                    try:
                        db.execute("INSERT INTO acquisition_sample_disposals VALUES (?,?,?,?)", (sample["id"], reason, actor_user_id, utc_now()))
                    except sqlite3.IntegrityError as exc:
                        if "sample already analyzed" not in str(exc):
                            raise
                        raise AcquisitionError("sample_already_analyzed", "样品已被分析引用，请在重复性质控中剔除", status_code=409) from exc
                    self.repository._audit(db, actor_user_id, "acquisition.sample.discard", sample["id"],
                                           {"task_id": task_id, "reason": reason, "result_sha256": sample["result_sha256"]})
                if task["status"] not in {"completed", "failed", "stopped"}:
                    db.execute("UPDATE acquisition_tasks SET status='stopped', completed_at=?, updated_at=? WHERE id=?", (utc_now(), utc_now(), task_id))
                    db.execute("UPDATE acquisition_samples SET status='stopped', updated_at=? WHERE task_id=? AND status='collecting'", (utc_now(), task_id))
                db.execute("UPDATE acquisition_tasks SET last_message=?, updated_at=? WHERE id=?", (f"异常样品已删除：{reason}", utc_now(), task_id))
                if task["queue_id"] is not None:
                    self.sample_queues.release_acquisition(task["queue_id"], task["queue_item_id"], task["result_sha256"], connection=db)
                self.repository._message(db, task_id, "warning", "sample.discard", "异常样品已删除，原始帧保留供审计", {"reason": reason})
            # 处置提交后关闭仍保留的采集适配器，再读取服务确认后的任务详情。
            self._close_adapter(task_id)
            return self.repository._task_dict(task_id)

    @staticmethod
    def management_task_ids(db: sqlite3.Connection) -> set[int]:
        return {int(row[0]) for row in db.execute('SELECT task_id FROM acquisition_management_tasks')}
