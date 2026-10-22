from __future__ import annotations
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any
from ...db import Database, utc_now
from ..legacy_migration import LegacyMigrationError, LegacyMigrationService
from ..methods import _json
from .parsing import SpectrumParser
from .reader import SpectrumAccessReader
from .records import _run_dict
from .staging import SpectrumStaging
from .values import SUPPORTED_FORMATS


class SpectrumMigrationService:
    def evaporation_curve(self, identifier: int) -> dict:
        from .timecurve import evaporation_curve
        return evaporation_curve(self, identifier)

    def evaporation_records(self) -> list[dict]:
        with self.database.read() as db:
            return self.source_records(db, ('edt',))

    def opened_records(self, source_sha256: str) -> list[dict]:
        with self.database.read() as db:
            return [dict(row) for row in db.execute(
                'SELECT id,format,sample_name,sample_no,record_index,layout_json,ignition_json '
                'FROM spectrum_bands WHERE source_sha256=? ORDER BY record_index', (source_sha256,))]

    def __init__(self, database: Database) -> None:
        self.database = database
        self.parsing = SpectrumParser()
        self.reader = SpectrumAccessReader()
        self.staging = SpectrumStaging(database)

    def diagnostics(self) -> dict[str, Any]:
        diagnostic = LegacyMigrationService(self.database).diagnostics()
        return {
            **diagnostic,
            "formats": sorted(SUPPORTED_FORMATS),
            "layout_tables": ["LAYOUT", "CCD_BAND"],
            "read_only": True,
            "streaming_blobs": True,
            "parser_version": "s08-spectrum-2",
        }

    @staticmethod
    def source_record(connection, identifier: int) -> dict[str, Any]:
        """Public immutable source snapshot for downstream read-only adaptation."""
        row = connection.execute("SELECT * FROM spectrum_bands WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise LegacyMigrationError("spectrum_record_not_found", "旧谱记录不存在")
        return dict(row)

    @staticmethod
    def source_records(connection, formats: tuple[str, ...]) -> list[dict[str, Any]]:
        marks = ",".join("?" for _ in formats)
        return [
            dict(row)
            for row in connection.execute(
                (
                    f"SELECT id,format,sample_name,band_name,source_sha256,record_index,sample_no FROM "
                    f"spectrum_bands WHERE format IN ({marks}) ORDER BY id"
                ),
                formats,
            )
        ]

    def stage(self, path_value: str, actor_user_id: int) -> dict[str, Any]:
        path = Path(path_value).expanduser()
        fmt = path.suffix.lower().lstrip(".")
        if fmt not in SUPPORTED_FORMATS:
            raise LegacyMigrationError(
                "spectrum_source_extension_invalid", "谱文件扩展名必须是 .cdt、.cmt、.edt 或 .wdt"
            )
        source = self._source_snapshot(path)
        fingerprint = source["sha256"]
        with self.database.read() as db:
            existing = db.execute(
                "SELECT * FROM spectrum_migration_runs WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if existing is not None and existing["status"] == "committed":
                result = _run_dict(existing)
                result["already_committed"] = True
                return result
        access, reader = self.reader.read(path, source)
        bundle_value = access.get("_streaming_bundle")
        try:
            after = self._source_snapshot(path)
            if source != after:
                raise LegacyMigrationError("spectrum_source_changed", "只读解析期间谱文件发生变化，已中止")
            if bundle_value:
                return self.staging._stage_streaming(access, reader, source, fmt, actor_user_id, existing)
            normalized = self.parsing._normalize(access, fmt)
            normalized["source_unchanged"] = True
            public_staging = {key: value for key, value in normalized.items() if key != "_records"}
            public_staging["parser_version"] = "s08-spectrum-2"
            report = {
                "phase": "staged",
                "format": fmt,
                "record_count": normalized["record_count"],
                "table_counts": normalized["table_counts"],
                "checks": normalized["checks"],
                "issues": normalized["issues"],
                "atomic_scope": "single_source_file",
                "already_committed": False,
            }
            now = utc_now()
            run_id = existing["id"] if existing is not None else str(uuid.uuid4())
            try:
                with self.database.write() as db:
                    db.execute(
                        "INSERT INTO spectrum_migration_runs(id, fingerprint, format, status, "
                        "source_json, reader_json, staging_json, report_json, created_by, created_at, "
                        "updated_at) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(fingerprint) DO UPDATE SET id=excluded.id, format=excluded.format, "
                        "status='staged', source_json=excluded.source_json, "
                        "reader_json=excluded.reader_json, staging_json=excluded.staging_json, "
                        "report_json=excluded.report_json, error_code=NULL, error_message=NULL, "
                        "created_by=excluded.created_by, updated_at=excluded.updated_at, "
                        "committed_at=NULL",
                        (
                            run_id,
                            fingerprint,
                            fmt,
                            _json(source),
                            _json(reader),
                            _json(public_staging),
                            _json(report),
                            actor_user_id,
                            now,
                            now,
                        ),
                    )
                    db.execute("DELETE FROM spectrum_migration_staging_records WHERE run_id=?", (run_id,))
                    for item in normalized["_records"]:
                        db.execute(
                            (
                                "INSERT INTO spectrum_migration_staging_records(run_id, record_index, band_id, "
                                "sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, "
                                "frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, "
                                "layout_json, ignition_json, bad_frame_indices_json, mean_blob, burn_adcs_blob, "
                                "dark_adcs_blob, mean_sha256, burn_sha256, dark_sha256, sampled_values_json, "
                                "details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                                "?, ?, ?, ?, ?, ?)"
                            ),
                            (
                                run_id,
                                item["record_index"],
                                item["band_id"],
                                item["sample_no"],
                                item["sample_name"],
                                item["band_name"],
                                item["long_name"],
                                item["measure_time"],
                                item["real_ref_step"],
                                normalized["layout"]["frame_count"],
                                normalized["layout"]["ccds_per_frame"],
                                normalized["layout"]["points_per_ccd"],
                                normalized["layout"]["ccd_count"],
                                _json(normalized["layout"]["ccd_indices"]),
                                _json(normalized["layout"]),
                                _json(normalized["ignition"]),
                                _json(item["bad_frame_indices"]),
                                item["mean_blob"],
                                item["burn_adcs_blob"],
                                item["dark_adcs_blob"],
                                item["mean_sha256"],
                                item["burn_sha256"],
                                item["dark_sha256"],
                                _json(item["sampled_values"]),
                                _json(item["details"]),
                            ),
                        )
                    db.execute(
                        (
                            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                            "details_json, created_at) VALUES (?, 'spectrum_migration.stage', "
                            "'spectrum_migration', NULL, ?, ?)"
                        ),
                        (
                            actor_user_id,
                            _json(
                                {
                                    "run_id": run_id,
                                    "source_sha256": fingerprint,
                                    "format": fmt,
                                    "record_count": normalized["record_count"],
                                }
                            ),
                            now,
                        ),
                    )
                    row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
                    return {**_run_dict(row), "already_committed": False}
            except Exception as exc:
                if isinstance(exc, LegacyMigrationError):
                    raise
                raise LegacyMigrationError(
                    "spectrum_stage_failed", "谱文件暂存失败", details={"reason": str(exc)}
                ) from exc
        finally:
            if bundle_value:
                bundle = Path(str(bundle_value)).resolve()
                temporary_root = Path(tempfile.gettempdir()).resolve()
                if bundle.name.startswith("geospectrum-s08-") and temporary_root in bundle.parents:
                    shutil.rmtree(bundle, ignore_errors=True)

    @staticmethod
    def _source_snapshot(path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise LegacyMigrationError(
                "spectrum_source_unreadable", f"无法读取谱文件：{path}", details={"reason": str(exc)}
            ) from exc
        return {
            "path": str(path.resolve()),
            "name": path.name,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": digest.hexdigest(),
        }

    def commit(self, run_id: str, actor_user_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("spectrum_run_not_found", "谱迁移任务不存在", status_code=404)
            if row["status"] == "committed":
                result = _run_dict(row)
                result["already_committed"] = True
                return result
            source = json.loads(row["source_json"])
            staging = json.loads(row["staging_json"])
            fingerprint = row["fingerprint"]
        current = self._source_snapshot(Path(source["path"]))
        if current != source:
            raise LegacyMigrationError(
                "spectrum_source_changed_since_stage",
                "源文件在暂存后发生变化，请重新暂存",
                details={"before": source, "current": current},
            )
        now = utc_now()
        try:
            with self.database.write() as db:
                if db.execute("SELECT 1 FROM spectrum_bands WHERE source_sha256=? LIMIT 1", (fingerprint,)).fetchone():
                    raise LegacyMigrationError(
                        "spectrum_source_already_imported", "该谱文件已由其他迁移任务提交", status_code=409
                    )
                record_count = int(
                    db.execute(
                        "SELECT COUNT(*) FROM spectrum_migration_staging_records WHERE run_id=?", (run_id,)
                    ).fetchone()[0]
                )
                db.execute(
                    "INSERT INTO spectrum_bands(import_run_id, source_sha256, record_index, format, "
                    "band_id, sample_no, sample_name, band_name, long_name, measure_time, "
                    "real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, "
                    "ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, "
                    "mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, burn_sha256, "
                    "dark_sha256, sampled_values_json, details_json) "
                    "SELECT run_id, ?, record_index, ?, band_id, sample_no, sample_name, band_name, "
                    "long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, "
                    "points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, "
                    "bad_frame_indices_json, mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, "
                    "burn_sha256, dark_sha256, sampled_values_json, details_json FROM "
                    "spectrum_migration_staging_records WHERE run_id=? ORDER BY record_index",
                    (fingerprint, row["format"], run_id),
                )
                report = {
                    **json.loads(row["report_json"]),
                    "phase": "committed",
                    "checks": {
                        **json.loads(row["report_json"])["checks"],
                        "source_unchanged": True,
                        "atomic_commit": True,
                        "idempotency_guarded": True,
                    },
                    "already_committed": False,
                    "imported": {"spectrum_bands": record_count},
                }
                db.execute(
                    (
                        "UPDATE spectrum_migration_runs SET status='committed', report_json=?, "
                        "error_code=NULL, error_message=NULL, updated_at=?, committed_at=? WHERE id=?"
                    ),
                    (_json(report), now, now, run_id),
                )
                db.execute(
                    (
                        "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                        "details_json, created_at) VALUES (?, 'spectrum_migration.commit', "
                        "'spectrum_migration', NULL, ?, ?)"
                    ),
                    (
                        actor_user_id,
                        _json({"run_id": run_id, "source_sha256": fingerprint, "record_count": record_count}),
                        now,
                    ),
                )
        except Exception as exc:
            code = exc.code if isinstance(exc, LegacyMigrationError) else "spectrum_commit_failed"
            message = exc.message if isinstance(exc, LegacyMigrationError) else str(exc)
            with self.database.write() as db:
                db.execute(
                    "UPDATE spectrum_migration_runs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?",
                    (code, message[:1000], utc_now(), run_id),
                )
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError(
                "spectrum_commit_failed", "谱文件提交失败，已完整回滚", details={"reason": message}
            ) from exc
        return self.get(run_id, already_committed=False)

    def get(self, run_id: str, *, already_committed: bool | None = None) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("spectrum_run_not_found", "谱迁移任务不存在", status_code=404)
            result = _run_dict(row)
            result["already_committed"] = bool(already_committed)
            return result

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute(
                "SELECT * FROM spectrum_migration_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)
            ).fetchall()
            return [_run_dict(row, include_staging=False) for row in rows]
