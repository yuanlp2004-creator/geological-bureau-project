"""Module inventory and optional read-only probes against the current ASGI app."""
from __future__ import annotations

import asyncio
import sqlite3
from graphlib import TopologicalSorter
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from starlette.routing import Match

from ..modules.manifest import ModuleManifest, registered_manifests
from ..schemas.system import ModuleDiagnostic


# Resolve the static dependency order once. Probe results still follow manifest order.
_PROBE_ORDER = tuple(TopologicalSorter({
    manifest.key: manifest.dependencies for manifest in registered_manifests()
}).static_order())


def database_tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def summarize_modules(manifests: tuple[ModuleManifest, ...], tables: set[str]) -> list[ModuleDiagnostic]:
    rows = []
    for manifest in manifests:
        row = ModuleDiagnostic(
            key=manifest.key, title=manifest.title, version=manifest.version, route=manifest.route,
            enabled=manifest.enabled, status="unchecked", message="未执行接口探测（可按需触发）",
            probe_path=manifest.diagnostic_path, note=manifest.diagnostic_note,
        )
        missing_tables = set(manifest.diagnostic_tables) - tables
        if not manifest.enabled:
            row.status, row.message = "disabled", "配置未启用"
        elif missing_tables:
            row.status, row.message = "error", "数据表缺失：" + "、".join(sorted(missing_tables))
        rows.append(row)
    return rows


async def inspect_modules(
    request: Request, manifests: tuple[ModuleManifest, ...], rows: list[ModuleDiagnostic],
) -> list[ModuleDiagnostic]:
    # Forward only this request's authorization and desktop process key.
    headers = {key: request.headers[key] for key in ("authorization", "x-geospectrum-process-key") if key in request.headers}
    transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(transport=transport, base_url="http://module-check.local", headers=headers) as client:
        async def check(manifest: ModuleManifest, row: ModuleDiagnostic) -> None:
            if row.status != "unchecked":
                return
            if not manifest.diagnostic_path:
                row.message = "未配置只读检测"
                return
            path = urlsplit(manifest.diagnostic_path).path
            scope = {**request.scope, "type": "http", "method": "GET", "path": path, "root_path": "", "query_string": b""}
            if not any(route.matches(scope)[0] == Match.FULL for route in request.app.routes):
                row.status, row.message = "error", "只读接口未注册"
                return
            async with semaphore:
                try:
                    response = await asyncio.wait_for(client.get(manifest.diagnostic_path), timeout=3)
                    row.http_status = response.status_code
                    if response.status_code in {401, 403}:
                        row.status, row.message = "restricted", "当前账号无权检测此接口"
                    elif response.status_code != 200:
                        row.status, row.message = "error", f"查询接口异常（HTTP {response.status_code}）"
                    else:
                        expected = list if manifest.diagnostic_response == "list" else dict
                        if not isinstance(response.json(), expected):
                            row.status, row.message = "error", "查询接口响应格式异常"
                        else:
                            row.status, row.message = "active", "数据结构与只读接口检测通过"
                except TimeoutError:
                    row.status, row.message = "error", "查询接口检测超时"
                except Exception:
                    row.status, row.message = "error", "查询接口检测失败"

        await asyncio.gather(*(check(manifest, row) for manifest, row in zip(manifests, rows, strict=True)))

    by_key = {row.key: row for row in rows}
    definitions = {manifest.key: manifest for manifest in manifests}
    for key in _PROBE_ORDER:
        row = by_key[key]
        if row.status != "active":
            continue
        for dependency in definitions[key].dependencies:
            source = by_key[dependency]
            if source.status != "active":
                row.status = "restricted" if source.status in {"restricted", "unchecked"} else "error"
                row.message = f"依赖模块未通过检测：{source.title}"
                break
    return rows
