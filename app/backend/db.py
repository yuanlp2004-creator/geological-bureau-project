"""SQLite connection, write boundary and ordered migration orchestration."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .migrations import MIGRATIONS, SCHEMA_BASELINE_VERSION, SCHEMA_VERSION
from .migrations.baseline import create_baseline
from .migrations.defaults import initialize_defaults
from .migrations.sql import _columns
from .modules.extensions import apply_test_extension_migrations


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    """SQLite gateway with one process-wide write lock and idempotent migrations."""

    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            create_baseline(connection)
            applied_versions = {
                int(row[0])
                for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
            }
            recorded_steps = {version for version in applied_versions if version >= 11}
            if recorded_steps and recorded_steps != set(range(11, max(recorded_steps) + 1)):
                # Development builds before the S11-S16 gate wrote only the latest
                # monolithic marker. Rebase that unaccepted marker onto the S10
                # baseline, then execute the ordered migrations below.
                connection.execute("DELETE FROM schema_migrations WHERE version >= 11")
                applied_versions = {version for version in applied_versions if version < 11}
            if "points_json" in _columns(connection, "dispersion_task_frames") and 12 in applied_versions:
                # The earlier unaccepted S12 implementation stored ADC arrays as
                # JSON. Re-run v12 and all dependent migrations to convert it.
                connection.execute("DELETE FROM schema_migrations WHERE version >= 12")
                applied_versions = {version for version in applied_versions if version < 12}
            if SCHEMA_BASELINE_VERSION not in applied_versions:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_BASELINE_VERSION, utc_now()),
                )
                applied_versions.add(SCHEMA_BASELINE_VERSION)
            for version, _module_key, migration in MIGRATIONS:
                if version in applied_versions:
                    continue
                migration(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
                applied_versions.add(version)
            apply_test_extension_migrations(connection)
            now = utc_now()
            initialize_defaults(connection, now)
            connection.executemany(
                "INSERT INTO app_metadata(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                [("schema_version", str(SCHEMA_VERSION), now), ("app_name", "GeoSpectrum", now)],
            )

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        # SQLite WAL 允许并发读取，但应用写入仍需串行化，
        # 使跨表变更及其审计记录在同一短事务中提交。
        with self._write_lock:
            connection = self.connect()
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
