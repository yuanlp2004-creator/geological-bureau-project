from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..db import Database, utc_now


class MaintenanceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class MaintenanceService:
    """SQLite maintenance operations with isolated verification and append-only records."""

    SAMPLE_TABLES = (
        ("dispersion_task_frames", "points_blob"),
        ("acquisition_frames", "points_blob"),
        ("acquisition_sample_bands", "mean_blob"),
        ("hardware_frames", "points_blob"),
        ("mercury_frames", "points_blob"),
    )
    ENTITY_TABLES = (
        "users", "methods", "method_versions", "sample_queues", "acquisition_tasks",
        "acquisition_samples", "analysis_runs", "reports", "report_exports", "audit_events",
    )
    ERROR_TOPIC_PREFIXES = (
        (("SPECTRUM_MIGRATION",), "spectrum-migration"),
        (("RESULT_MIGRATION", "LEGACY_RESULT"), "result-migration"),
        (("HARDWARE",), "hardware-acquisition"),
        (("MERCURY",), "mercury-calibration"),
        (("DISPERSION",), "dispersion"),
        (("POSTPROCESSING", "RECALCULATION", "EDT", "CMT", "PDT"), "postprocessing"),
        (("SPECTRUM",), "spectra"),
        (("ANALYSIS", "CURVE", "QC", "CALCULATION"), "analysis"),
        (("ACQUISITION", "DEVICE", "SERIAL"), "devices"),
        (("SAMPLE",), "samples"),
        (("METHOD", "SPECTRAL_LINE"), "methods"),
        (("REPORT", "PRINT", "EXPORT"), "reports"),
        (("MAINTENANCE", "BACKUP"), "maintenance"),
        (("AUTH", "USER", "ROLE", "PERMISSION", "SESSION", "AUDIT"), "administration"),
        (("MIGRATION", "LEGACY", "DIRECT"), "migration"),
        (("HELP",), "errors"),
    )

    def __init__(self, database: Database, runtime_log_path: Path | None = None):
        self.database = database
        self.runtime_log_path = runtime_log_path

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _table_columns(self, connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}

    def _snapshot(self, connection: sqlite3.Connection) -> dict[str, Any]:
        tables = {
            str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        counts: dict[str, int] = {}
        for table in self.ENTITY_TABLES:
            if table in tables:
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        blobs: list[dict[str, Any]] = []
        for table, column in self.SAMPLE_TABLES:
            if table not in tables or column not in self._table_columns(connection, table):
                continue
            rows = connection.execute(
                f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY rowid LIMIT 5"
            ).fetchall()
            for row in rows:
                payload = bytes(row[1])
                blobs.append({"table": table, "rowid": int(row[0]), "sha256": hashlib.sha256(payload).hexdigest(), "byte_length": len(payload)})
        return {"entity_counts": counts, "blob_samples": blobs}

    def _verify_path(self, path: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
        if not path.exists() or not path.is_file():
            raise MaintenanceError("MAINTENANCE_BACKUP_PATH", "备份文件不存在", 404, {"path": str(path)})
        try:
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            snapshot = self._snapshot(connection)
            connection.close()
        except (OSError, sqlite3.DatabaseError) as exc:
            raise MaintenanceError("MAINTENANCE_BACKUP_VERIFY", "备份校验失败", 422, {"reason": str(exc)}) from exc
        if integrity != "ok" or foreign_keys:
            raise MaintenanceError("MAINTENANCE_BACKUP_VERIFY", "备份完整性或外键校验失败", 422, {"integrity": integrity, "foreign_key_errors": len(foreign_keys)})
        if expected:
            if snapshot != {"entity_counts": expected.get("entity_counts", {}), "blob_samples": expected.get("blob_samples", [])}:
                raise MaintenanceError("MAINTENANCE_BACKUP_VERIFY", "备份实体计数或 BLOB 抽样哈希不一致", 422, {"expected": expected, "actual": snapshot})
        return {"integrity": integrity, "foreign_keys": 1, **snapshot}

    def _record_operation(self, operation: str, status: str, details: dict[str, Any], actor_user_id: int | None = None) -> str:
        operation_id = str(uuid.uuid4())
        with self.database.write() as connection:
            connection.execute(
                "INSERT INTO maintenance_operations(id, operation, status, details_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation, status, self._json(details), actor_user_id, utc_now()),
            )
        return operation_id

    def status(self) -> dict[str, Any]:
        with self.database.read() as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            wal = self.database.path.with_name(self.database.path.name + "-wal")
            backups = [dict(row) for row in connection.execute("SELECT * FROM maintenance_backups ORDER BY created_at DESC LIMIT 20").fetchall()]
            operations = [dict(row) for row in connection.execute("SELECT * FROM maintenance_operations ORDER BY created_at DESC LIMIT 20").fetchall()]
        for row in backups:
            for key in ("entity_counts_json", "blob_samples_json"):
                row[key[:-5]] = json.loads(row.pop(key))
        for row in operations:
            row["details"] = json.loads(row.pop("details_json"))
        return {"database_path": str(self.database.path), "database_bytes": self.database.path.stat().st_size if self.database.path.exists() else 0, "wal_bytes": wal.stat().st_size if wal.exists() else 0, "integrity": integrity, "foreign_key_errors": len(foreign_keys), "backups": backups, "operations": operations}

    def list_backups(self) -> list[dict[str, Any]]:
        return self.status()["backups"]

    def backup(self, output_directory: str, filename: str | None = None, retention_days: int = 30, actor_user_id: int | None = None) -> dict[str, Any]:
        if retention_days < 1 or retention_days > 3650:
            raise MaintenanceError("MAINTENANCE_RETENTION", "保留天数必须在 1 到 3650 之间")
        destination = Path(output_directory).expanduser()
        try:
            destination.mkdir(parents=True, exist_ok=True)
            if not os.access(destination, os.W_OK):
                raise PermissionError("backup directory is not writable")
        except OSError as exc:
            raise MaintenanceError("MAINTENANCE_PERMISSION", "备份目录不可写", 403, {"path": str(destination), "reason": str(exc)}) from exc
        if destination.resolve() == self.database.path.resolve().parent:
            raise MaintenanceError("MAINTENANCE_BACKUP_PATH", "备份目录不能与数据库目录相同")
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        target = destination / (filename or f"geospectrum-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3")
        if target.exists():
            raise MaintenanceError("MAINTENANCE_BACKUP_PATH", "备份文件已存在", 409, {"path": str(target)})
        temporary = destination / f".{target.name}.{uuid.uuid4().hex}.tmp"
        try:
            with self.database.read() as source:
                source.execute("BEGIN")
                source_snapshot = self._snapshot(source)
                replica = sqlite3.connect(temporary)
                try:
                    source.backup(replica)
                    replica.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    replica.commit()
                finally:
                    replica.close()
            os.replace(temporary, target)
            verification = self._verify_path(target, source_snapshot)
            source_hash = self._sha256(self.database.path)
            backup_hash = self._sha256(target)
            created = utc_now()
            expires = (self._now() + timedelta(days=retention_days)).isoformat(timespec="milliseconds")
            backup_id = str(uuid.uuid4())
            with self.database.write() as connection:
                connection.execute(
                    "INSERT INTO maintenance_backups(id, kind, source_path, backup_path, source_sha256, backup_sha256, byte_length, integrity, foreign_keys, entity_counts_json, blob_samples_json, retention_expires_at, status, created_by, created_at, completed_at) VALUES (?, 'online', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)",
                    (backup_id, str(self.database.path), str(target), source_hash, backup_hash, target.stat().st_size, verification["integrity"], verification["foreign_keys"], self._json(verification["entity_counts"]), self._json(verification["blob_samples"]), expires, actor_user_id, created, created),
                )
            self._record_operation("backup", "completed", {"backup_id": backup_id, "path": str(target), "verification": verification}, actor_user_id)
            return {"id": backup_id, "kind": "online", "backup_path": str(target), "created_at": created, "retention_expires_at": expires, "verification": verification, "backup_sha256": backup_hash, "byte_length": target.stat().st_size}
        except MaintenanceError:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            temporary.unlink(missing_ok=True)
            raise MaintenanceError("MAINTENANCE_BACKUP_VERIFY", "在线备份失败", 422, {"reason": str(exc)}) from exc

    def verify_backup(self, backup_id: str) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM maintenance_backups WHERE id=?", (backup_id,)).fetchone()
        if row is None:
            raise MaintenanceError("MAINTENANCE_BACKUP_PATH", "未找到备份记录", 404, {"id": backup_id})
        verification = self._verify_path(Path(row["backup_path"]), {"entity_counts": json.loads(row["entity_counts_json"]), "blob_samples": json.loads(row["blob_samples_json"])})
        return {"id": backup_id, "backup_path": row["backup_path"], "verification": verification, "backup_sha256": self._sha256(Path(row["backup_path"]))}

    def restore_rehearsal(self, backup_id: str, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM maintenance_backups WHERE id=?", (backup_id,)).fetchone()
        if row is None:
            raise MaintenanceError("MAINTENANCE_BACKUP_PATH", "未找到备份记录", 404, {"id": backup_id})
        source = Path(row["backup_path"])
        fd, isolated_name = tempfile.mkstemp(prefix="geospectrum-restore-", suffix=".sqlite3")
        os.close(fd)
        isolated = Path(isolated_name)
        try:
            shutil.copy2(source, isolated)
            verification = self._verify_path(isolated, {"entity_counts": json.loads(row["entity_counts_json"]), "blob_samples": json.loads(row["blob_samples_json"])})
            operation_id = self._record_operation("restore_rehearsal", "completed", {"backup_id": backup_id, "verification": verification}, actor_user_id)
            return {"backup_id": backup_id, "operation_id": operation_id, "status": "verified", "verification": verification}
        except MaintenanceError as exc:
            self._record_operation("restore_rehearsal", "failed", {"backup_id": backup_id, "code": exc.code, "message": exc.message}, actor_user_id)
            raise MaintenanceError("MAINTENANCE_RESTORE_VERIFY", "恢复演练校验失败，当前数据库未切换", 422, {"cause": exc.detail()}) from exc
        finally:
            isolated.unlink(missing_ok=True)

    def checkpoint(self, mode: str = "PASSIVE", actor_user_id: int | None = None) -> dict[str, Any]:
        normalized = mode.upper()
        if normalized not in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}:
            raise MaintenanceError("MAINTENANCE_CHECKPOINT", "不支持的 WAL checkpoint 模式")
        with self.database._write_lock, self.database.connect() as connection:
            result = [int(value) for value in connection.execute(f"PRAGMA wal_checkpoint({normalized})").fetchone()]
        operation_id = self._record_operation("checkpoint", "completed", {"mode": normalized, "result": result}, actor_user_id)
        return {"operation_id": operation_id, "mode": normalized, "result": result}

    def optimize(self, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database._write_lock, self.database.connect() as connection:
            result = connection.execute("PRAGMA optimize").fetchall()
        operation_id = self._record_operation("optimize", "completed", {"result": [list(row) for row in result]}, actor_user_id)
        return {"operation_id": operation_id, "result": [list(row) for row in result]}

    def reclaim(self, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.read() as connection:
            before = self._snapshot(connection)
            free_before = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        with self.database._write_lock, self.database.connect() as connection:
            connection.execute("VACUUM")
        with self.database.read() as connection:
            after = self._snapshot(connection)
            free_after = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        if before != after:
            raise MaintenanceError("MAINTENANCE_RECLAIM_VERIFY", "空间回收改变了实体计数或 BLOB 哈希", 422, {"before": before, "after": after})
        operation_id = self._record_operation("reclaim", "completed", {"freelist_before": free_before, "freelist_after": free_after, "snapshot": after}, actor_user_id)
        return {"operation_id": operation_id, "freelist_before": free_before, "freelist_after": free_after, "snapshot": after}

    def retention(self, actor_user_id: int | None = None) -> dict[str, Any]:
        now = self._now()
        removed: list[str] = []
        with self.database.read() as connection:
            rows = connection.execute("SELECT id, backup_path, retention_expires_at FROM maintenance_backups WHERE retention_expires_at IS NOT NULL AND retention_expires_at < ?", (now.isoformat(timespec="milliseconds"),)).fetchall()
        for row in rows:
            path = Path(row["backup_path"])
            try:
                path.unlink(missing_ok=True)
                removed.append(str(path))
            except OSError as exc:
                raise MaintenanceError("MAINTENANCE_RETENTION", "备份保留清理失败", 422, {"path": str(path), "reason": str(exc)}) from exc
        operation_id = self._record_operation("retention", "completed", {"removed": removed}, actor_user_id)
        return {"operation_id": operation_id, "removed": removed}

    def cleanup_logs(self, retention_days: int = 30, actor_user_id: int | None = None) -> dict[str, Any]:
        if not self.runtime_log_path:
            raise MaintenanceError("MAINTENANCE_LOG_PATH", "未配置运行日志路径")
        cutoff = self._now() - timedelta(days=max(1, retention_days))
        removed: list[str] = []
        for path in self.runtime_log_path.parent.glob(f"{self.runtime_log_path.name}.*"):
            if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                path.unlink(missing_ok=True)
                removed.append(str(path))
        operation_id = self._record_operation("logs", "completed", {"removed": removed, "retention_days": retention_days}, actor_user_id)
        return {"operation_id": operation_id, "removed": removed}

    def cleanup_temp(self, retention_days: int = 7, actor_user_id: int | None = None) -> dict[str, Any]:
        root = self.database.path.parent / "tmp"
        if not root.exists():
            return {"operation_id": self._record_operation("temp", "completed", {"removed": []}, actor_user_id), "removed": []}
        cutoff = self._now() - timedelta(days=max(1, retention_days))
        removed: list[str] = []
        for path in root.iterdir():
            if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                path.unlink(missing_ok=True)
                removed.append(str(path))
        operation_id = self._record_operation("temp", "completed", {"removed": removed, "retention_days": retention_days}, actor_user_id)
        return {"operation_id": operation_id, "removed": removed}

    def help_topics(self, query: str | None = None) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute("SELECT * FROM help_topics WHERE enabled=1 ORDER BY section, slug").fetchall()
        result = []
        needle = (query or "").strip().lower()
        for row in rows:
            item = {"slug": row["slug"], "title": row["title"], "section": row["section"], "keywords": json.loads(row["keywords_json"]), "body": row["body"], "related_routes": json.loads(row["related_routes_json"]), "updated_at": row["updated_at"]}
            if not needle or needle in self._json(item).lower():
                result.append(item)
        if not result and needle and re.fullmatch(r"[a-z][a-z0-9_-]{2,119}", needle):
            return [self.help_topic_for_error(needle)["topic"]]
        return result

    def help_topic(self, slug: str) -> dict[str, Any]:
        matches = [item for item in self.help_topics() if item["slug"] == slug]
        if not matches:
            raise MaintenanceError("HELP_TOPIC_NOT_FOUND", "帮助主题不存在", 404, {"slug": slug})
        return matches[0]

    def help_topic_for_error(self, code: str) -> dict[str, Any]:
        normalized = code.strip().upper().replace("-", "_")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,119}", normalized):
            raise MaintenanceError("HELP_ERROR_CODE_INVALID", "错误码格式无效", 422, {"code": code})
        slug = "errors"
        for prefixes, topic_slug in self.ERROR_TOPIC_PREFIXES:
            if normalized.startswith(prefixes):
                slug = topic_slug
                break
        return {"error_code": normalized, "topic": self.help_topic(slug)}
