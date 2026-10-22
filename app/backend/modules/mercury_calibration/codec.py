from __future__ import annotations
import struct
from .values import MercuryError


def _pack(points: list[int]) -> bytes:
    return struct.pack(f"<{len(points)}H", *points)


def _unpack(blob: bytes, count: int) -> list[int]:
    if len(blob) != count * 2:
        raise MercuryError("mercury_frame_invalid", "stored mercury frame length is inconsistent", status_code=409)
    return list(struct.unpack(f"<{count}H", blob))
