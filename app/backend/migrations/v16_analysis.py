"""Existing v16 migration: analysis."""

import sqlite3

from .sql import _require_tables


def _migrate_v16(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        16,
        (
            "analysis_runs",
            "analysis_run_samples",
            "analysis_checkpoints",
            "analysis_interventions",
            "analysis_line_results",
            "analysis_messages",
        ),
    )
