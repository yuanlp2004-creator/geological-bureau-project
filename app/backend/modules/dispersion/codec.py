from __future__ import annotations
import hashlib
import struct
import zlib
from .values import DispersionError


def _pack_points(points: list[int]) -> bytes:
    if not points or any(isinstance(point, bool) or point < 0 or point > 65535 for point in points):
        raise DispersionError("dispersion_points_invalid", "色散帧不是有效的 uint16 点数组")
    return struct.pack(f"<{len(points)}H", *points)


def _unpack_points(
    blob: bytes | bytearray | memoryview, points_count: int, expected_sha256: str, compression: str
) -> list[int]:
    try:
        raw = zlib.decompress(bytes(blob)) if compression == "zlib" else b""
    except zlib.error as exc:
        raise DispersionError("dispersion_frame_integrity_failed", "色散帧压缩 BLOB 无法解码") from exc
    if points_count <= 0 or len(raw) != points_count * 2 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise DispersionError(
            "dispersion_frame_integrity_failed",
            "色散帧长度或 SHA-256 校验失败",
            details={"points_count": points_count, "byte_length": len(raw)},
        )
    return list(struct.unpack(f"<{points_count}H", raw))
