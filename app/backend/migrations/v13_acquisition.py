"""Existing v13 migration: acquisition."""

import sqlite3

from .sql import _require_tables


def _migrate_v13(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        13,
        (
            "acquisition_tasks",
            "acquisition_samples",
            "acquisition_frames",
            "acquisition_sample_bands",
            "acquisition_intervals",
            "acquisition_messages",
        ),
    )
