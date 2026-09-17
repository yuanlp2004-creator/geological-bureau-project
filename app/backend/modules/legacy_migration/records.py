"""旧数值、标准点和色散 BLOB 解码与证据校验。"""

from __future__ import annotations

import base64
import math
import struct
from typing import Any
from .errors import LegacyMigrationError
from .sources import _sha256_bytes


def _number(value: Any, *, integer: bool = False, default: float | int = 0) -> float | int:
    if isinstance(value, dict) and value.get("kind") == "number":
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(str(value)) if integer else float(str(value))
    except (TypeError, ValueError):
        return default


def _blob(value: Any, *, field: str, expected_lengths: set[int] | None = None) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(value, dict) or value.get("kind") != "blob":
        raise LegacyMigrationError("legacy_blob_missing", f"{field} 不是有效的旧版 BLOB")
    try:
        raw = base64.b64decode(str(value["base64"]), validate=True)
    except (KeyError, ValueError) as exc:
        raise LegacyMigrationError("legacy_blob_base64_invalid", f"{field} 的 BLOB 编码无效") from exc
    if int(value.get("byte_length", -1)) != len(raw) or value.get("sha256") != _sha256_bytes(raw):
        raise LegacyMigrationError("legacy_blob_hash_mismatch", f"{field} 的长度或 SHA-256 校验失败")
    if expected_lengths is not None and len(raw) not in expected_lengths:
        raise LegacyMigrationError(
            "legacy_blob_length_invalid",
            f"{field} 的 BLOB 长度不受支持",
            details={"actual": len(raw), "expected": sorted(expected_lengths)},
        )
    return raw, {"byte_length": len(raw), "sha256": _sha256_bytes(raw), "base64": value["base64"]}


class LegacyRecordDecoder:

    @staticmethod
    def _standard_blob(value: Any, field: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raw, evidence = _blob(value, field=field, expected_lengths={224, 700})
        record_count = len(raw) // 14
        parsed: list[dict[str, Any]] = []
        for index in range(record_count):
            content, raw_black, current_black, valid, active = struct.unpack_from("<fffBB", raw, index * 14)
            if not all(math.isfinite(item) for item in (content, raw_black, current_black)):
                raise LegacyMigrationError("legacy_standard_nonfinite", f"{field} 包含非有限浮点数")
            if valid:
                parsed.append(
                    {
                        "index": index,
                        "content": content,
                        "raw_black": raw_black,
                        "current_black": current_black,
                        "valid": bool(valid),
                        "active": bool(active),
                    }
                )
        evidence.update({"record_size": 14, "record_count": record_count, "valid_count": len(parsed), "records": parsed})
        return [
            {"name": f"S{item['index'] + 1}", "value": item["content"], "active": item["active"]}
            for item in parsed
        ], evidence

    @staticmethod
    def _wstc(row: dict[str, Any], *, field: str) -> dict[str, Any]:
        count = int(_number(row.get("CcdCount"), integer=True, default=0))
        gaps_raw, gaps_evidence = _blob(row.get("CcdGapPoints"), field=f"{field}.CcdGapPoints")
        indices_raw, indices_evidence = _blob(row.get("CcdIndexs"), field=f"{field}.CcdIndexs")
        coefficients_raw, coefficients_evidence = _blob(row.get("WsCof"), field=f"{field}.WsCof")
        if len(gaps_raw) != count * 4 or len(indices_raw) != count:
            raise LegacyMigrationError("legacy_wstc_shape_invalid", f"{field} 的 CCD BLOB 与 CcdCount 不一致")
        expected_coefficients = int(_number(row.get("FrameCount"), integer=True)) * int(_number(row.get("CcdsPerFrame"), integer=True))
        if len(coefficients_raw) != expected_coefficients * 4:
            raise LegacyMigrationError("legacy_wstc_shape_invalid", f"{field} 的色散系数数量不一致")
        return {
            "legacy_id": int(_number(row.get("WsId"), integer=True, default=-1)),
            "name": str(row.get("WsName") or "未命名色散"),
            "modified_at": row.get("ModifyTime"),
            "frame_count": int(_number(row.get("FrameCount"), integer=True)),
            "ccds_per_frame": int(_number(row.get("CcdsPerFrame"), integer=True)),
            "points_per_ccd": int(_number(row.get("PointsPerCcd"), integer=True)),
            "point_width": float(_number(row.get("PointWidth"))),
            "gap_points": list(struct.unpack(f"<{count}f", gaps_raw)),
            "ccd_indices": list(indices_raw),
            "coefficients": list(struct.unpack(f"<{expected_coefficients}f", coefficients_raw)),
            "blob_evidence": {
                "CcdGapPoints": gaps_evidence,
                "CcdIndexs": indices_evidence,
                "WsCof": coefficients_evidence,
            },
        }

