"""Persist module-owned device and sample-list selections without rewriting tasks."""
import sqlite3


def _migrate_v27(connection: sqlite3.Connection) -> None:
    connection.execute('''CREATE TABLE device_runtime_state (
        id INTEGER PRIMARY KEY CHECK(id=1),
        profile_id INTEGER REFERENCES device_profiles(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE sample_queue_runtime_state (
        id INTEGER PRIMARY KEY CHECK(id=1),
        queue_id INTEGER REFERENCES sample_queues(id) ON DELETE SET NULL,
        updated_at TEXT NOT NULL)''')
