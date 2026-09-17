"""Existing v19 migration: reports."""

import sqlite3

from .sql import _require_tables


def _migrate_v19(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        19,
        (
            "report_templates",
            "reports",
            "report_exports",
        ),
    )
