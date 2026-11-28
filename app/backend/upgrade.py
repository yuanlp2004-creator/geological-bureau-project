"""为已安装的 GeoSpectrum 数据提供崩溃安全的启动迁移。

正式数据库仅作为只读输入：先取得稳定的数据库与 WAL 快照，
再升级并校验暂存副本，只有全部成功后才原子切换。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database, contiguous_schema_history, has_legacy_dispersion_frames, read_schema_versions
from .migrations import SCHEMA_BASELINE_VERSION, SCHEMA_VERSION
from .migrations.defaults import install_triggers
from .migrations.v12_dispersion import _migrate_v12


class UpgradeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.expanduser().resolve().as_uri()}?mode=ro", uri=True)


def _monolithic_marker(
    connection: sqlite3.Connection, versions: set[int], current: int, legacy_frames: bool
) -> bool:
    # Only the pre-S17 development builds used a single v12–v16 marker.
    if current not in range(12, 17) or versions not in ({current}, {SCHEMA_BASELINE_VERSION, current}):
        return False
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "analysis_qc_decisions" in tables:
        return False
    if legacy_frames:
        return True
    if "app_metadata" not in tables:
        return False
    marker = connection.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()
    columns = {row[1] for row in connection.execute("PRAGMA table_info(dispersion_task_frames)")}
    return marker is not None and marker[0] == str(current) and {"points_blob", "points_sha256"} <= columns


def _preflight(path: Path) -> tuple[int, set[int], bool]:
    try:
        with closing(_connect_readonly(path)) as connection, connection:
            connection.execute("BEGIN")
            versions = read_schema_versions(connection)
            current = max(versions, default=0)
            if current > SCHEMA_VERSION:
                raise UpgradeError(f"database schema v{current} is newer than application schema v{SCHEMA_VERSION}")
            legacy_frames = has_legacy_dispersion_frames(connection)
            if not contiguous_schema_history(versions) and not _monolithic_marker(
                connection, versions, current, legacy_frames
            ):
                raise UpgradeError(f"unexpected schema_migrations history: {sorted(versions)}")
            return current, versions, legacy_frames
    except (OSError, sqlite3.DatabaseError, ValueError, TypeError) as exc:
        raise UpgradeError(f"database preflight failed: {exc}") from exc


def _repair_development_schema(path: Path, versions: set[int], legacy_frames: bool) -> None:
    current = max(versions, default=0)
    monolithic = not contiguous_schema_history(versions)
    with closing(Database(path).connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        if monolithic:
            connection.execute("DELETE FROM schema_migrations WHERE version=?", (current,))
        if legacy_frames:
            connection.execute("DROP TRIGGER IF EXISTS dispersion_task_frames_immutable_update")
            if 12 in versions and not monolithic:
                # Reapply the falsely recorded conversion without replaying later
                # published migrations, some of which rebuild or alter tables.
                _migrate_v12(connection)
                if current == SCHEMA_VERSION:
                    install_triggers(connection)
                    connection.execute("DELETE FROM app_metadata WHERE key IN ('defaults_sha256', 'builtin_roles_sha256')")


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


@contextmanager
def _source_snapshot(source: Path):
    """Yield a stable raw DB+WAL copy without opening or locking the source files."""

    source = source.expanduser().resolve()
    scratch = Path(tempfile.mkdtemp(prefix="geospectrum-source-snapshot-"))
    snapshot = scratch / source.name
    try:
        for _attempt in range(3):
            source_wal = source.with_name(source.name + "-wal")
            before = _source_hashes(source)
            shutil.copy2(source, snapshot)
            snapshot_wal = snapshot.with_name(snapshot.name + "-wal")
            snapshot_wal.unlink(missing_ok=True)
            if source_wal.exists():
                shutil.copy2(source_wal, snapshot_wal)
            if _source_hashes(source) == before:
                yield snapshot, before
                return
        raise UpgradeError("database changed while creating a read-only source snapshot")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _source_hashes(source: Path) -> dict[str, str | None]:
    wal = source.with_name(source.name + "-wal")
    return {"database": _sha256(source), "wal": _sha256(wal) if wal.exists() else None}


def _inspect(path: Path) -> dict[str, Any]:
    try:
        with closing(_connect_readonly(path)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            schema_version = int(row[0] or 0)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise UpgradeError(f"database inspection failed: {exc}") from exc
    if integrity != "ok" or foreign_key_errors:
        raise UpgradeError(
            f"database verification failed: integrity={integrity}, foreign_key_errors={foreign_key_errors}"
        )
    return {"integrity": integrity, "foreign_key_errors": foreign_key_errors, "schema_version": schema_version}


def _table_counts(path: Path) -> dict[str, int]:
    with closing(_connect_readonly(path)) as connection:
        names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        return {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"').fetchone()[0])
            for name in names
        }


def prepare_legacy_data_directory(legacy_data_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Copy the old install-adjacent data into the identifier-based data directory.

    Only known runtime data is copied. The legacy directory is never deleted or
    rewritten, so an installer rollback cannot destroy the previous database.
    """

    legacy_data_dir = legacy_data_dir.expanduser().resolve()
    data_dir = data_dir.expanduser().resolve()
    if legacy_data_dir == data_dir:
        return {"status": "same_directory"}
    source_database = legacy_data_dir / "geospectrum.sqlite3"
    target_database = data_dir / "geospectrum.sqlite3"
    if target_database.exists():
        return {"status": "target_present", "path": str(target_database)}
    if not source_database.exists():
        return {"status": "legacy_absent", "path": str(source_database)}
    if data_dir.exists():
        try:
            next(data_dir.iterdir())
        except StopIteration:
            data_dir.rmdir()
        else:
            raise UpgradeError(f"target data directory exists without database: {data_dir}")

    data_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = data_dir.with_name(f".{data_dir.name}-migration-{uuid.uuid4().hex}")
    staging.mkdir()
    staged_database = staging / "geospectrum.sqlite3"
    try:
        with _source_snapshot(source_database) as (snapshot_database, source_hashes):
            source_before = _inspect(snapshot_database)
            source_counts = _table_counts(snapshot_database)
            with (
                closing(_connect_readonly(snapshot_database)) as source,
                closing(sqlite3.connect(staged_database)) as replica,
            ):
                source.backup(replica)
                replica.commit()
        staged_after = _inspect(staged_database)
        staged_counts = _table_counts(staged_database)
        if staged_after != source_before or staged_counts != source_counts:
            raise UpgradeError("legacy data migration verification failed")
        for directory_name in ("backups", "logs", "print-jobs", "prints"):
            source_directory = legacy_data_dir / directory_name
            if source_directory.is_dir():
                shutil.copytree(source_directory, staging / directory_name)
        last_upgrade = legacy_data_dir / "last-upgrade.json"
        if last_upgrade.is_file():
            shutil.copy2(last_upgrade, staging / last_upgrade.name)
        result = {
            "status": "migrated",
            "legacy_data_dir": str(legacy_data_dir),
            "data_dir": str(data_dir),
            "source_database_sha256": source_hashes["database"],
            "target_database_sha256": _sha256(staged_database),
            "schema_version": int(staged_after["schema_version"]),
            "table_counts": staged_counts,
            "legacy_preserved": True,
        }
        (staging / "legacy-data-migration.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _replace_with_retry(staging, data_dir)
        return result
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def prepare_database_upgrade(database_path: Path) -> dict[str, Any]:
    """Validate an upgrade on a copy, then atomically replace the live database."""

    database_path = database_path.expanduser().resolve()
    if not database_path.exists():
        return {"status": "new_database", "target_schema_version": SCHEMA_VERSION}
    current, _, legacy_frames = _preflight(database_path)
    if current == SCHEMA_VERSION and not legacy_frames:
        return {"status": "not_required", "schema_version": current}

    with _source_snapshot(database_path) as (snapshot_database, source_hashes):
        current, versions, legacy_frames = _preflight(snapshot_database)
        if current == SCHEMA_VERSION and not legacy_frames:
            return {"status": "not_required", "schema_version": current}
        _inspect(snapshot_database)

        data_dir = database_path.parent.resolve()
        backup_dir = data_dir / "backups"
        temp_dir = data_dir / "tmp"
        backup_dir.mkdir(parents=True, exist_ok=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"pre-upgrade-v{current}-to-v{SCHEMA_VERSION}-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
        fd, staged_name = tempfile.mkstemp(prefix="upgrade-", suffix=".sqlite3", dir=temp_dir)
        os.close(fd)
        staged_path = Path(staged_name)
        switched = False
        try:
            with (
                closing(_connect_readonly(snapshot_database)) as source,
                closing(sqlite3.connect(backup_path)) as replica,
            ):
                source.backup(replica)
                replica.commit()
            backup_before = _inspect(backup_path)
            shutil.copy2(backup_path, staged_path)
            if legacy_frames or not contiguous_schema_history(versions):
                _repair_development_schema(staged_path, versions, legacy_frames)
            Database(staged_path).initialize()
            staged_after = _inspect(staged_path)
            if staged_after["schema_version"] != SCHEMA_VERSION:
                raise UpgradeError(f"staged migration stopped at schema v{staged_after['schema_version']}")
            source_hash = source_hashes["database"]
            backup_hash = _sha256(backup_path)
            if _source_hashes(database_path) != source_hashes:
                raise UpgradeError("database changed before switching to the staged upgrade")
            os.replace(staged_path, database_path)
            switched = True
            for suffix in ("-wal", "-shm"):
                sidecar = database_path.with_name(database_path.name + suffix)
                if sidecar.exists() and sidecar.resolve().parent == data_dir:
                    sidecar.unlink(missing_ok=True)
            after = _inspect(database_path)
            result = {
                "status": "upgraded",
                "from_schema_version": current,
                "to_schema_version": SCHEMA_VERSION,
                "backup_path": str(backup_path),
                "source_sha256": source_hash,
                "backup_sha256": backup_hash,
                "before": backup_before,
                "after": after,
            }
            (data_dir / "last-upgrade.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return result
        except Exception:
            if switched and backup_path.exists():
                rollback_fd, rollback_name = tempfile.mkstemp(prefix="rollback-", suffix=".sqlite3", dir=temp_dir)
                os.close(rollback_fd)
                rollback_path = Path(rollback_name)
                try:
                    shutil.copy2(backup_path, rollback_path)
                    os.replace(rollback_path, database_path)
                finally:
                    rollback_path.unlink(missing_ok=True)
            staged_path.unlink(missing_ok=True)
            raise
