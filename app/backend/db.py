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
from .migrations.defaults import initialize_defaults, install_triggers


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_schema_versions(connection: sqlite3.Connection) -> set[int]:
    return {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}


def contiguous_schema_history(versions: set[int]) -> bool:
    return not versions or (
        min(versions) == SCHEMA_BASELINE_VERSION and len(versions) == max(versions) - SCHEMA_BASELINE_VERSION + 1
    )


def has_legacy_dispersion_frames(connection: sqlite3.Connection) -> bool:
    return any(row[1] == "points_json" for row in connection.execute("PRAGMA table_info(dispersion_task_frames)"))


def _initialization_versions(connection: sqlite3.Connection) -> set[int]:
    has_history = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    versions = read_schema_versions(connection) if has_history else set()
    current = max(versions, default=0)
    if current > SCHEMA_VERSION:
        raise sqlite3.OperationalError(f"database schema v{current} is newer than application schema v{SCHEMA_VERSION}")
    if not contiguous_schema_history(versions):
        raise sqlite3.OperationalError(f"unexpected schema_migrations history: {sorted(versions)}")
    if 12 in versions and has_legacy_dispersion_frames(connection):
        raise sqlite3.OperationalError("legacy dispersion frames require a staged database upgrade")
    return versions


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
            versions = _initialization_versions(connection)
            if SCHEMA_VERSION in versions:
                initialize_defaults(connection, utc_now())
                return

            rebuild = any(
                version not in versions and getattr(migration, "requires_foreign_keys_off", False)
                for version, _, migration in MIGRATIONS
            )
            if rebuild:
                connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            versions = _initialization_versions(connection)
            if SCHEMA_VERSION in versions:
                connection.rollback()
                if rebuild:
                    connection.execute("PRAGMA foreign_keys = ON")
                initialize_defaults(connection, utc_now())
                return

            create_baseline(connection)
            now = utc_now()
            if SCHEMA_BASELINE_VERSION not in versions:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_BASELINE_VERSION, now),
                )
            for version, _module_key, migration in MIGRATIONS:
                if version not in versions:
                    migration(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, now)
                    )
            initialize_defaults(connection, now, force=True)
            install_triggers(connection)
            connection.executemany(
                "INSERT INTO app_metadata(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                [("schema_version", str(SCHEMA_VERSION), now), ("app_name", "GeoSpectrum", now)],
            )
            connection.execute("DELETE FROM app_metadata WHERE key='builtin_roles_sha256'")
            if rebuild and connection.execute("PRAGMA foreign_key_check").fetchone():
                raise sqlite3.IntegrityError("migration left invalid foreign key references")

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
