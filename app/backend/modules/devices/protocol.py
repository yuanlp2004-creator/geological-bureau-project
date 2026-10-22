from __future__ import annotations
import hashlib
import struct
from typing import Any, Protocol
from .profiles import validate_profile
from .values import ACQ_CCDS_PER_FRAME, ACQ_FRAME_COUNT, ACQ_HEADER_GOOD, ACQ_POINTS_PER_CCD, DeviceError, DeviceEvent


def _ccd_points(
    raw_frames: list[list[int]],
    ccd_index: int,
    *,
    frame_count: int,
    ccds_per_frame: int,
    points_per_ccd: int,
    mirror: bool,
) -> list[int]:
    volume = frame_count * ccds_per_frame
    if ccd_index < 0 or ccd_index >= volume:
        raise DeviceError(
            "ccd_index_invalid",
            "CCD index is outside the frame layout",
            details={"ccd_index": ccd_index, "volume": volume},
        )
    if mirror:
        frame_index = ccd_index // ccds_per_frame
        slot = ccd_index % ccds_per_frame
        values = [raw_frames[frame_index][ccds_per_frame * point + slot] for point in range(points_per_ccd)]
        return list(reversed(values))
    frame_index = (volume - (ccd_index + 1)) // ccds_per_frame
    slot = (ccds_per_frame - 1) - ccd_index % ccds_per_frame
    return [raw_frames[frame_index][ccds_per_frame * point + slot] for point in range(points_per_ccd)]


def parse_acq_frame(
    payload: bytes,
    *,
    frame_count: int = ACQ_FRAME_COUNT,
    ccds_per_frame: int = ACQ_CCDS_PER_FRAME,
    points_per_ccd: int = ACQ_POINTS_PER_CCD,
    mirror: bool = False,
    ccd_indices: list[int] | None = None,
) -> dict[str, Any]:
    """Parse one legacy ACQ transfer without allocating an unbounded buffer."""

    if frame_count < 1 or ccds_per_frame < 1 or points_per_ccd < 1:
        raise DeviceError("acq_layout_invalid", "ACQ layout dimensions must be positive")
    frame_size = 1 + ccds_per_frame * points_per_ccd * 2
    expected = frame_count * frame_size
    if len(payload) != expected:
        offset = min(len(payload), expected)
        raw_header = payload[offset] if offset < len(payload) else None
        raise DeviceError(
            "acq_frame_incomplete",
            "ACQ frame length does not match the selected layout",
            details={"offset": offset, "expected": expected, "actual": len(payload), "raw_header": raw_header},
        )
    raw_frames: list[list[int]] = []
    headers: list[int] = []
    for frame_index in range(frame_count):
        offset = frame_index * frame_size
        header = payload[offset]
        headers.append(header)
        if header != ACQ_HEADER_GOOD:
            raise DeviceError(
                "acq_frame_header_invalid",
                "ACQ frame header indicates a CCD checksum/fault error",
                details={"offset": offset, "frame_index": frame_index, "raw_header": header},
            )
        count = ccds_per_frame * points_per_ccd
        raw_frames.append(list(struct.unpack_from(f"<{count}H", payload, offset + 1)))
    volume = frame_count * ccds_per_frame
    selected = ccd_indices if ccd_indices is not None else list(range(volume))
    normalized = validate_profile(
        {
            "name": "_acq",
            "frame_count": frame_count,
            "ccds_per_frame": ccds_per_frame,
            "points_per_ccd": points_per_ccd,
            "ccd_indices": selected,
            "mirror": mirror,
        },
        partial=False,
    )
    ccds: list[dict[str, Any]] = []
    for ccd_index in normalized["ccd_indices"]:
        points = _ccd_points(
            raw_frames,
            ccd_index,
            frame_count=frame_count,
            ccds_per_frame=ccds_per_frame,
            points_per_ccd=points_per_ccd,
            mirror=mirror,
        )
        peak = max(points)
        ccds.append({"ccd_index": ccd_index, "points": points, "peak": peak, "peak_position": points.index(peak)})
    return {
        "frame_count": frame_count,
        "ccds_per_frame": ccds_per_frame,
        "points_per_ccd": points_per_ccd,
        "frame_size": frame_size,
        "byte_length": len(payload),
        "headers": headers,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mirror": mirror,
        "ccd_indices": normalized["ccd_indices"],
        "ccds": ccds,
        "raw_frames": raw_frames,
    }


class DeviceAdapter(Protocol):
    def connect(self, profile: dict[str, Any], *, correlation_id: str) -> DeviceEvent: ...
    def disconnect(self, *, correlation_id: str) -> DeviceEvent: ...
    def start_debug(self, *, sample: str, seed: int, fault_frame: int | None, correlation_id: str) -> DeviceEvent: ...
    def step_debug(self, *, correlation_id: str) -> DeviceEvent: ...
    def stop_debug(self, *, correlation_id: str) -> DeviceEvent: ...
