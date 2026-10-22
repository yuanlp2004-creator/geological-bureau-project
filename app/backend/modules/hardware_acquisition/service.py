from __future__ import annotations
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Any
from ...db import Database, utc_now
from .adapters import SerialTurnAdapter, SimulatorTurnAdapter
from .repository import HardwareRepository
from .rules import _simulated_anomalies
from .values import HardwareError, HardwareTaskState, _DECISION_STATES, _json, _sha
from .exposures import capture_exposure, exposure_config, exposure_results


class HardwareAcquisitionService:
    def __init__(self, database: Database):
        self.database = database
        self._adapters: dict[int, SimulatorTurnAdapter | SerialTurnAdapter] = {}
        self._task_locks: dict[int, threading.Lock] = {}
        self._task_locks_guard = threading.Lock()
        self.repository = HardwareRepository(database)

    @contextmanager
    def _control_scope(self, task_id: int):
        with self._task_locks_guard:
            lock = self._task_locks.setdefault(task_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise HardwareError(
                "hardware_task_busy",
                "another hardware control operation is in progress",
                details={"task_id": task_id},
                status_code=409,
            )
        try:
            yield
        finally:
            lock.release()

    def _adapter(self, task_id: int, profile: dict[str, Any]) -> SimulatorTurnAdapter | SerialTurnAdapter:
        adapter = self._adapters.get(task_id)
        if adapter is None:
            adapter = SimulatorTurnAdapter() if profile["transport"] == "simulator" else SerialTurnAdapter()
            self._adapters[task_id] = adapter
        return adapter

    def _start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        if task["status"] != HardwareTaskState.DRAFT.value:
            if task["status"] in _DECISION_STATES:
                return self.repository._task_dict(task_id)
            raise HardwareError(
                "hardware_task_not_startable",
                "hardware task is not startable",
                details={"status": task["status"]},
                status_code=409,
            )
        correlation_id = f"hardware-{task_id}-{uuid.uuid4().hex[:10]}"
        adapter = self._adapter(task_id, profile)
        if profile["transport"] == "serial":
            with self.database.write() as db:
                self.repository._trace(
                    db,
                    task_id,
                    "internal",
                    "event",
                    "protocol.deferred",
                    {"reason": "missing_serial_turn_protocol", "transport": "serial"},
                    correlation_id,
                    HardwareTaskState.DEFERRED_EXTERNAL.value,
                )
                db.execute(
                    (
                        "UPDATE hardware_tasks SET status='deferred_external', failure_code=?, "
                        "failure_message=?, completed_at=?, last_message=?, updated_at=? WHERE id=?"
                    ),
                    (
                        "hardware_protocol_unavailable",
                        "real serial/turn protocol documentation or capture is not available",
                        utc_now(),
                        "真实串口协议缺失，任务延期",
                        utc_now(),
                        task_id,
                    ),
                )
                self.repository._message(
                    db,
                    task_id,
                    "warning",
                    "task.deferred_external",
                    "real serial/turn protocol is unavailable; no command bytes were sent",
                    {"correlation_id": correlation_id},
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.task.deferred",
                    task_id,
                    {"reason": "missing_serial_turn_protocol", "correlation_id": correlation_id},
                )
            self._adapters.pop(task_id, None)
            return self.repository._task_dict(task_id)
        try:
            connected = adapter.connect(profile, correlation_id)
            pre_event = adapter.pre_excitation(
                sample=json.loads(task["simulator_json"] or "{}").get("sample", "280-288.acq"),
                seed=int(json.loads(task["simulator_json"] or "{}").get("seed", 0)),
                correlation_id=correlation_id,
            )
        except HardwareError as exc:
            with self.database.write() as db:
                self.repository._trace(
                    db,
                    task_id,
                    "internal",
                    "safety",
                    "startup.failed",
                    {"code": exc.code, "message": exc.message, "commands_sent": False},
                    correlation_id,
                    HardwareTaskState.FAILED.value,
                )
                db.execute(
                    (
                        "UPDATE hardware_tasks SET status='failed', failure_code=?, failure_message=?, "
                        "completed_at=?, last_message=?, updated_at=? WHERE id=?"
                    ),
                    (exc.code, exc.message, utc_now(), exc.message, utc_now(), task_id),
                )
                self.repository._message(
                    db,
                    task_id,
                    "error",
                    "task.failed",
                    exc.message,
                    {"code": exc.code, "correlation_id": correlation_id},
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.task.safety_stop",
                    task_id,
                    {"reason": exc.message, "code": exc.code, "correlation_id": correlation_id},
                )
            adapter.close(correlation_id=f"hardware-close-{task_id}-{uuid.uuid4().hex[:8]}")
            self._adapters.pop(task_id, None)
            raise
        with self.database.write() as db:
            db.execute(
                (
                    "UPDATE hardware_tasks SET status='pre_excitation', adapter_session_id=?, "
                    "last_event_json=?, started_at=?, last_message=?, updated_at=? WHERE id=?"
                ),
                (
                    adapter.session_id if isinstance(adapter, SimulatorTurnAdapter) else None,
                    _json(pre_event),
                    utc_now(),
                    "hardware connected; pre-excitation started",
                    utc_now(),
                    task_id,
                ),
            )
            self.repository._trace(
                db,
                task_id,
                "inbound",
                "connection",
                "connected",
                connected,
                correlation_id,
                HardwareTaskState.PRE_EXCITATION.value,
            )
            self.repository._trace(
                db,
                task_id,
                "internal",
                "event",
                "pre_excitation.started",
                pre_event,
                correlation_id,
                HardwareTaskState.PRE_EXCITATION.value,
            )
            self.repository._message(db, task_id, "info", "task.start", "hardware task started", {"state": "pre_excitation"})
            self.repository._audit(
                db,
                actor_user_id,
                "hardware.task.start",
                task_id,
                {"state": "pre_excitation", "correlation_id": correlation_id},
            )
        return self.repository._task_dict(task_id)

    def _safe_stop_db(
        self,
        db: sqlite3.Connection,
        task: sqlite3.Row,
        actor_user_id: int | None,
        reason: str,
        *,
        state: str = "safety_stopped",
    ) -> None:
        correlation_id = f"hardware-safe-{task['id']}-{uuid.uuid4().hex[:10]}"
        self.repository._trace(
            db,
            task["id"],
            "internal",
            "safety",
            "safety.stop",
            {"reason": reason, "commands_sent": False},
            correlation_id,
            state,
        )
        db.execute(
            (
                "UPDATE hardware_tasks SET status=?, failure_code=?, failure_message=?, "
                "completed_at=?, last_message=?, updated_at=? WHERE id=?"
            ),
            (state, "safety_stop", reason, utc_now(), reason, utc_now(), task["id"]),
        )
        self.repository._message(db, task["id"], "error", "task.safety_stop", reason, {"correlation_id": correlation_id})
        self.repository._audit(
            db,
            actor_user_id,
            "hardware.task.safety_stop",
            int(task["id"]),
            {"reason": reason, "correlation_id": correlation_id},
        )

    def _close_adapter(self, task_id: int) -> None:
        adapter = self._adapters.pop(task_id, None)
        if adapter is not None:
            adapter.close(correlation_id=f"hardware-close-{task_id}-{uuid.uuid4().hex[:8]}")

    def _complete_step(
        self, db: sqlite3.Connection, task: sqlite3.Row, step: sqlite3.Row, actor_user_id: int | None
    ) -> bool:
        db.execute(
            "UPDATE hardware_plan_steps SET status='confirmed', updated_at=? WHERE id=?", (utc_now(), step["id"])
        )
        completed = int(task["completed_steps"]) + 1
        # 完成计数达到计划总数才结束任务，否则移动到下一计划项而不重采已完成角度。
        if completed >= int(task["total_steps"]):
            hashes = [
                row[0]
                for row in db.execute(
                    "SELECT points_sha256 FROM hardware_frames WHERE task_id=? AND confirmed=1 ORDER BY step_id, attempt, ccd_index",
                    (task["id"],),
                ).fetchall()
            ]
            interval_hashes = [row[0] for row in db.execute('SELECT mean_sha256 FROM hardware_exposure_results '
                'WHERE task_id=? ORDER BY step_id,attempt,ccd_index', (task['id'],))]
            result_sha = _sha('|'.join(value or '' for value in hashes + interval_hashes) + task['plan_json'])
            db.execute(
                "UPDATE hardware_tasks SET status='completed', completed_steps=?, result_sha256=?, completed_at=?, last_message=?, updated_at=? WHERE id=?",
                (completed, result_sha, utc_now(), "all turn steps confirmed", utc_now(), task["id"]),
            )
            self.repository._message(
                db, task["id"], "success", "task.completed", "all turn steps confirmed", {"result_sha256": result_sha}
            )
            self.repository._audit(
                db,
                actor_user_id,
                "hardware.task.completed",
                int(task["id"]),
                {"result_sha256": result_sha, "completed_steps": completed},
            )
            return True
        # 尚未到末步时只移动计划索引并回到转角状态，下一次步进才执行下一角度。
        next_index = int(task["current_step_index"]) + 1
        db.execute(
            "UPDATE hardware_tasks SET status='turning', current_step_index=?, current_retry_count=0, completed_steps=?, last_message=?, updated_at=? WHERE id=?",
            (next_index, completed, "next turn step ready", utc_now(), task["id"]),
        )
        return False

    def _step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, profile = self.repository._context(task_id)
        status = str(task["status"])
        # 预激发结束仅进入转角阶段，本次步进不采正式帧。
        if status == HardwareTaskState.PRE_EXCITATION.value:
            with self.database.write() as db:
                current = self.repository._context(task_id, db)[0]
                db.execute(
                    "UPDATE hardware_tasks SET status='turning', last_message=?, updated_at=? WHERE id=?",
                    ("pre-excitation complete; turn plan ready", utc_now(), task_id),
                )
                self.repository._trace(
                    db,
                    task_id,
                    "internal",
                    "event",
                    "pre_excitation.complete",
                    {"seconds": current["pre_excitation_seconds"]},
                    f"hardware-{task_id}",
                    HardwareTaskState.TURNING.value,
                )
                self.repository._message(
                    db, task_id, "info", "pre_excitation.complete", "pre-excitation complete; turn plan ready", {}
                )
            return self.repository._task_dict(task_id)
        # 当前计划项可转动时发送模拟转角，再将任务和该计划项切换为采集中。
        if status == HardwareTaskState.TURNING.value:
            with self.database.write() as db:
                current, _, current_profile = self.repository._context(task_id, db)
                step_row = self.repository._current_step(db, current)
                if step_row["status"] not in {"pending", "retry_pending", "turning"}:
                    raise HardwareError(
                        "hardware_step_not_pending", "current turn step is not pending", status_code=409
                    )
                correlation_id = f"hardware-turn-{task_id}-{step_row['order_index']}-{uuid.uuid4().hex[:8]}"
                adapter = self._adapter(task_id, current_profile)
                response = (
                    adapter.turn(angle_deg=float(step_row["angle_deg"]), correlation_id=correlation_id)
                    if isinstance(adapter, SimulatorTurnAdapter)
                    else {}
                )
                db.execute(
                    "UPDATE hardware_plan_steps SET status='collecting', updated_at=? WHERE id=?",
                    (utc_now(), step_row["id"]),
                )
                db.execute(
                    "UPDATE hardware_tasks SET status='collecting', last_message=?, updated_at=? WHERE id=?",
                    ("turn complete; collecting CCD frame", utc_now(), task_id),
                )
                self.repository._trace(
                    db,
                    task_id,
                    "outbound",
                    "command",
                    "turn.request",
                    {
                        "angle_deg": step_row["angle_deg"],
                        "order_index": step_row["order_index"],
                        "simulated": isinstance(adapter, SimulatorTurnAdapter),
                    },
                    correlation_id,
                    HardwareTaskState.COLLECTING.value,
                )
                self.repository._trace(
                    db,
                    task_id,
                    "inbound",
                    "response",
                    "turn.response",
                    response,
                    correlation_id,
                    HardwareTaskState.COLLECTING.value,
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.turn.request",
                    task_id,
                    {
                        "order_index": step_row["order_index"],
                        "angle_deg": step_row["angle_deg"],
                        "correlation_id": correlation_id,
                    },
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.turn.response",
                    task_id,
                    {"order_index": step_row["order_index"], "correlation_id": correlation_id},
                )
            return self.repository._task_dict(task_id)
        if status != HardwareTaskState.COLLECTING.value:
            if status == HardwareTaskState.MANUAL_INTERVENTION.value:
                raise HardwareError(
                    "hardware_manual_intervention_required",
                    "manual intervention is required before continuing",
                    status_code=409,
                )
            raise HardwareError(
                "hardware_task_not_running",
                "hardware task is not ready to capture",
                details={"status": status},
                status_code=409,
            )
        adapter = self._adapters.get(task_id)
        # 当前可执行帧来自模拟适配器；缺会话或真实协议未接通时拒绝继续，不生成替代帧。
        if not isinstance(adapter, SimulatorTurnAdapter):
            raise HardwareError(
                "hardware_adapter_unavailable", "no active simulator adapter is available", status_code=409
            )
        with self.database.read() as db:
            current = self.repository._context(task_id, db)[0]
            current_step = self.repository._current_step(db, current)
            attempt = int(current_step['last_attempt']) + 1
            forced = _simulated_anomalies(current, current_step, attempt)
            observation = exposure_config(current, current_step)
        try:
            event = adapter.capture(correlation_id=f"hardware-frame-{task_id}-{uuid.uuid4().hex[:8]}",
                                    observation=observation, anomalies=forced)
        except HardwareError as exc:
            event = {"event_type": "fault", "ccds": [], "details": {"code": exc.code}, "message": exc.message}
        completed_now = False
        should_close = False
        with self.database.write() as db:
            current = self.repository._context(task_id, db)[0]
            step_row = self.repository._current_step(db, current)
            attempt = int(step_row["last_attempt"]) + 1
            forced = _simulated_anomalies(current, step_row, attempt)
            finished = capture_exposure(db, current, step_row, attempt, event, forced)
            if not finished:
                db.execute('UPDATE hardware_tasks SET last_event_json=?,updated_at=? WHERE id=?',
                           (_json(event), utc_now(), task_id))
                return self.repository._task_dict(task_id, db)
            # 先保存本次全部 CCD 的帧及异常指标，随后才决定是否接受，失败尝试也保留原始证据。
            observed, _ = self.repository._store_frames(db, current, step_row, attempt, event, forced, False)
            anomaly_kinds = sorted({item for row in observed for item in row["detected"]})
            if not anomaly_kinds and event.get("event_type") == "fault":
                anomaly_kinds = ["frame_fault"]
            db.execute(
                "UPDATE hardware_plan_steps SET last_attempt=?, updated_at=? WHERE id=?",
                (attempt, utc_now(), step_row["id"]),
            )
            self.repository._trace(
                db,
                task_id,
                "inbound",
                "frame",
                "frame.capture",
                {
                    "attempt": attempt,
                    "event_type": event.get("event_type"),
                    "sha256": (event.get("details") or {}).get("sha256"),
                    "anomaly_kinds": anomaly_kinds,
                },
                f"hardware-frame-{task_id}",
                HardwareTaskState.COLLECTING.value,
            )
            self.repository._audit(
                db,
                actor_user_id,
                "hardware.frame.capture",
                task_id,
                {
                    "order_index": step_row["order_index"],
                    "attempt": attempt,
                    "anomaly_kinds": anomaly_kinds,
                    "frame_sha256": (event.get("details") or {}).get("sha256"),
                },
            )
            # 异常策略按优先级选择修正、有限重试、人工接管或安全停止，所有决定都绑定本次尝试。
            if anomaly_kinds:
                anomaly_text = ",".join(anomaly_kinds)
                db.execute(
                    "UPDATE hardware_tasks SET status='anomaly', current_retry_count=?, last_event_json=?, last_message=?, updated_at=? WHERE id=?",
                    (
                        int(step_row["retry_count"]),
                        _json(event),
                        f"anomaly detected: {anomaly_text}",
                        utc_now(),
                        task_id,
                    ),
                )
                self.repository._message(
                    db,
                    task_id,
                    "warning",
                    "anomaly.detected",
                    f"anomaly detected: {anomaly_text}",
                    {"order_index": step_row["order_index"], "attempt": attempt},
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.anomaly.detected",
                    task_id,
                    {"order_index": step_row["order_index"], "attempt": attempt, "anomaly_kinds": anomaly_kinds},
                )
                retry_count = int(step_row["retry_count"])
                if anomaly_kinds == ["peak_shift"] and retry_count < int(current["retry_limit"]):
                    peak_observed = next((row for row in observed if row['peak_monitored']), observed[0])
                    db.execute(
                        "UPDATE hardware_plan_steps SET status='retry_pending', retry_count=retry_count+1, correction_offset=?, updated_at=? WHERE id=?",
                        (
                            float(step_row["expected_peak_position"]) - float(peak_observed["peak_position"]),
                            utc_now(),
                            step_row["id"],
                        ),
                    )
                    self.repository._decision(
                        db,
                        current,
                        step_row,
                        attempt,
                        anomaly_text,
                        "correct",
                        observed,
                        actor_user_id,
                        "automatic peak-position correction scheduled",
                    )
                    self.repository._message(
                        db,
                        task_id,
                        "info",
                        "anomaly.correct",
                        "automatic peak-position correction scheduled",
                        {"order_index": step_row["order_index"]},
                    )
                    self.repository._audit(
                        db,
                        actor_user_id,
                        "hardware.decision.correct",
                        task_id,
                        {"order_index": step_row["order_index"], "attempt": attempt},
                    )
                    db.execute(
                        "UPDATE hardware_tasks SET status='turning', current_retry_count=current_retry_count+1, last_message=?, updated_at=? WHERE id=?",
                        ("retrying after automatic correction", utc_now(), task_id),
                    )
                # 重试次数未耗尽时保留失败帧并回到转角阶段；再次采集使用新的 attempt 编号。
                elif retry_count < int(current["retry_limit"]):
                    db.execute(
                        "UPDATE hardware_plan_steps SET status='retry_pending', retry_count=retry_count+1, updated_at=? WHERE id=?",
                        (utc_now(), step_row["id"]),
                    )
                    self.repository._decision(
                        db,
                        current,
                        step_row,
                        attempt,
                        anomaly_text,
                        "retry",
                        observed,
                        actor_user_id,
                        "retry limit not exhausted",
                    )
                    self.repository._message(
                        db,
                        task_id,
                        "info",
                        "anomaly.retry",
                        "retry scheduled after anomaly",
                        {"order_index": step_row["order_index"], "retry_count": retry_count + 1},
                    )
                    self.repository._audit(
                        db,
                        actor_user_id,
                        "hardware.decision.retry",
                        task_id,
                        {"order_index": step_row["order_index"], "attempt": attempt, "retry_count": retry_count + 1},
                    )
                    db.execute(
                        "UPDATE hardware_tasks SET status='turning', current_retry_count=current_retry_count+1, last_message=?, updated_at=? WHERE id=?",
                        ("retry scheduled", utc_now(), task_id),
                    )
                # 自动尝试耗尽后，只有 manual 策略暂停等待人工决定，其余策略进入安全停止。
                elif current["anomaly_policy"] == "manual":
                    db.execute(
                        "UPDATE hardware_plan_steps SET status='manual', updated_at=? WHERE id=?",
                        (utc_now(), step_row["id"]),
                    )
                    self.repository._decision(
                        db,
                        current,
                        step_row,
                        attempt,
                        anomaly_text,
                        "manual",
                        observed,
                        actor_user_id,
                        "retry limit exhausted; manual takeover required",
                    )
                    db.execute(
                        "UPDATE hardware_tasks SET status='manual_intervention', last_message=?, updated_at=? WHERE id=?",
                        ("manual intervention required", utc_now(), task_id),
                    )
                    self.repository._audit(
                        db,
                        actor_user_id,
                        "hardware.decision.manual",
                        task_id,
                        {"order_index": step_row["order_index"], "attempt": attempt},
                    )
                else:
                    self.repository._decision(
                        db,
                        current,
                        step_row,
                        attempt,
                        anomaly_text,
                        "stop",
                        observed,
                        actor_user_id,
                        "retry limit exhausted; safety stop",
                    )
                    self._safe_stop_db(
                        db,
                        current,
                        actor_user_id,
                        f"retry limit exhausted at turn {step_row['order_index']}: {anomaly_text}",
                    )
                    should_close = True
            else:
                db.execute(
                    "UPDATE hardware_frames SET confirmed=1 WHERE task_id=? AND step_id=? AND attempt=?",
                    (task_id, step_row["id"], attempt),
                )
                self.repository._decision(
                    db,
                    current,
                    step_row,
                    attempt,
                    "none",
                    "accept",
                    observed,
                    actor_user_id,
                    "baseline and peak checks passed",
                )
                completed_now = self._complete_step(db, current, step_row, actor_user_id)
                should_close = completed_now
        # 需要收尾时先完成数据库状态与审计，再关闭任务适配器，已收帧仍可查看。
        if should_close:
            self._close_adapter(task_id)
        return self.repository._task_dict(task_id, include_points=True)

    def _pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self.repository._context(task_id)
        if task["status"] == HardwareTaskState.PAUSED.value:
            return self.repository._task_dict(task_id)
        if task["status"] not in {
            HardwareTaskState.PRE_EXCITATION.value,
            HardwareTaskState.TURNING.value,
            HardwareTaskState.COLLECTING.value,
            HardwareTaskState.ANOMALY.value,
        }:
            raise HardwareError(
                "hardware_task_not_pauseable",
                "hardware task cannot be paused in its current state",
                details={"status": task["status"]},
                status_code=409,
            )
        with self.database.write() as db:
            db.execute(
                "UPDATE hardware_tasks SET status='paused', paused_from=?, last_message=?, updated_at=? WHERE id=?",
                (task["status"], "hardware task paused", utc_now(), task_id),
            )
            self.repository._message(db, task_id, "warning", "task.pause", "hardware task paused", {"from": task["status"]})
            self.repository._audit(db, actor_user_id, "hardware.task.pause", task_id, {"from": task["status"]})
        return self.repository._task_dict(task_id)

    def _resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self.repository._context(task_id)
        if task["status"] != HardwareTaskState.PAUSED.value:
            raise HardwareError(
                "hardware_task_not_resumable",
                "hardware task is not paused",
                details={"status": task["status"]},
                status_code=409,
            )
        target = task["paused_from"] or HardwareTaskState.TURNING.value
        with self.database.write() as db:
            db.execute(
                "UPDATE hardware_tasks SET status=?, paused_from=NULL, last_message=?, updated_at=? WHERE id=?",
                (target, "hardware task resumed", utc_now(), task_id),
            )
            self.repository._message(db, task_id, "info", "task.resume", "hardware task resumed", {"to": target})
            self.repository._audit(db, actor_user_id, "hardware.task.resume", task_id, {"to": target})
        return self.repository._task_dict(task_id)

    def _intervene(self, task_id: int, action: str, note: str = "", actor_user_id: int | None = None) -> dict[str, Any]:
        if action not in {"accept", "retry", "stop"}:
            raise HardwareError("hardware_intervention_invalid", "intervention action is not supported")
        task, _, _ = self.repository._context(task_id)
        if task["status"] != HardwareTaskState.MANUAL_INTERVENTION.value:
            raise HardwareError(
                "hardware_manual_intervention_not_required",
                "manual intervention is not currently required",
                status_code=409,
            )
        should_close = False
        with self.database.write() as db:
            current = self.repository._context(task_id, db)[0]
            step = self.repository._current_step(db, current)
            latest_attempt = int(step["last_attempt"])
            # 人工接管只处理当前计划项最后一次尝试，不把较早或其他角度的帧当作本次结果。
            rows = db.execute(
                "SELECT * FROM hardware_frames WHERE task_id=? AND step_id=? AND attempt=?",
                (task_id, step["id"], latest_attempt),
            ).fetchall()
            observed = [
                {key: value for key, value in dict(row).items() if key not in {"points_blob", "raw_payload"}}
                for row in rows
            ]
            # 接受仍须有完整未损坏帧；人工确认不能让缺失或损坏传输变成合格数据。
            if action == "accept":
                interval_count = db.execute('SELECT COUNT(*) FROM hardware_exposure_results WHERE step_id=? AND attempt=?',
                                            (step['id'], latest_attempt)).fetchone()[0]
                if not interval_count and exposure_config(current, step)['end_frame'] > 1:
                    raise HardwareError('hardware_manual_accept_invalid', '曝光区间未完成，请重采或停止', status_code=409)
                if not rows or any(row["damaged"] for row in rows):
                    raise HardwareError(
                        "hardware_manual_accept_invalid", "damaged frames cannot be accepted", status_code=409
                    )
                db.execute(
                    "UPDATE hardware_frames SET confirmed=1 WHERE task_id=? AND step_id=? AND attempt=?",
                    (task_id, step["id"], latest_attempt),
                )
                anomaly_kind = (
                    ",".join(
                        sorted({kind for row in rows for kind in str(row["anomaly_kind"] or "").split(",") if kind})
                    )
                    or "none"
                )
                self.repository._decision(
                    db,
                    current,
                    step,
                    latest_attempt,
                    anomaly_kind,
                    "accept",
                    observed,
                    actor_user_id,
                    note or "manual takeover accepted the latest frame",
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.decision.accept",
                    task_id,
                    {"order_index": step["order_index"], "attempt": latest_attempt, "note": note},
                )
                should_close = self._complete_step(db, current, step, actor_user_id)
            elif action == "retry":
                db.execute(
                    "UPDATE hardware_plan_steps SET status='retry_pending', retry_count=retry_count+1, updated_at=? WHERE id=?",
                    (utc_now(), step["id"]),
                )
                self.repository._decision(
                    db,
                    current,
                    step,
                    latest_attempt,
                    step["status"],
                    "retry",
                    observed,
                    actor_user_id,
                    note or "manual takeover requested a retry",
                )
                db.execute(
                    "UPDATE hardware_tasks SET status='turning', current_retry_count=current_retry_count+1, last_message=?, updated_at=? WHERE id=?",
                    ("manual retry scheduled", utc_now(), task_id),
                )
                self.repository._audit(
                    db,
                    actor_user_id,
                    "hardware.decision.manual",
                    task_id,
                    {"action": "retry", "order_index": step["order_index"], "note": note},
                )
            else:
                self.repository._decision(
                    db,
                    current,
                    step,
                    latest_attempt,
                    step["status"],
                    "stop",
                    observed,
                    actor_user_id,
                    note or "manual takeover requested a safety stop",
                )
                self._safe_stop_db(db, current, actor_user_id, note or "manual takeover requested a safety stop")
                should_close = True
        # 人工停止或全部计划完成后关闭适配器，重试则保留当前计划项进入新尝试。
        if should_close:
            self._close_adapter(task_id)
        return self.repository._task_dict(task_id, include_points=True)

    def _stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        task, _, _ = self.repository._context(task_id)
        if task["status"] in {
            HardwareTaskState.COMPLETED.value,
            HardwareTaskState.FAILED.value,
            HardwareTaskState.STOPPED.value,
            HardwareTaskState.SAFETY_STOPPED.value,
            HardwareTaskState.DEFERRED_EXTERNAL.value,
        }:
            return self.repository._task_dict(task_id)
        with self.database.write() as db:
            db.execute(
                "UPDATE hardware_tasks SET status='stopping', last_message=?, updated_at=? WHERE id=?",
                ("stopping hardware safely", utc_now(), task_id),
            )
            self.repository._trace(
                db,
                task_id,
                "internal",
                "safety",
                "stop.request",
                {"reason": "user_requested"},
                f"hardware-stop-{task_id}",
                HardwareTaskState.STOPPING.value,
            )
            self.repository._audit(db, actor_user_id, "hardware.task.stop", task_id, {"from": task["status"]})
            db.execute(
                "UPDATE hardware_tasks SET status='stopped', completed_at=?, last_message=?, updated_at=? WHERE id=?",
                (utc_now(), "hardware task stopped safely", utc_now(), task_id),
            )
            self.repository._message(db, task_id, "warning", "task.stop", "hardware task stopped safely", {})
        self._close_adapter(task_id)
        return self.repository._task_dict(task_id)

    def start(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._start(task_id, actor_user_id)

    def step(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._step(task_id, actor_user_id)

    def pause(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._pause(task_id, actor_user_id)

    def resume(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._resume(task_id, actor_user_id)

    def intervene(self, task_id: int, action: str, note: str = "", actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._intervene(task_id, action, note, actor_user_id)

    def stop(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self._control_scope(task_id):
            return self._stop(task_id, actor_user_id)

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.repository.list_tasks(limit)

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    def create_task(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        return self.repository.create_task(payload, actor_user_id)

    def frames(self, task_id: int, *, step_id: int | None = None, include_points: bool = False) -> list[dict[str, Any]]:
        return self.repository.frames(task_id, step_id=step_id, include_points=include_points)

    def traces(self, task_id: int) -> list[dict[str, Any]]:
        return self.repository.traces(task_id)

    def decisions(self, task_id: int) -> list[dict[str, Any]]:
        return self.repository.decisions(task_id)

    def get_task(self, task_id: int, *, include_points: bool = False) -> dict[str, Any]:
        return self.repository._task_dict(task_id, include_points=include_points)

    def save_analysis_sample(self, task_id: int, payload: dict, actor_user_id: int | None = None) -> dict:
        from .analysis_sample import save_analysis_sample
        with self._control_scope(task_id):
            return save_analysis_sample(self, task_id, payload, actor_user_id)
