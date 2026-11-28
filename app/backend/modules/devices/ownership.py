"""In-memory ownership of the instrument shared by the runtime services."""
from contextlib import nullcontext
from dataclasses import dataclass, field
import threading

from .serial_acq import SerialAcqAdapter
from .values import DeviceError


@dataclass(eq=False)
class DeviceUse:
    owner: str
    profile_id: int
    transport: str
    port: str | None
    state: str
    task_id: int | None
    sequence: bool
    cancel: threading.Event = field(default_factory=threading.Event)
    error: dict | None = None


class DeviceOwnership:
    def __init__(self, exit_gate=None):
        self._lock = threading.Lock()
        self._current: DeviceUse | None = None
        self._exit_gate = exit_gate

    @staticmethod
    def _busy():
        return DeviceError('device_busy', '设备正在使用，请先停止并完成当前操作或确认停机', status_code=409)

    def _check_exit(self):
        if self._exit_gate is not None and self._exit_gate.is_set():
            raise DeviceError('device_exit_in_progress', '正在停止设备，不能开始新的操作', status_code=409)

    def reserve(self, owner, profile, state, *, task_id=None, sequence=False, handoff=None, reuse=False):
        transport = profile['transport']
        with self._lock:
            self._check_exit()
            previous = self._current
            if previous is not None:
                if (reuse and not previous.sequence and not previous.cancel.is_set()
                        and previous.state != 'stop_unconfirmed'
                        and (previous.owner, previous.task_id, previous.profile_id) == (owner, task_id, profile['id'])):
                    return previous, False
                if not (handoff and previous.owner == 'alignment' and previous.state == 'connected'
                        and previous.profile_id == profile['id'] and not previous.cancel.is_set()):
                    raise self._busy()
            use = self._current = DeviceUse(owner, profile['id'], transport,
                                          f"COM{profile['port']}" if transport == 'serial' else None,
                                          state, task_id, sequence)
        if previous is not None:
            try:
                handoff(profile['id'])
            except Exception:
                self.release(use, restore=previous)
                raise
        return use, True

    def update(self, use, state, *, task_id=None, profile_id=None, error=None):
        with self._lock:
            if use is not None:
                use.state = state
                use.error = error
                if task_id is not None:
                    use.task_id = task_id
                if profile_id is not None:
                    use.profile_id = profile_id

    def begin_alignment(self, use, state):
        with self._lock:
            self._check_exit()
            if self._current is not use or use is not None and (use.cancel.is_set() or use.state == 'stop_unconfirmed'):
                raise self._busy()
            if use is not None:
                use.state = state

    def for_capture(self, owners, task_id=None, *, cancel=False):
        with self._lock:
            use = self._current
            if (use is None or use.owner not in owners or use.task_id is None
                    or task_id is not None and task_id != use.task_id):
                return None
            if cancel:
                use.cancel.set()
            return use

    def check_alignment(self, use):
        with self._lock:
            self._check_exit()
            if self._current is not use:
                raise self._busy()

    def interrupt(self):
        with self._lock:
            if self._current is not None:
                self._current.cancel.set()

    def release(self, use, *, restore=None):
        with self._lock:
            if use is not None and self._current is use:
                self._current = restore

    def snapshot(self):
        with self._lock:
            use = self._current
            if use is None:
                return None
            return {'owner': use.owner, 'task_id': use.task_id, 'profile_id': use.profile_id,
                    'transport': use.transport, 'port': use.port, 'state': use.state,
                    'last_error': use.error}


class CaptureDevice:
    """Keep a serial reservation across adapter replacement and sequence gaps."""

    def __init__(self, source, owners, adapters, task_locks, ownership, handoff, exit_gate, error):
        self.source = source
        self.owners = owners
        self.adapters = adapters
        self.task_locks = task_locks
        self.ownership = ownership or DeviceOwnership(exit_gate)
        self.handoff = handoff
        self.error = error

    def reserve(self, owner, profile, task_id, actor, *, sequence=False):
        if profile['transport'] != 'serial':
            return None, False
        handoff = (lambda profile_id: self.handoff(profile_id, actor)) if self.handoff else None
        try:
            return self.ownership.reserve(owner, profile, 'reserved', task_id=task_id,
                                          sequence=sequence, handoff=handoff, reuse=not sequence)
        except DeviceError as exc:
            raise self.error(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc

    def current(self):
        return self.ownership.for_capture(self.owners)

    def for_task(self, task_id):
        return self.ownership.for_capture(self.owners, task_id)

    def starting(self, task_id):
        use = self.for_task(task_id)
        if use is not None and use.cancel.is_set():
            raise self.error('capture_sequence_cancelled', '摄谱已停止', status_code=409)
        self.ownership.update(use, 'capturing')

    def request_stop(self, task_id):
        use = self.ownership.for_capture(self.owners, task_id, cancel=True)
        adapter = self.adapters.get(task_id)
        if isinstance(adapter, SerialAcqAdapter):
            adapter.request_stop()
        return use is not None or isinstance(adapter, SerialAcqAdapter)

    def close(self, task_id, *, strict=False, retain=False, retry=False):
        correlation_id = f'{self.source}-{task_id}'
        use = self.for_task(task_id)
        adapter = self.adapters.get(task_id)
        if adapter is not None:
            try:
                if not isinstance(adapter, SerialAcqAdapter):
                    adapter.stop_debug(correlation_id=correlation_id)
                elif retry:
                    adapter.confirm_stop(correlation_id=correlation_id)
                elif use is not None and use.state == 'stop_unconfirmed':
                    if strict:
                        raise DeviceError(use.error['code'], use.error['message'],
                                          details=use.error['details'], status_code=409)
                    return
                adapter.disconnect(correlation_id=correlation_id)
            except DeviceError as exc:
                if isinstance(adapter, SerialAcqAdapter):
                    self.ownership.update(use, 'stop_unconfirmed', error=exc.detail())
                    if strict:
                        raise
                    return
            self.adapters.pop(task_id, None)
        if use is not None and (use.sequence or retain):
            self.ownership.update(use, 'reserved')
        else:
            self.ownership.release(use)

    def sequence(self, runner, pending, *, owner, profile, actor, start, **callbacks):
        use, _ = self.reserve(owner, profile, pending[0], actor, sequence=True)

        def settle():
            if use is not None:
                # The task may publish completion just before its adapter closes.
                with self.task_locks.get(use.task_id, nullcontext()):
                    self.close(use.task_id, strict=True)

        def start_member(task_id):
            self.ownership.update(use, 'reserved', task_id=task_id)
            return start(task_id)

        def finish():
            settle()
            if use is not None:
                self.ownership.release(use)

        try:
            return runner.start(pending, start=start_member, ready=settle, finish=finish, **callbacks)
        except Exception:
            if use is not None and use.state != 'stop_unconfirmed' and use.task_id not in self.adapters:
                self.ownership.release(use)
            raise
