"""只读源文件快照与指纹。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from ..methods import _json
from .errors import LegacyMigrationError


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_json(value).encode("utf-8"))


def _source_snapshot(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        raw = path.read_bytes()
    except OSError as exc:
        raise LegacyMigrationError(
            "legacy_source_unreadable", f"无法读取旧版源文件：{path}", details={"reason": str(exc)}
        ) from exc
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256_bytes(raw),
    }
