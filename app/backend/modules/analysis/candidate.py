from __future__ import annotations
from typing import Any
from .errors import AnalysisError
from .algorithms import _float32, _legacy_floor, legacy_gaussian, _bounded_range, _search_peak, MIN_SIGNAL


def calculate_candidate(
    line: dict[str, Any],
    lines: list[dict[str, Any]],
    sample_position: int,
    line_position: int,
    ccd_index: int,
    expected_float: float,
    values: list[float],
    offsets: dict[str, int],
    prior_results: dict[str, dict[str, Any]],
    calculation_profile: str,
    forced_position: int | None,
) -> dict[str, Any]:
    """Calculate one candidate from validated input values and prior line results."""
    count = len(values)
    reference = next((item for item in lines if item.get("line_type") == "baseline"), None)
    correction = offsets.get(str(reference.get("id")), 0) if reference else 0
    alignment_id = line.get("alignment_line_id")
    if alignment_id:
        correction += offsets.get(str(alignment_id), 0)
    expected = int(round(expected_float)) + correction
    maximum = line.get("line_type") == "baseline"
    checked = line.get("line_type") not in {"baseline", "positioning"}
    search = _search_peak(
        values,
        expected,
        int(line.get("scan_width_points", 9)),
        checked=checked,
        lower_peak=float(line.get("lower_peak", 300)),
        minimum_ratio=float(line.get("minimum_peak_ratio", 1.5)),
        maximum=maximum,
    )
    peak_position = int(forced_position if forced_position is not None else search["position"])
    if not 0 <= peak_position < count:
        raise AnalysisError(
            "analysis_adjustment_outside_ccd",
            "人工定位点超出 CCD 范围",
            details={"position": peak_position, "point_count": count},
        )
    if forced_position is not None:
        allowed_left, allowed_right, _ = _bounded_range(expected, int(line.get("scan_width_points", 9)), count)
        if not allowed_left <= peak_position <= allowed_right:
            raise AnalysisError(
                "analysis_adjustment_outside_window",
                "人工定位点必须位于谱线扫描窗口内",
                details={"position": peak_position, "window_start": allowed_left, "window_end": allowed_right},
            )
    peak_height = float(values[peak_position])
    gaussian: dict[str, Any] | None = None
    if line.get("peak_mode") == "gaussian":
        left, right, gaussian_adjusted = _bounded_range(peak_position, int(line.get("peak_width_points", 3)), count)
        gaussian = legacy_gaussian(values[left : right + 1])
        if not gaussian["ok"] and calculation_profile != "legacy_2_0_2":
            raise AnalysisError(
                "analysis_gaussian_fit_failed",
                "高斯峰拟合失败",
                details={
                    "line_id": line.get("id"),
                    "sample_position": sample_position,
                    "values": values[left : right + 1],
                    "window_start": left,
                    "window_end": right,
                },
            )
        gaussian = {**gaussian, "center": float(gaussian["center"]) + left, "boundary_adjusted": gaussian_adjusted}
        if gaussian["ok"]:
            peak_height = float(gaussian["peak_height"])
        else:
            gaussian.update({"fallback": "searched_peak_height", "center": None, "peak_height": peak_height})
    background = 0.0
    background_adjusted = False
    if int(line.get("background_offset_points", 0)):
        background_center = peak_position + int(line["background_offset_points"])
        left, right, background_adjusted = _bounded_range(background_center, 7, count)
        background = min(float(value) for value in values[left : right + 1])
    legacy_profile = calculation_profile == "legacy_2_0_2"
    stored_peak_height = _float32(peak_height) if legacy_profile else peak_height
    stored_background = _float32(background) if legacy_profile else background
    if int(line.get("background_offset_points", 0)):
        net = (
            stored_peak_height / stored_background
            if line.get("line_type") == "analysis"
            and line.get("internal_standard_mode") == "background"
            and stored_background != 0
            else stored_peak_height - stored_background
        )
    else:
        net = stored_peak_height
    net = _legacy_floor(net) if legacy_profile else max(MIN_SIGNAL, net)
    quantitative = net
    if line.get("line_type") == "analysis" and line.get("internal_standard_mode") == "line":
        internal_id = str(line.get("internal_standard_line_id"))
        internal = prior_results.get(internal_id)
        if internal is None or float(internal["net_signal"]) <= 0:
            raise AnalysisError(
                "analysis_internal_standard_missing",
                "普通内标线尚未产生有效结果",
                details={"line_id": line.get("id"), "internal_standard_line_id": internal_id},
            )
        denominator = float(internal["net_signal"])
        if legacy_profile:
            denominator = float(internal.get("peak_height", denominator))
            if int(line.get("background_offset_points", 0)):
                denominator -= float(internal.get("background", 0))
            denominator = _legacy_floor(denominator)
        quantitative = _legacy_floor(net / denominator) if legacy_profile else max(MIN_SIGNAL, net / denominator)
    if calculation_profile == "modern_v1" and gaussian is not None:
        quantitative = float(gaussian["area"])
        if line.get("internal_standard_mode") == "background":
            quantitative = max(MIN_SIGNAL, quantitative / background) if background > 0 else MIN_SIGNAL
        elif line.get("internal_standard_mode") == "line":
            internal_id = str(line.get("internal_standard_line_id"))
            internal = prior_results.get(internal_id)
            if internal is None or float(internal["quantitative_signal"]) <= 0:
                raise AnalysisError(
                    "analysis_internal_standard_missing",
                    "普通内标线尚未产生有效面积结果",
                    details={"line_id": line.get("id"), "internal_standard_line_id": internal_id},
                )
            quantitative = max(MIN_SIGNAL, quantitative / float(internal["quantitative_signal"]))
    window_left, window_right, _ = _bounded_range(peak_position, min(31, count), count)
    return {
        "sample_position": sample_position,
        "line_position": line_position,
        "line_id": str(line.get("id")),
        "line_type": line.get("line_type"),
        "element": line.get("element", ""),
        "wavelength_nm": float(line.get("wavelength_nm")),
        "ccd_index": ccd_index,
        "expected_position": float(expected_float),
        "corrected_expected_position": expected,
        "peak_position": peak_position,
        "peak_height": stored_peak_height,
        "background": stored_background,
        "net_signal": net,
        "gaussian_center": gaussian.get("center") if gaussian else None,
        "gaussian_peak_height": gaussian.get("peak_height") if gaussian else None,
        "gaussian_sigma": gaussian.get("sigma") if gaussian else None,
        "gaussian_area": gaussian.get("area") if gaussian else None,
        "quantitative_signal": quantitative,
        "calculation_profile": calculation_profile,
        "intermediates": {
            "search": search,
            "reference_correction_points": correction,
            "corrected_expected_position": expected,
            "background_boundary_adjusted": background_adjusted,
            "gaussian": gaussian,
        },
        "spectrum_window": [
            {"point_index": index, "value": float(values[index])} for index in range(window_left, window_right + 1)
        ],
        "window_start": window_left,
        "window_end": window_right,
    }
