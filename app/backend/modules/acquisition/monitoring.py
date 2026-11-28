"""Pure arc/baseline & peak-position anomaly monitoring and attempt-state helpers."""
from __future__ import annotations

import math
from typing import Any

from .values import AcquisitionError

DEFAULT_MONITORING_THRESHOLDS: dict[str, float] = {
    "baseline_min": 10.0,
    "baseline_max": 60000.0,
    "baseline_position_tolerance": 25.0,
    "peak_position_tolerance": 25.0,
}

ANOMALY_KINDS: tuple[str, ...] = (
    "baseline_low",
    "baseline_high",
    "baseline_shift",
    "peak_shift",
    "frame_fault",
    "turn_timeout",
)

ANOMALY_POLICIES: tuple[str, ...] = ("warn", "stop", "manual")

_ANOMALY_LABELS: dict[str, str] = {
    "baseline_low": "基线强度过低",
    "baseline_high": "基线强度过高",
    "baseline_shift": "基线位置漂移",
    "peak_shift": "定位峰位偏移",
    "frame_fault": "CCD 帧损坏",
    "turn_timeout": "转角定位超时",
}


def _finite_threshold(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise AcquisitionError("threshold_invalid", f"{field} 必须是有限数值", details={"field": field})
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise AcquisitionError("threshold_invalid", f"{field} 必须是有限数值", details={"field": field}) from exc
    if not math.isfinite(numeric) or numeric < minimum or numeric > maximum:
        raise AcquisitionError("threshold_invalid", f"{field} 超出允许范围", details={"field": field})
    return numeric


def normalize_thresholds(raw: dict[str, Any] | None) -> dict[str, float]:
    """Validate and merge anomaly monitoring thresholds with defaults."""
    thresholds = dict(DEFAULT_MONITORING_THRESHOLDS)
    for key, value in (raw or {}).items():
        if key not in thresholds:
            raise AcquisitionError("threshold_invalid", "未知的异常监测阈值字段", details={"field": key})
        thresholds[key] = _finite_threshold(value, key, 0.0, 65535.0)
    if thresholds["baseline_min"] > thresholds["baseline_max"]:
        raise AcquisitionError("threshold_invalid", "baseline_min 不能大于 baseline_max", details={"field": "baseline_min"})
    return thresholds


def normalize_monitoring_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate optional sample acquisition monitoring configuration."""
    data = payload or {}
    policy = str(data.get("anomaly_policy", "warn")).lower()
    if policy not in ANOMALY_POLICIES:
        raise AcquisitionError("monitoring_policy_invalid", "异常处置策略必须是 warn、stop 或 manual")
    raw_retry = data.get("retry_limit", 0)
    if isinstance(raw_retry, bool) or not isinstance(raw_retry, int) or not 0 <= raw_retry <= 5:
        raise AcquisitionError("monitoring_retry_invalid", "异常重试次数必须是 0 到 5 之间的整数")
    radius_raw = data.get("search_radius_points")
    radius: int | None = None
    if radius_raw is not None:
        if isinstance(radius_raw, bool) or not isinstance(radius_raw, int) or not 1 <= radius_raw <= 1024:
            raise AcquisitionError("monitoring_radius_invalid", "寻峰半径必须是 1 到 1024 之间的整数")
        radius = int(radius_raw)
    return {
        "anomaly_policy": policy,
        "retry_limit": int(raw_retry),
        "thresholds": normalize_thresholds(data.get("thresholds")),
        "search_radius_points": radius,
    }


def _window_peak(points: list[int], center: float, radius: int) -> tuple[int | None, float]:
    start = max(0, int(center) - radius)
    end = min(len(points), int(center) + radius + 1)
    if start >= end:
        return None, 0.0
    position = max(range(start, end), key=lambda index: (points[index], -abs(index - center)))
    return position, float(points[position])


def evaluate_ccd_window(
    points: list[int],
    ccd_index: int,
    monitor_spec: dict[str, Any] | None,
    thresholds: dict[str, float],
    *,
    damaged: bool = False,
    fault_kind: str | None = None,
    radius_override: int | None = None,
) -> dict[str, Any]:
    """Evaluate baseline/positioning windows for one CCD without substituting out-of-window peaks."""
    spec = monitor_spec if monitor_spec and monitor_spec.get('monitored') else {}
    baseline_spec = spec.get("baseline") if isinstance(spec.get("baseline"), dict) else None
    positioning_spec = spec.get("positioning") if isinstance(spec.get("positioning"), dict) else None

    baseline_monitored = baseline_spec is not None and int(baseline_spec.get("ccd_index", -1)) == int(ccd_index)
    peak_monitored = positioning_spec is not None and int(positioning_spec.get("ccd_index", -1)) == int(ccd_index)

    baseline_expected = float(baseline_spec["point_index"]) if baseline_monitored else None
    peak_expected = float(positioning_spec["point_index"]) if peak_monitored else None

    baseline_position: int | None = None
    baseline_intensity: float | None = None
    peak_position: int | None = None
    raw_peak_value: float | None = None

    if points and not damaged and baseline_monitored:
        b_radius = int(radius_override or baseline_spec.get("search_radius_points") or 64)
        baseline_position, baseline_intensity = _window_peak(points, baseline_expected, b_radius)
    if points and not damaged and peak_monitored:
        p_radius = int(radius_override or positioning_spec.get("search_radius_points") or 64)
        peak_position, raw_peak_value = _window_peak(points, peak_expected, p_radius)

    detected: list[str] = []
    if damaged or (not points and (baseline_monitored or peak_monitored)):
        detected.append("turn_timeout" if fault_kind == "turn_timeout" else "frame_fault")
    if baseline_monitored and not damaged and points:
        intensity_val = float(baseline_intensity or 0.0)
        if intensity_val < float(thresholds["baseline_min"]):
            detected.append("baseline_low")
        if intensity_val > float(thresholds["baseline_max"]):
            detected.append("baseline_high")
        if baseline_position is None or abs(baseline_position - baseline_expected) > float(
            thresholds["baseline_position_tolerance"]
        ):
            detected.append("baseline_shift")
    if peak_monitored and not damaged and points:
        if peak_position is None or abs(peak_position - peak_expected) > float(thresholds["peak_position_tolerance"]):
            detected.append("peak_shift")

    correction_offset = (
        float(peak_expected) - float(peak_position)
        if ("peak_shift" in detected and peak_expected is not None and peak_position is not None)
        else None
    )
    return {
        "ccd_index": int(ccd_index),
        "baseline_monitored": baseline_monitored,
        "peak_monitored": peak_monitored,
        "expected_baseline_position": baseline_expected,
        "baseline_position": baseline_position if baseline_position is not None else -1,
        "baseline_intensity": baseline_intensity if points else None,
        "expected_peak_position": peak_expected,
        "peak_position": peak_position if peak_position is not None else -1,
        "raw_peak_value": raw_peak_value if points else None,
        "correction_offset": correction_offset,
        "detected": detected,
    }


def evaluate_event_monitoring(
    event_ccds: list[dict[str, Any]] | None,
    monitor_spec: dict[str, Any] | None,
    thresholds: dict[str, float],
    *,
    damaged: bool = False,
    fault_kind: str | None = None,
    radius_override: int | None = None,
    selected_ccds: list[int] | None = None,
) -> dict[str, Any]:
    """Evaluate all CCD curves in a captured frame against turn monitoring bindings."""
    ccds = event_ccds or []
    by_index = {ccd['ccd_index']: ccd.get('points', []) for ccd in ccds}
    indices = sorted(by_index) if selected_ccds is None else selected_ccds
    observations: list[dict[str, Any]] = []
    detected: list[str] = []
    correction_offset: float | None = None
    for index in indices:
        obs = evaluate_ccd_window(
            by_index.get(index, []),
            index,
            monitor_spec,
            thresholds,
            damaged=damaged,
            fault_kind=fault_kind,
            radius_override=radius_override,
        )
        observations.append(obs)
        for kind in obs["detected"]:
            if kind not in detected:
                detected.append(kind)
        if correction_offset is None and obs["correction_offset"] is not None:
            correction_offset = obs["correction_offset"]
    if damaged and not detected:
        detected.append("turn_timeout" if fault_kind == "turn_timeout" else "frame_fault")
    monitored = any(obs["baseline_monitored"] or obs["peak_monitored"] for obs in observations)
    return {
        "monitored": monitored,
        "abnormal": bool(detected),
        "detected": detected,
        "correction_offset": correction_offset,
        "observations": observations,
    }


def format_anomaly_summary(detected: list[str], observations: list[dict[str, Any]]) -> str:
    labels = [_ANOMALY_LABELS.get(kind, kind) for kind in detected]
    details = []
    for obs in observations:
        if not obs.get("detected"):
            continue
        parts = []
        if obs.get("baseline_monitored") and obs.get("baseline_intensity") is not None:
            parts.append(f"基线强度 {obs['baseline_intensity']:.1f}，点位 {obs['baseline_position']}"
                         f"（预期 {obs['expected_baseline_position']:.1f}）")
        if obs.get("peak_monitored") and obs.get("peak_position", -1) >= 0:
            parts.append(f"峰位 {obs['peak_position']} (预期 {obs['expected_peak_position']:.1f})")
        if parts:
            details.append(f"CCD{obs['ccd_index'] + 1} " + " / ".join(parts))
    suffix = f"（{'；'.join(details)}）" if details else ""
    return f"监测异常：{'、'.join(labels)}{suffix}"
