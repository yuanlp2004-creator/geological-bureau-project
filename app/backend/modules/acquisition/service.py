from __future__ import annotations
import hashlib
import json
import sqlite3
import threading
from contextlib import ExitStack, contextmanager
from functools import partial
from typing import Any
from ...db import Database, utc_now
from ..devices import (AcqSimulatorAdapter, SerialAcqAdapter, create_device_adapter, monitor_capture,
                       AcquisitionState as DeviceAcquisitionState, DeviceError, DeviceEvent)
from ..devices.motor_turn import prepare_motor_turn, requires_motor
from ..devices.capture_sequence import CaptureSequence
from ..sample_queues import SampleQueueService
from .repository import AcquisitionRepository
from .simulation import _seeded_acquisition_event
from .values import AcquisitionError, AcquisitionState, _json


class AcquisitionService:
    def current_sample_context(self) -> dict[str, Any]:
        from ..methods import MethodService
        from ..devices.service import DeviceService
        method = MethodService(self.database).current()
        if not method['method_id'] or not method['actions']['can_acquire']:
            raise AcquisitionError('current_method_required', '请先打开可用于摄谱的当前方法')
        profile = DeviceService(self.database).current_profile()
        if not profile:
            raise AcquisitionError('current_device_required', '请先在设备参数选择并保存当前设备')
        queue = self.sample_queues.current_queue()
        if not queue:
            raise AcquisitionError('current_sample_queue_required', '请先在预录样号中选择样号表')
        item = next((item for item in queue['items'] if not item['spectrum_hash'] and item['repeats'] > 0), None)
        if not item:
            raise AcquisitionError('sample_queue_exhausted', '当前样号表没有待测样品，请先在预录样号中录入')
        from ..methods import MethodDomainError
        with self.database.read() as db:
            try:
                plan = MethodService(self.database).sample_plan(db, method['referenced_version']['id'])
            except MethodDomainError as exc:
                raise AcquisitionError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        position_controlled = requires_motor(self.database, profile, multiple=plan['multiple'])
        if position_controlled:
            try:
                prepare_motor_turn(self.database, profile, [turn['angle_deg'] for turn in plan['plan']])
            except DeviceError as exc:
                raise AcquisitionError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        return {'method': {'id': method['method_id'], 'version': method['version'], 'name': method['title']},
                'profile': {'id': profile['id'], 'name': profile['name'], 'transport': profile['transport']},
                'position_controlled': position_controlled,
                'queue': {'id': queue['id'], 'name': queue['name'], 'name_length': queue['name_length']},
                'item': {'id': item['id'], 'name': item['post_name'] or item['pre_name'], 'repeats': item['repeats']}}

    @staticmethod
    def interval_band(connection, sample_id: int, ccd_index: int, interval: tuple[int, int] | None = None, *, turn_index: int | None = None,
                      allow_single_frame: bool = False):
        """Detached, hash-checked acquisition values in the caller's transaction."""
        from .codec import average_points, _unpack_float32
        from .turns import interval_band
        turn_band = interval_band(connection, sample_id, ccd_index, interval, turn_index)
        if turn_band is not None:
            return turn_band
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
            minimum_end = start if allow_single_frame else start + 1
            frames = connection.execute('SELECT * FROM acquisition_frames WHERE sample_id=? AND ccd_index=? AND damaged=0 ORDER BY frame_index', (sample_id, ccd_index)).fetchall()
            if frames:
                for frame in frames:
                    blob = bytes(frame['points_blob'] or b'')
                    if len(blob) != count * 2 or hashlib.sha256(blob).hexdigest() != frame['points_sha256']:
                        raise AcquisitionError('analysis_band_integrity_failed', '分时帧校验失败')
                burns = [bytes(frame['points_blob']) for frame in frames if frame['phase'] == 'burn' and start - 1 <= frame['frame_index'] < end]
                darks = [bytes(frame['points_blob']) for frame in frames if frame['phase'] == 'dark']
                if not (1 <= start and minimum_end <= end) or len(burns) != end - start + 1:
                    raise AcquisitionError('analysis_interval_invalid', '谱线曝光段超出实际完整帧范围')
                mean = average_points(burns, darks, count, burn_cycle_seconds=row['burn_cycle_seconds'], dark_cycle_seconds=row['dark_cycle_seconds'])
                return {'points': _unpack_float32(mean, count), 'mean_sha256': row['mean_sha256'], 'interval': interval}
            if not (1 <= start and minimum_end <= end <= int(row['burn_frame_count'])):
                raise AcquisitionError('analysis_interval_invalid', '谱线曝光段超出实际燃烧帧范围')
            mean = average_points([burn[i * count * 2:(i + 1) * count * 2] for i in range(start - 1, end)],
                [dark[i * count * 2:(i + 1) * count * 2] for i in range(int(row['dark_frame_count']))], count,
                burn_cycle_seconds=row['burn_cycle_seconds'], dark_cycle_seconds=row['dark_cycle_seconds'])
        return {'points': _unpack_float32(mean, count), 'mean_sha256': row['mean_sha256'], 'interval': interval}

    def __init__(self, database: Database, *, exit_gate=None, on_frame_saved=None, on_serial_notice=None):
        self.database = database
        self.sample_queues = SampleQueueService(database)
        self._adapters: dict[int, AcqSimulatorAdapter | SerialAcqAdapter] = {}
        self._task_locks: dict[int, threading.Lock] = {}
        self._task_locks_guard = threading.Lock()
        self.repository = AcquisitionRepository(database)
        self._exit_gate = exit_gate
        self._on_frame_saved = on_frame_saved
        self._on_serial_notice = on_serial_notice
        self._start_lock = threading.Lock()
        self._sequence = CaptureSequence(AcquisitionError, exit_gate)

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

    def _adapter(self, task_id: int, profile: sqlite3.Row) -> AcqSimulatorAdapter | SerialAcqAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            notice = partial(self._on_serial_notice, task_id=task_id) if self._on_serial_notice else None
            adapter = create_device_adapter(dict(profile), exit_gate=self._exit_gate, on_serial_notice=notice)
            self._adapters[task_id] = adapter
        if adapter.state == DeviceAcquisitionState.IDLE:
            adapter.connect(self.repository._profile_dict(profile), correlation_id=f"acquisition-{task_id}")
        return adapter

    def active_serial_connections(self) -> list[dict[str, Any]]:
        result = [{"task_id": task_id, **adapter.diagnostics()} for task_id, adapter in list(self._adapters.items())
                  if isinstance(adapter, SerialAcqAdapter) and adapter.diagnostics()['connected']]
        current = self._sequence.current()
        if current is not None and not any(item['task_id'] == current for item in result):
            _, _, profile = self.repository._context(current)
            if profile['transport'] == 'serial':
                result.append({'task_id': current, 'port': f"COM{profile['port']}", 'state': 'reserved'})
        return result

    def _start_adapter(self, task_id: int, task: sqlite3.Row, profile: sqlite3.Row, *,
                       next_repeat=False, continuation=False) -> tuple[AcqSimulatorAdapter | SerialAcqAdapter, Any]:
        from .turns import context
        with self.database.read() as db:
            config, state = context(db, task_id)
        turn = json.loads(task['excitation_condition_json'] or '{}').get('capture_turn')
        simulator = json.loads(task["simulator_json"] or "{}")
        try:
            motor_turn = None
            if (config or turn) and requires_motor(self.database, profile, multiple=bool((config or turn)['multiple'])):
                if config:
                    angles = [item['angle_deg'] for item in config['plan']]
                    angle = angles[0 if next_repeat else state['turn_index']]
                    motor_turn = (prepare_motor_turn(self.database, profile, angles, preflight=False), angle)
                else:
                    angle = turn['angle_deg']
                    motor_turn = (prepare_motor_turn(self.database, profile, [angle], preflight=False), angle)
            adapter = self._adapter(task_id, profile)
            if isinstance(adapter, SerialAcqAdapter):
                if abs(float(task["sampling_period_seconds"]) - float(task["burn_cycle_seconds"])) > 1e-8:
                    raise DeviceError("serial_period_mismatch", "真实采集的采样周期须与燃烧周期一致")
                event = adapter.prepare_capture(
                    pre_seconds=float(task["pre_excitation_seconds"]), burn_seconds=float(task["burn_cycle_seconds"]),
                    burn_count=int(task["burn_frame_count"]), dark_seconds=float(task["dark_cycle_seconds"]),
                    dark_count=int(task["dark_frame_count"]),
                    countdown_seconds=float(task["countdown_seconds"]) if int(task["current_repeat_index"]) == 0 and not continuation else 0,
                    correlation_id=f"acquisition-{task_id}",
                    **({'motor_turn': motor_turn} if motor_turn else {}),
                )
                return adapter, event
            args = {'sample': str(simulator.get('sample', '280-288.acq')),
                    'seed': int(simulator.get('seed', 0)) + int(task['current_repeat_index']),
                    'fault_frame': simulator.get('fault_frame'), 'correlation_id': f'acquisition-{task_id}'}
            event = adapter.start_debug(**args)
            if turn and turn['multiple']:
                from ..hardware_acquisition import confirm_simulated_turn
                position = confirm_simulated_turn(adapter, turn['angle_deg'], args['correlation_id'])
                event = adapter.start_debug(**{**args, 'seed': args['seed'] + turn['turn_index'] * 1009})
                with self.database.write() as db:
                    self.repository._message(db, task_id, 'info', 'acquisition.turn.positioned',
                                             f"转角 {turn['angle_deg']:g}° 已到位", position)
            event = _seeded_acquisition_event(
                event,
                repeat_index=int(task["current_repeat_index"]),
                phase="burn",
                frame_index=0,
                sample_kind=str(task["sample_kind"]),
            )
        except DeviceError as exc:
            raise AcquisitionError(
                exc.code if motor_turn or exc.code.startswith(('motor_', 'hardware_protocol_')) else "acquisition_start_failed",
                exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        return adapter, event

    def _run_serial(self, task_id: int, adapter: Any, actor_user_id: int | None, *, monitor=True) -> None:
        if isinstance(adapter, SerialAcqAdapter):
            try:
                if self._sequence.cancelled(task_id):
                    adapter.request_stop()
                adapter.begin_capture()
            except DeviceError as exc:
                self._fail_task(task_id, exc.code, exc.message, actor_user_id)
                raise AcquisitionError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
            if monitor:
                monitor_capture(adapter, lambda: self.step(task_id, actor_user_id, single_repeat=True),
                                lambda message: self._fail_task(task_id, "serial_capture_failed", message, actor_user_id))

    def shutdown(self) -> list[dict[str, Any]]:
        errors = self._sequence.shutdown()
        for task_id in list(self._adapters):
            adapter = self._adapters.get(task_id)
            if isinstance(adapter, SerialAcqAdapter):
                # Signal the physical stop before waiting for a database/control
                # lock held by the background saver.
                try:
                    adapter.disconnect(correlation_id="application-shutdown")
                except DeviceError as exc:
                    errors.append({"task_id": task_id, **exc.detail()})
                try:
                    with self._task_locks[task_id]:
                        self._stop(task_id)
                except Exception as exc:
                    errors.append({"task_id": task_id, "message": str(exc)})
                    import logging
                    logging.getLogger(__name__).exception("Serial acquisition shutdown was not confirmed")
        return errors

    def start(self, task_id: int, actor_user_id: int | None = None, *, turn_index: int | None = None,
              single_turn: bool = False, _sequence=False) -> dict[str, Any]:
        with self._control_scope(task_id), self._start_lock:
            if not _sequence and self._sequence.current(task_id) is not None:
                raise AcquisitionError('capture_sequence_busy', '当前任务正在执行连续摄谱', status_code=409)
            if _sequence and self._sequence.cancelled(task_id):
                raise AcquisitionError('capture_sequence_cancelled', '连续摄谱已停止', status_code=409)
            return self._start(task_id, actor_user_id, turn_index=turn_index, single_turn=single_turn)

    def start_sequence(self, task_id: int, actor_user_id: int, *, turn_index: int | None = None):
        task = self.get_task(task_id)
        turn = task.get('capture_turn')
        members = task.get('capture_turns') if turn and turn.get('multiple') and task['sample_kind'] != 'preheat' else None
        if members:
            if any(item['status'] not in {'draft', 'completed'} for item in members):
                raise AcquisitionError('capture_sequence_incomplete', '有转角已中止或正在摄谱，请检查状态后新建整组摄谱任务', status_code=409)
            pending = [item['id'] for item in members if item['status'] == 'draft']
        elif task['task_kind'] == 'sample' and task['sample_kind'] != 'preheat':
            pending = [task_id]
        else:
            return self.start(task_id, actor_user_id, turn_index=turn_index)
        if not pending:
            raise AcquisitionError('acquisition_task_not_startable', '全部转角已完成', status_code=409)
        return self._sequence.start(pending, all_members=[item['id'] for item in members] if members else None,
                                    start=lambda i: self.start(i, actor_user_id, turn_index=turn_index, _sequence=True),
                                    step=lambda i: self.step(i, actor_user_id, single_repeat=True),
                                    get_task=self.get_task, stop=lambda i: self._stop_control(i, actor_user_id),
                                    fail=lambda i, code, message: self._fail_task(i, code, message, actor_user_id))

    def _start(self, task_id: int, actor_user_id: int | None = None, *, turn_index: int | None = None,
               single_turn: bool = False) -> dict[str, Any]:
        from .turns import context, runtime

        task, _, profile = self.repository._context(task_id)
        if task["discarded_at"]:
            raise AcquisitionError("acquisition_task_discarded", "该摄谱任务已删除", status_code=409)
        status = str(task["status"])
        capture_turn = json.loads(task['excitation_condition_json'] or '{}').get('capture_turn')
        with self.database.read() as db:
            config, state = context(db, task_id)
            members = self.repository.capture_turn_members(db, capture_turn, include_preheat=True) if capture_turn else []
        if any(row['id'] != task_id and row['status'] not in {'draft', 'completed', 'failed', 'stopped'} for row in members):
            raise AcquisitionError('acquisition_task_busy', '请先完成或停止正在摄谱的转角', status_code=409)
        awaiting = status == 'paused' and state and state.get('awaiting_turn')
        expected = state['turn_index'] if state and status not in {'draft', 'between_repeats'} else 0
        if (turn_index is not None and (not config or turn_index != expected)) or (single_turn and turn_index is None):
            raise AcquisitionError('sample_turn_out_of_order', '请从当前待采转角开始摄谱', status_code=409)
        if awaiting:
            try:
                adapter, _ = self._start_adapter(task_id, task, profile, continuation=True)
            except AcquisitionError as exc:
                self._fail_task(task_id, exc.code, exc.message, actor_user_id)
                raise
            with self.database.write() as db:
                runtime(db, task_id, awaiting_turn=False, single_turn=single_turn)
                db.execute("UPDATE acquisition_tasks SET status='pre_excitation',paused_from=NULL,adapter_session_id=?,last_message=?,updated_at=? WHERE id=?",
                           (adapter.session_id, '准备下一转角摄谱', utc_now(), task_id))
                self.repository._audit(db, actor_user_id, 'acquisition.turn.start', task_id, {'turn_index': expected, 'single_turn': single_turn})
            self._run_serial(task_id, adapter, actor_user_id)
            return self.repository._task_dict(task_id)
        if status == AcquisitionState.BETWEEN_REPEATS.value:
            try:
                self._begin_next_repeat(task_id, actor_user_id, single_turn=single_turn)
            except AcquisitionError as exc:
                self._fail_task(task_id, exc.code, exc.message, actor_user_id)
                raise
            return self.repository._task_dict(task_id)
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
            runtime(db, task_id, single_turn=single_turn)
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
        self._run_serial(task_id, adapter, actor_user_id)
        return self.repository._task_dict(task_id)

    def _finish_repeat(
        self,
        db: sqlite3.Connection,
        task: sqlite3.Row,
        sample: sqlite3.Row,
        actor_user_id: int | None,
    ) -> str:
        """在调用方事务内固化本次重复，并决定等待下一次还是完成任务。"""
        from .turns import context, runtime
        config, state = context(db, task['id'])
        if config and config['multiple']:
            next_turn = state['turn_index'] + 1
            runtime(db, task['id'], completed_turns=next_turn)
            if next_turn < len(config['plan']):
                waiting = bool(state.get('single_turn'))
                runtime(db, task['id'], turn_index=next_turn, positioned=False, awaiting_turn=waiting)
                status = 'paused' if waiting else 'burn'
                db.execute("UPDATE acquisition_tasks SET status=?,adapter_session_id=?,burn_frames_captured=0,dark_frames_captured=0,last_event_json=NULL,last_message=?,updated_at=? WHERE id=?",
                    (status, None if waiting else task['adapter_session_id'],
                     '本转角完成，请开始下一转角摄谱' if waiting else '本转角完成，继续本次重复的下一转角', utc_now(), task['id']))
                return status
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
                    "本次摄谱已完成，请装样后再次点击试样摄谱",
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

    def _close_adapter(self, task_id: int, *, strict: bool = False) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            try:
                if not isinstance(adapter, SerialAcqAdapter):
                    adapter.stop_debug(correlation_id=f"acquisition-{task_id}")
                adapter.disconnect(correlation_id=f"acquisition-{task_id}")
            except DeviceError:
                if strict and isinstance(adapter, SerialAcqAdapter):
                    raise

    def _begin_next_repeat(self, task_id: int, actor_user_id: int | None = None, *, single_turn: bool = False) -> None:
        task, _, profile = self.repository._context(task_id)
        adapter, event = self._start_adapter(task_id, task, profile, next_repeat=True)
        with self.database.write() as db:
            from .turns import runtime
            runtime(db, task_id, turn_index=0, completed_turns=0, positioned=False, awaiting_turn=False, single_turn=single_turn)
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
        self._run_serial(task_id, adapter, actor_user_id)

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

    def step(self, task_id: int, actor_user_id: int | None = None, *, single_repeat: bool = False) -> dict[str, Any]:
        with self._control_scope(task_id):
            try:
                return self._step(task_id, actor_user_id, single_repeat=single_repeat)
            except AcquisitionError as exc:
                if self.repository._context(task_id)[0]['status'] in {'countdown', 'pre_excitation', 'burn', 'dark'}:
                    self._fail_task(task_id, exc.code, exc.message, actor_user_id)
                raise

    def _step(self, task_id: int, actor_user_id: int | None = None, *, single_repeat: bool = False,
              continue_turn: bool = True) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        if task["discarded_at"]:
            raise AcquisitionError("acquisition_task_discarded", "该摄谱任务已删除", status_code=409)
        status = str(task["status"])
        adapter = self._adapters.get(task_id)
        real = isinstance(adapter, SerialAcqAdapter) or profile["transport"] == "serial"
        if real and adapter is None and status in {"countdown", "pre_excitation", "burn", "dark", "paused"}:
            self._fail_task(task_id, "acquisition_session_lost", "真实采集会话已丢失，已收帧保留，请检查仪器后新建任务", actor_user_id)
            raise AcquisitionError("acquisition_session_lost", "真实采集会话已丢失", status_code=409)
        if status == AcquisitionState.COUNTDOWN.value and not real:
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
            if single_repeat or real:
                return self.repository._task_dict(task_id)
            self._begin_next_repeat(task_id, actor_user_id)
            return self.repository._task_dict(task_id)
        if status not in {
            AcquisitionState.PRE_EXCITATION.value,
            AcquisitionState.BURN.value,
            AcquisitionState.DARK.value,
        } and not (real and status == AcquisitionState.COUNTDOWN.value):
            raise AcquisitionError(
                "acquisition_task_not_running", "当前任务未处于可采集状态", details={"status": status}, status_code=409
            )
        task, _, profile = self.repository._context(task_id)
        if not real:
            try:
                self._position_sample_turn(task, actor_user_id)
            except Exception as exc:
                self._fail_task(task_id, getattr(exc, 'code', 'sample_turn_failed'), str(exc), actor_user_id)
                if isinstance(exc, AcquisitionError):
                    raise
                raise AcquisitionError('sample_turn_failed', '转角执行失败，已停止采集') from exc
            task, _, profile = self.repository._context(task_id)
        with self.database.read() as db:
            sample = self.repository._current_sample(db, task_id, int(task["current_repeat_index"]))
        adapter = self._adapters.get(task_id)
        if not real and status == AcquisitionState.PRE_EXCITATION.value and float(task["pre_excitation_seconds"]) > 0:
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
            if real:
                position = adapter.turn_position
                if position:
                    from .turns import context, runtime
                    with self.database.read() as db:
                        config, state = context(db, task_id)
                    if config and config['multiple'] and not state['positioned']:
                        with self.database.write() as db:
                            runtime(db, task_id, positioned=True)
                            self.repository._message(db, task_id, 'info', 'sample.turn.positioned', f"转角 {position['angle_deg']:g}° 已到位", position)
                            self.repository._audit(db, actor_user_id, 'acquisition.turn.position', task_id,
                                                   {**position, 'turn_index': state['turn_index'], 'repeat_index': task['current_repeat_index']})
                event = adapter.next_capture_event()
                if event is None:
                    if status == "countdown" and adapter.capture_phase not in {"countdown", "turning"}:
                        with self.database.write() as db:
                            db.execute("UPDATE acquisition_tasks SET status='pre_excitation',countdown_remaining=0 WHERE id=?", (task_id,))
                    return self.repository._task_dict(task_id)
                phase = str(event.details["phase"])
                frame_index = int(event.details["phase_index"])
                expected = int(task["burn_frames_captured"] if phase == "burn" else task["dark_frames_captured"])
                if frame_index != expected:
                    raise DeviceError("serial_frame_sequence_invalid", "真实CCD帧序异常，已中止保存")
                stored = event
            elif status == AcquisitionState.PRE_EXCITATION.value:
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
            self._fail_task(task_id, exc.code, exc.message, actor_user_id,
                            event=DeviceEvent("fault", DeviceAcquisitionState.ERROR,
                                correlation_id=f"acquisition-{task_id}", details={**exc.detail(), **(adapter.diagnostics() if real else {})}))
            raise AcquisitionError(
                "acquisition_frame_failed", exc.message, details=exc.detail(), status_code=exc.status_code
            ) from exc
        except AcquisitionError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise
        frame = stored if status == "pre_excitation" else event
        next_state = status
        advance_real_turn = False
        with self.database.write() as db:
            live = self.repository._context(task_id, db)[0]
            current_sample = self.repository._current_sample(db, task_id, int(live["current_repeat_index"]))
            self.repository._store_event(
                db,
                live,
                current_sample,
                phase,
                frame_index,
                frame,
                event.details["elapsed_ms"] if real else self.repository._virtual_time(live, int(current_sample["repeat_index"]), phase, frame_index),
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
                    _json(frame.to_dict()),
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
                    "sha256": frame.details.get("sha256", ""),
                    **({"communication": event.details.get("communication", []),
                        "turn_position": event.details.get("turn_position")} if real else {}),
                },
            )
            if next_state == "completed":
                next_state = self._finish_repeat(db, live, current_sample, actor_user_id)
                advance_real_turn = real and next_state == "burn" and bool(frame.details.get("turn_position"))
        if self._on_frame_saved is not None:
            self._on_frame_saved(task_id, phase, frame_index, frame.details, current_sample["repeat_index"])
        if next_state in {"between_repeats", "completed", "paused"}:
            self._close_adapter(task_id)
        if advance_real_turn and continue_turn and not adapter.stop_requested and not self._sequence.cancelled(task_id):
            try:
                adapter.wait_for_capture_end()
                fresh, _, profile = self.repository._context(task_id)
                adapter, event = self._start_adapter(task_id, fresh, profile, continuation=True)
                with self.database.write() as db:
                    db.execute("UPDATE acquisition_tasks SET status='pre_excitation',adapter_session_id=?,last_event_json=?,updated_at=? WHERE id=?",
                               (adapter.session_id, _json(event.to_dict()), utc_now(), task_id))
                self._run_serial(task_id, adapter, actor_user_id, monitor=False)
            except DeviceError as exc:
                raise AcquisitionError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        return self.repository._task_dict(task_id, include_points=True)

    def _position_sample_turn(self, task, actor):
        from .turns import context, runtime
        from ..hardware_acquisition import confirm_simulated_turn
        with self.database.read() as db:
            config, state = context(db, task['id'])
        if not config or not config['multiple'] or state['positioned']:
            return
        adapter = self._adapters.get(task['id'])
        if not isinstance(adapter, AcqSimulatorAdapter):
            raise AcquisitionError('acquisition_session_lost', '转角采集会话已丢失，请检查后重新摄谱', status_code=409)
        turn = config['plan'][state['turn_index']]
        try:
            response = confirm_simulated_turn(adapter, turn['angle_deg'], f"acquisition-{task['id']}")
        except DeviceError as exc:
            raise AcquisitionError(exc.code, exc.message, status_code=exc.status_code) from exc
        # Distinct deterministic signals per physical position; these remain simulation evidence.
        source = json.loads(task['simulator_json'])
        event = adapter.start_debug(sample=source['sample'], seed=int(source['seed']) + task['current_repeat_index'] + turn['source_index'] * 1009,
            fault_frame=source.get('fault_frame'), correlation_id=f"acquisition-{task['id']}")
        event = _seeded_acquisition_event(event, repeat_index=task['current_repeat_index'], phase='burn', frame_index=0, sample_kind=task['sample_kind'])
        with self.database.write() as db:
            runtime(db, task['id'], positioned=True)
            db.execute('UPDATE acquisition_tasks SET last_event_json=?,adapter_session_id=?,last_message=? WHERE id=?',
                (_json(event.to_dict()), adapter.session_id, f"转角 {turn['angle_deg']:g}° 已到位", task['id']))
            self.repository._message(db, task['id'], 'info', 'sample.turn.positioned', f"转角 {turn['angle_deg']:g}° 已到位", response)
            self.repository._audit(db, actor, 'acquisition.turn.position', task['id'], {**response, 'turn_index': turn['turn_index'], 'repeat_index': task['current_repeat_index']})

    @staticmethod
    def line_location(connection, sample_id, line_id):
        from .turns import line_location
        return line_location(connection, sample_id, line_id)

    @staticmethod
    def band_metadata(connection, sample_id):
        from .turns import decoded_bands
        return decoded_bands(connection, sample_id)

    def pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._pause(task_id, actor_user_id)

    def _pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        if profile["transport"] == "serial":
            raise AcquisitionError("serial_pause_unsupported", "旧设备协议未提供暂停命令；请使用停止", status_code=409)
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
        from .turns import context

        task, _, _ = self.repository._context(task_id)
        status = str(task["status"])
        if status != "paused":
            if status in {"countdown", "pre_excitation", "burn", "dark"}:
                return self.repository._task_dict(task_id)
            raise AcquisitionError(
                "acquisition_task_not_resumable", "当前任务未暂停", details={"status": status}, status_code=409
            )
        with self.database.read() as db:
            _, state = context(db, task_id)
        if state and state.get('awaiting_turn'):
            raise AcquisitionError('sample_turn_start_required', '请在下一转角控制页开始摄谱', status_code=409)
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
        current = self._sequence.cancel(task_id)
        if current is not None:
            adapter = self._adapters.get(current)
            if isinstance(adapter, SerialAcqAdapter):
                adapter.request_stop()
            return self.get_task(current)
        return self._stop_control(task_id, actor_user_id)

    def _stop_control(self, task_id: int, actor_user_id: int | None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._stop(task_id, actor_user_id)

    def _stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        status = str(task["status"])
        if status in {"completed", "failed", "stopped"}:
            return self.repository._task_dict(task_id)
        if profile["transport"] == "serial" and task_id not in self._adapters and status in {"countdown", "pre_excitation", "burn", "dark", "paused"}:
            self._fail_task(task_id, "acquisition_session_lost", "真实采集会话已丢失，无法发送结束指令，请检查仪器状态", actor_user_id)
            raise AcquisitionError("acquisition_session_lost", "无法确认仪器已停止，请检查仪器状态", status_code=409)
        try:
            adapter = self._adapters.get(task_id)
            if isinstance(adapter, SerialAcqAdapter):
                try:
                    adapter.stop_debug(correlation_id=f"acquisition-{task_id}")
                except DeviceError:
                    pass  # retain complete queued frames before reporting failure
                while adapter.pending_frames and task_id in self._adapters:
                    self._step(task_id, actor_user_id, single_repeat=True, continue_turn=False)
                if adapter.capture_error:
                    raise adapter.capture_error
                if self.repository._context(task_id)[0]["status"] in {"completed", "between_repeats"}:
                    self._close_adapter(task_id, strict=True)
                    return self.repository._task_dict(task_id)
            self._close_adapter(task_id, strict=True)
        except DeviceError as exc:
            self._fail_task(task_id, exc.code, exc.message, actor_user_id)
            raise AcquisitionError(exc.code, exc.message, details=exc.details, status_code=409) from exc
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

    def list_tasks(self, limit: int = 50, *, task_kind: str | None = None,
                   include_discarded: bool = True) -> list[dict[str, Any]]:
        tasks = self.repository.list_tasks(limit, task_kind=task_kind, include_discarded=include_discarded)
        for task in tasks:
            if (current := self._sequence.current(task['id'])) is not None:
                task['active_capture_id'] = current
            plan = task.get('turns') or task.get('capture_turn')
            if plan:
                task['position_controlled'] = requires_motor(self.database, task['profile'], multiple=plan['multiple'])
        return tasks

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None, *, connection=None, capture_turn=None) -> dict[str, Any]:
        return self.repository.create_task(payload, actor_user_id, connection=connection, capture_turn=capture_turn)

    def preheat(self, task_id: int, actor_user_id: int | None = None, *, turn_index: int | None = None) -> dict[str, Any]:
        """Run one independent warm-up without consuming a formal sample or repeat."""
        with self._control_scope(task_id):
            source = self.repository._task_dict(task_id)
            if source["discarded_at"]:
                raise AcquisitionError("acquisition_task_discarded", "该摄谱任务已删除", status_code=409)
            if source["status"] not in {"draft", "between_repeats", "completed", "failed", "stopped"}:
                raise AcquisitionError("acquisition_task_busy", "当前摄谱尚未结束，不能预热", status_code=409)
            parent_id = source["excitation_condition"].get("preheat_source_task_id", task_id)
            capture_turn = source.get('capture_turn')
            payload = {key: source[key] for key in (
                "task_kind", "device_profile_id", "ccd_layout_id", "ccd_indices", "method_id", "method_version",
                "burn_frame_count", "dark_frame_count", "countdown_seconds", "pre_excitation_seconds",
                "sampling_period_seconds", "burn_cycle_seconds", "dark_cycle_seconds",
            )}
            if turn_index is not None:
                turns = source.get('turns') or {}
                turn = next((item for item in turns.get('plan', []) if item['turn_index'] == turn_index), None)
                if turn is None:
                    raise AcquisitionError('sample_turn_invalid', '任务没有指定的转角')
                payload['ccd_indices'] = turn['ccd_indices']
                capture_turn = {'turn_index': turn_index, 'angle_deg': turn['angle_deg'], 'multiple': turns['multiple']}
            payload.update(name=f"预热 · {source['name']}"[:120], sample_name="预热样品", sample_kind="preheat",
                           repeat_count=1, storage_mode="full_interval",
                           excitation_conditions={"preheat_source_task_id": parent_id},
                           simulator_sample=source["simulator"].get("sample", "280-288.acq"),
                           seed=source["simulator"].get("seed", 0))
            warmup = self.repository.create_task(payload, actor_user_id, source_task=source, capture_turn=capture_turn)
            return self.start(warmup["id"], actor_user_id)

    def frames(
        self,
        task_id: int,
        *,
        repeat_index: int | None = None,
        phase: str | None = None,
        ccd_index: int | None = None,
        include_points: bool = False,
        turn_index: int | None = None,
        frame_index: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.repository.frames(task_id, repeat_index=repeat_index, phase=phase, ccd_index=ccd_index,
                                      include_points=include_points, turn_index=turn_index, frame_index=frame_index)

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
        source_layout = json.loads(snapshot['sample']['simulator_json'] or '{}').get('source_layout') or {}
        snapshot['point_width_um'] = source_layout.get('point_width') or DeviceService(self.database).profile(snapshot['sample']['device_profile_id'])['point_width_um']
        return snapshot

    def spectrum_interval(self, sample_id: int, interval: tuple[int, int], *, band_position: int | None = None) -> dict[int | tuple[int, int], dict]:
        """Read an exposure view through the acquisition boundary; stored bands remain immutable."""
        snapshot = self.spectrum_snapshot(sample_id)
        bands = snapshot['bands']
        if band_position is not None:
            if not 0 <= band_position < len(bands) or bands[band_position]['storage_mode'] != 'full_interval':
                raise AcquisitionError('analysis_interval_frames_missing', '当前 CCD 没有可用于观察的全时帧')
            bands = [bands[band_position]]
        with self.database.read() as db:
            return {(band.get('turn_index', 0), band['ccd_index']) if (snapshot.get('turns') or {}).get('multiple') else band['ccd_index']:
                    self.interval_band(db, sample_id, band["ccd_index"], interval, turn_index=band.get('turn_index'),
                                       allow_single_frame=band_position is not None)
                    for band in bands}

    def get_task(self, task_id: int, *, include_points: bool = False) -> dict[str, Any]:
        task = self.repository._task_dict(task_id, include_points=include_points)
        current = self._sequence.current(task_id)
        if current is not None:
            task['active_capture_id'] = current
        plan = task.get('turns') or task.get('capture_turn')
        if plan:
            task['position_controlled'] = requires_motor(self.database, task['profile'], multiple=plan['multiple'])
        adapter = self._adapters.get(task_id)
        if isinstance(adapter, SerialAcqAdapter) and adapter.capture_phase == 'turning':
            task['last_message'] = '正在定位转角'
        return task

    def measurement_snapshot(self, task_id: int) -> dict[str, Any]:
        return self.repository.measurement_snapshot(task_id)

    def _discard_samples(self, db: sqlite3.Connection, task: sqlite3.Row, reason: str,
                         actor_user_id: int | None, *, allow_empty: bool = False) -> bool:
        task_id = task["id"]
        samples = db.execute("SELECT * FROM acquisition_samples WHERE task_id=?", (task_id,)).fetchall()
        if not samples and not allow_empty:
            raise AcquisitionError("sample_discard_empty", "尚未开始摄谱，没有可删除样品", status_code=409)
        changed = False
        for sample in samples:
            if db.execute("SELECT 1 FROM acquisition_sample_disposals WHERE sample_id=?", (sample["id"],)).fetchone():
                continue
            try:
                db.execute("INSERT INTO acquisition_sample_disposals VALUES (?,?,?,?)",
                           (sample["id"], reason, actor_user_id, utc_now()))
            except sqlite3.IntegrityError as exc:
                if "sample used in prepared collection" in str(exc):
                    raise AcquisitionError("sample_used_in_prepared_collection", "样品已收入预备摄谱输出集，请在该输出集中处理",
                                           status_code=409) from exc
                if "sample already analyzed" not in str(exc):
                    raise
                raise AcquisitionError("sample_already_analyzed", "样品已被分析引用，请在重复性质控中剔除", status_code=409) from exc
            self.repository._audit(db, actor_user_id, "acquisition.sample.discard", sample["id"],
                                   {"task_id": task_id, "reason": reason, "result_sha256": sample["result_sha256"]})
            changed = True
        if changed and task["queue_id"] is not None:
            self.sample_queues.release_acquisition(task["queue_id"], task["queue_item_id"], task["result_sha256"], connection=db)
        return bool(samples)

    def discard_session(self, task_id: int, actor_user_id: int, *, completed_evaporation_only: bool = False) -> None:
        with self.database.read() as db:
            task, _, _ = self.repository._context(task_id, db)
            turn = json.loads(task["excitation_condition_json"] or "{}").get("capture_turn")
            if (completed_evaporation_only and task["task_kind"] != "evaporation") or (turn and task["sample_kind"] == "preheat"):
                raise AcquisitionError("acquisition_task_not_found", "摄谱任务不存在", status_code=404)
            members = self.repository.capture_turn_members(db, turn) if turn else [task]
        ids = [member["id"] for member in members]
        if not ids:
            raise AcquisitionError("acquisition_task_not_found", "摄谱任务不存在", status_code=404)
        idle = {"draft", "between_repeats", "completed", "stopped", "failed"}
        with ExitStack() as locks:
            for identifier in ids:
                locks.enter_context(self._control_scope(identifier))
            with self.database.write() as db:
                db.execute("BEGIN IMMEDIATE")
                tasks = [self.repository._context(identifier, db)[0] for identifier in ids]
                if completed_evaporation_only and any(item["status"] != "completed" for item in tasks):
                    raise AcquisitionError("evaporation_session_incomplete", "只能删除已完成的蒸发摄谱任务", status_code=409)
                if any(item["status"] not in idle or self._adapters.get(item["id"]) is not None for item in tasks):
                    raise AcquisitionError("acquisition_task_busy", "请先完成或停止当前摄谱，再删除任务", status_code=409)
                if db.execute("""SELECT 1 FROM acquisition_tasks WHERE sample_kind='preheat'
                    AND status NOT IN ('draft','between_repeats','completed','stopped','failed')
                    AND json_extract(excitation_condition_json, '$.preheat_source_task_id') IN
                      (SELECT value FROM json_each(?)) LIMIT 1""", (_json(ids),)).fetchone():
                    raise AcquisitionError("acquisition_task_busy", "请先完成或停止当前预热，再删除任务", status_code=409)
                for item in tasks:
                    if item["discarded_at"]:
                        continue
                    had_samples = self._discard_samples(db, item, "从摄谱任务列表删除", actor_user_id, allow_empty=True)
                    if not had_samples and item["queue_id"] is not None:
                        db.execute("UPDATE acquisition_tasks SET queue_id=NULL, queue_item_id=NULL WHERE id=?", (item["id"],))
                    db.execute("UPDATE acquisition_tasks SET discarded_at=? WHERE id=?", (utc_now(), item["id"]))
                    self.repository._audit(db, actor_user_id, "acquisition.task.discard", item["id"],
                                           {"status": item["status"], "queue_id": item["queue_id"], "queue_item_id": item["queue_item_id"]})

    def discard(self, task_id: int, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        reason = reason.strip()
        if not reason:
            raise AcquisitionError("sample_discard_reason_missing", "删除异常样品必须说明原因")
        with self._control_scope(task_id):
            # 删除标记与队列解绑一起提交，实体和帧保留供审计；已被分析引用的样品会拒绝删除。
            # 在任务控制锁内处置异常样品，删除后的样品不得再改名或用作正式结果。
            with self.database.write() as db:
                task, _, _ = self.repository._context(task_id, db)
                self._discard_samples(db, task, reason, actor_user_id)
                if task["status"] not in {"completed", "failed", "stopped"}:
                    db.execute("UPDATE acquisition_tasks SET status='stopped', completed_at=?, updated_at=? WHERE id=?", (utc_now(), utc_now(), task_id))
                    db.execute("UPDATE acquisition_samples SET status='stopped', updated_at=? WHERE task_id=? AND status='collecting'", (utc_now(), task_id))
                db.execute("UPDATE acquisition_tasks SET last_message=?, updated_at=? WHERE id=?", (f"异常样品已删除：{reason}", utc_now(), task_id))
                self.repository._message(db, task_id, "warning", "sample.discard", "异常样品已删除，原始帧保留供审计", {"reason": reason})
            # 处置提交后关闭仍保留的采集适配器，再读取服务确认后的任务详情。
            self._close_adapter(task_id)
            return self.repository._task_dict(task_id)

    @staticmethod
    def management_task_ids(db: sqlite3.Connection) -> set[int]:
        return {int(row[0]) for row in db.execute('SELECT task_id FROM acquisition_management_tasks')}
