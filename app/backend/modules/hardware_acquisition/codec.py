from __future__ import annotations
import struct
from .values import HardwareError


def _pack_points(points: list[int]) -> bytes:
    if any(int(point) < 0 or int(point) > 65535 for point in points):
        raise HardwareError("hardware_points_invalid", "CCD points must fit uint16")
    return struct.pack(f"<{len(points)}H", *[int(point) for point in points])


def _unpack_points(blob: bytes | None, count: int) -> list[int]:
    if blob is None:
        return []
    if len(blob) != count * 2:
        raise HardwareError(
            "hardware_frame_invalid",
            "CCD frame payload length is inconsistent",
            details={"expected": count * 2, "actual": len(blob)},
        )
    return list(struct.unpack(f"<{count}H", blob))
