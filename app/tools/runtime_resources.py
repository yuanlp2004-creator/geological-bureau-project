from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
RESOURCE_ROOT = APP_ROOT / "backend" / "app" / "resources"
RESOURCE_MANIFEST = RESOURCE_ROOT / "resource-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_runtime_resources(*, verify_sources: bool = True) -> dict[str, Any]:
    payload = json.loads(RESOURCE_MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("resources"), list):
        raise RuntimeError("runtime resource manifest schema is invalid")
    seen: set[str] = set()
    for item in payload["resources"]:
        key = str(item.get("key", ""))
        relative = Path(str(item.get("path", "")))
        if not key or key in seen:
            raise RuntimeError(f"runtime resource key is missing or duplicated: {key!r}")
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"runtime resource path escapes its package: {relative}")
        seen.add(key)
        packaged = RESOURCE_ROOT / relative
        _verify_file(packaged, item, label="packaged")
        if verify_sources:
            source = REPO_ROOT / Path(str(item.get("source", "")))
            _verify_file(source, item, label="source")
    return payload


def _verify_file(path: Path, item: dict[str, Any], *, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} runtime resource is missing: {path}")
    expected_bytes = int(item.get("bytes", -1))
    expected_sha256 = str(item.get("sha256", "")).upper()
    if path.stat().st_size != expected_bytes or sha256(path) != expected_sha256:
        raise RuntimeError(f"{label} runtime resource does not match its manifest: {path}")
