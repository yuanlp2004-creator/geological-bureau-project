"""方法文档行、纸张、页边距和分页。"""

from __future__ import annotations

from typing import Any
from .settings import PrintSettings
from ..methods.errors import MethodDomainError


PAPER_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "Letter": (215.9, 279.4),
}


CONDITION_LABELS = (
    ("ccd_layout_id", "CCD 布局"),
    ("selected_ccds", "启用 CCD"),
    ("dispersion_calibration_id", "色散标定"),
    ("reference_wavelength_nm", "参考波长"),
    ("actual_reference_wavelength_nm", "实际参考波长"),
    ("reference_width_points", "参考线宽"),
    ("analysis_unit", "分析单位"),
    ("pre_excitation_seconds", "预激发时间"),
    ("sampling_period_seconds", "采样周期"),
    ("frame_count", "采集帧数"),
    ("dark_frame_count", "暗帧数"),
    ("sample_repeats", "样品重复次数"),
    ("standard_repeats", "标样重复次数"),
    ("control_repeats", "控制样重复次数"),
    ("standard_sample_name", "标准样品"),
    ("maximum_id_deviation", "最大 ID 偏差"),
    ("rsd_enabled", "RSD 检查"),
    ("rsd_threshold", "RSD 阈值"),
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


PEAK_LABELS = {"max_single_point": "最大单点", "gaussian": "高斯曲线"}


FIT_LABELS = {"linear": "直线", "quadratic": "二次", "cubic": "三次", "spline": "样条"}


COORDINATE_LABELS = {"normal": "普通坐标", "logarithmic": "对数坐标"}


INTERNAL_LABELS = {"none": "无内标", "background": "背景内标", "line": "普通内标线"}


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
        width, height = PAPER_MM[settings.paper]
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
            self._row("item", "工作类型", method["work_type"]),
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
            "maximum_id_deviation": " %",
            "rsd_threshold": " %",
            "calibration_threshold": " %",
            "qc_threshold": " %",
            "abnormal_threshold": " %",
        }
        for key, label in CONDITION_LABELS:
            rows.append(self._row("item", label, _display(conditions.get(key)) + suffixes.get(key, "")))
        rows.append(self._row("section", "分角度曝光"))
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
            line.get("id"): f"{line.get('element')} {float(line.get('wavelength_nm', 0)):.4f} nm"
            for line in lines
        }
        rows.append(self._row("section", f"分析谱线（{len(lines)} 条）"))
        for index, line in enumerate(lines, start=1):
            references = []
            for label, key in (
                ("背景", "background_line_id"),
                ("定位", "alignment_line_id"),
                ("内标", "internal_standard_line_id"),
            ):
                if line.get(key):
                    references.append(f"{label}={by_id.get(line[key], line[key])}")
            value = (
                f"{LINE_TYPE_LABELS.get(line.get('line_type'), line.get('line_type'))}; "
                f"实际 {float(line.get('actual_wavelength_nm', line.get('wavelength_nm', 0))):.4f} nm; "
                f"启用={_display(line.get('enabled'))}; 关键={_display(line.get('critical_band'))}; "
                f"优先级={line.get('priority')}; 扫描={line.get('scan_width_points')}点; "
                f"背景偏移={line.get('background_offset_points')}点; "
                f"峰值={PEAK_LABELS.get(line.get('peak_mode'), line.get('peak_mode'))}/{line.get('peak_width_points')}点; "
                f"拟合={FIT_LABELS.get(line.get('fit_mode'), line.get('fit_mode'))}/{COORDINATE_LABELS.get(line.get('coordinate_type'), line.get('coordinate_type'))}; "
                f"内标方式={INTERNAL_LABELS.get(line.get('internal_standard_mode'), line.get('internal_standard_mode'))}; "
                f"结果={line.get('value_kind')} {line.get('unit')} / {line.get('decimal_places')}位; "
                f"有效范围={line.get('valid_range_min')}-{line.get('valid_range_max')}; "
                f"超限容差={line.get('over_limit_tolerance_percent')}%"
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
        return rows

    @staticmethod
    def _paper(settings: PrintSettings) -> tuple[float, float]:
        width, height = PAPER_MM[settings.paper]
        return (height, width) if settings.orientation == "landscape" else (width, height)

    def _paginate(self, rows: list[dict[str, str]], settings: PrintSettings) -> dict[str, Any]:
        width_mm, height_mm = self._paper(settings)
        usable_pt = (height_mm - settings.margin_top_mm - settings.margin_bottom_mm) * (72.0 / 25.4) - 52
        line_height = settings.font_size_pt * (1.28 if settings.layout == "compact" else 1.48)
        capacity = max(12, int(usable_pt // line_height))
        value_limit = int((width_mm - settings.margin_left_mm - settings.margin_right_mm) * (0.46 if settings.layout == "compact" else 0.40))
        label_limit = max(18, int(value_limit * 0.42))
        value_limit = max(42, value_limit)
        prepared = []
        for row in rows:
            if row["kind"] == "section":
                prepared.append({**row, "label_lines": [row["label"]], "value_lines": [], "units": 2})
            else:
                labels = _wrap(row["label"], label_limit)
                values = _wrap(row["value"], value_limit)
                prepared.append({**row, "label_lines": labels, "value_lines": values, "units": max(len(labels), len(values)) + 1})
        pages: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        used = 0
        for index, row in enumerate(prepared):
            units = row["units"]
            if row["kind"] == "section" and current and used + units + (prepared[index + 1]["units"] if index + 1 < len(prepared) else 0) > capacity:
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

