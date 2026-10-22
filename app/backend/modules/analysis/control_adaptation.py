"""以管理样实测信号和给定含量适配标准强度，保留原始点值。"""

import math
from typing import Any
from .algorithms import evaluate_curve, fit_curve
from .errors import AnalysisError


# 求导数的实根，用于完整检查三次曲线每段是否单调。
def _roots(a: float, b: float, c: float) -> list[float]:
    if abs(a) < 1e-14:
        return [] if abs(b) < 1e-14 else [-c / b]
    delta = b * b - 4 * a * c
    if delta < 0:
        return []
    return [(-b - math.sqrt(delta)) / (2 * a), (-b + math.sqrt(delta)) / (2 * a)]


# 在标定区间内求唯一信号，非单调、平坦或越界曲线拒绝自动适配。
def signal_for_value(fit: dict[str, Any], target: float, coordinate: str) -> float:
    xs = fit['x']
    boundaries = list(xs)
    if fit['kind'] == 'polynomial':
        _, b, c, d = fit['coefficients']
        boundaries.extend(x for x in _roots(3 * d, 2 * c, b) if xs[0] < x < xs[-1])
    else:
        seconds, ys = fit['second_derivatives'], fit['y']
        for index in range(len(xs) - 1):
            width = xs[index + 1] - xs[index]
            a = (seconds[index + 1] - seconds[index]) / (6 * width)
            b = seconds[index] / 2
            c = (ys[index + 1] - ys[index]) / width - width * (2 * seconds[index] + seconds[index + 1]) / 6
            boundaries.extend(xs[index] + x for x in _roots(3 * a, 2 * b, c) if 0 < x < width)
    boundaries = sorted(set(boundaries))
    signals = [math.exp(x) if coordinate == 'logarithmic' else x for x in boundaries]
    values = [evaluate_curve(fit, x, coordinate) for x in signals]
    direction = 1 if values[-1] > values[0] else -1
    if any(direction * (right - left) <= 1e-12 for left, right in zip(values, values[1:])):
        raise AnalysisError('analysis_control_curve_ambiguous', '曲线在标定区间内不单调，不能自动适配')
    if not min(values[0], values[-1]) <= target <= max(values[0], values[-1]):
        raise AnalysisError('analysis_control_outside_calibration', '管理样给定值超出标定区间，不能外推适配')
    low, high = signals[0], signals[-1]
    for _ in range(80):
        middle = (low + high) / 2
        if direction * (evaluate_curve(fit, middle, coordinate) - target) < 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


# 用同质控版本的管理样均值计算倍率，返回独立证据及整组新标准强度。
def adapt_control(workspace: dict[str, Any], group: dict[str, Any], target: float) -> dict[str, Any]:
    measured = group['statistics']['mean']
    if (not math.isfinite(target) or target <= 0 or measured is None or not math.isfinite(measured)
            or measured <= 0 or group['statistics']['effective_count'] < 1):
        raise AnalysisError('analysis_control_value_invalid', '管理样给定值及有效实测强度必须为正有限数')
    if group.get('warnings') and not group.get('warning_accepted'):
        raise AnalysisError('analysis_control_qc_unresolved', '请先处理管理样的重复性质控预警')
    active = [point for point in workspace['points'] if point['active']]
    if any(point['adjusted_intensity'] is None for point in active):
        raise AnalysisError('analysis_control_standard_missing', '有效标准点缺少实测强度，不能适配')
    fit = fit_curve([point['adjusted_intensity'] for point in active],
                    [point['standard_value'] for point in active], workspace['fit_mode'], workspace['coordinate_type'])
    expected = signal_for_value(fit, target, workspace['coordinate_type'])
    if expected <= 0:
        raise AnalysisError('analysis_control_signal_invalid', '曲线对应信号非正，不能使用倍率适配')
    factor = measured / expected
    for point in workspace['points']:
        if point['adjusted_intensity'] is not None:
            adjusted = point['adjusted_intensity'] * factor
            if not math.isfinite(adjusted):
                raise AnalysisError('analysis_control_value_invalid', '适配强度超出有限数范围')
            point['adjusted_intensity'] = adjusted
    return {'algorithm': 'control_signal_scale_v1', 'acquisition_task_id': group['acquisition_task_id'],
            'sample_name': group['sample_name'], 'target_value': target, 'measured_signal': measured,
            'expected_signal': expected, 'factor': factor, 'fit_before': fit,
            'qc_members': group['members'], 'coordinate_type': workspace['coordinate_type']}
