from __future__ import annotations
import math
from .values import DispersionError

MIN_CALIBRATION_POINTS = 4
MAX_CALIBRATION_POINTS = 8


def validate_calibration_points(wavelengths: list[float], positions: list[float]) -> None:
    count = len(wavelengths)
    limits = {"minimum": MIN_CALIBRATION_POINTS, "maximum": MAX_CALIBRATION_POINTS, "actual": count}
    if count < MIN_CALIBRATION_POINTS:
        raise DispersionError("calibration_points_insufficient", f"至少需要四个有效定位点，当前有 {count} 个", details=limits)
    if count > MAX_CALIBRATION_POINTS:
        raise DispersionError("calibration_points_exceeded", f"最多可用八个有效定位点，当前有 {count} 个", details=limits)
    if any(not math.isfinite(wave) or wave <= 0 for wave in wavelengths):
        raise DispersionError("calibration_wavelength_missing", "请填写已定位谱线的有效已知波长")
    ordered = sorted(wavelengths)
    if any(right - left <= 0.01 for left, right in zip(ordered, ordered[1:])):
        raise DispersionError("calibration_duplicate_wavelength", "校准谱线不能有重复波长")
    ordered = sorted(positions)
    if any(not math.isfinite(position) for position in ordered) or any(
        right - left <= 1e-7 for left, right in zip(ordered, ordered[1:])
    ):
        raise DispersionError("calibration_positions_duplicate", "校准谱线必须具有不同的有效测量步数")


def _gaussian_solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise DispersionError("calibration_singular", "定位点不能形成可逆的校准拟合", details={"column": column})
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) < 1e-15:
                continue
            augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[column])]
    return [augmented[index][-1] for index in range(size)]


def _fit_polynomial(x_values: list[float], y_values: list[float], degree: int) -> list[float]:
    if len(x_values) != len(y_values) or len(x_values) < degree + 1:
        raise DispersionError(
            "calibration_points_insufficient",
            "校准定位点数量不足",
            details={"required": degree + 1, "actual": len(x_values), "degree": degree},
        )
    center = sum(x_values) / len(x_values)
    scale = max(max(abs(value - center) for value in x_values), 1.0)
    normalized = [(value - center) / scale for value in x_values]
    matrix: list[list[float]] = []
    vector: list[float] = []
    for row_power in range(degree + 1):
        matrix.append([sum(x ** (row_power + column_power) for x in normalized) for column_power in range(degree + 1)])
        vector.append(sum((x**row_power) * y for x, y in zip(normalized, y_values)))
    normalized_coefficients = _gaussian_solve(matrix, vector)
    ascending = [0.0] * (degree + 1)
    for power, coefficient in enumerate(normalized_coefficients):
        for raw_power in range(power + 1):
            ascending[raw_power] += (
                coefficient * math.comb(power, raw_power) * ((-center) ** (power - raw_power)) / (scale**power)
            )
    if degree == 1:
        return [0.0, ascending[1], ascending[0]]
    return list(reversed(ascending))


def _evaluate(coefficients: list[float], value: float) -> float:
    result = 0.0
    for coefficient in coefficients:
        result = result * value + coefficient
    return result


def _calibration_position(wavelength: float, coefficients: list[float]) -> float:
    return _evaluate(coefficients, wavelength)


def legacy_results(coefficients: list[float], points: list[dict]) -> dict | None:
    """FmWstc.DisplayStep/DisplayWsCof; error is measured minus fitted step."""
    if len(coefficients) != 3 or len(points) < 2:
        return None
    ordered = sorted(points, key=lambda point: (point['ccd_index'], point['measured_position']))
    first = ordered[0]
    differences = [point['measured_position'] - first['measured_position'] for point in ordered[1:]]
    distinct = not any(math.isclose(value, 0, abs_tol=1e-12) for value in differences)
    rows = [{**point, 'step_error': point['measured_position'] - point['predicted_position']} for point in ordered]
    return {
        'quadratic_coefficient': coefficients[0], 'linear_coefficient': coefficients[1], 'intercept': coefficients[2],
        'wave_per_step': sum((point['wavelength_nm'] - first['wavelength_nm']) / difference
                             for point, difference in zip(ordered[1:], differences)) / len(differences) if distinct else None,
        'wavelength_range': [first['wavelength_nm'], ordered[-1]['wavelength_nm']],
        'step_range': [min(first['measured_position'], first['predicted_position']),
                       max(ordered[-1]['measured_position'], ordered[-1]['predicted_position'])],
        'maximum_error': max(abs(row['step_error']) for row in rows), 'rows': rows,
    }
