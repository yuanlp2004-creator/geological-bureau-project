from __future__ import annotations
import math
from .values import DispersionError


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
