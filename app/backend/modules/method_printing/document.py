"""方法文档行、纸张、页边距和分页。"""

from __future__ import annotations

from typing import Any
from .settings import PrintSettings
from ..methods.errors import MethodDomainError


from ...printing.paper import PAPER_MM, paper_mm


CONDITION_LABELS = (
    ("ccd_layout_id", "CCD 布局"),
    ("selected_ccds", "启用 CCD"),
    ("dispersion_calibration_id", "色散曲线"),
    ("reference_wavelength_nm", "基线波长"),
    ("actual_reference_wavelength_nm", "实际基线波长"),
    ("reference_width_points", "扫描宽度"),
    ("analysis_unit", "分析单位"),
    ("pre_excitation_seconds", "预激时间"),
    ("sampling_period_seconds", "采样周期"),
    ("frame_count", "采样次数"),
    ("dark_frame_count", "空白次数"),
    ("sample_repeats", "普通样品重复次数"),
    ("standard_repeats", "标准样品重复次数"),
    ("control_repeats", "管理样重复次数"),
    ("standard_sample_name", "标准样品"),
    ("maximum_id_deviation", "重复摄谱最大允许误差[^P]"),
    ("rsd_enabled", "相对偏差校验"),
    ("rsd_threshold", "最大允许Rsd[%]"),
    ("calibration_threshold", "校准阈值"),
    ("qc_threshold", "质控阈值"),
    ("abnormal_threshold", "异常阈值"),
)


LINE_TYPE_LABELS = {
    "baseline": "参考基线",
    "analysis": "分析线",
    "internal_standard": "内标线",
    "positioning": "定位线",
}


PEAK_LABELS = {"max_single_point": "最大值", "gaussian": "高斯曲线"}


FIT_LABELS = {"linear": "直线函数", "quadratic": "二次曲线", "cubic": "三次曲线", "spline": "样条函数"}


COORDINATE_LABELS = {"normal": "普通坐标", "logarithmic": "对数坐标"}


INTERNAL_LABELS = {"none": "无内标", "background": "背景做内标", "line": "内标线"}


def _display(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_display(item) for item in value)
    return str(value)


def _weighted_length(value: str) -> int:
    return sum(1 if ord(char) < 128 else 2 for char in value)


def _wrap(value: str, limit: int) -> list[str]:
    text = value or "-"
    result: list[str] = []
    current = ""
    units = 0
    for char in text:
        if char == "\n":
            result.append(current or " ")
            current, units = "", 0
            continue
        weight = 1 if ord(char) < 128 else 2
        if current and units + weight > limit:
            result.append(current)
            current, units = char, weight
        else:
            current += char
            units += weight
    if current or not result:
        result.append(current or " ")
    return result


