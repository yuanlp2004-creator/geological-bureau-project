"""Timed acquisition stays active independently of browser polling."""
import threading

from .values import HardwareError


class ManualTurnRunner:
    def __init__(self, service):
        self.service = service
        self.workers = {}
        self.guard = threading.Lock()

    def start(self, task_id, actor):
        with self.guard:
            existing = self.workers.get(task_id)
            if existing and existing[0].is_alive():
                return
            stop = threading.Event()
            thread = threading.Thread(target=self.run, args=(task_id, actor, stop), daemon=True,
                                      name=f'manual-turn-{task_id}')
            self.workers[task_id] = (thread, stop)
            thread.start()

    def run(self, task_id, actor, stop):
        try:
            while not stop.wait(.02):
                task = self.service.repository._context(task_id)[0]
                if task['status'] in {'paused', 'manual_intervention'}:
                    continue
                if task['status'] not in {'pre_excitation', 'turning', 'collecting'}:
                    break
                clock = self.service._capture_clocks.get(task_id)
                if task['status'] == 'collecting' and clock:
                    elapsed = self.service._clock() - clock['start'] - clock['paused']
                    if elapsed < clock['next']:
                        stop.wait(min(.1, clock['next'] - elapsed))
                        continue
                try:
                    self.service.step(task_id, actor)
                except HardwareError as exc:
                    if exc.code != 'hardware_task_busy':
                        raise
        except Exception as exc:
            # A worker failure never confirms partial data or silently resumes it.
            with self.service._task_locks[task_id], self.service.database.write() as db:
                task = self.service.repository._context(task_id, db)[0]
                if task['status'] in {'pre_excitation', 'turning', 'collecting', 'paused', 'manual_intervention'}:
                    self.service._safe_stop_db(db, task, actor, f'timed acquisition failed: {type(exc).__name__}')
            self.service._close_adapter(task_id)
        finally:
            with self.guard:
                if self.workers.get(task_id, (None,))[0] is threading.current_thread():
                    self.workers.pop(task_id, None)

    def shutdown(self):
        with self.guard:
            workers = list(self.workers.items())
        for _, (_, stop) in workers:
            stop.set()
        for task_id, (thread, _) in workers:
            thread.join(timeout=5)
            self.service.stop(task_id)
