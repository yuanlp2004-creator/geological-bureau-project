"""Persistence for formal sample monitoring decisions and attempt selection."""
import json
import sqlite3
from typing import Any

from ...db import utc_now
from .values import _json


def attempt_key(repeat_index, turn_index):
    return f'{repeat_index}:{turn_index}'


def monitoring_config(task):
    return json.loads(task['excitation_condition_json'] or '{}').get('monitoring', {})


def default_monitoring_state() -> dict[str, Any]:
    return {
        "status": "pending",
        "attempt": 0,
        "retry_count": 0,
        "awaiting_intervention": False,
        "can_accept": False,
        "accept_blocked_reason": None,
        "last_anomalies": [],
        "last_summary": None,
        "accepted_attempts": {},
    }


def get_monitoring_state(db: sqlite3.Connection, task_id: int) -> dict[str, Any]:
    row = db.execute("SELECT state_json FROM acquisition_monitoring_state WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        return default_monitoring_state()
    merged = default_monitoring_state()
    merged.update(json.loads(row["state_json"] or "{}"))
    return merged


def save_monitoring_state(db: sqlite3.Connection, task_id: int, state: dict[str, Any]) -> None:
    db.execute(
        """INSERT INTO acquisition_monitoring_state(task_id, state_json, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(task_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at""",
        (task_id, _json(state), utc_now()),
    )


def record_decision(
    db: sqlite3.Connection,
    *,
    task_id: int,
    repeat_index: int,
    turn_index: int,
    attempt: int,
    frame_index: int,
    anomaly_kinds: list[str],
    decision: str,
    correction_offset: float | None,
    observed: Any,
    reason: str,
    actor_user_id: int | None,
) -> int:
    cursor = db.execute(
        """INSERT INTO acquisition_monitoring_decisions(
               task_id, repeat_index, turn_index, attempt, frame_index,
               anomaly_kinds_json, decision, correction_offset, observed_json,
               reason, actor_user_id, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task_id,
            int(repeat_index),
            int(turn_index),
            int(attempt),
            int(frame_index),
            _json(anomaly_kinds),
            decision,
            correction_offset,
            _json(observed),
            reason,
            actor_user_id,
            utc_now(),
        ),
    )
    return int(cursor.lastrowid)


def list_decisions(db: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM acquisition_monitoring_decisions WHERE task_id=? ORDER BY id DESC LIMIT 40",
        (task_id,),
    ).fetchall()
    result = []
    for row in reversed(rows):
        item = dict(row)
        item["anomaly_kinds"] = json.loads(item.pop("anomaly_kinds_json") or "[]")
        item["observed"] = json.loads(item.pop("observed_json") or "[]")
        result.append(item)
    return result
