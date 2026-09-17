"""重复统计、曲线拟合和谱峰算法，不依赖数据库或输出组件。"""

from __future__ import annotations

import math
import struct
from typing import Any
from .errors import AnalysisError


MIN_SIGNAL = 1e-5

FIT_MODES = {"linear": 1, "quadratic": 2, "cubic": 3, "spline": 3}

COORDINATE_TYPES = {"normal", "logarithmic"}


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _legacy_floor(value: float) -> float:
    minimum = _float32(MIN_SIGNAL)
    return minimum if value < minimum else _float32(value)


def repeat_statistics(values: list[float]) -> dict[str, Any]:
    """Legacy-compatible repeat statistics used by the S17 QC workflow."""

    numbers = [float(value) for value in values]
    if any(not math.isfinite(value) for value in numbers):
        raise AnalysisError("analysis_qc_value_invalid", "重复测量值必须是有限数字", status_code=422)
    count = len(numbers)
    if count == 0:
        return {"effective_count": 0, "mean": None, "minimum": None, "maximum": None, "range": None, "stddev": None, "rsd": None, "id": None}
    minimum, maximum = min(numbers), max(numbers)
    mean = sum(numbers) / count
    stddev = 0.0 if count == 1 else math.sqrt(sum((value - mean) ** 2 for value in numbers) / (count - 1))
    rsd = 0.0 if stddev == 0 else min(999.0, abs(100.0 * stddev / mean)) if mean != 0 else 999.0
    identity = 0.0
    if minimum <= 0:
        identity = 999.0 if maximum > minimum else 0.0
    elif maximum > minimum:
        identity = 21.7147 * math.log(maximum / minimum)
    return {
        "effective_count": count,
        "mean": mean,
        "minimum": minimum,
        "maximum": maximum,
        "range": maximum - minimum,
        "stddev": stddev,
        "rsd": rsd,
        "id": identity,
    }


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [list(matrix[row]) + [float(vector[row])] for row in range(size)]
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = max(1e-14, scale * 1e-12)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= tolerance:
            raise AnalysisError("analysis_curve_ill_conditioned", "标准点矩阵病态，无法稳定拟合", details={"pivot": column})
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [value - factor * pivot_value for value, pivot_value in zip(augmented[row], augmented[column], strict=True)]
    return [augmented[row][-1] for row in range(size)]


def fit_curve(x_values: list[float], y_values: list[float], mode: str, coordinate_type: str = "normal") -> dict[str, Any]:
    if mode not in FIT_MODES:
        raise AnalysisError("analysis_curve_fit_mode_invalid", "拟合方式无效", status_code=422)
    if coordinate_type not in COORDINATE_TYPES:
        raise AnalysisError("analysis_curve_coordinate_invalid", "坐标方式无效", status_code=422)
    if len(x_values) != len(y_values):
        raise AnalysisError("analysis_curve_shape_invalid", "标准点强度与含量数量不一致", status_code=422)
    minimum_count = 4
    if len(x_values) < minimum_count:
        raise AnalysisError("analysis_curve_points_insufficient", f"{mode} 拟合至少需要 {minimum_count} 个有效标准点", details={"minimum": minimum_count, "actual": len(x_values)})
    pairs = [(float(x), float(y)) for x, y in zip(x_values, y_values, strict=True)]
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in pairs):
        raise AnalysisError("analysis_curve_value_invalid", "标准点必须是有限数字", status_code=422)
    if coordinate_type == "logarithmic":
        if any(x <= 0 or y <= 0 for x, y in pairs):
            raise AnalysisError("analysis_curve_log_nonpositive", "对数坐标要求强度和含量均大于零")
        pairs = [(math.log(x), math.log(y)) for x, y in pairs]
    pairs.sort(key=lambda item: item[0])
    if any(math.isclose(pairs[index][0], pairs[index - 1][0], rel_tol=0.0, abs_tol=1e-12) for index in range(1, len(pairs))):
        raise AnalysisError("analysis_curve_duplicate_x", "标准点存在重复强度，无法拟合")
    xs, ys = map(list, zip(*pairs, strict=True))
    if mode != "spline":
        degree = FIT_MODES[mode]
        matrix = [[sum(x ** (row + column) for x in xs) for column in range(degree + 1)] for row in range(degree + 1)]
        vector = [sum(y * (x ** row) for x, y in zip(xs, ys, strict=True)) for row in range(degree + 1)]
        coefficients = [_float32(value) for value in _solve_linear(matrix, vector)]
        coefficients += [0.0] * (4 - len(coefficients))
        return {"kind": "polynomial", "coefficients": coefficients, "x": xs, "y": ys}

    count = len(xs)
    h = [xs[index + 1] - xs[index] for index in range(count - 1)]
    if any(value <= 1e-12 for value in h):
        raise AnalysisError("analysis_curve_duplicate_x", "标准点存在重复强度，无法拟合")
    if count == 2:
        second = [0.0, 0.0]
    else:
        matrix = [[0.0] * (count - 2) for _ in range(count - 2)]
        vector = [0.0] * (count - 2)
        for row in range(count - 2):
            index = row + 1
            if row > 0:
                matrix[row][row - 1] = h[index - 1]
            matrix[row][row] = 2.0 * (h[index - 1] + h[index])
            if row < count - 3:
                matrix[row][row + 1] = h[index]
            vector[row] = 6.0 * ((ys[index + 1] - ys[index]) / h[index] - (ys[index] - ys[index - 1]) / h[index - 1])
        second = [0.0, *(_float32(value) for value in _solve_linear(matrix, vector)), 0.0]
    slopes = [_float32((second[index + 1] - second[index]) / h[index]) for index in range(count - 1)]
    dy = [_float32((ys[index + 1] - ys[index]) / h[index]) for index in range(count - 1)]
    return {"kind": "spline", "x": xs, "y": ys, "second_derivatives": second, "segment_slopes": slopes, "dy": dy}


