"""Existing v15 migration: mercury_calibration."""

import sqlite3

from .sql import _require_tables


def _migrate_v15(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        15,
        (
            "mercury_reference_lines",
            "mercury_sessions",
            "mercury_session_lines",
            "mercury_frames",
            "mercury_alignment_versions",
            "mercury_active_alignments",
            "mercury_traces",
            "mercury_messages",
        ),
    )
