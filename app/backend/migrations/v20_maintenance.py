"""Existing v20 migration: maintenance."""

import sqlite3

from .sql import _require_tables


def _migrate_v20(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        20,
        ("maintenance_backups", "maintenance_operations", "help_topics"),
    )
