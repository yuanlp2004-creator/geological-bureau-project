"""方法条件校验，复用调用方数据库连接。"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any
from ...db import Database
from .geometry import MethodGeometry
from .repository import MethodRepository

class MethodValidator:
    def __init__(self, database: Database, repository: MethodRepository, geometry: MethodGeometry):
        self.database = database
        self.repository = repository
        self.geometry = geometry

    @staticmethod
    def _issue(field: str, code: str, message: str) -> dict[str, str]:
        return {"field": field, "code": code, "message": message}

    def validate_conditions(
        self, conditions: dict[str, Any], db: sqlite3.Connection | None = None
    ) -> list[dict[str, str]]:
        if db is None:
            with self.database.read() as connection:
                return self.validate_conditions(conditions, connection)

        errors: list[dict[str, str]] = []

        def add(field: str, code: str, message: str) -> None:
            errors.append(self._issue(field, code, message))

        def number(
            field: str,
            minimum: float | None = None,
            maximum: float | None = None,
            *,
            integer: bool = False,
        ) -> float | None:
            value = conditions.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                add(field, "number_required", "必须是有限数字")
                return None
            numeric = float(value)
            if integer and not numeric.is_integer():
                add(field, "integer_required", "必须是整数")
            if minimum is not None and numeric < minimum:
                add(field, "below_minimum", f"不能小于 {minimum:g}")
            if maximum is not None and numeric > maximum:
                add(field, "above_maximum", f"不能大于 {maximum:g}")
            return numeric

        layout_reference = conditions.get("ccd_layout_id", "default")
        layout = self.repository._layout(db, layout_reference)
        if layout is None:
            add("ccd_layout_id", "ccd_layout_not_found", "未找到 CCD 布局")

        selected = conditions.get("selected_ccds")
        selected_ccds: list[int] = []
        if not isinstance(selected, list) or not selected:
            add("selected_ccds", "ccd_selection_required", "至少选择一个 CCD")
        elif any(isinstance(value, bool) or not isinstance(value, int) for value in selected):
            add("selected_ccds", "ccd_selection_invalid", "CCD 编号必须是整数")
        else:
            selected_ccds = [int(value) for value in selected]
            if len(selected_ccds) != len(set(selected_ccds)):
                add("selected_ccds", "ccd_selection_duplicate", "CCD 不能重复选择")
            if layout is not None:
                available = {int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")}
                if not set(selected_ccds).issubset(available):
                    add("selected_ccds", "ccd_not_installed", "选择中包含未安装的 CCD")

        dispersion_reference = conditions.get("dispersion_calibration_id", "default")
        dispersion = self.repository._dispersion(db, dispersion_reference)
        if dispersion is None:
            add("dispersion_calibration_id", "dispersion_not_found", "未找到已启用的色散引用")
        elif layout is not None and int(dispersion["ccd_layout_id"]) != int(layout["id"]):
            add(
                "dispersion_calibration_id",
                "dispersion_layout_mismatch",
                "色散引用与 CCD 布局不匹配",
            )

        reference = number("reference_wavelength_nm", 160, 800)
        actual = number("actual_reference_wavelength_nm", 160, 800)
        if reference is not None and actual is not None and abs(actual - reference) > 0.3:
            add(
                "actual_reference_wavelength_nm",
                "reference_offset_too_large",
                "实际参考波长与理论值的偏差不能大于 0.3 nm",
            )
        if layout is not None and dispersion is not None and int(dispersion["ccd_layout_id"]) == int(layout["id"]):
            reference_positions: dict[str, tuple[int, float, bool] | None] = {}
            for field, wave in (
                ("reference_wavelength_nm", reference),
                ("actual_reference_wavelength_nm", actual),
            ):
                if wave is None:
                    continue
                position = self.geometry._reference_position(wave, layout, dispersion)
                reference_positions[field] = position
                if position is None:
                    add(field, "reference_not_on_ccd", "参考波长不在当前 CCD/色散覆盖范围内")
                elif position[0] not in selected_ccds:
                    add(field, "reference_ccd_not_selected", f"参考波长位于 CCD{position[0] + 1}，但该 CCD 未选中")
                elif not position[2]:
                    add(field, "reference_outside_safe_boundary", "参考波长超出 CCD 安全边界")
            theoretical = reference_positions.get("reference_wavelength_nm")
            measured = reference_positions.get("actual_reference_wavelength_nm")
            if theoretical and measured and theoretical[0] != measured[0]:
                add(
                    "actual_reference_wavelength_nm",
                    "reference_ccd_changed",
                    "理论与实际参考波长必须位于同一 CCD",
                )

        number("reference_width_points", 11, 50, integer=True)
        if conditions.get("analysis_unit") not in {"ug/g", "mg/g", "%"}:
            add("analysis_unit", "analysis_unit_invalid", "分析单位只能是 ug/g、mg/g 或 %")
        if conditions.get("calculation_profile") not in {"legacy_2_0_2", "modern_v1"}:
            add("calculation_profile", "calculation_profile_invalid", "计算档案只能是 legacy_2_0_2 或 modern_v1")
        number("pre_excitation_seconds", 1, 10)
        number("sampling_period_seconds", 1, 2)
        frame_count = number("frame_count", 1, 255, integer=True)
        number("dark_frame_count", 0, 20, integer=True)
        for field in ("sample_repeats", "standard_repeats", "control_repeats"):
            number(field, 1, 10, integer=True)
        number("maximum_id_deviation", 0, 20)
        if not isinstance(conditions.get("rsd_enabled"), bool):
            add("rsd_enabled", "boolean_required", "必须是布尔值")
        number("rsd_threshold", 0, 20)
        for field in ("calibration_threshold", "qc_threshold", "abnormal_threshold"):
            number(field, 0, 100)
        sample_name = conditions.get("standard_sample_name")
        if not isinstance(sample_name, str) or len(sample_name) > 100:
            add("standard_sample_name", "standard_sample_invalid", "标准样品名称不能超过 100 个字符")

        exposures = conditions.get("angle_exposures")
        if not isinstance(exposures, list) or not exposures:
            add("angle_exposures", "angle_exposure_required", "至少配置一个转角曝光区间")
        else:
            seen_angles: set[float] = set()
            for index, exposure in enumerate(exposures):
                prefix = f"angle_exposures.{index}"
                if not isinstance(exposure, dict):
                    add(prefix, "angle_exposure_invalid", "转角曝光配置必须是对象")
                    continue
                angle = exposure.get("angle_deg")
                if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(float(angle)):
                    add(f"{prefix}.angle_deg", "angle_invalid", "转角必须是有限数字")
                elif not 0 <= float(angle) <= 360:
                    add(f"{prefix}.angle_deg", "angle_out_of_range", "转角必须在 0–360° 范围内")
                elif float(angle) in seen_angles:
                    add(f"{prefix}.angle_deg", "angle_duplicate", "同一转角只能配置一次")
                else:
                    seen_angles.add(float(angle))
                if exposure.get("storage_mode") not in {"averaged", "full_interval"}:
                    add(
                        f"{prefix}.storage_mode",
                        "storage_mode_invalid",
                        "保存方式只能是区间平均或全区间保存",
                    )
                start = exposure.get("start_frame")
                end = exposure.get("end_frame")
                if isinstance(start, bool) or not isinstance(start, int):
                    add(f"{prefix}.start_frame", "integer_required", "起始帧必须是整数")
                if isinstance(end, bool) or not isinstance(end, int):
                    add(f"{prefix}.end_frame", "integer_required", "结束帧必须是整数")
                if isinstance(start, int) and not isinstance(start, bool) and isinstance(end, int) and not isinstance(end, bool):
                    if start < 1:
                        add(f"{prefix}.start_frame", "frame_out_of_range", "起始帧不能小于 1")
                    if frame_count is not None and end > int(frame_count):
                        add(f"{prefix}.end_frame", "frame_out_of_range", "结束帧不能超过采样帧数")
                    if end - start + 1 < 2:
                        add(prefix, "exposure_too_short", "曝光区间必须至少包含两帧")
        return errors

