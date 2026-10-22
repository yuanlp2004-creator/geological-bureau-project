"""SpecDirect TCurver, TLsFiter and CalResult compatibility, without I/O."""
from __future__ import annotations

import math
from typing import Any
from .algorithms import _float32, fit_curve, evaluate_curve
from .errors import AnalysisError


def _spline(xs: list[float], ys: list[float]) -> dict[str, Any]:
    count = len(xs)
    h = [_float32(xs[i + 1] - xs[i]) for i in range(count - 1)]
    if any(abs(span) < 1e-12 for span in h):
        raise AnalysisError('analysis_curve_duplicate_x', '旧样条存在重复自变量')
    dy = [_float32((ys[i + 1] - ys[i]) / h[i]) for i in range(count - 1)]
    second = [0.0] + [_float32((dy[i] - dy[i - 1]) * 6) for i in range(1, count - 1)] + [0.0]
    slopes, e = [0.0] * (count - 1), [0.0] * (count - 2)
    z = _float32((h[0] + h[1]) * 2)
    try:
        slopes[0], e[0] = _float32(-h[1] / z), _float32(second[1] / z)
        for i in range(1, count - 2):
            z = _float32((h[i] + h[i + 1]) * 2 + h[i] * slopes[i - 1])
            slopes[i] = _float32(-h[i + 1] / z)
            e[i] = _float32((second[i + 1] - h[i] * e[i - 1]) / z)
        second[-2] = e[-1]
        for i in range(count - 3, 0, -1):
            second[i] = _float32(slopes[i - 1] * second[i + 1] + e[i - 1])
        slopes = [_float32((second[i + 1] - second[i]) / h[i]) for i in range(count - 1)]
    except ArithmeticError as exc:
        raise AnalysisError('analysis_curve_ill_conditioned', '旧样条退化，不能形成曲线') from exc
    return {'kind': 'spline', 'x': xs, 'y': ys, 'second_derivatives': second, 'segment_slopes': slopes,
            'dy': dy, 'spline_precision': 'legacy_single'}


def _raw_evaluate(fit: dict, value: float) -> float:
    if fit.get('spline_precision') == 'legacy_single':
        xs, ys, second = fit['x'], fit['y'], fit['second_derivatives']
        index = 0
        while index < len(xs) - 2 and value > xs[index + 1]:
            index += 1
        h = _float32(value - xs[index])
        return _float32(ys[index] + h * (fit['dy'][index] + (value - xs[index + 1]) *
            (second[index + 1] + 2 * second[index] + h * fit['segment_slopes'][index]) / 6))
    return _float32(evaluate_curve(fit, value))


def _polynomial(xs: list[float], ys: list[float], mode: str) -> tuple[list[float], bool]:
    cx = [0.0] * 10
    for x, y in zip(xs, ys, strict=True):
        power = 1.0
        for j in range(6):
            if j < 4:
                cx[j + 6] += power * y
            power *= x
            cx[j] += power
    size = len(xs)
    cx[6] /= size
    for i in range(7, 10):
        cx[i] -= cx[i - 7] * cx[6]
    d, e, zz, c = cx[1] / size, cx[3] - cx[1] * (cx[1] / size), cx[2] / size, cx[0] / size
    for i in range(3):
        cx[i + 3] -= cx[i] * zz
    cx[2] -= cx[0] * d
    cx[0] = cx[1] - cx[0] * c
    square2, square4 = cx[2] ** 2, cx[4] ** 2
    product = cx[2] * cx[3] * cx[4]
    determinant = 2 * product + cx[0] * (e * cx[5] - square4) - e * cx[3] ** 2 - square2 * cx[5]
    coefficients = [0.0] * 4
    fallback = abs(determinant) < 1e-19 and mode != 'linear'
    try:
        if fallback or mode == 'linear':
            coefficients[1] = cx[7] / cx[0]
        elif mode == 'quadratic':
            denominator = e * cx[0] - cx[2] ** 2
            coefficients[2] = (cx[8] * cx[0] - cx[2] * cx[7]) / denominator
            coefficients[1] = (e * cx[7] - cx[2] * cx[8]) / denominator
        else:
            coefficients[3] = (cx[7] * (cx[2] * cx[4] - cx[3] * e)
                + cx[8] * (cx[2] * cx[3] - cx[0] * cx[4])
                + cx[9] * (cx[0] * e - square2)) / determinant
            coefficients[2] = (cx[7] * (cx[3] * cx[4] - cx[2] * cx[5])
                + cx[8] * (cx[0] * cx[5] - cx[3] ** 2)
                + cx[9] * (cx[2] * cx[3] - cx[0] * cx[4])) / determinant
            coefficients[1] = (cx[7] * (e * cx[5] - square4)
                + cx[8] * (cx[3] * cx[4] - cx[2] * cx[5])
                + cx[9] * (cx[2] * cx[4] - cx[3] * e)) / determinant
        coefficients[0] = cx[6] - coefficients[1] * c - coefficients[2] * d - coefficients[3] * zz
        result = [_float32(value) for value in coefficients]
        if not all(math.isfinite(value) for value in result):
            raise ArithmeticError()
    except (ArithmeticError, OverflowError) as exc:
        raise AnalysisError('analysis_curve_ill_conditioned', '旧版标准曲线退化，不能形成有限系数') from exc
    return result, fallback


