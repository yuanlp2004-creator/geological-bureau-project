"""方法名称、条件默认值、归一化与稳定序列化。"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from ...schemas.methods import MethodCondition
from .errors import MethodDomainError


NAME_MAX_GB18030_BYTES = 20


METHOD_NAME_INVALID = set(r"\/:*?<>|")


DEFAULT_CONDITIONS = MethodCondition().model_dump(mode="json")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _condition_patch(value: MethodCondition | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, MethodCondition):
        return value.model_dump(mode="json", exclude_unset=True)
    return deepcopy(value)


def _normalize_conditions(
    base: dict[str, Any], value: MethodCondition | dict[str, Any] | None
) -> dict[str, Any]:
    """Merge a draft patch while accepting names emitted by the abandoned S03 draft."""

    patch = _condition_patch(value)
    aliases = {
        "ccd_layout": "ccd_layout_id",
        "dispersion_reference": "dispersion_calibration_id",
        "real_reference_wavelength_nm": "actual_reference_wavelength_nm",
        "burn_cycle_seconds": "sampling_period_seconds",
        "dark_frames": "dark_frame_count",
        "standard_sample": "standard_sample_name",
        "id_threshold": "maximum_id_deviation",
    }
    for old, new in aliases.items():
        if old in patch and new not in patch:
            patch[new] = patch[old]
    if "repetition_count" in patch and "sample_repeats" not in patch:
        patch["sample_repeats"] = patch["repetition_count"]
    if "repeats" in patch and "sample_repeats" not in patch:
        patch["sample_repeats"] = patch["repeats"]
    if "ccd" in patch and "selected_ccds" not in patch:
        ccd = str(patch["ccd"]).upper().removeprefix("CCD")
        if ccd.isdigit():
            patch["selected_ccds"] = [int(ccd) - 1]
    if "line_width_nm" in patch and "reference_width_points" not in patch:
        width = patch["line_width_nm"]
        if isinstance(width, (int, float)) and width >= 11:
            patch["reference_width_points"] = width
    if "exposure_intervals" in patch and "angle_exposures" not in patch:
        intervals = patch["exposure_intervals"]
        if isinstance(intervals, list):
            patch["angle_exposures"] = [
                {
                    "angle_deg": item.get("angle_deg", item.get("angle", index)),
                    "storage_mode": {
                        "average": "averaged",
                        "full": "full_interval",
                    }.get(item.get("mode"), item.get("mode", "averaged")),
                    "start_frame": item.get("start", 1),
                    "end_frame": item.get("end", patch.get("frame_count", base.get("frame_count", 20))),
                }
                for index, item in enumerate(intervals)
                if isinstance(item, dict)
            ]

    merged = deepcopy(DEFAULT_CONDITIONS)
    merged.update(deepcopy(base))
    merged.update(patch)
    merged["storage_profile"] = "modern_v1"
    return merged


def validate_method_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise MethodDomainError("method_name_required", "方法名称不能为空", fields=["name"])
    try:
        byte_length = len(value.encode("gb18030"))
    except UnicodeEncodeError as exc:
        raise MethodDomainError(
            "method_name_encoding", "方法名称无法使用 GB18030 编码", fields=["name"]
        ) from exc
    if byte_length > NAME_MAX_GB18030_BYTES:
        raise MethodDomainError(
            "method_name_too_long",
            f"方法名称 GB18030 字节长度不能大于 {NAME_MAX_GB18030_BYTES}",
            fields=["name"],
            details={"gb18030_bytes": byte_length, "maximum": NAME_MAX_GB18030_BYTES},
        )
    if any(char in METHOD_NAME_INVALID for char in value):
        raise MethodDomainError(
            "method_name_invalid_character",
            "方法名称不能含有 \\ / : * ? < > |",
            fields=["name"],
        )
    return value
