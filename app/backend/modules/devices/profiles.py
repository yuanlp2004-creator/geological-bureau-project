from __future__ import annotations
import math
from typing import Any
from .values import ACQ_CCDS_PER_FRAME, ACQ_FRAME_COUNT, ACQ_POINTS_PER_CCD, DEFAULT_CCD_INDICES, DeviceError


DEFAULT_BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]


def _finite_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DeviceError(
            "device_profile_invalid", f"{field_name} must be numeric", details={"field": field_name}
        ) from exc
    if not math.isfinite(number):
        raise DeviceError("device_profile_invalid", f"{field_name} must be finite", details={"field": field_name})
    return number


def validate_profile(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Normalize and validate profile values at the domain boundary."""

    result = dict(payload)
    if not partial or "name" in result:
        name = str(result.get("name", "")).strip()
        if not 1 <= len(name) <= 100:
            raise DeviceError(
                "device_profile_invalid", "name must contain 1 to 100 characters", details={"field": "name"}
            )
        result["name"] = name
    if not partial or "transport" in result:
        transport = str(result.get("transport", "simulator")).lower()
        if transport not in {"simulator", "serial"}:
            raise DeviceError(
                "device_profile_invalid", "transport must be simulator or serial", details={"field": "transport"}
            )
        result["transport"] = transport
    if not partial or "port" in result:
        port = int(result.get("port", 3))
        if not 1 <= port <= 256:
            raise DeviceError("device_profile_invalid", "port must be between 1 and 256", details={"field": "port"})
        result["port"] = port
    if not partial or "baud_rate" in result:
        baud = int(result.get("baud_rate", 460800))
        if baud not in DEFAULT_BAUD_RATES:
            raise DeviceError(
                "device_profile_invalid",
                "unsupported baud rate",
                details={"field": "baud_rate", "allowed": DEFAULT_BAUD_RATES},
            )
        result["baud_rate"] = baud
    if not partial or "frame_count" in result:
        frame_count = int(result.get("frame_count", ACQ_FRAME_COUNT))
        if not 1 <= frame_count <= 32:
            raise DeviceError(
                "device_profile_invalid", "frame_count must be between 1 and 32", details={"field": "frame_count"}
            )
        result["frame_count"] = frame_count
    if not partial or "ccds_per_frame" in result:
        ccds_per_frame = int(result.get("ccds_per_frame", ACQ_CCDS_PER_FRAME))
        if not 1 <= ccds_per_frame <= 8:
            raise DeviceError(
                "device_profile_invalid", "ccds_per_frame must be between 1 and 8", details={"field": "ccds_per_frame"}
            )
        result["ccds_per_frame"] = ccds_per_frame
    if not partial or "points_per_ccd" in result:
        points = int(result.get("points_per_ccd", ACQ_POINTS_PER_CCD))
        if not 1 <= points <= 4096:
            raise DeviceError(
                "device_profile_invalid",
                "points_per_ccd must be between 1 and 4096",
                details={"field": "points_per_ccd"},
            )
        result["points_per_ccd"] = points
    volume = int(result.get("frame_count", ACQ_FRAME_COUNT)) * int(result.get("ccds_per_frame", ACQ_CCDS_PER_FRAME))
    if not partial or "ccd_indices" in result or "selected_ccds" in result:
        if "ccd_indices" in result:
            raw_indices = result["ccd_indices"]
        elif "selected_ccds" in result:
            raw_indices = result["selected_ccds"]
        else:
            raw_indices = DEFAULT_CCD_INDICES if volume >= len(DEFAULT_CCD_INDICES) + 1 else list(range(volume))
        try:
            indices = [int(item) for item in raw_indices]
        except (TypeError, ValueError) as exc:
            raise DeviceError(
                "device_profile_invalid", "ccd_indices must be integers", details={"field": "ccd_indices"}
            ) from exc
        if len(indices) != len(set(indices)) or not indices or any(item < 0 or item >= volume for item in indices):
            raise DeviceError(
                "device_profile_invalid",
                "ccd_indices contains a duplicate or out-of-range index",
                details={"field": "ccd_indices", "volume": volume},
            )
        result["ccd_indices"] = indices
    for field_name, default, minimum, maximum in (
        ("point_width_um", 14.0, 0.001, 1000.0),
        ("protection_time_ms", 200.0, 0.0, 60_000.0),
        ("screen_width_mm", 40.92, 1.0, 10_000.0),
    ):
        if not partial or field_name in result:
            number = _finite_number(result.get(field_name, default), field_name)
            if number < minimum or number > maximum:
                raise DeviceError(
                    "device_profile_invalid",
                    f"{field_name} is outside the supported range",
                    details={"field": field_name},
                )
            result[field_name] = number
    if not partial or "screen_resolution_px" in result:
        resolution = int(result.get("screen_resolution_px", 1920))
        if not 320 <= resolution <= 16_000:
            raise DeviceError(
                "device_profile_invalid",
                "screen_resolution_px is outside the supported range",
                details={"field": "screen_resolution_px"},
            )
        result["screen_resolution_px"] = resolution
    if not partial or "mirror" in result:
        result["mirror"] = bool(result.get("mirror", False))
    if not partial or "enabled" in result:
        result["enabled"] = bool(result.get("enabled", True))
    return result


def screen_conversion(profile: dict[str, Any]) -> dict[str, float]:
    profile = validate_profile(profile)
    pixels_per_mm = profile["screen_resolution_px"] / profile["screen_width_mm"]
    return {
        "pixels_per_mm": pixels_per_mm,
        "um_per_pixel": 1000.0 / pixels_per_mm,
        "point_width_px": profile["point_width_um"] / 1000.0 * pixels_per_mm,
    }
