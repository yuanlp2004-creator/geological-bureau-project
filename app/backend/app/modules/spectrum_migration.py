from __future__ import annotations

import base64
import hashlib
import json
import math
import shutil
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..db import Database, utc_now
from .legacy_migration import LegacyMigrationError, LegacyMigrationService
from .methods import _json


SUPPORTED_FORMATS = {"cdt", "cmt", "edt", "wdt"}
FLOAT_BLOB_FIELDS = {"CcdGapPoints", "WsCof", "CcdAvgs"}
WORD_BLOB_FIELDS = {"BurnAdcs", "DarkAdcs"}


class SpectrumMigrationService:
    """Read-only importer for SpecDirect CCD spectrum Access files."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _number(value: Any, *, integer: bool = False, default: float | int = 0) -> float | int:
        if isinstance(value, dict) and value.get("kind") == "number":
            value = value.get("value")
        if value is None or isinstance(value, bool):
            return default
        try:
            return int(str(value)) if integer else float(str(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sha256(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _blob(cls, value: Any, field: str, *, required: bool = True) -> tuple[bytes | None, dict[str, Any] | None]:
        if value is None and not required:
            return None, None
        if not isinstance(value, dict) or value.get("kind") not in {"blob", "blob_file"}:
            raise LegacyMigrationError("spectrum_blob_missing", f"{field} 不是有效的旧版 BLOB")
        try:
            if value.get("kind") == "blob_file":
                raw = Path(str(value["path"])).read_bytes()
            else:
                raw = base64.b64decode(str(value["base64"]), validate=True)
        except (KeyError, OSError, ValueError, TypeError) as exc:
            raise LegacyMigrationError("spectrum_blob_base64_invalid", f"{field} 的 BLOB 编码无效") from exc
        digest = cls._sha256(raw)
        if int(value.get("byte_length", -1)) != len(raw) or value.get("sha256") != digest:
            raise LegacyMigrationError("spectrum_blob_hash_mismatch", f"{field} 的长度或 SHA-256 校验失败")
        return raw, {"byte_length": len(raw), "sha256": digest}

    @staticmethod
    def _field(row: dict[str, Any], *names: str, default: Any = None) -> Any:
        if not isinstance(row, dict):
            return default
        exact = {str(key): value for key, value in row.items()}
        folded = {str(key).casefold(): value for key, value in row.items()}
        for name in names:
            if name in exact:
                return exact[name]
            if name.casefold() in folded:
                return folded[name.casefold()]
        return default

    @classmethod
    def _tables(cls, access: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        tables = access.get("tables")
        if not isinstance(tables, dict):
            raise LegacyMigrationError("spectrum_tables_missing", "旧谱文件读取结果缺少表集合")
        result: dict[str, list[dict[str, Any]]] = {}
        for name, rows in tables.items():
            if isinstance(rows, list):
                result[str(name).upper()] = [row for row in rows if isinstance(row, dict)]
        if "CCD_BAND" not in result:
            raise LegacyMigrationError("spectrum_tables_missing", "旧谱文件缺少 CCD_BAND 表", details={"tables": sorted(result)})
        if "LAYOUT" not in result:
            raise LegacyMigrationError("spectrum_tables_missing", "旧谱文件缺少 LAYOUT 表", details={"tables": sorted(result)})
        return result

    @classmethod
    def _layout(cls, row: dict[str, Any]) -> dict[str, Any]:
        frame_count = int(cls._number(cls._field(row, "FrameCount"), integer=True, default=0))
        ccds_per_frame = int(cls._number(cls._field(row, "CcdsPerFrame"), integer=True, default=0))
        points_per_ccd = int(cls._number(cls._field(row, "PointsPerCcd"), integer=True, default=0))
        ccd_count = int(cls._number(cls._field(row, "CcdCount"), integer=True, default=0))
        point_width = float(cls._number(cls._field(row, "PointWidth"), default=0.0))
        if not (1 <= frame_count <= 255 and 1 <= ccds_per_frame <= 255 and 1 <= points_per_ccd <= 65535):
            raise LegacyMigrationError("spectrum_layout_invalid", "LAYOUT 的帧数、CCD 数或点数不在旧版范围内")
        if not (1 <= ccd_count <= frame_count * ccds_per_frame <= 255 * 255):
            raise LegacyMigrationError("spectrum_layout_invalid", "LAYOUT 的 CcdCount 无效")
        gap_count = frame_count * ccds_per_frame - 1
        gaps, gap_evidence = cls._blob(cls._field(row, "CcdGapPoints"), "LAYOUT.CcdGapPoints")
        indices, index_evidence = cls._blob(cls._field(row, "CcdIndexs", "CcdIndices"), "LAYOUT.CcdIndexs")
        coefficients, coefficient_evidence = cls._blob(cls._field(row, "WsCof", "WavesCof"), "LAYOUT.WsCof")
        assert gaps is not None and indices is not None and coefficients is not None
        if len(gaps) != gap_count * 4 or len(indices) != ccd_count or len(coefficients) != 24:
            raise LegacyMigrationError(
                "spectrum_layout_shape_invalid",
                "LAYOUT BLOB 长度与帧/CCD 维度不一致",
                details={"gap_bytes": len(gaps), "expected_gap_bytes": gap_count * 4, "index_bytes": len(indices), "expected_index_bytes": ccd_count, "ws_cof_bytes": len(coefficients), "expected_ws_cof_bytes": 24},
            )
        gap_points = list(struct.unpack(f"<{gap_count}f", gaps)) if gap_count else []
        ws_cof = list(struct.unpack("<6f", coefficients))
        if not all(math.isfinite(value) for value in [*gap_points, *ws_cof, point_width]):
            raise LegacyMigrationError("spectrum_layout_nonfinite", "LAYOUT 包含非有限浮点数")
        ccd_indices = list(indices)
        max_index = frame_count * ccds_per_frame
        if len(set(ccd_indices)) != ccd_count or any(index >= max_index for index in ccd_indices):
            raise LegacyMigrationError("spectrum_ccd_mapping_invalid", "LAYOUT 的 CCD 映射包含重复或越界索引")
        return {
            "frame_count": frame_count,
            "ccds_per_frame": ccds_per_frame,
            "points_per_ccd": points_per_ccd,
            "point_width": point_width,
            "ccd_count": ccd_count,
            "ccd_indices": ccd_indices,
            "gap_points": gap_points,
            "ws_cof": ws_cof,
            "endianness": "little",
            "blob_evidence": {"CcdGapPoints": gap_evidence, "CcdIndexs": index_evidence, "WsCof": coefficient_evidence},
        }

    @classmethod
    def _ignition(cls, tables: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], bool]:
        row = next((tables[name][0] for name in ("MTD_BURN", "IGNITION", "BURN") if tables.get(name)), None)
        source_table = next((name for name in ("MTD_BURN", "IGNITION", "BURN") if tables.get(name)), None)
        if row is None and tables.get("LAYOUT"):
            layout_row = tables["LAYOUT"][0]
            if cls._field(layout_row, "BurnCount") is not None or cls._field(layout_row, "DarkCount") is not None:
                row = layout_row
                source_table = "LAYOUT"
        if row is None:
            return {"present": False, "source_table": None, "pre_burn": None, "burn_cyc": None, "dark_cyc": None, "burn_count": 0, "dark_count": 0}, False
        values = {
            "present": True,
            "source_table": source_table,
            "pre_burn": float(cls._number(cls._field(row, "PreBurn"), default=0.0)),
            "burn_cyc": float(cls._number(cls._field(row, "BurnCyc"), default=0.0)),
            "dark_cyc": float(cls._number(cls._field(row, "DarkCyc"), default=0.0)),
            "burn_count": int(cls._number(cls._field(row, "BurnCount"), integer=True, default=0)),
            "dark_count": int(cls._number(cls._field(row, "DarkCount"), integer=True, default=0)),
        }
        if values["burn_count"] < 0 or values["dark_count"] < 0:
            raise LegacyMigrationError("spectrum_ignition_invalid", "激发条件的燃烧/暗场帧数不能为负数")
        return values, True

    @classmethod
    def _samples(cls, raw: bytes | None, *, fmt: str, count: int, kind: str) -> dict[str, Any] | None:
        if raw is None:
            return None
        width = 4 if kind == "float32" else 2
        expected = count * width
        if len(raw) != expected:
            raise LegacyMigrationError("spectrum_array_shape_invalid", f"{fmt} 数据 BLOB 长度与布局不一致", details={"actual": len(raw), "expected": expected})
        sample_indices = sorted(set(index for index in (0, 1, count // 2, count - 1) if 0 <= index < count))
        type_code = "f" if kind == "float32" else "H"
        sampled = [{"index": index, "value": struct.unpack_from(f"<{type_code}", raw, index * width)[0]} for index in sample_indices]
        if kind == "float32":
            for (value,) in struct.iter_unpack("<f", raw):
                if not math.isfinite(value):
                    raise LegacyMigrationError("spectrum_array_nonfinite", f"{fmt} 均值数组包含非有限浮点数")
        return {"kind": kind, "count": count, "endianness": "little", "first": sampled[0]["value"] if sampled else None, "last": struct.unpack_from(f"<{type_code}", raw, (count - 1) * width)[0] if count else None, "samples": sampled}

    @classmethod
    def _bad_frames(cls, row: dict[str, Any]) -> list[dict[str, Any]]:
        value = cls._field(row, "ErrIndex", "BadFrameIndex", "BadFrameIndices", "ErrIndexs", default=0)
        if isinstance(value, dict):
            value = cls._number(value, integer=True, default=0)
        if isinstance(value, list):
            values = [int(cls._number(item, integer=True, default=0)) for item in value]
        else:
            values = [int(cls._number(value, integer=True, default=0))] if int(cls._number(value, integer=True, default=0)) != 0 else []
        result: list[dict[str, Any]] = []
        for legacy_value in values:
            if legacy_value > 0:
                result.append({"phase": "burn", "index": legacy_value - 1, "legacy_value": legacy_value})
            elif legacy_value < 0:
                result.append({"phase": "dark", "index": -legacy_value - 1, "legacy_value": legacy_value})
        return result

    @classmethod
    def _normalize(cls, access: dict[str, Any], fmt: str) -> dict[str, Any]:
        tables = cls._tables(access)
        layout = cls._layout(tables["LAYOUT"][0])
        ignition, ignition_present = cls._ignition(tables)
        expected_mean = layout["ccd_count"] * layout["points_per_ccd"]
        expected_cycle = ignition["burn_count"] * expected_mean
        expected_dark = ignition["dark_count"] * expected_mean
        records: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        if not ignition_present and fmt in {"cmt", "edt", "wdt"}:
            issues.append({"level": "warning", "code": "spectrum_ignition_missing", "message": "文件缺少 MTD_BURN，已保留缺失状态"})
        for index, row in enumerate(tables["CCD_BAND"]):
            mean_blob, mean_evidence = cls._blob(cls._field(row, "CcdAvgs"), f"CCD_BAND[{index}].CcdAvgs", required=fmt in {"cdt"})
            burn_blob, burn_evidence = cls._blob(cls._field(row, "BurnAdcs"), f"CCD_BAND[{index}].BurnAdcs", required=fmt in {"cmt", "edt", "wdt"})
            dark_blob, dark_evidence = cls._blob(cls._field(row, "DarkAdcs"), f"CCD_BAND[{index}].DarkAdcs", required=False)
            if fmt in {"cmt", "edt", "wdt"} and ignition["burn_count"] > 0 and burn_blob is not None and len(burn_blob) != expected_cycle * 2:
                raise LegacyMigrationError("spectrum_array_shape_invalid", f"CCD_BAND[{index}].BurnAdcs 长度与燃烧帧数不一致", details={"actual": len(burn_blob), "expected": expected_cycle * 2})
            if ignition["dark_count"] > 0 and dark_blob is not None and len(dark_blob) != expected_dark * 2:
                raise LegacyMigrationError("spectrum_array_shape_invalid", f"CCD_BAND[{index}].DarkAdcs 长度与暗场帧数不一致", details={"actual": len(dark_blob), "expected": expected_dark * 2})
            if fmt in {"cmt", "edt", "wdt"} and ignition["dark_count"] > 0 and dark_blob is None:
                raise LegacyMigrationError("spectrum_blob_missing", f"CCD_BAND[{index}].DarkAdcs 缺失")
            records.append({
                "record_index": index,
                "band_id": int(cls._number(cls._field(row, "BandId"), integer=True, default=index + 1)),
                "sample_no": int(cls._number(cls._field(row, "SampNo"), integer=True, default=0)),
                "sample_name": str(cls._field(row, "SampName", default="") or ""),
                "band_name": str(cls._field(row, "BandName", "LongName", default="") or ""),
                "long_name": str(cls._field(row, "LongName", default="") or ""),
                "measure_time": cls._field(row, "MeasureTime"),
                "real_ref_step": float(cls._number(cls._field(row, "RealRefStep"), default=0.0)),
                "layout": layout,
                "ignition": ignition,
                "bad_frame_indices": cls._bad_frames(row),
                "mean_blob": mean_blob,
                "burn_adcs_blob": burn_blob,
                "dark_adcs_blob": dark_blob,
                "mean_sha256": mean_evidence["sha256"] if mean_evidence else None,
                "burn_sha256": burn_evidence["sha256"] if burn_evidence else None,
                "dark_sha256": dark_evidence["sha256"] if dark_evidence else None,
                "sampled_values": {
                    "mean": cls._samples(mean_blob, fmt=fmt, count=expected_mean, kind="float32") if mean_blob is not None else None,
                    "burn": cls._samples(burn_blob, fmt=fmt, count=expected_cycle, kind="uint16") if burn_blob is not None else None,
                    "dark": cls._samples(dark_blob, fmt=fmt, count=expected_dark, kind="uint16") if dark_blob is not None else None,
                },
                "details": {
                    "source_fields": sorted(str(key) for key in row if str(key) not in FLOAT_BLOB_FIELDS.union(WORD_BLOB_FIELDS)),
                    "array_order": "ccd-major, point-minor; cycle-major for raw frames",
                    "angle_deg": (
                        float(cls._number(cls._field(row, "AngleDeg", "Angle", "TurnAngle", "RotationAngle"), default=0.0))
                        if cls._field(row, "AngleDeg", "Angle", "TurnAngle", "RotationAngle") is not None
                        else None
                    ),
                },
            })
        if not records:
            issues.append({"level": "warning", "code": "spectrum_no_records", "message": "CCD_BAND 表没有记录"})
        checks = {
            "format_supported": fmt in SUPPORTED_FORMATS,
            "required_tables_present": True,
            "record_shapes_valid": True,
            "little_endian_decoded": True,
            "ccd_mapping_valid": True,
            "source_unchanged": True,
            "bad_frames_marked_without_replacement": True,
            "hashes_verified": True,
        }
        public_records = [{key: value for key, value in item.items() if not key.endswith("_blob")} for item in records]
        return {"format": fmt, "record_count": len(records), "table_counts": {name: len(rows) for name, rows in tables.items()}, "layout": layout, "ignition": ignition, "records": public_records, "checks": checks, "issues": issues, "_records": records}

    @staticmethod
    def _run_dict(row: Any, *, include_staging: bool = True) -> dict[str, Any]:
        result = {
            "id": row["id"], "fingerprint": row["fingerprint"], "format": row["format"], "status": row["status"],
            "source_file": json.loads(row["source_json"]), "reader": json.loads(row["reader_json"]), "report": json.loads(row["report_json"]),
            "error": {"code": row["error_code"], "message": row["error_message"]} if row["error_code"] else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"], "committed_at": row["committed_at"],
        }
        if include_staging:
            result["staging"] = json.loads(row["staging_json"])
        return result

    def diagnostics(self) -> dict[str, Any]:
        diagnostic = LegacyMigrationService(self.database).diagnostics()
        return {**diagnostic, "formats": sorted(SUPPORTED_FORMATS), "layout_tables": ["LAYOUT", "CCD_BAND"], "read_only": True, "streaming_blobs": True, "parser_version": "s08-spectrum-2"}

    def _read_access(self, source: Path, before: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        legacy = LegacyMigrationService(self.database)
        diagnostic = legacy.diagnostics()
        if not diagnostic["available"]:
            raise LegacyMigrationError("legacy_reader_unavailable", diagnostic["message"], status_code=503, details=diagnostic)
        candidate = next((item for item in legacy._reader_candidates() if item[0] == "windows-powershell-x86"), None)
        if candidate is None:
            raise LegacyMigrationError(
                "spectrum_streaming_reader_unavailable",
                "未找到支持分块 BLOB 输出的 32 位 Jet 读取器",
                status_code=503,
                details=diagnostic,
            )

        bundle = Path(tempfile.mkdtemp(prefix="geospectrum-s08-"))
        copied = bundle / source.name
        output = bundle / "reader-output"
        output.mkdir()
        timeout_seconds = max(120, min(540, int(before["size"] / (1024 * 1024) * 1.5) + 120))
        try:
            shutil.copy2(source, copied)
            command = [*candidate[1], "-Path", str(copied), "-OutputDirectory", str(output)]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=timeout_seconds, check=False)
            if result.returncode != 0:
                raise LegacyMigrationError(
                    "legacy_reader_failed",
                    "Jet 无法分块读取旧谱文件临时副本",
                    details={"exit_code": result.returncode, "stderr": result.stderr.strip()[-1000:]},
                )
            try:
                manifest = json.loads(result.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError) as exc:
                raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱读取器返回了无效 JSON") from exc
            if manifest.get("format_version") != 2:
                raise LegacyMigrationError("legacy_reader_version_invalid", "旧谱分块读取器输出版本不兼容")

            tables: dict[str, list[dict[str, Any]]] = {}
            rows_path = (output / str(manifest.get("rows_file", ""))).resolve()
            if output.resolve() not in rows_path.parents or not rows_path.is_file():
                raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱分块读取器缺少行清单")
            with rows_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱分块读取器行清单无效", details={"line": line_number}) from exc
                    table = str(record.get("table", ""))
                    values = record.get("values")
                    if not table or not isinstance(values, dict):
                        raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱分块读取器行清单字段无效", details={"line": line_number})
                    for value in values.values():
                        if isinstance(value, dict) and value.get("kind") == "blob_file":
                            blob_path = (output / str(value.get("file", ""))).resolve()
                            if output.resolve() not in blob_path.parents or not blob_path.is_file():
                                raise LegacyMigrationError("legacy_reader_output_invalid", "旧谱分块读取器 BLOB 文件无效", details={"line": line_number})
                            value["path"] = str(blob_path)
                    tables.setdefault(table, []).append(values)
            payload = {
                "format_version": 2,
                "provider": manifest.get("provider"),
                "mode": manifest.get("mode"),
                "file": manifest.get("file"),
                "tables": tables,
                "_streaming_bundle": str(bundle),
            }
            return payload, {**diagnostic, "reader": candidate[0], "streaming_blobs": True, "timeout_seconds": timeout_seconds}
        except Exception:
            shutil.rmtree(bundle, ignore_errors=True)
            raise

    def _stage_streaming(
        self,
        access: dict[str, Any],
        reader: dict[str, Any],
        source: dict[str, Any],
        fmt: str,
        actor_user_id: int,
        existing: Any,
    ) -> dict[str, Any]:
        tables = self._tables(access)
        layout = self._layout(tables["LAYOUT"][0])
        ignition, _ = self._ignition(tables)
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
                empty_staging = {"format": fmt, "record_count": 0, "table_counts": table_counts, "layout": layout, "ignition": ignition, "records": [], "checks": checks, "issues": [], "source_unchanged": True, "parser_version": "s08-spectrum-2"}
                empty_report = {"phase": "staged", "format": fmt, "record_count": 0, "table_counts": table_counts, "checks": checks, "issues": [], "atomic_scope": "single_source_file", "already_committed": False}
                db.execute(
                    "INSERT INTO spectrum_migration_runs(id, fingerprint, format, status, source_json, reader_json, staging_json, report_json, created_by, created_at, updated_at) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(fingerprint) DO UPDATE SET id=excluded.id, format=excluded.format, status='staged', source_json=excluded.source_json, reader_json=excluded.reader_json, staging_json=excluded.staging_json, report_json=excluded.report_json, error_code=NULL, error_message=NULL, created_by=excluded.created_by, updated_at=excluded.updated_at, committed_at=NULL",
                    (run_id, fingerprint, fmt, _json(source), _json(reader), _json(empty_staging), _json(empty_report), actor_user_id, now, now),
                )
                db.execute("DELETE FROM spectrum_migration_staging_records WHERE run_id=?", (run_id,))
                for index, source_row in enumerate(tables["CCD_BAND"]):
                    one_tables = {**tables, "CCD_BAND": [source_row]}
                    normalized = self._normalize({"tables": one_tables}, fmt)
                    item = normalized["_records"][0]
                    item["record_index"] = index
                    if self._field(source_row, "BandId") is None:
                        item["band_id"] = index + 1
                    public_item = {key: value for key, value in item.items() if not key.endswith("_blob")}
                    public_records.append(public_item)
                    if not issues:
                        issues = normalized["issues"]
                    db.execute(
                        "INSERT INTO spectrum_migration_staging_records(run_id, record_index, band_id, sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, burn_sha256, dark_sha256, sampled_values_json, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, item["record_index"], item["band_id"], item["sample_no"], item["sample_name"], item["band_name"], item["long_name"], item["measure_time"], item["real_ref_step"], layout["frame_count"], layout["ccds_per_frame"], layout["points_per_ccd"], layout["ccd_count"], _json(layout["ccd_indices"]), _json(layout), _json(ignition), _json(item["bad_frame_indices"]), item["mean_blob"], item["burn_adcs_blob"], item["dark_adcs_blob"], item["mean_sha256"], item["burn_sha256"], item["dark_sha256"], _json(item["sampled_values"]), _json(item["details"])),
                    )
                if not public_records:
                    issues.append({"level": "warning", "code": "spectrum_no_records", "message": "CCD_BAND 表没有记录"})
                public_staging = {"format": fmt, "record_count": len(public_records), "table_counts": table_counts, "layout": layout, "ignition": ignition, "records": public_records, "checks": checks, "issues": issues, "source_unchanged": True, "parser_version": "s08-spectrum-2"}
                report = {"phase": "staged", "format": fmt, "record_count": len(public_records), "table_counts": table_counts, "checks": checks, "issues": issues, "atomic_scope": "single_source_file", "already_committed": False}
                db.execute("UPDATE spectrum_migration_runs SET staging_json=?, report_json=?, updated_at=? WHERE id=?", (_json(public_staging), _json(report), now, run_id))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum_migration.stage', 'spectrum_migration', NULL, ?, ?)", (actor_user_id, _json({"run_id": run_id, "source_sha256": fingerprint, "format": fmt, "record_count": len(public_records), "streaming_blobs": True}), now))
                row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
                return {**self._run_dict(row), "already_committed": False}
        except Exception as exc:
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError("spectrum_stage_failed", "谱文件分块暂存失败", details={"reason": str(exc)}) from exc

    def stage(self, path_value: str, actor_user_id: int) -> dict[str, Any]:
        path = Path(path_value).expanduser()
        fmt = path.suffix.lower().lstrip(".")
        if fmt not in SUPPORTED_FORMATS:
            raise LegacyMigrationError("spectrum_source_extension_invalid", "谱文件扩展名必须是 .cdt、.cmt、.edt 或 .wdt")
        source = self._source_snapshot(path)
        fingerprint = source["sha256"]
        with self.database.read() as db:
            existing = db.execute("SELECT * FROM spectrum_migration_runs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing is not None and existing["status"] == "committed":
                result = self._run_dict(existing)
                result["already_committed"] = True
                return result
        access, reader = self._read_access(path, source)
        bundle_value = access.get("_streaming_bundle")
        try:
            after = self._source_snapshot(path)
            if source != after:
                raise LegacyMigrationError("spectrum_source_changed", "只读解析期间谱文件发生变化，已中止")
            if bundle_value:
                return self._stage_streaming(access, reader, source, fmt, actor_user_id, existing)
            normalized = self._normalize(access, fmt)
            normalized["source_unchanged"] = True
            public_staging = {key: value for key, value in normalized.items() if key != "_records"}
            public_staging["parser_version"] = "s08-spectrum-2"
            report = {"phase": "staged", "format": fmt, "record_count": normalized["record_count"], "table_counts": normalized["table_counts"], "checks": normalized["checks"], "issues": normalized["issues"], "atomic_scope": "single_source_file", "already_committed": False}
            now = utc_now()
            run_id = existing["id"] if existing is not None else str(uuid.uuid4())
            try:
                with self.database.write() as db:
                    db.execute(
                        "INSERT INTO spectrum_migration_runs(id, fingerprint, format, status, source_json, reader_json, staging_json, report_json, created_by, created_at, updated_at) VALUES (?, ?, ?, 'staged', ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(fingerprint) DO UPDATE SET id=excluded.id, format=excluded.format, status='staged', source_json=excluded.source_json, reader_json=excluded.reader_json, staging_json=excluded.staging_json, report_json=excluded.report_json, error_code=NULL, error_message=NULL, created_by=excluded.created_by, updated_at=excluded.updated_at, committed_at=NULL",
                        (run_id, fingerprint, fmt, _json(source), _json(reader), _json(public_staging), _json(report), actor_user_id, now, now),
                    )
                    db.execute("DELETE FROM spectrum_migration_staging_records WHERE run_id=?", (run_id,))
                    for item in normalized["_records"]:
                        db.execute(
                            "INSERT INTO spectrum_migration_staging_records(run_id, record_index, band_id, sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, burn_sha256, dark_sha256, sampled_values_json, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (run_id, item["record_index"], item["band_id"], item["sample_no"], item["sample_name"], item["band_name"], item["long_name"], item["measure_time"], item["real_ref_step"], normalized["layout"]["frame_count"], normalized["layout"]["ccds_per_frame"], normalized["layout"]["points_per_ccd"], normalized["layout"]["ccd_count"], _json(normalized["layout"]["ccd_indices"]), _json(normalized["layout"]), _json(normalized["ignition"]), _json(item["bad_frame_indices"]), item["mean_blob"], item["burn_adcs_blob"], item["dark_adcs_blob"], item["mean_sha256"], item["burn_sha256"], item["dark_sha256"], _json(item["sampled_values"]), _json(item["details"])),
                        )
                    db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum_migration.stage', 'spectrum_migration', NULL, ?, ?)", (actor_user_id, _json({"run_id": run_id, "source_sha256": fingerprint, "format": fmt, "record_count": normalized["record_count"]}), now))
                    row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
                    return {**self._run_dict(row), "already_committed": False}
            except Exception as exc:
                if isinstance(exc, LegacyMigrationError):
                    raise
                raise LegacyMigrationError("spectrum_stage_failed", "谱文件暂存失败", details={"reason": str(exc)}) from exc
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
            raise LegacyMigrationError("spectrum_source_unreadable", f"无法读取谱文件：{path}", details={"reason": str(exc)}) from exc
        return {"path": str(path.resolve()), "name": path.name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}

    def commit(self, run_id: str, actor_user_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("spectrum_run_not_found", "谱迁移任务不存在", status_code=404)
            if row["status"] == "committed":
                result = self._run_dict(row)
                result["already_committed"] = True
                return result
            source = json.loads(row["source_json"])
            staging = json.loads(row["staging_json"])
            fingerprint = row["fingerprint"]
        current = self._source_snapshot(Path(source["path"]))
        if current != source:
            raise LegacyMigrationError("spectrum_source_changed_since_stage", "源文件在暂存后发生变化，请重新暂存", details={"before": source, "current": current})
        now = utc_now()
        try:
            with self.database.write() as db:
                if db.execute("SELECT 1 FROM spectrum_bands WHERE source_sha256=? LIMIT 1", (fingerprint,)).fetchone():
                    raise LegacyMigrationError("spectrum_source_already_imported", "该谱文件已由其他迁移任务提交", status_code=409)
                record_count = int(db.execute("SELECT COUNT(*) FROM spectrum_migration_staging_records WHERE run_id=?", (run_id,)).fetchone()[0])
                db.execute(
                    "INSERT INTO spectrum_bands(import_run_id, source_sha256, record_index, format, band_id, sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, burn_sha256, dark_sha256, sampled_values_json, details_json) "
                    "SELECT run_id, ?, record_index, ?, band_id, sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, burn_sha256, dark_sha256, sampled_values_json, details_json FROM spectrum_migration_staging_records WHERE run_id=? ORDER BY record_index",
                    (fingerprint, row["format"], run_id),
                )
                report = {**json.loads(row["report_json"]), "phase": "committed", "checks": {**json.loads(row["report_json"])["checks"], "source_unchanged": True, "atomic_commit": True, "idempotency_guarded": True}, "already_committed": False, "imported": {"spectrum_bands": record_count}}
                db.execute("UPDATE spectrum_migration_runs SET status='committed', report_json=?, error_code=NULL, error_message=NULL, updated_at=?, committed_at=? WHERE id=?", (_json(report), now, now, run_id))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum_migration.commit', 'spectrum_migration', NULL, ?, ?)", (actor_user_id, _json({"run_id": run_id, "source_sha256": fingerprint, "record_count": record_count}), now))
        except Exception as exc:
            code = exc.code if isinstance(exc, LegacyMigrationError) else "spectrum_commit_failed"
            message = exc.message if isinstance(exc, LegacyMigrationError) else str(exc)
            with self.database.write() as db:
                db.execute("UPDATE spectrum_migration_runs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?", (code, message[:1000], utc_now(), run_id))
            if isinstance(exc, LegacyMigrationError):
                raise
            raise LegacyMigrationError("spectrum_commit_failed", "谱文件提交失败，已完整回滚", details={"reason": message}) from exc
        return self.get(run_id, already_committed=False)

    def get(self, run_id: str, *, already_committed: bool | None = None) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM spectrum_migration_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise LegacyMigrationError("spectrum_run_not_found", "谱迁移任务不存在", status_code=404)
            result = self._run_dict(row)
            result["already_committed"] = bool(already_committed)
            return result

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute("SELECT * FROM spectrum_migration_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)).fetchall()
            return [self._run_dict(row, include_staging=False) for row in rows]