class MethodDocument:
    @staticmethod
    def _validate_geometry(settings: PrintSettings) -> None:
        width, height = paper_mm(settings.paper)
        if settings.orientation == "landscape":
            width, height = height, width
        if settings.margin_left_mm + settings.margin_right_mm > width - 80:
            raise MethodDomainError(
                "print_margin_width_invalid",
                "左右边距过大，可打印宽度不足",
                fields=["margin_left_mm", "margin_right_mm"],
            )
        if settings.margin_top_mm + settings.margin_bottom_mm > height - 100:
            raise MethodDomainError(
                "print_margin_height_invalid",
                "上下边距过大，可打印高度不足",
                fields=["margin_top_mm", "margin_bottom_mm"],
            )

    @staticmethod
    def _row(kind: str, label: str, value: str = "") -> dict[str, str]:
        return {"kind": kind, "label": label, "value": value}

    def _document_rows(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        method = snapshot["method"]
        version = snapshot["version"]
        conditions = version["conditions"]
        lines = version["lines"]
        rows = [
            self._row("section", "方法概要"),
            self._row("item", "方法名称", method["name"]),
            self._row("item", "版本", f"v{version['version']} / {version['state']}"),
            self._row("item", "说明", method["description"] or "-"),
            self._row("item", "内容 SHA-256", version["content_sha256"]),
            self._row("item", "版本创建时间", str(version["created_at"])),
            self._row("section", "方法条件"),
        ]
        suffixes = {
            "reference_wavelength_nm": " nm",
            "actual_reference_wavelength_nm": " nm",
            "reference_width_points": " 点",
            "pre_excitation_seconds": " s",
            "sampling_period_seconds": " s",
            "maximum_id_deviation": "",
            "rsd_threshold": " %",
            "calibration_threshold": " %",
            "qc_threshold": " %",
            "abnormal_threshold": " %",
        }
        compatibility_keys = {"standard_sample_name", "calibration_threshold", "qc_threshold", "abnormal_threshold"}
        compatibility_rows = [self._row("item", "工作类型", method["work_type"])]
        for key, label in CONDITION_LABELS:
            target = compatibility_rows if key in compatibility_keys else rows
            target.append(self._row("item", label, _display(conditions.get(key)) + suffixes.get(key, "")))
        from ..spectral_lines import exposure_interval, method_exposure_mode
        mode = method_exposure_mode(conditions, lines)
        rows.append(self._row('item', '曝光模式', '区间曝光' if mode == 'line_interval' else '简单均值'))
        rows.append(self._row("section", "转角与存储方式"))
        for index, exposure in enumerate(conditions.get("angle_exposures", []), start=1):
            rows.append(
                self._row(
                    "item",
                    f"角度 {index}",
                    f"{_display(exposure.get('angle_deg'))}° / {exposure.get('storage_mode')} / "
                    f"帧 {exposure.get('start_frame')}-{exposure.get('end_frame')}",
                )
            )
        by_id = {
            line.get("id"): f"{line.get('element')} {float(line.get('wavelength_nm', 0)):.4f} nm" for line in lines
        }
        rows.append(self._row("section", f"分析谱线（{len(lines)} 条）"))
        for index, line in enumerate(lines, start=1):
            references = []
            interval = exposure_interval(line, conditions)
            if interval is not None:
                references.append(f'曝光帧={interval[0]}-{interval[1]}')
            for label, key in (
                ("定位谱线", "alignment_line_id"),
            ):
                if line.get(key):
                    references.append(f"{label}={by_id.get(line[key], line[key])}")
            if not line.get("alignment_line_id"):
                references.append("定位谱线=参考线定位")
            internal = (by_id.get(line.get("internal_standard_line_id"), line.get("internal_standard_line_id"))
                        if line.get("internal_standard_mode") == "line"
                        else INTERNAL_LABELS.get(line.get("internal_standard_mode"), line.get("internal_standard_mode")))
            value = (
                f"{LINE_TYPE_LABELS.get(line.get('line_type'), line.get('line_type'))}; "
                f"实际 {float(line.get('actual_wavelength_nm', line.get('wavelength_nm', 0))):.4f} nm; "
                f"启用={_display(line.get('enabled'))}; 关键={_display(line.get('critical_band'))}; "
                f"扫描点数={line.get('scan_width_points')}; 背景位置={line.get('background_offset_points')}点; "
                f"峰值方式={PEAK_LABELS.get(line.get('peak_mode'), line.get('peak_mode'))}; 计算点数={line.get('peak_width_points')}; "
                f"拟合方式={FIT_LABELS.get(line.get('fit_mode'), line.get('fit_mode'))}/{COORDINATE_LABELS.get(line.get('coordinate_type'), line.get('coordinate_type'))}; "
                f"内标谱线={internal}; 单位={line.get('unit')}; 小数位数={line.get('decimal_places')}; "
                f"最低峰值={line.get('lower_peak')}; 最小倍数={line.get('minimum_peak_ratio')}; "
                f"有效范围={line.get('valid_range_min')}-{line.get('valid_range_max')}"
            )
            if references:
                value += "; " + "; ".join(references)
            rows.append(
                self._row(
                    "item",
                    f"{index}. {line.get('element')} {float(line.get('wavelength_nm', 0)):.4f} nm",
                    value,
                )
            )
            compatibility_rows.append(self._row(
                "item", f"{line.get('element')} {float(line.get('wavelength_nm', 0)):.4f} nm",
                f"数值类型={line.get('value_kind')}; 超限容差={line.get('over_limit_tolerance_percent')}%; "
                f"优先级={line.get('priority')}; 背景引用={by_id.get(line.get('background_line_id'), line.get('background_line_id')) or '-'}",
            ))
        standard_count = sum(len(line.get("standard_points", [])) for line in lines)
        rows.append(self._row("section", f"标准点（{standard_count} 个）"))
        for line in lines:
            for point_index, point in enumerate(line.get("standard_points", []), start=1):
                rows.append(
                    self._row(
                        "item",
                        f"{line.get('element')} / {point.get('name') or f'S{point_index}'}",
                        f"{point.get('value')} {line.get('unit')} / 启用={_display(point.get('active'))}",
                    )
                )
        issues = version.get("validation_errors", [])
        if issues:
            rows.append(self._row("section", f"草稿验证问题（{len(issues)} 项）"))
            for issue in issues:
                rows.append(self._row("item", issue.get("field", "-"), f"{issue.get('code')}: {issue.get('message')}"))
        rows.append(self._row("section", "兼容参数（保留原值）"))
        rows.extend(compatibility_rows)
        return rows

    @staticmethod
    def _paper(settings: PrintSettings) -> tuple[float, float]:
        width, height = paper_mm(settings.paper)
        return (height, width) if settings.orientation == "landscape" else (width, height)

    def _paginate(self, rows: list[dict[str, str]], settings: PrintSettings) -> dict[str, Any]:
        width_mm, height_mm = self._paper(settings)
        usable_pt = (height_mm - settings.margin_top_mm - settings.margin_bottom_mm) * (72.0 / 25.4) - 52
        line_height = settings.font_size_pt * (1.28 if settings.layout == "compact" else 1.48)
        capacity = max(12, int(usable_pt // line_height))
        content_pt = (width_mm - settings.margin_left_mm - settings.margin_right_mm) * (72.0 / 25.4)
        # Wrapping must shrink with larger type and smaller driver paper sizes.
        # CJK characters consume two units; allow for HTML/PDF cell padding.
        unit_width = settings.font_size_pt * 0.65
        label_limit = max(6, int((content_pt * 0.28 - 12) / unit_width))
        value_limit = max(6, int((content_pt * 0.72 - 12) / unit_width))
        prepared = []
        for row in rows:
            if row["kind"] == "section":
                prepared.append({**row, "label_lines": [row["label"]], "value_lines": [], "units": 2})
            else:
                labels = _wrap(row["label"], label_limit)
                values = _wrap(row["value"], value_limit)
                prepared.append(
                    {**row, "label_lines": labels, "value_lines": values, "units": max(len(labels), len(values)) + 1}
                )
        pages: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        used = 0
        for index, row in enumerate(prepared):
            units = row["units"]
            if (
                row["kind"] == "section"
                and current
                and used + units + (prepared[index + 1]["units"] if index + 1 < len(prepared) else 0) > capacity
            ):
                pages.append(current)
                current, used = [], 0
            elif current and used + units > capacity:
                pages.append(current)
                current, used = [], 0
            current.append(row)
            used += units
        if current:
            pages.append(current)
        return {
            "pages": pages,
            "page_count": len(pages),
            "field_count": sum(1 for row in rows if row["kind"] == "item"),
            "line_height": line_height,
            "width_mm": width_mm,
            "height_mm": height_mm,
        }
