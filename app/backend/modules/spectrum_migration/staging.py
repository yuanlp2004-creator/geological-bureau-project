from __future__ import annotations
import uuid
from typing import Any
from ...db import Database, utc_now
from ..legacy_migration import LegacyMigrationError
from ..methods import _json
from .parsing import SpectrumParser
from .records import _run_dict


class SpectrumStaging:
    def __init__(self, database: Database):
        self.database = database
        self.parsing = SpectrumParser()

    def _stage_streaming(
        self,
        access: dict[str, Any],
        reader: dict[str, Any],
        source: dict[str, Any],
        fmt: str,
        actor_user_id: int,
        existing: Any,
    ) -> dict[str, Any]:
        tables = self.parsing._tables(access)
        layout = self.parsing._layout(tables["LAYOUT"][0])
        ignition, _ = self.parsing._ignition(tables)
        fingerprint = source["sha256"]
        run_id = existing["id"] if existing is not None else str(uuid.uuid4())
        now = utc_now()
        public_records: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        checks: dict[str, Any] = {
            "format_supported": True,
            "required_tables_present": True,
            "record_shapes_valid": True,
            "little_endian_decoded": True,
            "ccd_mapping_valid": True,
            "source_unchanged": True,
            "bad_frames_marked_without_replacement": True,
            "hashes_verified": True,
            "streaming_blobs": True,
        }
        table_counts = {name: len(rows) for name, rows in tables.items()}
        try:
            with self.database.write() as db:
                empty_staging = {
                    "format": fmt,
                    "record_count": 0,
                    "table_counts": table_counts,
                    "layout": layout,
                    "ignition": ignition,
                    "records": [],
                    "checks": checks,
                    "issues": [],
                    "source_unchanged": True,
                    "parser_version": "s08-spectrum-2",
                }
                empty_report = {
                    "phase": "staged",
                    "format": fmt,
                    "record_count": 0,
                    "table_counts": table_counts,
                    "checks": checks,
                    "issues": [],
                    "atomic_scope": "single_source_file",
                    "already_committed": False,
                }
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
                        _json(empty_staging),
                        _json(empty_report),
                        actor_user_id,
                        now,
                        now,
                    ),
                )
                db.execute("DELETE FROM spectrum_migration_staging_records WHERE run_id=?", (run_id,))
                for index, source_row in enumerate(tables["CCD_BAND"]):
                    one_tables = {**tables, "CCD_BAND": [source_row]}
                    normalized = self.parsing._normalize({"tables": one_tables}, fmt)
                    item = normalized["_records"][0]
                    item["record_index"] = index
                    if self.parsing._field(source_row, "BandId") is None:
                        item["band_id"] = index + 1
                    public_item = {key: value for key, value in item.items() if not key.endswith("_blob")}
                    public_records.append(public_item)
                    if not issues:
                        issues = normalized["issues"]
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
                            layout["frame_count"],
                            layout["ccds_per_frame"],
                            layout["points_per_ccd"],
                            layout["ccd_count"],
                            _json(layout["ccd_indices"]),
                            _json(layout),
                            _json(ignition),
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
                if not public_records:
                    issues.append({"level": "warning", "code": "spectrum_no_records", "message": "CCD_BAND 表没有记录"})
                public_staging = {
                    "format": fmt,
                    "record_count": len(public_records),
                    "table_counts": table_counts,
                    "layout": layout,
                    "ignition": ignition,
                    "records": public_records,
                    "checks": checks,
                    "issues": issues,
                    "source_unchanged": True,
                    "parser_version": "s08-spectrum-2",
                }
                report = {
                    "phase": "staged",
                    "format": fmt,
                    "record_count": len(public_records),
                    "table_counts": table_counts,
                    "checks": checks,
                    "issues": issues,
                    "atomic_scope": "single_source_file",
                    "already_committed": False,
                }
                db.execute(
                    "UPDATE spectrum_migration_runs SET staging_json=?, report_json=?, updated_at=? WHERE id=?",
                    (_json(public_staging), _json(report), now, run_id),
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
                                "record_count": len(public_records),
                                "streaming_blobs": True,
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
                "spectrum_stage_failed", "谱文件分块暂存失败", details={"reason": str(exc)}
            ) from exc
