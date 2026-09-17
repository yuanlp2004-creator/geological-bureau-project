"""System, settings and runtime-message HTTP endpoints."""
from __future__ import annotations

import platform
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import __version__
from ..auth import Session
from ..runtime import Runtime
from ..modules.manifest import registered_manifests, validate_manifests
from ..schemas.system import (
    AboutResponse,
    CapabilitiesResponse,
    Capability,
    DiagnosticsResponse,
    HealthResponse,
    RuntimeEvent,
    RuntimeEventCreate,
    SettingsPatch,
    SettingsResponse,
)
from .dependencies import get_runtime, require_permission

router = APIRouter()


def _capabilities() -> list[Capability]:
    # 后端清单是导航和权限的事实来源；前端只过滤此响应，不得维护第二份模块列表。
    manifests = registered_manifests()
    validate_manifests(manifests)
    return [
        Capability(
            key=manifest.key,
            version=manifest.version,
            title=manifest.title,
            api_prefix=manifest.api_prefix,
            route=manifest.route,
            enabled=manifest.enabled,
            permissions=list(manifest.permissions),
            audit_actions=list(manifest.audit_actions),
            navigation_entries=[entry.to_dict() for entry in manifest.navigation_entries],
        )
        for manifest in manifests
    ]


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(*, runtime: Runtime = Depends(get_runtime)) -> HealthResponse:
    return HealthResponse(**runtime.service.health())


@router.get("/about", response_model=AboutResponse, tags=["system"])
@router.get("/api/v1/about", response_model=AboutResponse, include_in_schema=False)
def about(_: Session = Depends(require_permission("about.read")), *, runtime: Runtime = Depends(get_runtime)) -> AboutResponse:
    return AboutResponse(
        name="geospectrum",
        display_name="GeoSpectrum 自动转角平面光栅光谱仪分析平台",
        version=__version__,
        api_version="v1",
        stage="S21 · Windows 内部测试发布",
        description="面向 SpecDirect 2.0.2 兼容重构的本地分析工作台。",
        runtime=f"Python {platform.python_version()} · {platform.system()}",
        database=str(runtime.config.database_path),
        modules=[manifest.to_dict() for manifest in registered_manifests()],
        license="内部测试包（未签名，不得作为正式发布）",
        build={"version": __version__, "schema_version": 20, "api_version": "v1", "python": platform.python_version(), "channel": "internal-test", "signed": False},
    )


@router.get("/api/v1/capabilities", response_model=CapabilitiesResponse, tags=["system"])
def capabilities(*, runtime: Runtime = Depends(get_runtime)) -> CapabilitiesResponse:
    return CapabilitiesResponse(
        api_version="v1",
        generated_at=datetime.now(timezone.utc),
        capabilities=_capabilities(),
    )


@router.get("/api/v1/diagnostics", response_model=DiagnosticsResponse, tags=["system"])
def diagnostics(_: Session = Depends(require_permission("about.read")), *, runtime: Runtime = Depends(get_runtime)) -> DiagnosticsResponse:
    validate_manifests(registered_manifests())
    with runtime.database.read() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        schema_version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        event_count = connection.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
    return DiagnosticsResponse(
        service="ok",
        database_path=str(runtime.config.database_path),
        runtime_log_path=str(runtime.config.runtime_log_path),
        schema_version=schema_version,
        sqlite_integrity=integrity,
        journal_mode=journal_mode,
        foreign_keys=foreign_keys,
        event_count=event_count,
        manifest_valid=True,
    )


@router.get("/api/v1/settings", response_model=SettingsResponse, tags=["settings"])
def get_settings(_: Session = Depends(require_permission("settings.read")), *, runtime: Runtime = Depends(get_runtime)) -> SettingsResponse:
    return SettingsResponse(**runtime.service.get_settings())


@router.patch("/api/v1/settings", response_model=SettingsResponse, tags=["settings"])
async def patch_settings(patch: SettingsPatch, session: Session = Depends(require_permission("settings.write")), *, runtime: Runtime = Depends(get_runtime)) -> SettingsResponse:
    try:
        settings = runtime.service.update_settings(patch, session.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    event = runtime.service.list_events(limit=1)[0]
    await runtime.publish(event)
    return SettingsResponse(**settings)


@router.post("/api/v1/settings/reset", response_model=SettingsResponse, tags=["settings"])
async def reset_settings(session: Session = Depends(require_permission("settings.write")), *, runtime: Runtime = Depends(get_runtime)) -> SettingsResponse:
    settings = runtime.service.reset_settings(session.user_id)
    event = runtime.service.list_events(limit=1)[0]
    await runtime.publish(event)
    return SettingsResponse(**settings)


@router.get("/api/v1/logs", response_model=list[RuntimeEvent], tags=["runtime-events"])
@router.get("/api/v1/events", response_model=list[RuntimeEvent], include_in_schema=False)
def list_logs(
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: Session = Depends(require_permission("runtime-events.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[RuntimeEvent]:
    return [RuntimeEvent(**event) for event in runtime.service.list_events(category=category, severity=severity, limit=limit)]


@router.post("/api/v1/logs", response_model=RuntimeEvent, status_code=201, tags=["runtime-events"])
async def create_log(event: RuntimeEventCreate, session: Session = Depends(require_permission("runtime-events.write")), *, runtime: Runtime = Depends(get_runtime)) -> RuntimeEvent:
    result = runtime.service.append_event(event, actor_user_id=session.user_id, audit_action="runtime_event.create")
    await runtime.publish(result)
    return RuntimeEvent(**result)


@router.delete("/api/v1/logs", tags=["runtime-events"])
async def clear_logs(session: Session = Depends(require_permission("runtime-events.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, int]:
    deleted = runtime.service.clear_events(actor_user_id=session.user_id)
    event = runtime.service.append_event(RuntimeEventCreate(category="action", severity="info", message="运行消息已清空"))
    await runtime.publish(event)
    return {"deleted": deleted}