def fit_legacy_curve(x_values: list[float], y_values: list[float], mode: str, coordinate: str) -> dict[str, Any]:
    if mode not in {'linear', 'quadratic', 'cubic', 'spline'} or coordinate not in {'normal', 'logarithmic'}:
        raise AnalysisError('analysis_curve_fit_mode_invalid', '曲线拟合方式或坐标无效')
    if len(x_values) != len(y_values):
        raise AnalysisError('analysis_curve_shape_invalid', '标准点强度与含量数量不一致')
    if len(x_values) < 4:
        raise AnalysisError('analysis_curve_points_insufficient', '至少需要四个有效标准点')
    if any(not math.isfinite(float(value)) for value in x_values + y_values):
        raise AnalysisError('analysis_curve_value_invalid', '标准点必须是有限数字')
    if coordinate == 'logarithmic' and any(value <= 0 for value in x_values + y_values):
        raise AnalysisError('analysis_curve_log_nonpositive', '对数坐标要求正强度及含量')
    pairs = sorted(zip(x_values, y_values, strict=True), key=lambda pair: pair[1])
    xs, ys = [[_float32(math.log(value) if coordinate == 'logarithmic' else value)
               for value in axis] for axis in zip(*pairs, strict=True)]
    original_count = len(xs)
    smoothed = coordinate == 'logarithmic' and mode != 'linear' and original_count < 16
    if smoothed:
        inverse = _spline(ys, xs)
        position, step = ys[0], _float32((ys[-1] - ys[0]) / 15)
        ys = []
        for _ in range(16):
            ys.append(position)
            position = _float32(position + step)
        raw = [_raw_evaluate(inverse, value) for value in ys]
        xs = [0.0] * 16
        xs[0] = (69 * raw[0] + 4 * (raw[1] + raw[3]) - 6 * raw[2] - raw[4]) / 70
        xs[1] = (2 * (raw[0] + raw[4]) + 27 * raw[1] + 12 * raw[2] - 8 * raw[3]) / 35
        for i in range(2, 14):
            xs[i] = (12 * (raw[i - 1] + raw[i + 1]) - 3 * (raw[i - 2] + raw[i + 2]) + 17 * raw[i]) / 35
        xs[14] = (2 * (raw[15] + raw[11]) + 27 * raw[14] + 12 * raw[13] - 8 * raw[12]) / 35
        xs[15] = (69 * raw[15] + 4 * (raw[14] + raw[12]) - 6 * raw[13] - raw[11]) / 70
        xs = [_float32(value) for value in xs]
    if mode == 'spline':
        result = _spline(xs, ys)
        fallback = False
    else:
        coefficients, fallback = _polynomial(xs, ys, mode)
        result = {'kind': 'polynomial', 'coefficients': coefficients, 'x': xs, 'y': ys}
    return {**result, 'calculation_profile': 'legacy_2_0_2', 'legacy_fit_mode': mode,
            'legacy_coordinate': coordinate, 'legacy_maximum_content': max(y_values),
            'source_point_count': original_count, 'smoothed': smoothed, 'linear_fallback': fallback}


def evaluate_legacy_curve(fit: dict[str, Any], intensity: float) -> float:
    logarithmic = fit['legacy_coordinate'] == 'logarithmic'
    if logarithmic and intensity <= 0:
        raise AnalysisError('analysis_curve_log_nonpositive', '对数坐标不能计算非正强度')
    x = _float32(math.log(intensity) if logarithmic else intensity)
    raw_fit = {key: value for key, value in fit.items() if key != 'calculation_profile'}
    xs, ys = fit['x'], fit['y']
    if x > xs[-1]:
        maximum = _float32(math.log(fit['legacy_maximum_content']) if logarithmic else fit['legacy_maximum_content'])
        try:
            result = _raw_evaluate(raw_fit, x)
        except (AnalysisError, ArithmeticError):
            result = maximum
        if result > maximum or (fit['legacy_fit_mode'] != 'linear' and result < xs[-1]):
            result = maximum
    elif x < xs[0] and fit['legacy_fit_mode'] != 'linear':
        result = _float32((x - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0]) + ys[0])
        lower = _float32(ys[0] - 1.10 if logarithmic else ys[0] / 3)
        result = min(ys[0], max(lower, result))
    else:
        result = _raw_evaluate(raw_fit, x)
    return _float32(math.exp(result) if logarithmic else result)


def merge_legacy_lines(items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = items[0]
    for candidate in items[1:]:
        if selected['legacy_switch_content'] < candidate['legacy_switch_content']:
            if selected['value'] > selected['legacy_switch_content']:
                selected = candidate
        elif candidate['value'] < candidate['legacy_switch_content']:
            selected = candidate
    return selected
