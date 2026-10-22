"""Read-only module probes against this application's actual ASGI routes."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from starlette.routing import Match

from ..modules.manifest import ModuleManifest
from ..runtime import Runtime
from ..schemas.system import ModuleDiagnostic


async def inspect_modules(
    request: Request, runtime: Runtime, manifests: tuple[ModuleManifest, ...], manifest_error: str | None,
) -> list[ModuleDiagnostic]:
    with runtime.database.read() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Local ASGI transport cannot send requests to the network. Forward only this
    # request's authorization, preserving both user and desktop process boundaries.
    headers = {key: request.headers[key] for key in ("authorization", "x-geospectrum-process-key") if key in request.headers}
    transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(transport=transport, base_url="http://module-check.local", headers=headers) as client:
        async def check(manifest: ModuleManifest) -> ModuleDiagnostic:
            row = ModuleDiagnostic(key=manifest.key, title=manifest.title, version=manifest.version,
                                   route=manifest.route, enabled=manifest.enabled, status="unchecked",
                                   message="未配置只读检测", probe_path=manifest.diagnostic_path, note=manifest.diagnostic_note)
            if not manifest.enabled:
                row.status, row.message = "disabled", "配置未启用"
                return row
            if manifest_error:
                row.status, row.message = "error", "模块清单结构异常，未执行检测"
                return row
            missing_tables = set(manifest.diagnostic_tables) - tables
            if missing_tables:
                row.status = "error"
                row.message = "数据表缺失：" + "、".join(sorted(missing_tables))
                return row
            if not manifest.diagnostic_path:
                return row
            path = urlsplit(manifest.diagnostic_path).path
            scope = {**request.scope, "type": "http", "method": "GET", "path": path, "root_path": "", "query_string": b""}
            if not any(route.matches(scope)[0] == Match.FULL for route in request.app.routes):
                row.status, row.message = "error", "只读接口未注册"
                return row
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
            return row

        rows = await asyncio.gather(*(check(manifest) for manifest in manifests))
    by_key = {row.key: row for row in rows}
    definitions = {manifest.key: manifest for manifest in manifests}
    resolved: set[str] = set()

    def resolve(key: str, stack: set[str]) -> None:
        if key in resolved:
            return
        row = by_key[key]
        if key in stack:
            row.status, row.message = "error", "模块依赖存在循环"
            return
        for dependency in definitions[key].dependencies:
            if dependency not in by_key:
                if row.status == "active":
                    row.status, row.message = "error", f"依赖模块未注册：{dependency}"
                continue
            resolve(dependency, stack | {key})
            source = by_key[dependency]
            if row.status == "active" and source.status != "active":
                row.status = "restricted" if source.status in {"restricted", "unchecked"} else "error"
                row.message = f"依赖模块未通过检测：{source.title}"
        resolved.add(key)

    for key in by_key:
        resolve(key, set())
    return rows
