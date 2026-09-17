"""旧 Access 方法、谱线与配置的归一化装配。"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any
from ..methods import DEFAULT_CONDITIONS
from .errors import LegacyMigrationError
from .records import _number, _blob
from .configuration import _typed_cfg, _typed_opt
from .records import LegacyRecordDecoder

REQUIRED_TABLES = {"MTD_PRIM", "MTD_BURN", "MTD_WSTC", "LINES", "WSTC", "USER"}


LINE_TYPES = {0: "analysis", 1: "internal_standard", 2: "positioning"}


PEAK_MODES = {0: "max_single_point", 1: "gaussian"}


FIT_MODES = {0: "linear", 1: "quadratic", 2: "cubic", 3: "spline"}


class LegacyNormalizer:
    def __init__(self, records: LegacyRecordDecoder):
        self.records = records

    def _normalize_access(
        self,
        access: dict[str, Any],
        cfg: dict[str, dict[str, str]],
        opt: dict[str, dict[str, str]],
        cfg_encoding: str,
        opt_encoding: str,
    ) -> dict[str, Any]:
        tables = access.get("tables")
        if not isinstance(tables, dict):
            raise LegacyMigrationError("legacy_tables_missing", "旧方法读取结果缺少表集合")
        missing = sorted(REQUIRED_TABLES.difference(tables))
        if missing:
            raise LegacyMigrationError("legacy_tables_missing", "旧方法库缺少必需表", details={"tables": missing})

        table_counts = {name: len(rows) if isinstance(rows, list) else -1 for name, rows in tables.items()}
        prim_rows = tables["MTD_PRIM"]
        burn_by_id = {int(_number(row.get("MtdId"), integer=True)): row for row in tables["MTD_BURN"]}
        method_wstc_by_id = {int(_number(row.get("MtdId"), integer=True)): row for row in tables["MTD_WSTC"]}
        lines_by_id: dict[int, list[dict[str, Any]]] = {}
        for row in tables["LINES"]:
            lines_by_id.setdefault(int(_number(row.get("MtdId"), integer=True)), []).append(row)

        dispersions = [self.records._wstc(row, field=f"WSTC[{index}]") for index, row in enumerate(tables["WSTC"])]
        dispersion_by_name = {item["name"]: item for item in dispersions}
        dispersion_names = set(dispersion_by_name)
        issues: list[dict[str, Any]] = []
        methods: list[dict[str, Any]] = []
        migrated_line_count = 0

        for method_index, primary in enumerate(prim_rows):
            legacy_id = int(_number(primary.get("MtdId"), integer=True))
            burn = burn_by_id.get(legacy_id)
            method_wstc = method_wstc_by_id.get(legacy_id)
            if burn is None or method_wstc is None:
                raise LegacyMigrationError(
                    "legacy_method_reference_missing", "方法、燃烧条件与色散条件无法一一配对", details={"mtd_id": legacy_id}
                )
            dispersion_name = str(method_wstc.get("WsName") or "")
            if dispersion_name not in dispersion_names:
                raise LegacyMigrationError(
                    "legacy_dispersion_reference_missing", "方法引用的色散曲线不在 WSTC 表中", details={"mtd_id": legacy_id, "name": dispersion_name}
                )
            paired_dispersion = dispersion_by_name[dispersion_name]
            scalar_pairs = {
                "FrameCount": "frame_count",
                "CcdsPerFrame": "ccds_per_frame",
                "PointsPerCcd": "points_per_ccd",
                "PointWidth": "point_width",
            }
            for legacy_field, normalized_field in scalar_pairs.items():
                if not math.isclose(
                    float(_number(method_wstc.get(legacy_field))),
                    float(paired_dispersion[normalized_field]),
                    rel_tol=0,
                    abs_tol=1e-6,
                ):
                    raise LegacyMigrationError(
                        "legacy_method_dispersion_mismatch",
                        "方法内嵌色散参数与 WSTC 曲线不一致",
                        details={"mtd_id": legacy_id, "field": legacy_field, "name": dispersion_name},
                    )
            for blob_field in ("CcdGapPoints", "CcdIndexs", "WsCof"):
                embedded = method_wstc.get(blob_field)
                if not isinstance(embedded, dict) or embedded.get("sha256") != paired_dispersion["blob_evidence"][blob_field]["sha256"]:
                    raise LegacyMigrationError(
                        "legacy_method_dispersion_blob_mismatch",
                        "方法内嵌色散 BLOB 与 WSTC 曲线不一致",
                        details={"mtd_id": legacy_id, "field": blob_field, "name": dispersion_name},
                    )
            raw_lines = sorted(lines_by_id.get(legacy_id, []), key=lambda row: int(_number(row.get("Order"), integer=True)))
            line_ids = [f"legacy-{legacy_id}-{index + 1}" for index in range(len(raw_lines))]
            wave_targets = [(float(_number(row.get("Wave"))), line_ids[index], int(_number(row.get("LineType"), integer=True))) for index, row in enumerate(raw_lines)]

            def reference_for(wave: float, allowed: set[int]) -> str | None:
                if math.isclose(wave, 0.0, abs_tol=1e-7):
                    return None
                candidates = [item for item in wave_targets if item[2] in allowed]
                target = min(candidates, key=lambda item: abs(item[0] - wave), default=None)
                return target[1] if target is not None and abs(target[0] - wave) <= 0.01 else None

            normalized_lines: list[dict[str, Any]] = []
            line_evidence: list[dict[str, Any]] = []
            for index, row in enumerate(raw_lines):
                line_type_value = int(_number(row.get("LineType"), integer=True, default=-1))
                if line_type_value not in LINE_TYPES:
                    raise LegacyMigrationError("legacy_line_type_invalid", "旧谱线类型无法识别", details={"mtd_id": legacy_id, "index": index})
                standard_points, standard_evidence = self.records._standard_blob(row.get("Stds"), f"LINES[{legacy_id}:{index}].Stds")
                line_type = LINE_TYPES[line_type_value]
                inter_wave = float(_number(row.get("InterWave")))
                align_wave = float(_number(row.get("AlignWave")))
                internal_reference = reference_for(inter_wave, {1})
                alignment_reference = reference_for(align_wave, {1, 2})
                if not math.isclose(inter_wave, 0.0, abs_tol=1e-7) and internal_reference is None:
                    raise LegacyMigrationError("legacy_line_reference_missing", "旧谱线内标引用无法配对", details={"mtd_id": legacy_id, "wave": inter_wave})
                if not math.isclose(align_wave, 0.0, abs_tol=1e-7) and alignment_reference is None:
                    raise LegacyMigrationError("legacy_line_reference_missing", "旧谱线定位引用无法配对", details={"mtd_id": legacy_id, "wave": align_wave})
                peak_mode = PEAK_MODES.get(int(_number(row.get("PeakMode"), integer=True)), "max_single_point")
                peak_width = int(_number(row.get("PeakWidth"), integer=True, default=1))
                if peak_mode == "max_single_point":
                    peak_width = 1
                line = {
                    "id": line_ids[index],
                    "order": index + 1,
                    "line_type": line_type,
                    "element": str(row.get("Ele") or "?").strip(),
                    "wavelength_nm": float(_number(row.get("Wave"))),
                    "actual_wavelength_nm": float(_number(row.get("RealWave"))),
                    "enabled": True,
                    "critical_band": False,
                    "priority": max(0, min(100, int(_number(row.get("PriLevel"), integer=True)))),
                    "background_line_id": None,
                    "alignment_line_id": alignment_reference,
                    "internal_standard_mode": "line" if line_type == "analysis" and internal_reference else "none",
                    "internal_standard_line_id": internal_reference if line_type == "analysis" else None,
                    "scan_width_points": int(_number(row.get("SeekWidth"), integer=True, default=9)),
                    "background_offset_points": int(_number(row.get("Back"), integer=True)),
                    "peak_mode": peak_mode,
                    "peak_width_points": peak_width,
                    "fit_mode": FIT_MODES.get(int(_number(row.get("FitMode"), integer=True)), "linear"),
                    "coordinate_type": "logarithmic" if int(_number(row.get("CoordType"), integer=True)) > 0 else "normal",
                    "unit": str(primary.get("MtdUnit") or "ug/g"),
                    "value_kind": "content",
                    "decimal_places": int(_number(row.get("Digit"), integer=True, default=2)),
                    "lower_peak": int(_number(row.get("LowPeak"), integer=True, default=300)),
                    "minimum_peak_ratio": float(_number(row.get("LowRatio"), default=1.5)),
                    "valid_range_min": 0.0,
                    "valid_range_max": 9_999_999.0,
                    "over_limit_tolerance_percent": 0.0,
                    "standard_points": standard_points if line_type == "analysis" else [],
                    "reference_baseline": False,
                }
                normalized_lines.append(line)
                line_evidence.append(
                    {
                        "legacy_order": int(_number(row.get("Order"), integer=True)),
                        "legacy_element": row.get("Ele"),
                        "legacy_inter_wave": inter_wave,
                        "legacy_align_wave": align_wave,
                        "normalized_id": line_ids[index],
                        "standards_blob": standard_evidence,
                    }
                )
            migrated_line_count += len(normalized_lines)
            frame_count = int(_number(burn.get("BurnCount"), integer=True, default=20))
            conditions = deepcopy(DEFAULT_CONDITIONS)
            conditions.update(
                {
                    "ccd_layout_id": None,
                    "dispersion_calibration_id": None,
                    "legacy_dispersion_name": dispersion_name,
                    "selected_ccds": list(_blob(method_wstc.get("CcdIndexs"), field=f"MTD_WSTC[{legacy_id}].CcdIndexs")[0]),
                    "reference_wavelength_nm": float(_number(primary.get("RefWave"))),
                    "actual_reference_wavelength_nm": float(_number(primary.get("RealRefWave"))),
                    "reference_width_points": int(_number(primary.get("RefWidth"), integer=True, default=21)),
                    "analysis_unit": str(primary.get("MtdUnit") or "ug/g"),
                    "calculation_profile": "legacy_2_0_2",
                    "pre_excitation_seconds": float(_number(burn.get("PreBurn"), default=3.0)),
                    "sampling_period_seconds": float(_number(burn.get("BurnCyc"), default=1.0)),
                    "frame_count": frame_count,
                    "dark_frame_count": int(_number(burn.get("DarkCount"), integer=True, default=8)),
                    "sample_repeats": int(_number(primary.get("RepOfSam"), integer=True, default=1)),
                    "standard_repeats": int(_number(primary.get("RepOfStd"), integer=True, default=3)),
                    "control_repeats": int(_number(primary.get("RepOfDiag"), integer=True, default=1)),
                    "standard_sample_name": str(primary.get("DefaultSamName") or ""),
                    "maximum_id_deviation": float(_number(primary.get("LimitIda"), default=5.0)),
                    "rsd_enabled": bool(primary.get("CheckRsd")),
                    "rsd_threshold": float(_number(primary.get("LimitRsd"), default=5.0)),
                    "angle_exposures": [{"angle_deg": 0.0, "storage_mode": "averaged", "start_frame": 1, "end_frame": frame_count}],
                    "storage_profile": "legacy_specdirect_202",
                }
            )
            issues.append(
                {
                    "level": "warning",
                    "code": "legacy_angle_exposure_synthesized",
                    "field": f"methods.{legacy_id}.conditions.angle_exposures",
                    "message": "旧方法没有当前模型的转角区间字段，已按完整采样帧范围生成单一区间",
                }
            )
            methods.append(
                {
                    "legacy_id": legacy_id,
                    "name": str(primary.get("MtdName") or f"旧方法 {legacy_id}"),
                    "description": str(primary.get("MtdMemo") or "从 SpecDirect 2.0.2 迁移"),
                    "modified_at": primary.get("ModifyTime"),
                    "conditions": conditions,
                    "lines": normalized_lines,
                    "evidence": {"primary": primary, "burn": burn, "method_wstc": method_wstc, "lines": line_evidence},
                }
            )

        orphan_ids = sorted(set(burn_by_id).union(method_wstc_by_id).union(lines_by_id).difference(int(_number(row.get("MtdId"), integer=True)) for row in prim_rows))
        if orphan_ids:
            raise LegacyMigrationError("legacy_orphan_records", "旧方法表中存在无法配对的孤立记录", details={"mtd_ids": orphan_ids})

        issues.append(
            {
                "level": "warning",
                "code": "legacy_ccd_boundary_compatibility",
                "field": "configuration.opt.CCD.AllowCcdDrift",
                "message": "旧版 AllowCcdDrift 是漂移诊断阈值，不等同于当前谱线边界禁入宽度；原值完整保留在配置快照，迁移布局不附加边界禁入宽度",
            }
        )

        return {
            "format_version": 1,
            "counts": {
                "methods": len(methods),
                "spectral_lines": migrated_line_count,
                "dispersion_curves": len(dispersions),
                "users_ignored": table_counts.get("USER", 0),
            },
            "table_counts": table_counts,
            "methods": methods,
            "dispersions": dispersions,
            "configuration": {
                "cfg": {"encoding": cfg_encoding, "sections": cfg, "normalized": _typed_cfg(cfg)},
                "opt": {"encoding": opt_encoding, "sections": opt, "normalized": _typed_opt(opt)},
            },
            "issues": issues,
            "checks": {
                "required_tables_present": True,
                "method_burn_pairing": len(methods) == len(burn_by_id),
                "method_dispersion_pairing": len(methods) == len(method_wstc_by_id),
                "method_dispersion_blob_pairing": True,
                "line_references_resolved": True,
                "blob_hashes_verified": True,
            },
            "raw_table_counts": table_counts,
        }

