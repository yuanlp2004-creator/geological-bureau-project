"""Existing v14 migration: hardware_acquisition."""

import sqlite3

from .sql import _require_tables


def _migrate_v14(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        14,
        (
            "hardware_tasks",
            "hardware_plan_steps",
            "hardware_frames",
            "hardware_traces",
            "hardware_decisions",
            "hardware_messages",
        ),
    )
