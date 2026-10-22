from __future__ import annotations
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Any
from ...db import Database, utc_now
from .adapters import MercuryAdapter, MercurySpectrumSimulatorAdapter, SerialMercuryAdapter
from .repository import MercuryRepository
from .values import MercuryError, _json


class MercuryCalibrationService:
    def __init__(self, database: Database):
        self.database = database
        self._adapters: dict[int, MercuryAdapter] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self.repository = MercuryRepository(database)

    @contextmanager
    def _control_scope(self, session_id: int):
        with self._locks_guard:
            lock = self._locks.setdefault(session_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise MercuryError(
                "mercury_session_busy", "another mercury control operation is in progress", status_code=409
            )
        try:
            yield
        finally:
            lock.release()

    def _build_adapter(
        self,
        session_id: int,
        profile: sqlite3.Row,
        layout: dict[str, Any],
        session: sqlite3.Row,
        db: sqlite3.Connection,
    ) -> MercuryAdapter:
        if profile["transport"] == "serial":
            return SerialMercuryAdapter()
        config = json.loads(session["simulator_json"] or "{}")
        before = db.execute(
            "SELECT * FROM mercury_alignment_versions WHERE id=?", (session["before_version_id"],)
        ).fetchone()
        if before is None:
            raise MercuryError("mercury_alignment_missing", "before alignment version was not found", status_code=409)
        return MercurySpectrumSimulatorAdapter(
            layout=layout,
            lines=self.repository._lines(db, session_id),
            active_offset=float(before["offset_points"]),
            physical_offset=float(config.get("offset_points", 6.0)),
            seed=int(config.get("seed", 0)),
            fault=str(config.get("fault", "none")),
        )

    def start(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, profile, layout = self.repository._context(session_id)
            if session["status"] != "draft":
                if session["status"] in {"stabilizing", "acquiring", "ready"}:
                    return self.repository.session(session_id, include_points=True)
                raise MercuryError(
                    "mercury_session_not_startable",
                    "mercury session is not startable",
                    details={"status": session["status"]},
                    status_code=409,
                )
            correlation_id = f"mercury-{session_id}-{uuid.uuid4().hex[:10]}"
            if profile["transport"] == "serial":
                with self.database.write() as db:
                    self.repository._trace(
                        db,
                        session_id,
                        "internal",
                        "event",
                        "protocol.deferred",
                        {"reason": "missing_mercury_protocol", "commands_sent": False},
                        correlation_id,
                        "safe_off",
                    )
                    now = utc_now()
                    db.execute(
                        (
                            "UPDATE mercury_sessions SET status='deferred_external', safe_off=1, "
                            "failure_code='mercury_protocol_unavailable', failure_message=?, last_message=?, "
                            "completed_at=?, updated_at=? WHERE id=?"
                        ),
                        (
                            "real mercury lamp protocol documentation or capture is unavailable",
                            "真实汞灯协议缺失，未发送命令",
                            now,
                            now,
                            session_id,
                        ),
                    )
                    self.repository._message(
                        db,
                        session_id,
                        "warning",
                        "session.deferred_external",
                        "real mercury protocol is unavailable; no command bytes were sent",
                        {"commands_sent": False},
                    )
                    self.repository._audit(
                        db,
                        actor,
                        "mercury.session.deferred",
                        session_id,
                        {"reason": "missing_mercury_protocol", "commands_sent": False},
                    )
                return self.repository.session(session_id)
            with self.database.read() as db:
                adapter = self._build_adapter(session_id, profile, layout, session, db)
            try:
                event = adapter.start(correlation_id=correlation_id)
            except MercuryError as exc:
                self._safe_off(session_id, exc, correlation_id, actor, adapter=adapter)
                return self.repository.session(session_id)
            self._adapters[session_id] = adapter
            now = utc_now()
            with self.database.write() as db:
                db.execute(
                    (
                        "UPDATE mercury_sessions SET status='stabilizing', safe_off=0, "
                        "adapter_session_id=?, last_event_json=?, last_message=?, started_at=?, "
                        "updated_at=? WHERE id=?"
                    ),
                    (adapter.session_id, _json(event), "模拟汞谱源已启动，等待稳定", now, now, session_id),
                )
                self.repository._trace(
                    db,
                    session_id,
                    "internal",
                    "event",
                    "simulation.spectrum.started",
                    event,
                    correlation_id,
                    "simulation_active",
                )
                self.repository._message(
                    db,
                    session_id,
                    "info",
                    "session.started",
                    "synthetic mercury spectrum started; no physical lamp command was issued",
                    {"physical_lamp_command": False},
                )
                self.repository._audit(
                    db,
                    actor,
                    "mercury.session.start",
                    session_id,
                    {"source": "synthetic_spectrum", "physical_lamp_command": False},
                )
            return self.repository.session(session_id, include_points=True)

    def _safe_off(
        self,
        session_id: int,
        exc: MercuryError,
        correlation_id: str,
        actor: int | None,
        *,
        adapter: MercuryAdapter | None = None,
    ) -> None:
        current = adapter or self._adapters.get(session_id)
        close_event = (
            current.close(correlation_id=f"{correlation_id}-close")
            if current is not None
            else {"event_type": "close_not_required", "commands_sent": False}
        )
        self._adapters.pop(session_id, None)
        now = utc_now()
        with self.database.write() as db:
            self.repository._trace(
                db,
                session_id,
                "internal",
                "safety",
                "safe_off",
                {"code": exc.code, "message": exc.message, "close": close_event},
                correlation_id,
                "safe_off",
            )
            db.execute(
                (
                    "UPDATE mercury_sessions SET status='safe_off', safe_off=1, "
                    "adapter_session_id=NULL, failure_code=?, failure_message=?, last_event_json=?, "
                    "last_message=?, completed_at=?, updated_at=? WHERE id=?"
                ),
                (exc.code, exc.message, _json(close_event), exc.message, now, now, session_id),
            )
            self.repository._message(
                db, session_id, "error", "session.safe_off", exc.message, {"code": exc.code, "close": close_event}
            )
            self.repository._audit(db, actor, "mercury.session.safe_off", session_id, {"code": exc.code, "close": close_event})

    def step(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self.repository._context(session_id)
            if session["status"] == "ready":
                return self.repository.session(session_id, include_points=True)
            if session["status"] not in {"stabilizing", "acquiring"}:
                raise MercuryError(
                    "mercury_session_not_running",
                    "mercury session is not running",
                    details={"status": session["status"]},
                    status_code=409,
                )
            adapter = self._adapters.get(session_id)
            if adapter is None:
                exc = MercuryError(
                    "mercury_adapter_lost",
                    "mercury adapter session is unavailable; restart with a new session",
                    status_code=409,
                )
                self._safe_off(session_id, exc, f"mercury-{session_id}-adapter-lost", actor)
                return self.repository.session(session_id)
            phase = "stabilization" if session["status"] == "stabilizing" else "measurement"
            frame_index = int(session["stabilized_frames"]) if phase == "stabilization" else 0
            correlation_id = f"mercury-{session_id}-{phase}-{frame_index}-{uuid.uuid4().hex[:8]}"
            try:
                event = adapter.frame(frame_index=frame_index, phase=phase, correlation_id=correlation_id)
            except MercuryError as exc:
                self._safe_off(session_id, exc, correlation_id, actor)
                return self.repository.session(session_id)
            with self.database.write() as db:
                self.repository._store_frame(db, session_id, event)
                self.repository._trace(
                    db,
                    session_id,
                    "inbound",
                    "frame",
                    f"{phase}.frame",
                    {key: value for key, value in event.items() if key != "ccds"}
                    | {"ccd_hashes": [item["points_sha256"] for item in event["ccds"]]},
                    correlation_id,
                    "simulation_active",
                )
                if phase == "stabilization":
                    stabilized = int(session["stabilized_frames"]) + 1
                    next_state = "acquiring" if stabilized >= int(session["stabilization_frames"]) else "stabilizing"
                    db.execute(
                        "UPDATE mercury_sessions SET status=?, stabilized_frames=?, last_event_json=?, last_message=?, updated_at=? WHERE id=?",
                        (
                            next_state,
                            stabilized,
                            _json(event),
                            f"稳定帧 {stabilized}/{session['stabilization_frames']}",
                            utc_now(),
                            session_id,
                        ),
                    )
                    self.repository._message(
                        db,
                        session_id,
                        "info",
                        "stability.frame",
                        "mercury stabilization frame captured",
                        {"stabilized_frames": stabilized, "required": session["stabilization_frames"]},
                    )
                    self.repository._audit(
                        db,
                        actor,
                        "mercury.frame.capture",
                        session_id,
                        {"phase": phase, "frame_index": frame_index, "frame_sha256": event["frame_sha256"]},
                    )
                else:
                    db.execute(
                        "UPDATE mercury_sessions SET last_event_json=?, last_message=?, updated_at=? WHERE id=?",
                        (_json(event), "测量帧已采集，正在计算校准建议", utc_now(), session_id),
                    )
                    refreshed = db.execute("SELECT * FROM mercury_sessions WHERE id=?", (session_id,)).fetchone()
                    self.repository._analyze(db, refreshed, event, actor)
                    self.repository._audit(
                        db,
                        actor,
                        "mercury.frame.capture",
                        session_id,
                        {"phase": phase, "frame_index": frame_index, "frame_sha256": event["frame_sha256"]},
                    )
            return self.repository.session(session_id, include_points=True)

    def apply(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self.repository._context(session_id)
            if session["status"] == "applied":
                return self.repository.session(session_id)
            if session["status"] != "ready" or session["candidate_version_id"] is None:
                raise MercuryError(
                    "mercury_calibration_not_ready",
                    "mercury correction is not ready to apply",
                    details={"status": session["status"]},
                    status_code=409,
                )
            analysis = json.loads(session["analysis_json"] or "{}")
            if not analysis.get("within_tolerance"):
                raise MercuryError(
                    "mercury_calibration_out_of_tolerance",
                    "corrected mercury peaks remain outside tolerance",
                    details=analysis,
                    status_code=409,
                )
            adapter = self._adapters.get(session_id)
            close_event = (
                adapter.close(correlation_id=f"mercury-{session_id}-apply-close")
                if adapter is not None
                else {"event_type": "close_not_required", "physical_lamp_command": False}
            )
            self._adapters.pop(session_id, None)
            now = utc_now()
            with self.database.write() as db:
                db.execute(
                    (
                        "INSERT INTO mercury_active_alignments(device_profile_id, ccd_layout_id, "
                        "version_id, updated_by, updated_at) VALUES (?, ?, ?, ?, ?) ON "
                        "CONFLICT(device_profile_id, ccd_layout_id) DO UPDATE SET "
                        "version_id=excluded.version_id, updated_by=excluded.updated_by, "
                        "updated_at=excluded.updated_at"
                    ),
                    (
                        session["device_profile_id"],
                        session["ccd_layout_id"],
                        session["candidate_version_id"],
                        actor,
                        now,
                    ),
                )
                self.repository._trace(
                    db,
                    session_id,
                    "internal",
                    "event",
                    "calibration.applied",
                    {
                        "before_version_id": session["before_version_id"],
                        "candidate_version_id": session["candidate_version_id"],
                        "close": close_event,
                    },
                    f"mercury-{session_id}-apply",
                    "safe_off",
                )
                db.execute(
                    (
                        "UPDATE mercury_sessions SET status='applied', safe_off=1, "
                        "adapter_session_id=NULL, last_event_json=?, last_message=?, completed_at=?, "
                        "updated_at=? WHERE id=?"
                    ),
                    (_json(close_event), "光学调整版本已应用，模拟谱源已关闭", now, now, session_id),
                )
                self.repository._message(
                    db,
                    session_id,
                    "success",
                    "calibration.applied",
                    "optical alignment version applied and source safely closed",
                    {"version_id": session["candidate_version_id"]},
                )
                self.repository._audit(
                    db,
                    actor,
                    "mercury.calibration.apply",
                    session_id,
                    {"before_version_id": session["before_version_id"], "version_id": session["candidate_version_id"]},
                )
            return self.repository.session(session_id)

    def rollback(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self.repository._context(session_id)
            if session["status"] == "rolled_back":
                return self.repository.session(session_id)
            if session["status"] != "applied":
                raise MercuryError(
                    "mercury_calibration_not_applied",
                    "only an applied mercury correction can be rolled back",
                    details={"status": session["status"]},
                    status_code=409,
                )
            now = utc_now()
            with self.database.write() as db:
                db.execute(
                    (
                        "UPDATE mercury_active_alignments SET version_id=?, updated_by=?, updated_at=? "
                        "WHERE device_profile_id=? AND ccd_layout_id=?"
                    ),
                    (session["before_version_id"], actor, now, session["device_profile_id"], session["ccd_layout_id"]),
                )
                self.repository._trace(
                    db,
                    session_id,
                    "internal",
                    "event",
                    "calibration.rolled_back",
                    {"from_version_id": session["candidate_version_id"], "to_version_id": session["before_version_id"]},
                    f"mercury-{session_id}-rollback",
                    "safe_off",
                )
                db.execute(
                    "UPDATE mercury_sessions SET status='rolled_back', safe_off=1, last_message=?, updated_at=? WHERE id=?",
                    ("已回滚到校准前光学调整版本", now, session_id),
                )
                self.repository._message(
                    db,
                    session_id,
                    "success",
                    "calibration.rolled_back",
                    "optical alignment restored to the before version",
                    {"version_id": session["before_version_id"]},
                )
                self.repository._audit(
                    db,
                    actor,
                    "mercury.calibration.rollback",
                    session_id,
                    {"from_version_id": session["candidate_version_id"], "to_version_id": session["before_version_id"]},
                )
            return self.repository.session(session_id)

    def stop(self, session_id: int, actor: int | None = None) -> dict[str, Any]:
        with self._control_scope(session_id):
            session, _, _ = self.repository._context(session_id)
            if session["status"] in {"applied", "rolled_back", "stopped", "safe_off", "deferred_external"}:
                return self.repository.session(session_id)
            adapter = self._adapters.get(session_id)
            close_event = (
                adapter.close(correlation_id=f"mercury-{session_id}-stop")
                if adapter is not None
                else {"event_type": "close_not_required", "physical_lamp_command": False}
            )
            self._adapters.pop(session_id, None)
            now = utc_now()
            with self.database.write() as db:
                self.repository._trace(
                    db,
                    session_id,
                    "internal",
                    "safety",
                    "session.stopped",
                    {"close": close_event},
                    f"mercury-{session_id}-stop",
                    "safe_off",
                )
                db.execute(
                    (
                        "UPDATE mercury_sessions SET status='stopped', safe_off=1, "
                        "adapter_session_id=NULL, last_event_json=?, last_message=?, completed_at=?, "
                        "updated_at=? WHERE id=?"
                    ),
                    (_json(close_event), "会话已停止并进入安全态", now, now, session_id),
                )
                self.repository._message(
                    db,
                    session_id,
                    "info",
                    "session.stopped",
                    "mercury session stopped in a safe state",
                    {"close": close_event},
                )
                self.repository._audit(
                    db,
                    actor,
                    "mercury.session.stop",
                    session_id,
                    {"previous_status": session["status"], "close": close_event},
                )
            return self.repository.session(session_id)

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    def create_session(self, payload: dict[str, Any], actor: int | None = None) -> dict[str, Any]:
        return self.repository.create_session(payload, actor)

    def session(self, session_id: int, *, include_points: bool = False) -> dict[str, Any]:
        return self.repository.session(session_id, include_points=include_points)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.repository.list_sessions(limit)
