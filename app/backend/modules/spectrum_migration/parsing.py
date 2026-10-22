from __future__ import annotations
import base64
import hashlib
import math
import struct
from pathlib import Path
from typing import Any
from ..legacy_migration import LegacyMigrationError
from .values import FLOAT_BLOB_FIELDS, SUPPORTED_FORMATS, WORD_BLOB_FIELDS


class SpectrumParser:
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
            raise LegacyMigrationError(
                "spectrum_tables_missing", "旧谱文件缺少 CCD_BAND 表", details={"tables": sorted(result)}
            )
        if "LAYOUT" not in result:
            raise LegacyMigrationError(
                "spectrum_tables_missing", "旧谱文件缺少 LAYOUT 表", details={"tables": sorted(result)}
            )
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
                details={
                    "gap_bytes": len(gaps),
                    "expected_gap_bytes": gap_count * 4,
                    "index_bytes": len(indices),
                    "expected_index_bytes": ccd_count,
                    "ws_cof_bytes": len(coefficients),
                    "expected_ws_cof_bytes": 24,
                },
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
            return {
                "present": False,
                "source_table": None,
                "pre_burn": None,
                "burn_cyc": None,
                "dark_cyc": None,
                "burn_count": 0,
                "dark_count": 0,
            }, False
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
            raise LegacyMigrationError(
                "spectrum_array_shape_invalid",
                f"{fmt} 数据 BLOB 长度与布局不一致",
                details={"actual": len(raw), "expected": expected},
            )
        sample_indices = sorted(set(index for index in (0, 1, count // 2, count - 1) if 0 <= index < count))
        type_code = "f" if kind == "float32" else "H"
        sampled = [
            {"index": index, "value": struct.unpack_from(f"<{type_code}", raw, index * width)[0]}
            for index in sample_indices
        ]
        if kind == "float32":
            for (value,) in struct.iter_unpack("<f", raw):
                if not math.isfinite(value):
                    raise LegacyMigrationError("spectrum_array_nonfinite", f"{fmt} 均值数组包含非有限浮点数")
        return {
            "kind": kind,
            "count": count,
            "endianness": "little",
            "first": sampled[0]["value"] if sampled else None,
            "last": struct.unpack_from(f"<{type_code}", raw, (count - 1) * width)[0] if count else None,
            "samples": sampled,
        }

    @classmethod
    def _bad_frames(cls, row: dict[str, Any]) -> list[dict[str, Any]]:
        value = cls._field(row, "ErrIndex", "BadFrameIndex", "BadFrameIndices", "ErrIndexs", default=0)
        if isinstance(value, dict):
            value = cls._number(value, integer=True, default=0)
        if isinstance(value, list):
            values = [int(cls._number(item, integer=True, default=0)) for item in value]
        else:
            values = (
                [int(cls._number(value, integer=True, default=0))]
                if int(cls._number(value, integer=True, default=0)) != 0
                else []
            )
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
            issues.append(
                {
                    "level": "warning",
                    "code": "spectrum_ignition_missing",
                    "message": "文件缺少 MTD_BURN，已保留缺失状态",
                }
            )
        for index, row in enumerate(tables["CCD_BAND"]):
            mean_blob, mean_evidence = cls._blob(
                cls._field(row, "CcdAvgs"), f"CCD_BAND[{index}].CcdAvgs", required=fmt in {"cdt"}
            )
            burn_blob, burn_evidence = cls._blob(
                cls._field(row, "BurnAdcs"), f"CCD_BAND[{index}].BurnAdcs", required=fmt in {"cmt", "edt", "wdt"}
            )
            dark_blob, dark_evidence = cls._blob(
                cls._field(row, "DarkAdcs"), f"CCD_BAND[{index}].DarkAdcs", required=False
            )
            if (
                fmt in {"cmt", "edt", "wdt"}
                and ignition["burn_count"] > 0
                and burn_blob is not None
                and len(burn_blob) != expected_cycle * 2
            ):
                raise LegacyMigrationError(
                    "spectrum_array_shape_invalid",
                    f"CCD_BAND[{index}].BurnAdcs 长度与燃烧帧数不一致",
                    details={"actual": len(burn_blob), "expected": expected_cycle * 2},
                )
            if ignition["dark_count"] > 0 and dark_blob is not None and len(dark_blob) != expected_dark * 2:
                raise LegacyMigrationError(
                    "spectrum_array_shape_invalid",
                    f"CCD_BAND[{index}].DarkAdcs 长度与暗场帧数不一致",
                    details={"actual": len(dark_blob), "expected": expected_dark * 2},
                )
            if fmt in {"cmt", "edt", "wdt"} and ignition["dark_count"] > 0 and dark_blob is None:
                raise LegacyMigrationError("spectrum_blob_missing", f"CCD_BAND[{index}].DarkAdcs 缺失")
            records.append(
                {
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
                        "mean": cls._samples(mean_blob, fmt=fmt, count=expected_mean, kind="float32")
                        if mean_blob is not None
                        else None,
                        "burn": cls._samples(burn_blob, fmt=fmt, count=expected_cycle, kind="uint16")
                        if burn_blob is not None
                        else None,
                        "dark": cls._samples(dark_blob, fmt=fmt, count=expected_dark, kind="uint16")
                        if dark_blob is not None
                        else None,
                    },
                    "details": {
                        "source_fields": sorted(
                            str(key) for key in row if str(key) not in FLOAT_BLOB_FIELDS.union(WORD_BLOB_FIELDS)
                        ),
                        "array_order": "ccd-major, point-minor; cycle-major for raw frames",
                        "angle_deg": (
                            float(
                                cls._number(
                                    cls._field(row, "AngleDeg", "Angle", "TurnAngle", "RotationAngle"), default=0.0
                                )
                            )
                            if cls._field(row, "AngleDeg", "Angle", "TurnAngle", "RotationAngle") is not None
                            else None
                        ),
                    },
                }
            )
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
        return {
            "format": fmt,
            "record_count": len(records),
            "table_counts": {name: len(rows) for name, rows in tables.items()},
            "layout": layout,
            "ignition": ignition,
            "records": public_records,
            "checks": checks,
            "issues": issues,
            "_records": records,
        }
