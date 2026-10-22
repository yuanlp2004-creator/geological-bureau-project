from __future__ import annotations
import json
from typing import Any
from .values import HardwareError, _STRATEGIES, _finite


def _normalize_plan(turns: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
    if strategy not in _STRATEGIES:
        raise HardwareError(
            "turn_strategy_invalid", "turn strategy is not supported", details={"strategy": strategy}
        )
    normalized: list[dict[str, Any]] = []
    wavelengths: list[float] = []
    angles: list[float] = []
    # 逐项校验角度、波长、重复及关键点，保留 source_index 供说明实际计划来源。
    for source_index, raw in enumerate(turns):
        wavelength = _finite(raw.get("wavelength_nm"), "wavelength_nm", 160, 800)
        angle = _finite(raw.get("angle_deg"), "angle_deg", -360, 360)
        priority = int(raw.get("priority", 0))
        if not 0 <= priority <= 100:
            raise HardwareError(
                "turn_priority_invalid",
                "turn priority must be between 0 and 100",
                details={"source_index": source_index},
            )
        if any(abs(wavelength - existing) <= 0.01 for existing in wavelengths):
            raise HardwareError(
                "turn_duplicate_wavelength",
                "duplicate wavelength bands are not allowed",
                details={"wavelength_nm": wavelength, "source_index": source_index},
                status_code=409,
            )
        if any(abs(angle - existing) <= 0.001 for existing in angles):
            raise HardwareError(
                "turn_duplicate_angle",
                "duplicate turn angles are not allowed",
                details={"angle_deg": angle, "source_index": source_index},
                status_code=409,
            )
        wavelengths.append(wavelength)
        angles.append(angle)
        normalized.append(
            {
                "source_index": source_index,
                "angle_deg": angle,
                "wavelength_nm": wavelength,
                "priority": priority,
                "key_band": bool(raw.get("key_band", False)),
                "expected_peak_position": _finite(
                    raw.get("expected_peak_position", 1024), "expected_peak_position", 0, 4096
                ),
                "expected_baseline_position": _finite(raw.get('expected_baseline_position', 256), 'expected_baseline_position', 0, 4096),
                "search_radius_points": int(_finite(raw.get('search_radius_points', 64), 'search_radius_points', 1, 1024)),
                "storage_mode": raw.get('storage_mode', 'averaged'),
                "start_frame": raw.get('start_frame', 1),
                "end_frame": raw.get('end_frame', 1),
                'baseline_ccd_index': raw.get('baseline_ccd_index'),
                'peak_ccd_index': raw.get('peak_ccd_index'),
            }
        )
    for item in normalized:
        start, end = item['start_frame'], item['end_frame']
        if (item['storage_mode'] not in {'averaged', 'full_interval'} or isinstance(start, bool)
                or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int)
                or not 1 <= start <= end <= 255):
            raise HardwareError('hardware_exposure_invalid', '转角区间必须为 1–255 内的整数闭区间，保存模式须有效')
    # 策略只改变计划执行顺序，最后重建连续 order_index，不能改变用户输入的测量参数。
    if strategy == "key_first":
        normalized.sort(
            key=lambda item: (
                not item["key_band"],
                -item["priority"],
                item["wavelength_nm"],
                item["angle_deg"],
                item["source_index"],
            )
        )
    else:
        normalized.sort(
            key=lambda item: (item["wavelength_nm"], item["angle_deg"], -item["priority"], item["source_index"])
        )
    for order_index, item in enumerate(normalized):
        item["order_index"] = order_index
    return normalized


def _thresholds(payload: dict[str, Any]) -> dict[str, float]:
    defaults = {
        "baseline_min": 10.0,
        "baseline_max": 60000.0,
        "baseline_position_tolerance": 25.0,
        "peak_position_tolerance": 25.0,
    }
    for key, value in (payload.get("thresholds") or {}).items():
        if key not in defaults:
            raise HardwareError("threshold_invalid", "unknown hardware anomaly threshold", details={"field": key})
        defaults[key] = _finite(value, key, 0 if key.endswith("tolerance") else 0, 65535)
    if defaults["baseline_min"] > defaults["baseline_max"]:
        raise HardwareError("threshold_invalid", "baseline_min must not exceed baseline_max")
    return defaults


def _metrics(task: dict[str, Any], step: dict[str, Any], ccd: dict[str, Any] | None, anomalies: list[str]
) -> tuple[list[int], dict[str, Any], bool]:
    points = [int(value) for value in (ccd or {}).get("points", [])]
    thresholds = json.loads(task["thresholds_json"] or "{}")
    expected = float(step["expected_peak_position"])
    config = next((item for item in json.loads(task['plan_json'])
                   if item['order_index'] == step['order_index']), step)
    baseline_expected = float(config.get('expected_baseline_position', 256))
    radius = int(config.get('search_radius_points', 64))
    # 各窗口只寻找自己的峰，其他 CCD 或远处的大峰不能代替被检测谱线。
    def peak(center: float) -> tuple[int | None, float]:
        start, end = max(0, int(center) - radius), min(len(points), int(center) + radius + 1)
        if start >= end:
            return None, 0.0
        position = max(range(start, end), key=points.__getitem__)
        return position, float(points[position])
    baseline_position, baseline_intensity = peak(baseline_expected)
    peak_position, raw_peak = peak(expected)
    baseline_monitored = config.get('baseline_ccd_index') in (None, (ccd or {}).get('ccd_index'))
    peak_monitored = config.get('peak_ccd_index') in (None, (ccd or {}).get('ccd_index'))
    damaged = ccd is None or not points or bool(set(anomalies).intersection({"frame_fault", "turn_timeout"}))
    observed = {
        "baseline_intensity": baseline_intensity,
        "baseline_position": baseline_position,
        "expected_peak_position": expected,
        "expected_baseline_position": baseline_expected,
        "peak_position": peak_position,
        "raw_peak_value": raw_peak,
        "anomaly_script": anomalies,
        'baseline_monitored': baseline_monitored,
        'peak_monitored': peak_monitored,
    }
    # 分别检查基准强度、基准位置和峰位阈值，返回全部异常类型供服务选择处理策略。
    detected: list[str] = []
    if damaged:
        detected.append(
            "frame_fault" if "frame_fault" in anomalies or "turn_timeout" not in anomalies else "turn_timeout"
        )
    if baseline_monitored and baseline_intensity < float(thresholds["baseline_min"]):
        detected.append("baseline_low")
    if baseline_monitored and baseline_intensity > float(thresholds["baseline_max"]):
        detected.append("baseline_high")
    if baseline_monitored and (baseline_position is None or abs(baseline_position - baseline_expected) > float(thresholds["baseline_position_tolerance"])):
        detected.append("baseline_shift")
    if peak_monitored and (peak_position is None or abs(peak_position - expected) > float(thresholds["peak_position_tolerance"])):
        detected.append("peak_shift")
    observed['baseline_position'] = baseline_position if baseline_position is not None else -1
    observed['peak_position'] = peak_position if peak_position is not None else -1
    observed['raw_peak_value'] = raw_peak if points else None
    observed['detected'] = detected
    return points, observed, bool(detected)


def _simulated_anomalies(task: dict[str, Any], step: dict[str, Any], attempt: int) -> list[str]:
    config = json.loads(task["simulator_json"] or "{}")
    result: list[str] = []
    for item in config.get("anomalies", []):
        if int(item.get("step_index", -1)) == int(step["order_index"]) and attempt < int(item.get("count", 1)):
            result.append(str(item["kind"]))
    return sorted(set(result))
