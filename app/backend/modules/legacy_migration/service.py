"""旧方法暂存与完整原子提交，对外服务入口。"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from ...db import Database, utc_now
from ..methods import MethodService, _json
from .errors import LegacyMigrationError
from .sources import _sha256_json, _source_snapshot
from .configuration import _decode_ini
from .normalization import LegacyNormalizer
from .reader import LegacyAccessReader
from .records import LegacyRecordDecoder



class LegacyMigrationService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.methods = MethodService(database)
        self.reader = LegacyAccessReader()
        self.records = LegacyRecordDecoder()
        self.normalization = LegacyNormalizer(self.records)

    def resolve_method_id(self, legacy_id: int) -> int | None:
        """Resolve a legacy method id through the migration service contract."""
        with self.database.read() as db:
            row = db.execute(
                "SELECT target_id FROM legacy_import_entities WHERE entity_type='method' AND legacy_key=? AND target_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                (str(int(legacy_id)),),
            ).fetchone()
            return int(row["target_id"]) if row is not None else None

    @staticmethod
    def _fingerprint(sources: dict[str, dict[str, Any]]) -> str:
        return _sha256_json({name: item["sha256"] for name, item in sorted(sources.items())})

    @staticmethod
    def _run_dict(row: Any, *, include_staging: bool = True) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "fingerprint": row["fingerprint"],
            "status": row["status"],
            "source_files": json.loads(row["source_files_json"]),
            "reader": json.loads(row["reader_json"]),
            "report": json.loads(row["report_json"]),
            "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "committed_at": row["committed_at"],
        }
        if include_staging:
            result["staging"] = json.loads(row["staging_json"])
        return result

    def stage(self, mtd_path: str, cfg_path: str, opt_path: str, actor_user_id: int) -> dict[str, Any]:
        paths = {"mtd": Path(mtd_path).expanduser(), "cfg": Path(cfg_path).expanduser(), "opt": Path(opt_path).expanduser()}
        expected = {"mtd": ".mtd", "cfg": ".cfg", "opt": ".opt"}
        for key, path in paths.items():
            if path.suffix.lower() != expected[key]:
                raise LegacyMigrationError("legacy_source_extension_invalid", f"{key.upper()} 文件扩展名必须是 {expected[key]}")
        sources = {name: _source_snapshot(path) for name, path in paths.items()}
        fingerprint = self._fingerprint(sources)
        with self.database.read() as db:
            existing = db.execute("SELECT * FROM legacy_migration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing is not None and existing["status"] == "committed":
                result = self._run_dict(existing)
                result["already_committed"] = True
                return result

        access, reader = self.reader._read_access(paths["mtd"], sources["mtd"])
        cfg, cfg_encoding = _decode_ini(paths["cfg"])
        opt, opt_encoding = _decode_ini(paths["opt"])
        after_sources = {name: _source_snapshot(path) for name, path in paths.items()}
        if sources != after_sources:
            raise LegacyMigrationError("legacy_source_changed", "暂存期间旧版源文件发生变化，已中止")
        staging = self.normalization._normalize_access(access, cfg, opt, cfg_encoding, opt_encoding)
        staging["fingerprint"] = fingerprint
        staging["sources_unchanged"] = True
        report = {
            "phase": "staged",
            "counts": staging["counts"],
            "checks": {**staging["checks"], "sources_unchanged": True},
            "issues": staging["issues"],
            "atomic_scope": "source_set",
            "already_committed": False,
        }
        now = utc_now()
        run_id = existing["id"] if existing is not None else str(uuid.uuid4())
        with self.database.write() as db:
            db.execute(
                "INSERT INTO legacy_migration_runs(id, fingerprint, status, source_files_json, reader_json, staging_json, report_json, error_code, error_message, created_by, created_at, updated_at, committed_at) "
                "VALUES (?, ?, 'staged', ?, ?, ?, ?, NULL, NULL, ?, ?, ?, NULL) "
                "ON CONFLICT(fingerprint) DO UPDATE SET status='staged', source_files_json=excluded.source_files_json, reader_json=excluded.reader_json, staging_json=excluded.staging_json, report_json=excluded.report_json, error_code=NULL, error_message=NULL, created_by=excluded.created_by, updated_at=excluded.updated_at, committed_at=NULL",
                (run_id, fingerprint, _json(sources), _json(reader), _json(staging), _json(report), actor_user_id, now, now),
            )
            db.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'legacy_migration.stage', 'legacy_migration', NULL, ?, ?)",
                (actor_user_id, _json({"run_id": run_id, "fingerprint": fingerprint, "counts": staging["counts"]}), now),
            )
            row = db.execute("SELECT * FROM legacy_migration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            return {**self._run_dict(row), "already_committed": False}

    @staticmethod
    def _unique_name(db: Any, table: str, desired: str, fingerprint: str) -> str:
        if db.execute(f"SELECT 1 FROM {table} WHERE name=? COLLATE NOCASE", (desired,)).fetchone() is None:
            return desired
        return f"{desired} · 旧版 {fingerprint[:6]}"

    @staticmethod
    def _record_entity(
        db: Any,
        *,
        run_id: str,
        source_sha256: str,
        entity_type: str,
        legacy_key: str,
        target_id: int | None,
        payload: Any,
        details: Any,
        now: str,
    ) -> None:
        db.execute(
            "INSERT INTO legacy_import_entities(run_id, source_sha256, entity_type, legacy_key, target_id, payload_sha256, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, source_sha256, entity_type, legacy_key, target_id, _sha256_json(payload), _json(details), now),
        )

    def _after_entity_insert(self, _entity_type: str, _legacy_key: str) -> None:
        """Test seam for proving transaction rollback; production intentionally does nothing."""

    def _assert_sources_current(self, sources: dict[str, dict[str, Any]]) -> None:
        for source in sources.values():
            current = _source_snapshot(Path(source["path"]))
            if current != source:
                raise LegacyMigrationError(
                    "legacy_source_changed_since_stage",
                    "源文件在暂存后发生变化，请重新暂存",
                    details={"before": source, "current": current},
                )

    def commit(self, run_id: str, actor_user_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM legacy_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("legacy_run_not_found", "迁移任务不存在", status_code=404)
            if row["status"] == "committed":
                result = self._run_dict(row)
                result["already_committed"] = True
                return result
            staging = json.loads(row["staging_json"])
            sources = json.loads(row["source_files_json"])
            fingerprint = row["fingerprint"]
        self._assert_sources_current(sources)

        now = utc_now()
        mtd_hash = sources["mtd"]["sha256"]
        imported = {"methods": [], "spectral_lines": staging["counts"]["spectral_lines"], "dispersion_curves": [], "ccd_layouts": [], "configuration_profile_id": None}
        try:
            with self.database.write() as db:
                if db.execute("SELECT 1 FROM legacy_import_entities WHERE source_sha256=? LIMIT 1", (mtd_hash,)).fetchone():
                    raise LegacyMigrationError("legacy_source_already_imported", "该 MTD 内容已由其他迁移任务导入", status_code=409)

                layout_ids: dict[str, int] = {}
                calibration_ids: dict[str, int] = {}
                for dispersion in staging["dispersions"]:
                    geometry = {key: dispersion[key] for key in ("frame_count", "ccds_per_frame", "points_per_ccd", "point_width", "gap_points", "ccd_indices")}
                    geometry_key = _sha256_json(geometry)
                    if geometry_key not in layout_ids:
                        layout_name = self._unique_name(db, "ccd_layouts", f"旧版布局 · {dispersion['name']}", fingerprint)
                        cursor = db.execute(
                            "INSERT INTO ccd_layouts(name, frame_count, ccds_per_frame, points_per_ccd, point_width, gap_points_json, ccd_indices_json, wavelength_min, wavelength_max, allow_drift_um, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 160, 800, ?, ?)",
                            (layout_name, dispersion["frame_count"], dispersion["ccds_per_frame"], dispersion["points_per_ccd"], dispersion["point_width"], _json(dispersion["gap_points"]), _json(dispersion["ccd_indices"]), 0.0, now),
                        )
                        layout_id = int(cursor.lastrowid)
                        layout_ids[geometry_key] = layout_id
                        imported["ccd_layouts"].append(layout_id)
                        self._record_entity(db, run_id=run_id, source_sha256=mtd_hash, entity_type="ccd_layout", legacy_key=geometry_key, target_id=layout_id, payload=geometry, details={"name": layout_name}, now=now)
                        self._after_entity_insert("ccd_layout", geometry_key)
                    layout_id = layout_ids[geometry_key]
                    calibration_name = self._unique_name(db, "dispersion_calibrations", dispersion["name"], fingerprint)
                    cursor = db.execute(
                        "INSERT INTO dispersion_calibrations(name, ccd_layout_id, wavelength_min, wavelength_max, coefficients_json, enabled, created_at) VALUES (?, ?, 160, 800, ?, 1, ?)",
                        (calibration_name, layout_id, _json(dispersion["coefficients"]), now),
                    )
                    calibration_id = int(cursor.lastrowid)
                    calibration_ids[dispersion["name"]] = calibration_id
                    imported["dispersion_curves"].append(calibration_id)
                    self._record_entity(db, run_id=run_id, source_sha256=mtd_hash, entity_type="dispersion_calibration", legacy_key=str(dispersion["legacy_id"]), target_id=calibration_id, payload=dispersion, details={"name": calibration_name, "blob_evidence": dispersion["blob_evidence"]}, now=now)
                    self._after_entity_insert("dispersion_calibration", str(dispersion["legacy_id"]))

                for method in staging["methods"]:
                    desired_name = method["name"]
                    target_name = self._unique_name(db, "methods", desired_name, fingerprint)
                    conditions = deepcopy(method["conditions"])
                    dispersion_name = conditions.pop("legacy_dispersion_name")
                    calibration_id = calibration_ids[dispersion_name]
                    calibration_row = db.execute("SELECT ccd_layout_id FROM dispersion_calibrations WHERE id=?", (calibration_id,)).fetchone()
                    conditions["dispersion_calibration_id"] = calibration_id
                    conditions["ccd_layout_id"] = int(calibration_row[0])
                    payload = {
                        "conditions": conditions,
                        "lines": method["lines"],
                        "legacy_migration": {
                            "run_id": run_id,
                            "source_sha256": mtd_hash,
                            "legacy_method_id": method["legacy_id"],
                            "evidence_sha256": _sha256_json(method["evidence"]),
                        },
                    }
                    canonical, validation_errors = self.methods._validate_payload(payload, db)
                    if validation_errors:
                        raise LegacyMigrationError(
                            "legacy_normalized_method_invalid",
                            f"旧方法“{desired_name}”转换后未通过当前规则校验",
                            details={"legacy_id": method["legacy_id"], "validation_errors": validation_errors},
                        )
                    cursor = db.execute(
                        "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES (?, ?, 'spectral', 'active', 1, ?, ?)",
                        (target_name, method["description"], now, now),
                    )
                    method_id = int(cursor.lastrowid)
                    db.execute(
                        "INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at, created_by) VALUES (?, 1, 'published', ?, '[]', ?, ?)",
                        (method_id, _json(canonical), now, actor_user_id),
                    )
                    imported["methods"].append(method_id)
                    self._record_entity(db, run_id=run_id, source_sha256=mtd_hash, entity_type="method", legacy_key=str(method["legacy_id"]), target_id=method_id, payload=canonical, details={"legacy_name": desired_name, "target_name": target_name, "evidence": method["evidence"]}, now=now)
                    self._after_entity_insert("method", str(method["legacy_id"]))

                cursor = db.execute(
                    "INSERT INTO legacy_configuration_profiles(run_id, name, cfg_source_sha256, opt_source_sha256, cfg_json, opt_json, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (run_id, f"SpecDirect 2.0.2 · {fingerprint[:8]}", sources["cfg"]["sha256"], sources["opt"]["sha256"], _json(staging["configuration"]["cfg"]), _json(staging["configuration"]["opt"]), now),
                )
                imported["configuration_profile_id"] = int(cursor.lastrowid)
                self._record_entity(db, run_id=run_id, source_sha256=fingerprint, entity_type="configuration_profile", legacy_key="DIRECT.CFG+DIRECT.OPT", target_id=imported["configuration_profile_id"], payload=staging["configuration"], details={"active": False}, now=now)
                self._after_entity_insert("configuration_profile", "DIRECT.CFG+DIRECT.OPT")

                report = {
                    "phase": "committed",
                    "counts": staging["counts"],
                    "checks": {**staging["checks"], "sources_unchanged": True, "target_validation_passed": True, "atomic_commit": True, "idempotency_guarded": True},
                    "issues": staging["issues"],
                    "atomic_scope": "source_set",
                    "already_committed": False,
                    "imported": imported,
                }
                db.execute(
                    "UPDATE legacy_migration_runs SET status='committed', report_json=?, error_code=NULL, error_message=NULL, updated_at=?, committed_at=? WHERE id=?",
                    (_json(report), now, now, run_id),
                )
                db.execute(
                    "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'legacy_migration.commit', 'legacy_migration', NULL, ?, ?)",
                    (actor_user_id, _json({"run_id": run_id, "fingerprint": fingerprint, "counts": staging["counts"], "imported": imported}), now),
                )
        except Exception as exc:
            code = exc.code if isinstance(exc, LegacyMigrationError) else "legacy_commit_failed"
            message = exc.message if isinstance(exc, LegacyMigrationError) else str(exc)
            with self.database.write() as db:
                db.execute(
                    "UPDATE legacy_migration_runs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?",
                    (code, message[:1000], utc_now(), run_id),
                )
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError("legacy_commit_failed", "旧方法提交失败，已完整回滚", details={"reason": message}) from exc

        return self.get(run_id, already_committed=False)

    def get(self, run_id: str, *, already_committed: bool | None = None) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM legacy_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("legacy_run_not_found", "迁移任务不存在", status_code=404)
            result = self._run_dict(row)
            result["already_committed"] = bool(already_committed)
            return result

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute("SELECT * FROM legacy_migration_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
            return [self._run_dict(row, include_staging=False) for row in rows]

    _reader_candidates = staticmethod(LegacyAccessReader._reader_candidates)

    def diagnostics(self) -> dict[str, Any]:
        return self.reader.diagnostics()

    def _read_access(self, source: Path, before: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.reader._read_access(source, before)

    _standard_blob = staticmethod(LegacyRecordDecoder._standard_blob)

    _wstc = staticmethod(LegacyRecordDecoder._wstc)

    def _normalize_access(self, access: dict[str, Any], cfg: dict[str, dict[str, str]], opt: dict[str, dict[str, str]], cfg_encoding: str, opt_encoding: str) -> dict[str, Any]:
        return self.normalization._normalize_access(access, cfg, opt, cfg_encoding, opt_encoding)