def evaluate_curve(fit: dict[str, Any], x_value: float, coordinate_type: str = "normal") -> float:
    x = float(x_value)
    if coordinate_type == "logarithmic":
        if x <= 0:
            raise AnalysisError("analysis_curve_log_nonpositive", "对数坐标不能计算非正强度")
        x = math.log(x)
    if fit["kind"] == "polynomial":
        c0, c1, c2, c3 = (float(value) for value in fit["coefficients"])
        result = x * (x * (x * c3 + c2) + c1) + c0
    else:
        xs = [float(value) for value in fit["x"]]
        ys = [float(value) for value in fit["y"]]
        second = [float(value) for value in fit["second_derivatives"]]
        index = 0
        while index < len(xs) - 2 and x > xs[index + 1]:
            index += 1
        h = x - xs[index]
        span = xs[index + 1] - xs[index]
        dy = (ys[index + 1] - ys[index]) / span
        slope = (second[index + 1] - second[index]) / span
        result = ys[index] + h * (dy + (x - xs[index + 1]) * (second[index + 1] + 2.0 * second[index] + h * slope) / 6.0)
    if coordinate_type == "logarithmic":
        result = math.exp(result)
    if not math.isfinite(result):
        raise AnalysisError("analysis_curve_result_invalid", "拟合结果不是有限数字")
    return result


def legacy_gaussian(values: list[float]) -> dict[str, float | int | bool | None]:
    """Direct, testable port of SpecDirect 2.0.2 TGaussCur.Cal."""

    size = len(values)
    invalid = {"ok": False, "size": size, "center": 0.0, "peak_height": 0.0, "sigma": None, "area": None}
    if size < 3 or size > 9 or size % 2 == 0:
        return invalid
    if size == 3:
        calculated_size, multiplier = 7, 3
    elif size == 5:
        calculated_size, multiplier = 9, 2
    else:
        calculated_size, multiplier = size, 1
    pace = 1.0 / multiplier
    xs: list[float] = []
    weights: list[float] = []
    ys: list[float] = []
    for index in range(calculated_size):
        x = index * pace
        source_index = index // multiplier
        weight = float(values[source_index])
        remainder = index % multiplier
        if remainder:
            weight += (float(values[source_index + 1]) - weight) * remainder * pace
        if weight <= 0 or not math.isfinite(weight):
            return invalid
        xs.append(x)
        weights.append(weight)
        ys.append(math.log(weight))
    buf = [0.0] * 8
    for x, weight, y in zip(xs, weights, ys, strict=True):
        weighted_power = weight
        for power in range(5):
            if power < 3:
                buf[power + 5] += weighted_power * y
            buf[power] += weighted_power
            weighted_power *= x
    mean_x = buf[1] / buf[0]
    mean_x2 = buf[2] / buf[0]
    buf[5] /= buf[0]
    buf[6] -= buf[1] * buf[5]
    buf[7] -= buf[2] * buf[5]
    buf[4] -= buf[2] * mean_x2
    buf[3] -= buf[1] * mean_x2
    buf[1] = buf[2] - buf[1] * mean_x
    determinant = buf[1] * buf[4] - buf[3] * buf[3]
    if abs(determinant) < 1e-100:
        return invalid
    a2 = (buf[1] * buf[7] - buf[3] * buf[6]) / determinant
    a1 = (buf[4] * buf[6] - buf[3] * buf[7]) / determinant
    a0 = buf[5] - a1 * mean_x - a2 * mean_x2
    if a2 >= 0:
        return invalid
    sigma = math.sqrt(-0.5 / a2)
    center = -0.5 * a1 / a2
    peak = math.exp(a0 + 0.5 * center * a1)
    return {
        "ok": True,
        "size": size,
        "center": center,
        "peak_height": peak,
        "sigma": sigma,
        "area": peak * sigma * math.sqrt(2.0 * math.pi),
    }


def _bounded_range(center: int, width: int, point_count: int) -> tuple[int, int, bool]:
    if width <= 0 or width > point_count:
        raise AnalysisError("analysis_window_invalid", "谱线计算窗口超出 CCD 点数", details={"center": center, "width": width, "point_count": point_count})
    left = center - width // 2
    adjusted = False
    if left < 0:
        left = 0
        adjusted = True
    right = left + width - 1
    if right >= point_count:
        right = point_count - 1
        left = right - width + 1
        adjusted = True
    return left, right, adjusted


def _search_peak(values: list[float], center: int, width: int, *, checked: bool, lower_peak: float, minimum_ratio: float, maximum: bool = False) -> dict[str, Any]:
    left, right, adjusted = _bounded_range(center, width, len(values))
    window = values[left:right + 1]
    minimum = min(window)
    if maximum:
        peak = max(window)
        position = left + window.index(peak)
        found = True
    else:
        position = max(left, min(right, center))
        peak = float(values[position])
        found = False
        candidate_peak = 0.0
        for index in range(left + 1, right):
            current = float(values[index])
            if current > values[index - 1] and current > values[index + 1] and candidate_peak < current:
                candidate_peak = current
                position = index
                found = True
        if found and checked and not (candidate_peak > lower_peak and candidate_peak > minimum * minimum_ratio):
            found = False
            position = max(left, min(right, center))
        peak = float(values[position])
    return {"position": position, "peak": peak, "minimum": float(minimum), "found": found, "window_start": left, "window_end": right, "boundary_adjusted": adjusted}
