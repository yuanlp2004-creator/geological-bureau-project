from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import ModuleManifest


KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,95}$")
ALLOWED_TAURI_CAPABILITIES = frozenset({"dialog:allow-open", "dialog:allow-save", "shell:allow-open"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class ExtensionManifest:
    key: str
    version: str
    title: str
    route: str
    permission: str
    audit_action: str
    event_type: str
    migration_version: int
    migration_sql: str
    tauri_capabilities: tuple[str, ...]

    def module_manifest(self) -> ModuleManifest:
        return ModuleManifest(
            key=self.key,
            version=self.version,
            title=self.title,
            api_prefix="/api/v1",
            route=self.route,
            permissions=(self.permission,),
            audit_actions=(self.audit_action,),
            dependencies=("core", "auth"),
            capabilities=(f"event:{self.event_type}", *(f"tauri:{item}" for item in self.tauri_capabilities)),
        )


def _load_manifest(path: Path) -> ExtensionManifest:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    migration = payload.get("migration") or {}
    manifest = ExtensionManifest(
        key=str(payload.get("key", "")),
        version=str(payload.get("version", "")),
        title=str(payload.get("title", "")),
        route=str(payload.get("route", "")),
        permission=str(payload.get("permission", "")),
        audit_action=str(payload.get("audit_action", "")),
        event_type=str(payload.get("event_type", "")),
        migration_version=int(migration.get("version", 0)),
        migration_sql=str(migration.get("sql", "")),
        tauri_capabilities=tuple(str(item) for item in payload.get("tauri_capabilities", [])),
    )
    if not KEY_PATTERN.fullmatch(manifest.key) or not PERMISSION_PATTERN.fullmatch(manifest.permission):
        raise ValueError(f"invalid extension key or permission in {path}")
    if not manifest.version or not manifest.title or not manifest.route.startswith("/test-"):
        raise ValueError(f"invalid extension metadata in {path}")
    if manifest.migration_version < 1 or not manifest.migration_sql.strip():
        raise ValueError(f"missing extension migration in {path}")
    if set(manifest.tauri_capabilities).difference(ALLOWED_TAURI_CAPABILITIES):
        raise ValueError(f"extension requests unsupported Tauri capability in {path}")
    statements = [item.strip() for item in manifest.migration_sql.split(";") if item.strip()]
    if not statements or any(not item.upper().startswith(("CREATE TABLE", "CREATE INDEX")) for item in statements):
        raise ValueError(f"extension migrations may only create owned tables or indexes: {path}")
    required_prefix = manifest.key.replace("-", "_") + "_"
    if required_prefix not in manifest.migration_sql:
        raise ValueError(f"extension migration must use table prefix {required_prefix}")
    return manifest


def discover_test_extensions() -> tuple[ExtensionManifest, ...]:
    if os.environ.get("GEOSPECTRUM_TEST_BUILD") != "1":
        return ()
    root_value = os.environ.get("GEOSPECTRUM_TEST_MODULES_DIR", "")
    if not root_value:
        return ()
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"test module directory does not exist: {root}")
    manifests = tuple(_load_manifest(path) for path in sorted(root.glob("*/manifest.json")))
    keys = [item.key for item in manifests]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate extension module key")
    return manifests


def apply_test_extension_migrations(connection: sqlite3.Connection) -> None:
    extensions = discover_test_extensions()
    if not extensions:
        return
    connection.execute(
        "CREATE TABLE IF NOT EXISTS extension_schema_migrations(module_key TEXT NOT NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL, PRIMARY KEY(module_key, version))"
    )
    for extension in extensions:
        applied = connection.execute(
            "SELECT 1 FROM extension_schema_migrations WHERE module_key=? AND version=?",
            (extension.key, extension.migration_version),
        ).fetchone()
        if applied:
            continue
        statement = ""
        for line in extension.migration_sql.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                connection.execute(statement.strip())
                statement = ""
        if statement.strip():
            raise sqlite3.OperationalError("incomplete extension migration statement")
        connection.execute(
            "INSERT INTO extension_schema_migrations(module_key, version, applied_at) VALUES (?, ?, ?)",
            (extension.key, extension.migration_version, _utc_now()),
        )
