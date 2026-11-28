"""Explicit assembly for the S21 manifest-only release rehearsal."""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse

from backend.api.dependencies import get_runtime, require_permission
from backend.auth import AuthService, Session
from backend.config import AppConfig
from backend.db import Database, utc_now
from backend.main import create_app
from backend.modules.manifest import ModuleManifest, nav, registered_manifests, validate_manifests
from backend.runtime import Runtime

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,95}$")
ALLOWED_TAURI_CAPABILITIES = frozenset({"dialog:allow-open", "dialog:allow-save", "shell:allow-open"})


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
            navigation_entries=(
                nav(self.key, "system", "扩展", self.title, "测试构建示例", "extension", 90,
                    (self.permission,)),
            ),
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
    if not manifest.version or not manifest.title or not re.fullmatch(r"/test-[a-z0-9-]+", manifest.route):
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


def discover_test_extensions(root: Path) -> tuple[ExtensionManifest, ...]:
    if not root.is_dir():
        raise ValueError(f"test module directory does not exist: {root}")
    manifests = tuple(_load_manifest(path) for path in sorted(root.glob("*/manifest.json")))
    keys = [item.key for item in manifests]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate extension module key")
    return manifests


def apply_test_extension_migrations(
    connection: sqlite3.Connection, extensions: tuple[ExtensionManifest, ...],
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        (
            "CREATE TABLE IF NOT EXISTS extension_schema_migrations(module_key TEXT NOT "
            "NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL, PRIMARY "
            "KEY(module_key, version))"
        )
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
            (extension.key, extension.migration_version, utc_now()),
        )


class _ExtensionDatabase(Database):
    def __init__(self, path: Path, extensions: tuple[ExtensionManifest, ...]):
        super().__init__(path)
        self.extensions = extensions

    def initialize(self) -> None:
        super().initialize()
        with self.write() as connection:
            apply_test_extension_migrations(connection, self.extensions)


class _ExtensionAuthService(AuthService):
    def __init__(self, database: Database, extensions: tuple[ExtensionManifest, ...]):
        super().__init__(database)
        extension_permissions = tuple(extension.permission for extension in extensions)
        self.builtin_roles = tuple(
            (name, description, permissions + extension_permissions if name == "system_administrator" else permissions)
            for name, description, permissions in self.builtin_roles
        )


def _execute(extension: ExtensionManifest):
    async def execute(
        session: Session = Depends(require_permission(extension.permission)), *, runtime: Runtime = Depends(get_runtime),
    ) -> dict[str, Any]:
        created_at = utc_now()
        payload = {"event_type": extension.event_type, "event_version": 1, "module": extension.key,
                   "created_at": created_at}
        details = json.dumps(payload, ensure_ascii=False)
        table = extension.key.replace("-", "_") + "_records"
        with runtime.database.write() as connection:
            record_id = connection.execute(
                f"INSERT INTO {table}(event_version, payload_json, created_at) VALUES (1, ?, ?)", (details, created_at),
            ).lastrowid
            connection.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session.user_id, extension.audit_action, extension.key, record_id, details, created_at),
            )
            event_id = connection.execute(
                "INSERT INTO runtime_events(category, severity, message, details_json, correlation_id, created_at) "
                "VALUES ('action', 'success', ?, ?, ?, ?)",
                (extension.title, details, extension.event_type, created_at),
            ).lastrowid
        event = {"id": event_id, "category": "action", "severity": "success", "message": extension.title,
                 "details": payload, "correlation_id": extension.event_type, "created_at": created_at}
        for queue in tuple(runtime.event_subscribers):
            try:
                queue.put_nowait({"type": extension.event_type, "version": 1, "event": event})
            except asyncio.QueueFull:
                pass
        return {"record_id": record_id, **payload}

    return execute


def register_extensions(application: FastAPI, extensions: tuple[ExtensionManifest, ...]) -> None:
    @application.get("/test-build", response_class=HTMLResponse)
    def test_navigation() -> str:
        links = "".join(f'<li><a href="{extension.route}">{escape(extension.title)}</a></li>' for extension in extensions)
        return f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><nav><ul>{links}</ul></nav></html>'

    def extension_page(extension: ExtensionManifest, endpoint: str):
        def page() -> str:
            return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
                <h1>{escape(extension.title)}</h1>
                <label>测试访问令牌 <input id="token" type="password"></label>
                <button id="execute">执行版本化事件</button><output></output>
                <script>
                document.querySelector('#execute').onclick = async () => {{
                    const token = document.querySelector('#token').value;
                    const result = await fetch({json.dumps(endpoint)}, {{
                        method: 'POST', headers: {{Authorization: 'Bearer ' + token}}
                    }});
                    document.querySelector('output').textContent = await result.text();
                }};
                </script></html>"""
        return page

    for extension in extensions:
        endpoint = f"/api/v1/extensions/{extension.key}/execute"
        application.add_api_route(endpoint, _execute(extension), methods=["POST"], tags=["test-extension"])
        application.add_api_route(extension.route, extension_page(extension, endpoint), methods=["GET"],
                                  response_class=HTMLResponse)


def create_test_build(config: AppConfig, fixture_root: Path) -> FastAPI:
    extensions = discover_test_extensions(fixture_root)
    manifests = registered_manifests() + tuple(extension.module_manifest() for extension in extensions)
    validate_manifests(manifests)
    database = _ExtensionDatabase(config.database_path, extensions)
    runtime = Runtime(config, database=database)
    runtime.auth_service = _ExtensionAuthService(database, extensions)
    application = create_app(runtime=runtime)

    @application.get("/test-build/manifest")
    def test_manifest() -> dict:
        return {"modules": [manifest.to_dict() for manifest in manifests]}

    register_extensions(application, extensions)
    return application
