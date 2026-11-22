"""Postprocessing-owned output collections and source dispersion working copies."""
import sqlite3


def _migrate_v28(connection: sqlite3.Connection) -> None:
    connection.execute('''CREATE TABLE postprocessing_prepared_targets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        storage_mode TEXT NOT NULL CHECK(storage_mode IN ('averaged','full_interval')),
        layout_json TEXT NOT NULL,
        ignition_json TEXT NOT NULL,
        method_version_id INTEGER REFERENCES method_versions(id),
        legacy_method_id INTEGER,
        records_json TEXT NOT NULL DEFAULT '[]',
        revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE postprocessing_prepared_dispersion (
        source_sha256 TEXT PRIMARY KEY,
        layout_json TEXT NOT NULL,
        method_version_id INTEGER NOT NULL REFERENCES method_versions(id),
        updated_at TEXT NOT NULL)''')
