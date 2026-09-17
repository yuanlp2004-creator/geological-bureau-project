"""Existing v18 migration: postprocessing."""

import sqlite3

from .sql import _require_tables


def _migrate_v18(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        18,
        (
            "postprocessing_conversion_runs",
            "postprocessing_recalculation_runs",
            "postprocessing_exports",
        ),
    )
