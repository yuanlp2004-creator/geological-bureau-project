"""Existing v11 migration: devices."""

import sqlite3

from .sql import _require_tables


def _migrate_v11(connection: sqlite3.Connection) -> None:
    _require_tables(connection, 11, ("device_profiles",))
