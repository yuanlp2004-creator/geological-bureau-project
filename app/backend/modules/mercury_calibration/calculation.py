from __future__ import annotations
import math
from typing import Any
from .values import MercuryError


def _expected_position(layout: dict[str, Any], wavelength_nm: float, active_offset: float) -> tuple[int, float]:
    low = float(layout["wavelength_min"])
    high = float(layout["wavelength_max"])
    indices = layout["ccd_indices"]
    points = int(layout["points_per_ccd"])
    if not low <= wavelength_nm <= high:
        raise MercuryError(
            "mercury_line_outside_layout",
            "selected mercury line is outside the CCD layout wavelength range",
            details={"wavelength_nm": wavelength_nm, "wavelength_min": low, "wavelength_max": high},
        )
    global_position = (wavelength_nm - low) / (high - low) * (len(indices) * points - 1)
    ordinal = min(len(indices) - 1, int(global_position // points))
    nominal = global_position - ordinal * points
    return int(indices[ordinal]), nominal - active_offset


def _locate(points: list[int], expected: float, radius: int) -> tuple[int, int] | None:
    start = max(0, int(math.floor(expected)) - radius)
    end = min(len(points) - 1, int(math.ceil(expected)) + radius)
    if start > end:
        return None
    peak_position = max(range(start, end + 1), key=lambda position: (points[position], -position))
    peak_value = int(points[peak_position])
    if peak_value < 500:
        return None
    return peak_position, peak_value


def offset_statistics(offsets: list[float], correction_limit_points: float):
    ordered = sorted(offsets)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    suggestion = -median
    before_rms = math.sqrt(sum(value * value for value in offsets) / len(offsets))
    after_offsets = [value + suggestion for value in offsets]
    after_rms = math.sqrt(sum(value * value for value in after_offsets) / len(after_offsets))
    maximum_before = max(abs(value) for value in offsets)
    maximum_after = max(abs(value) for value in after_offsets)
    if abs(suggestion) > float(correction_limit_points):
        raise MercuryError(
            "mercury_correction_limit_exceeded",
            "calibration suggestion exceeds the configured correction limit",
            details={"suggestion_points": suggestion, "limit_points": correction_limit_points},
            status_code=409,
        )
    return median, suggestion, before_rms, after_offsets, after_rms, maximum_before, maximum_after
