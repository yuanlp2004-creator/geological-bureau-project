"""Run a single capture sequence on existing per-angle tasks."""
from dataclasses import dataclass, field
import logging
import threading


@dataclass
class _Run:
    members: tuple[int, ...]
    current: int
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    error: dict | None = None


class CaptureSequence:
    def __init__(self, error, exit_gate):
        self._error = error
        self._exit_gate = exit_gate
        self._lock = threading.Lock()
        self._run: _Run | None = None

    def current(self, task_id=None):
        with self._lock:
            if self._run and (task_id is None or task_id in self._run.members):
                return self._run.current
        return None

    def cancelled(self, task_id):
        with self._lock:
            return self._run is not None and task_id in self._run.members and self._cancelled(self._run)

    def start(self, members, *, start, step, get_task, stop, fail, all_members=None):
        run = _Run(tuple(all_members or members), members[0])
        with self._lock:
            if self._run is not None or self._exit_gate is not None and self._exit_gate.is_set():
                raise self._error("capture_sequence_busy", "已有连续摄谱正在运行或程序正在停止设备", status_code=409)
            self._run = run
        try:
            first = start(run.current)
        except Exception:
            self._release(run)
            raise

        def work():
            try:
                result = first
                for index, task_id in enumerate(members):
                    if index:
                        with self._lock:
                            if self._cancelled(run):
                                return
                            run.current = task_id
                        result = start(task_id)
                    while not run.cancel.wait(.04) and not self._cancelled(run):
                        status = result["status"]
                        if status in {"failed", "stopped", "completed", "between_repeats"}:
                            break
                        if status == "paused" or result["profile"]["transport"] == "serial":
                            result = get_task(task_id)
                        else:
                            try:
                                result = step(task_id)
                            except self._error as exc:
                                if exc.code not in {"acquisition_task_busy", "dispersion_task_busy"}:
                                    raise
                    if self._cancelled(run):
                        for _ in range(100):
                            try:
                                stop(task_id)
                                break
                            except self._error as exc:
                                if exc.code not in {"acquisition_task_busy", "dispersion_task_busy"}:
                                    raise
                                threading.Event().wait(.04)
                        else:
                            raise self._error("capture_stop_busy", "停止请求未完成，请检查当前摄谱状态", status_code=409)
                        return
                    if result["status"] != "completed":
                        return
            except Exception as exc:
                if getattr(exc, "code", "") != "capture_sequence_cancelled":
                    if self._cancelled(run):
                        run.error = {"task_id": run.current, "code": getattr(exc, "code", "capture_stop_failed"), "message": str(exc)}
                    fail(run.current, getattr(exc, "code", "capture_sequence_failed"), str(exc))
                    logging.getLogger(__name__).exception("Capture sequence did not finish")
            finally:
                self._release(run)

        threading.Thread(target=work, name="capture-angle-sequence", daemon=True).start()
        return {**first, "active_capture_id": run.current}

    def _cancelled(self, run):
        return run.cancel.is_set() or self._exit_gate is not None and self._exit_gate.is_set()

    def _release(self, run):
        with self._lock:
            self._run = None
            run.done.set()

    def cancel(self, task_id):
        with self._lock:
            run = self._run
            if run is None or task_id not in run.members:
                return None
            run.cancel.set()
            return run.current

    def shutdown(self):
        with self._lock:
            run = self._run
            if run is None:
                return []
            run.cancel.set()
        if not run.done.wait(70):
            return [{"task_id": run.current, "code": "capture_stop_unconfirmed", "message": "未确认连续摄谱停止"}]
        return [run.error] if run.error else []
