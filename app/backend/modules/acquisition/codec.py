from __future__ import annotations
import struct
from .values import AcquisitionError


LOW_AVERAGE = 0.1


def _pack_uint16(points: list[int]) -> bytes:
    if not points:
        return b""
    if any(point < 0 or point > 65535 for point in points):
        raise AcquisitionError("acquisition_points_invalid", "CCD 点值超出 uint16 范围")
    return struct.pack(f"<{len(points)}H", *points)


def _unpack_uint16(blob: bytes | bytearray | memoryview | None, points_count: int) -> list[int]:
    if blob is None or points_count == 0:
        return []
    expected = points_count * 2
    if len(blob) != expected:
        raise AcquisitionError(
            "acquisition_blob_invalid", "原始 CCD BLOB 长度不匹配", details={"expected": expected, "actual": len(blob)}
        )
    return list(struct.unpack(f"<{points_count}H", blob))


def _pack_float32(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _unpack_float32(blob: bytes, points_count: int) -> list[float]:
    expected = points_count * 4
    if len(blob) != expected:
        raise AcquisitionError(
            "acquisition_blob_invalid", "均值 BLOB 长度不匹配", details={"expected": expected, "actual": len(blob)}
        )
    return list(struct.unpack(f"<{points_count}f", blob))


def average_points(
    burn_blobs: list[bytes],
    dark_blobs: list[bytes],
    points_count: int,
    *,
    burn_cycle_seconds: float = 1.0,
    dark_cycle_seconds: float = 1.0,
) -> bytes:
    """Match TCcdBand.CalAllAvgs: burn mean minus dark mean, floored at LowAvg=0.1."""

    if not burn_blobs:
        raise AcquisitionError("acquisition_burn_missing", "没有可用于均值计算的燃烧帧")
    burns = [_unpack_uint16(blob, points_count) for blob in burn_blobs]
    darks = [_unpack_uint16(blob, points_count) for blob in dark_blobs]
    values: list[float] = []
    for point_index in range(points_count):
        burn = sum(frame[point_index] for frame in burns) / (len(burns) * burn_cycle_seconds)
        dark = sum(frame[point_index] for frame in darks) / (len(darks) * dark_cycle_seconds) if darks else 0.0
        values.append(max(LOW_AVERAGE, burn - dark))
    return _pack_float32(values)
