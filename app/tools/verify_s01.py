from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify(database_path: Path, manifest_path: Path, dist_dir: Path) -> dict:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result = {
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "schema_version": connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
            "required_tables": all(name in tables for name in ("app_metadata", "app_settings", "runtime_events")),
            "tables": tables,
        }
    finally:
        connection.close()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = sorted(path for path in dist_dir.rglob("*") if path.is_file())
    result.update(
        {
            "manifest_modules": [module["key"] for module in manifest["modules"]],
            "manifest_sha256": sha256(manifest_path),
            "frontend_asset_count": len(assets),
            "frontend_asset_bytes": sum(path.stat().st_size for path in assets),
            "frontend_assets_have_sha256": all(len(sha256(path)) == 64 for path in assets),
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.database, args.manifest, args.dist)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    checks = [result["integrity_check"] == "ok", result["foreign_keys"] == 1, result["journal_mode"].lower() == "wal", result["schema_version"] == 1, result["required_tables"], result["frontend_asset_count"] > 0, result["frontend_assets_have_sha256"]]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
