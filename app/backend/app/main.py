from __future__ import annotations

import asyncio
import json
import platform
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

from . import __version__
from .config import config
from .db import Database, utc_now
from .modules.manifest import registered_manifests, validate_manifests
from .schemas import (
    AboutResponse,
    CapabilitiesResponse,
    Capability,
    DiagnosticsResponse,
    HealthResponse,
    RuntimeEvent,
    RuntimeEventCreate,
    SettingsPatch,
    SettingsResponse,
    MethodActionRequest,
    MethodCreate,
    MethodCurrentResponse,
    MethodPrintRequest,
    MethodPrintSettings,
    MethodRenderRequest,
    MethodResponse,
    MethodUpdate,
    MethodVersion,
    SpectralLineDetectRequest,
    SpectralLineInput,
    SpectralLineReorder,
    LegacyMigrationStageRequest,
    LegacyMigrationCommitRequest,
    SpectrumMigrationStageRequest,
    SpectrumMigrationCommitRequest,
    SpectrumPrintRequest,
    ResultMigrationStageRequest,
    ResultMigrationCommitRequest,
    SampleQueueCreate, SampleQueueUpdate, SampleQueueRename, SampleQueueImport,
)
from .services import AppService
from .auth import BUILTIN_ROLES, AuthService, Session, hash_password, require_permission, require_session
from .schemas import BootstrapRequest, LoginRequest, UserCreate, UserUpdate, RoleCreate, RoleUpdate
from .modules.methods import MethodDomainError, MethodService
from .modules.method_printing import MethodPrintService
from .modules.spectral_lines import SpectralLineService
from .modules.legacy_migration import LegacyMigrationError, LegacyMigrationService
from .modules.sample_queues import SampleQueueError, SampleQueueService
from .modules.spectrum_migration import SpectrumMigrationService
from .modules.result_migration import ResultMigrationError, ResultMigrationService
from .modules.spectrum_viewer import SpectrumViewerError, SpectrumViewerService

database = Database(config.database_path)
service = AppService(database, config.runtime_log_path)
auth_service = AuthService(database)
event_subscribers: set[asyncio.Queue[dict]] = set()


def methods_service() -> MethodService:
    # Resolve against the module-level database on every request so test
    # fixtures and the Tauri sidecar can swap their isolated data directory.
    return MethodService(database)


def spectral_lines_service() -> SpectralLineService:
    return SpectralLineService(database)


def method_print_service() -> MethodPrintService:
    return MethodPrintService(database)


def legacy_migration_service() -> LegacyMigrationService:
    return LegacyMigrationService(database)


def sample_queue_service() -> SampleQueueService:
    return SampleQueueService(database)


def spectrum_migration_service() -> SpectrumMigrationService:
    return SpectrumMigrationService(database)


def result_migration_service() -> ResultMigrationService:
    return ResultMigrationService(database)


def spectrum_viewer_service() -> SpectrumViewerService:
    return SpectrumViewerService(database)


def method_error(exc: MethodDomainError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def legacy_migration_error(exc: LegacyMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def sample_queue_error(exc: SampleQueueError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def spectrum_migration_error(exc: LegacyMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def result_migration_error(exc: ResultMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def spectrum_viewer_error(exc: SpectrumViewerError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_directories()
    database.initialize()
    auth_service.synchronize_builtin_permissions()
    service.append_event(RuntimeEventCreate(category="system", severity="success", message="本地服务已启动"))
    yield
    service.append_event(RuntimeEventCreate(category="system", severity="info", message="本地服务已停止"))


app = FastAPI(title="GeoSpectrum API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "tauri://localhost"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-ID"],
    expose_headers=["X-Page-Count", "X-Field-Count", "X-Method-Version", "X-Content-SHA256", "Content-Disposition"],
)


def _capabilities() -> list[Capability]:
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
        )
        for manifest in manifests
    ]


async def _publish(event: dict) -> None:
    if event.get("category") not in {"acquisition", "analysis", "import", "export"}:
        return
    for queue in tuple(event_subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(**service.health())


@app.get("/about", response_model=AboutResponse, tags=["system"])
@app.get("/api/v1/about", response_model=AboutResponse, include_in_schema=False)
def about() -> AboutResponse:
    return AboutResponse(
        name="geospectrum",
        display_name="GeoSpectrum 自动转角平面光栅光谱仪分析平台",
        version=__version__,
        api_version="v1",
        stage="S10 · 谱图查看与交互",
        description="面向 SpecDirect 2.0.2 兼容重构的本地分析工作台。",
        runtime=f"Python {platform.python_version()} · {platform.system()}",
        database=str(config.database_path),
        modules=[manifest.to_dict() for manifest in registered_manifests()],
    )


@app.get("/api/v1/capabilities", response_model=CapabilitiesResponse, tags=["system"])
def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        api_version="v1",
        generated_at=datetime.now(timezone.utc),
        capabilities=_capabilities(),
    )


@app.get("/api/v1/diagnostics", response_model=DiagnosticsResponse, tags=["system"])
def diagnostics() -> DiagnosticsResponse:
    validate_manifests(registered_manifests())
    with database.read() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        schema_version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        event_count = connection.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
    return DiagnosticsResponse(
        service="ok",
        database_path=str(config.database_path),
        runtime_log_path=str(config.runtime_log_path),
        schema_version=schema_version,
        sqlite_integrity=integrity,
        journal_mode=journal_mode,
        foreign_keys=foreign_keys,
        event_count=event_count,
        manifest_valid=True,
    )


@app.get("/api/v1/settings", response_model=SettingsResponse, tags=["settings"])
def get_settings(_: Session = Depends(require_permission("settings.read"))) -> SettingsResponse:
    return SettingsResponse(**service.get_settings())


@app.patch("/api/v1/settings", response_model=SettingsResponse, tags=["settings"])
async def patch_settings(patch: SettingsPatch, session: Session = Depends(require_permission("settings.write"))) -> SettingsResponse:
    try:
        settings = service.update_settings(patch, session.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    event = service.list_events(limit=1)[0]
    await _publish(event)
    return SettingsResponse(**settings)


@app.post("/api/v1/settings/reset", response_model=SettingsResponse, tags=["settings"])
async def reset_settings(session: Session = Depends(require_permission("settings.write"))) -> SettingsResponse:
    settings = service.reset_settings(session.user_id)
    event = service.list_events(limit=1)[0]
    await _publish(event)
    return SettingsResponse(**settings)


@app.get("/api/v1/logs", response_model=list[RuntimeEvent], tags=["runtime-events"])
@app.get("/api/v1/events", response_model=list[RuntimeEvent], include_in_schema=False)
def list_logs(
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: Session = Depends(require_permission("runtime-events.read")),
) -> list[RuntimeEvent]:
    return [RuntimeEvent(**event) for event in service.list_events(category=category, severity=severity, limit=limit)]


@app.post("/api/v1/logs", response_model=RuntimeEvent, status_code=201, tags=["runtime-events"])
async def create_log(event: RuntimeEventCreate, session: Session = Depends(require_permission("runtime-events.write"))) -> RuntimeEvent:
    result = service.append_event(event, actor_user_id=session.user_id, audit_action="runtime_event.create")
    await _publish(result)
    return RuntimeEvent(**result)


@app.delete("/api/v1/logs", tags=["runtime-events"])
async def clear_logs(session: Session = Depends(require_permission("runtime-events.write"))) -> dict[str, int]:
    deleted = service.clear_events(actor_user_id=session.user_id)
    event = service.append_event(RuntimeEventCreate(category="action", severity="info", message="运行消息已清空"))
    await _publish(event)
    return {"deleted": deleted}

@app.post("/api/v1/auth/bootstrap", status_code=201, tags=["auth"])
def bootstrap(payload: BootstrapRequest) -> dict:
    try:
        return auth_service.bootstrap(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/auth/status", tags=["auth"])
def auth_status() -> dict:
    """Public status used by the first-run UI; it never exposes account data."""
    return {"bootstrapped": auth_service.is_bootstrapped()}

@app.post("/api/v1/auth/login", tags=["auth"])
def login(payload: LoginRequest) -> dict:
    result = auth_service.login(payload.username, payload.password)
    if not result:
        raise HTTPException(status_code=401, detail="invalid credentials")
    token, session = result
    return {"access_token": token, "token_type": "bearer", "expires_at": session.expires_at, "user": {"id": session.user_id, "username": session.username, "roles": session.roles, "permissions": sorted(session.permissions)}}

@app.get("/api/v1/auth/me", tags=["auth"])
def me(session: Session = Depends(require_session)) -> dict:
    return {"id": session.user_id, "username": session.username, "roles": session.roles, "permissions": sorted(session.permissions), "expires_at": session.expires_at}

@app.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
def logout(authorization: str | None = Header(default=None), session: Session = Depends(require_session)) -> None:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    if token:
        auth_service.sessions.pop(token, None)

@app.get("/api/v1/users", tags=["auth"])
def users(_: Session = Depends(require_permission("users.read"))) -> list[dict]:
    with database.read() as db:
        rows = db.execute("SELECT id, username, enabled, created_at, updated_at FROM users ORDER BY username").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            role_rows = db.execute(
                "SELECT r.id, r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id WHERE ur.user_id = ? ORDER BY r.name",
                (row["id"],),
            ).fetchall()
            item["role_ids"] = [role["id"] for role in role_rows]
            item["roles"] = [role["name"] for role in role_rows]
            result.append(item)
        return result

@app.post("/api/v1/users", status_code=201, tags=["auth"])
def create_user(payload: UserCreate, session: Session = Depends(require_permission("users.write"))) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="username is required")
    try:
        with database.write() as db:
            if len(payload.role_ids) != len(set(payload.role_ids)):
                raise HTTPException(status_code=422, detail="duplicate role")
            if payload.role_ids:
                placeholders = ",".join("?" for _ in payload.role_ids)
                role_count = db.execute(f"SELECT COUNT(*) FROM roles WHERE id IN ({placeholders})", payload.role_ids).fetchone()[0]
                if role_count != len(set(payload.role_ids)):
                    raise HTTPException(status_code=422, detail="unknown role")
            cur = db.execute("INSERT INTO users(username, password_hash, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (username, hash_password(payload.password), now, now))
            user_id = cur.lastrowid
            for role_id in payload.role_ids:
                db.execute("INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role_id))
            db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'user.create', 'user', ?, ?, ?)", (session.user_id, user_id, json.dumps({"username": username, "role_ids": payload.role_ids}, ensure_ascii=False), now))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="username already exists") from exc
        raise
    return {"id": user_id, "username": username, "enabled": True, "role_ids": payload.role_ids}

@app.patch("/api/v1/users/{user_id}", tags=["auth"])
def update_user(user_id: int, payload: UserUpdate, session: Session = Depends(require_permission("users.write"))) -> dict:
    with database.write() as db:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise HTTPException(status_code=404, detail="user not found")
        if payload.enabled is False and user_id == session.user_id:
            raise HTTPException(status_code=422, detail="cannot disable the current user")
        if payload.role_ids is not None and payload.role_ids:
            if len(payload.role_ids) != len(set(payload.role_ids)):
                raise HTTPException(status_code=422, detail="duplicate role")
            placeholders = ",".join("?" for _ in payload.role_ids)
            role_count = db.execute(f"SELECT COUNT(*) FROM roles WHERE id IN ({placeholders})", payload.role_ids).fetchone()[0]
            if role_count != len(set(payload.role_ids)):
                raise HTTPException(status_code=422, detail="unknown role")
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if payload.enabled is not None:
            db.execute("UPDATE users SET enabled=?, updated_at=? WHERE id=?", (int(payload.enabled), now, user_id))
        if payload.role_ids is not None:
            db.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
            for role_id in payload.role_ids:
                db.execute("INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role_id))
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'user.permission.change', 'user', ?, ?, ?)", (session.user_id, user_id, json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False), now))
    return {"id": user_id, "updated": True}

@app.get("/api/v1/roles", tags=["auth"])
def roles(_: Session = Depends(require_permission("users.read"))) -> list[dict]:
    with database.read() as db:
        rows = db.execute("SELECT id, name, description FROM roles ORDER BY name").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["permission_keys"] = [permission[0] for permission in db.execute("SELECT p.key FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id WHERE rp.role_id=? ORDER BY p.key", (row["id"],)).fetchall()]
            item["built_in"] = row["name"] in {role[0] for role in BUILTIN_ROLES}
            result.append(item)
        return result

@app.post("/api/v1/roles", status_code=201, tags=["auth"])
def create_role(payload: RoleCreate, session: Session = Depends(require_permission("roles.write"))) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="role name is required")
    try:
        with database.write() as db:
            cur = db.execute("INSERT INTO roles(name, description) VALUES (?, ?)", (name, payload.description.strip()))
            role_id = cur.lastrowid
            for key in sorted(set(payload.permission_keys)):
                db.execute("INSERT OR IGNORE INTO permissions(key, description) VALUES (?, ?)", (key, key))
                db.execute("INSERT INTO role_permissions(role_id, permission_id) SELECT ?, id FROM permissions WHERE key=?", (role_id, key))
            db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'role.permission.change', 'role', ?, ?, ?)", (session.user_id, role_id, json.dumps({"permission_keys": sorted(set(payload.permission_keys))}, ensure_ascii=False), utc_now()))
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="role already exists") from exc
        raise
    return {"id": role_id, "name": name, "permission_keys": sorted(set(payload.permission_keys))}


@app.patch("/api/v1/roles/{role_id}", tags=["auth"])
def update_role(role_id: int, payload: RoleUpdate, session: Session = Depends(require_permission("roles.write"))) -> dict:
    with database.write() as db:
        row = db.execute("SELECT name FROM roles WHERE id=?", (role_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="role not found")
        if row["name"] in {"system_administrator", "method_administrator", "analyst", "read_only_auditor"}:
            raise HTTPException(status_code=422, detail="built-in role cannot be changed")
        if payload.description is not None:
            db.execute("UPDATE roles SET description=? WHERE id=?", (payload.description.strip(), role_id))
        if payload.permission_keys is not None:
            db.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
            for key in sorted(set(payload.permission_keys)):
                db.execute("INSERT OR IGNORE INTO permissions(key, description) VALUES (?, ?)", (key, key))
                db.execute("INSERT INTO role_permissions(role_id, permission_id) SELECT ?, id FROM permissions WHERE key=?", (role_id, key))
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'role.permission.change', 'role', ?, ?, ?)", (session.user_id, role_id, json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False), utc_now()))
    return {"id": role_id, "updated": True}

@app.get("/api/v1/audit", tags=["auth"])
def audit(_: Session = Depends(require_permission("audit.read")), limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    with database.read() as db:
            return [dict(row) for row in db.execute("SELECT id, actor_user_id, action, target_type, target_id, details_json, created_at FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


@app.get("/api/v1/methods", response_model=list[MethodResponse], tags=["methods"])
def list_methods(
    include_deleted: bool = Query(default=False),
    _: Session = Depends(require_permission("methods.read")),
) -> list[MethodResponse]:
    return [MethodResponse(**item) for item in methods_service().list(include_deleted=include_deleted)]


@app.get("/api/v1/methods/options", tags=["methods"])
def method_options(_: Session = Depends(require_permission("methods.read"))) -> dict:
    return methods_service().options()


@app.get("/api/v1/methods/current", response_model=MethodCurrentResponse, tags=["methods"])
def current_method(_: Session = Depends(require_permission("methods.read"))) -> MethodCurrentResponse:
    return MethodCurrentResponse(**methods_service().current())


@app.post("/api/v1/methods/current", response_model=MethodCurrentResponse, tags=["methods"])
def set_current_method(payload: MethodActionRequest, session: Session = Depends(require_permission("methods.write"))) -> MethodCurrentResponse:
    if payload.method_id is None:
        raise HTTPException(status_code=422, detail={"code": "method_id_required", "message": "必须提供 method_id", "field_errors": ["method_id"]})
    try:
        methods_service().open(payload.method_id, session.user_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    return MethodCurrentResponse(**methods_service().current())


@app.get("/api/v1/workspace/state", response_model=MethodCurrentResponse, tags=["methods"])
def workspace_state(_: Session = Depends(require_permission("methods.read"))) -> MethodCurrentResponse:
    return MethodCurrentResponse(**methods_service().current())


@app.post("/api/v1/methods", response_model=MethodResponse, status_code=201, tags=["methods"])
def create_method(payload: MethodCreate, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().create(payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/methods/{method_id}", response_model=MethodResponse, tags=["methods"])
def get_method(method_id: int, _: Session = Depends(require_permission("methods.read"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().get(method_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/methods/{method_id}/versions", response_model=list[MethodVersion], tags=["methods"])
def method_versions(method_id: int, _: Session = Depends(require_permission("methods.read"))) -> list[MethodVersion]:
    try:
        return [MethodVersion(**item) for item in methods_service().versions(method_id)]
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.patch("/api/v1/methods/{method_id}", response_model=MethodResponse, tags=["methods"])
def update_method(method_id: int, payload: MethodUpdate, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().update(method_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/publish", response_model=MethodResponse, tags=["methods"])
def publish_method(method_id: int, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().publish(method_id, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/copy", response_model=MethodResponse, status_code=201, tags=["methods"])
def copy_method(method_id: int, payload: MethodCreate, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().copy(method_id, payload.name, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/open", response_model=MethodResponse, tags=["methods"])
def open_method(method_id: int, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().open(method_id, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/pause", response_model=MethodResponse, tags=["methods"])
def pause_method(method_id: int, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().pause(method_id, session.user_id, paused=True))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/resume", response_model=MethodResponse, tags=["methods"])
def resume_method(method_id: int, session: Session = Depends(require_permission("methods.write"))) -> MethodResponse:
    try:
        return MethodResponse(**methods_service().pause(method_id, session.user_id, paused=False))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.delete("/api/v1/methods/{method_id}", status_code=200, tags=["methods"])
def delete_method(method_id: int, session: Session = Depends(require_permission("methods.write"))) -> dict:
    try:
        return methods_service().delete(method_id, session.user_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/spectral-lines/options", tags=["spectral-lines"])
def spectral_line_options(_: Session = Depends(require_permission("methods.read"))) -> dict:
    return spectral_lines_service().options()


@app.get("/api/v1/methods/{method_id}/lines", tags=["spectral-lines"])
def list_spectral_lines(method_id: int, _: Session = Depends(require_permission("methods.read"))) -> dict:
    try:
        return spectral_lines_service().list(method_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/lines/detect", tags=["spectral-lines"])
def detect_spectral_line(
    method_id: int,
    payload: SpectralLineDetectRequest,
    _: Session = Depends(require_permission("methods.read")),
) -> dict:
    try:
        return spectral_lines_service().detect(
            method_id,
            payload.wavelength_nm,
            payload.actual_wavelength_nm,
            payload.scan_width_points,
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/lines", response_model=MethodResponse, status_code=201, tags=["spectral-lines"])
def create_spectral_line(
    method_id: int,
    payload: SpectralLineInput,
    session: Session = Depends(require_permission("methods.write")),
) -> MethodResponse:
    try:
        return MethodResponse(**spectral_lines_service().create(method_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.patch("/api/v1/methods/{method_id}/lines/{line_id}", response_model=MethodResponse, tags=["spectral-lines"])
def update_spectral_line(
    method_id: int,
    line_id: str,
    payload: SpectralLineInput,
    session: Session = Depends(require_permission("methods.write")),
) -> MethodResponse:
    try:
        return MethodResponse(**spectral_lines_service().update(method_id, line_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.delete("/api/v1/methods/{method_id}/lines/{line_id}", response_model=MethodResponse, tags=["spectral-lines"])
def delete_spectral_line(
    method_id: int,
    line_id: str,
    session: Session = Depends(require_permission("methods.write")),
) -> MethodResponse:
    try:
        return MethodResponse(**spectral_lines_service().delete(method_id, line_id, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.post("/api/v1/methods/{method_id}/lines/reorder", response_model=MethodResponse, tags=["spectral-lines"])
def reorder_spectral_lines(
    method_id: int,
    payload: SpectralLineReorder,
    session: Session = Depends(require_permission("methods.write")),
) -> MethodResponse:
    try:
        return MethodResponse(**spectral_lines_service().reorder(method_id, payload.line_ids, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/method-print/settings", response_model=MethodPrintSettings, tags=["method-print"])
def get_method_print_settings(
    _: Session = Depends(require_permission("methods.read")),
) -> MethodPrintSettings:
    return MethodPrintSettings(**method_print_service().get_settings())


@app.patch("/api/v1/method-print/settings", response_model=MethodPrintSettings, tags=["method-print"])
def save_method_print_settings(
    payload: MethodPrintSettings,
    session: Session = Depends(require_permission("methods.write")),
) -> MethodPrintSettings:
    try:
        return MethodPrintSettings(**method_print_service().save_settings(payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/method-print/printers", tags=["method-print"])
def list_method_printers(
    _: Session = Depends(require_permission("methods.read")),
) -> dict:
    return {"printers": method_print_service().printers()}


@app.post("/api/v1/methods/{method_id}/preview", response_class=HTMLResponse, tags=["method-print"])
def preview_method(
    method_id: int,
    payload: MethodRenderRequest,
    session: Session = Depends(require_permission("methods.read")),
) -> HTMLResponse:
    try:
        markup, document = method_print_service().preview(
            method_id, payload.version, payload.settings, session.user_id
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    return HTMLResponse(
        markup,
        headers={
            "X-Page-Count": str(document["page_count"]),
            "X-Field-Count": str(document["field_count"]),
            "X-Method-Version": str(document["snapshot"]["version"]["version"]),
        },
    )


@app.post("/api/v1/methods/{method_id}/pdf", tags=["method-print"])
def export_method_pdf(
    method_id: int,
    payload: MethodRenderRequest,
    session: Session = Depends(require_permission("methods.read")),
) -> Response:
    try:
        pdf_bytes, document = method_print_service().pdf(
            method_id, payload.version, payload.settings, session.user_id
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    method_name = document["snapshot"]["method"]["name"]
    version = document["snapshot"]["version"]["version"]
    filename = f"{method_name}-v{version}-方法参数.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=method-v{version}.pdf; filename*=UTF-8''{quote(filename)}",
            "X-Page-Count": str(document["page_count"]),
            "X-Field-Count": str(document["field_count"]),
            "X-Method-Version": str(version),
        },
    )


@app.post("/api/v1/methods/{method_id}/print", tags=["method-print"])
def print_method(
    method_id: int,
    payload: MethodPrintRequest,
    session: Session = Depends(require_permission("methods.write")),
) -> dict:
    try:
        return method_print_service().print_method(
            method_id,
            payload.version,
            payload.settings,
            payload.printer_name,
            session.user_id,
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/methods/{method_id}/print-jobs", tags=["method-print"])
def list_method_print_jobs(
    method_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    _: Session = Depends(require_permission("methods.read")),
) -> dict:
    try:
        return {"jobs": method_print_service().jobs(method_id, limit)}
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/method-print/jobs/{job_id}", tags=["method-print"])
def get_method_print_job(
    job_id: str,
    _: Session = Depends(require_permission("methods.read")),
) -> dict:
    try:
        return method_print_service().job(job_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@app.get("/api/v1/legacy-migration/diagnostics", tags=["legacy-migration"])
def legacy_migration_diagnostics(
    _: Session = Depends(require_permission("migration.read")),
) -> dict:
    return legacy_migration_service().diagnostics()


@app.post("/api/v1/legacy-migration/stage", tags=["legacy-migration"])
def stage_legacy_migration(
    payload: LegacyMigrationStageRequest,
    session: Session = Depends(require_permission("migration.write")),
) -> dict:
    try:
        return legacy_migration_service().stage(
            payload.mtd_path, payload.cfg_path, payload.opt_path, session.user_id
        )
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@app.get("/api/v1/legacy-migration/runs", tags=["legacy-migration"])
def list_legacy_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("migration.read")),
) -> dict:
    return {"runs": legacy_migration_service().list(limit)}


@app.get("/api/v1/legacy-migration/runs/{run_id}", tags=["legacy-migration"])
def get_legacy_migration_run(
    run_id: str,
    _: Session = Depends(require_permission("migration.read")),
) -> dict:
    try:
        return legacy_migration_service().get(run_id)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@app.post("/api/v1/legacy-migration/commit", tags=["legacy-migration"])
def commit_legacy_migration(
    payload: LegacyMigrationCommitRequest,
    session: Session = Depends(require_permission("migration.write")),
) -> dict:
    try:
        return legacy_migration_service().commit(payload.run_id, session.user_id)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@app.get("/api/v1/spectrum-migration/diagnostics", tags=["spectrum-migration"])
def spectrum_migration_diagnostics(
    _: Session = Depends(require_permission("spectrum-migration.read")),
) -> dict:
    return spectrum_migration_service().diagnostics()


@app.post("/api/v1/spectrum-migration/stage", tags=["spectrum-migration"])
def stage_spectrum_migration(
    payload: SpectrumMigrationStageRequest,
    session: Session = Depends(require_permission("spectrum-migration.write")),
) -> dict:
    try:
        return spectrum_migration_service().stage(payload.path, session.user_id)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc


@app.get("/api/v1/spectrum-migration/runs", tags=["spectrum-migration"])
def list_spectrum_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("spectrum-migration.read")),
) -> dict:
    return {"runs": spectrum_migration_service().list(limit)}


@app.get("/api/v1/spectrum-migration/runs/{run_id}", tags=["spectrum-migration"])
def get_spectrum_migration_run(
    run_id: str,
    _: Session = Depends(require_permission("spectrum-migration.read")),
) -> dict:
    try:
        return spectrum_migration_service().get(run_id)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc


@app.post("/api/v1/spectrum-migration/commit", tags=["spectrum-migration"])
def commit_spectrum_migration(
    payload: SpectrumMigrationCommitRequest,
    session: Session = Depends(require_permission("spectrum-migration.write")),
) -> dict:
    try:
        return spectrum_migration_service().commit(payload.run_id, session.user_id)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc


@app.get("/api/v1/result-migration/diagnostics", tags=["result-migration"])
def result_migration_diagnostics(
    _: Session = Depends(require_permission("result-migration.read")),
) -> dict:
    return result_migration_service().diagnostics()


@app.post("/api/v1/result-migration/stage", tags=["result-migration"])
def stage_result_migration(
    payload: ResultMigrationStageRequest,
    session: Session = Depends(require_permission("result-migration.write")),
) -> dict:
    try:
        return result_migration_service().stage(payload.path, session.user_id)
    except ResultMigrationError as exc:
        raise result_migration_error(exc) from exc


@app.get("/api/v1/result-migration/runs", tags=["result-migration"])
def list_result_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("result-migration.read")),
) -> dict:
    return {"runs": result_migration_service().list(limit)}


@app.get("/api/v1/result-migration/runs/{run_id}", tags=["result-migration"])
def get_result_migration_run(
    run_id: str,
    _: Session = Depends(require_permission("result-migration.read")),
) -> dict:
    try:
        return result_migration_service().get(run_id)
    except ResultMigrationError as exc:
        raise result_migration_error(exc) from exc


@app.post("/api/v1/result-migration/commit", tags=["result-migration"])
def commit_result_migration(
    payload: ResultMigrationCommitRequest,
    session: Session = Depends(require_permission("result-migration.write")),
) -> dict:
    try:
        return result_migration_service().commit(payload.run_id, session.user_id)
    except ResultMigrationError as exc:
        raise result_migration_error(exc) from exc


@app.get("/api/v1/spectra/records", tags=["spectra"])
def list_spectrum_records(
    kind: str = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=200),
    angle_deg: float | None = Query(default=None),
    _: Session = Depends(require_permission("spectra.read")),
) -> list[dict]:
    try:
        return spectrum_viewer_service().list(kind=kind, limit=limit, angle_deg=angle_deg)
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc


@app.get("/api/v1/spectra/{record_id}", tags=["spectra"])
def get_spectrum_record(
    record_id: str,
    ccd: int = Query(default=0, ge=0, le=255),
    line: int = Query(default=0, ge=0, le=4095),
    detail: str = Query(default="summary"),
    phase: str = Query(default="burn"),
    frame: int = Query(default=0, ge=0, le=255),
    exposure_start: int | None = Query(default=None, ge=1, le=255),
    exposure_end: int | None = Query(default=None, ge=1, le=255),
    session: Session = Depends(require_permission("spectra.read")),
) -> dict:
    try:
        result = spectrum_viewer_service().get(record_id, ccd=ccd, line=line, detail=detail, phase=phase, frame=frame, exposure_start=exposure_start, exposure_end=exposure_end)
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    with database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.view', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps({"record_id": record_id, "ccd": ccd, "line": line, "detail": detail, "phase": phase, "frame": frame, "exposure_start": exposure_start, "exposure_end": exposure_end}, ensure_ascii=False), utc_now()),
        )
    return result


@app.get("/api/v1/spectra/{record_id}/export", tags=["spectra"])
def export_spectrum_record(
    record_id: str,
    ccd: int = Query(default=0, ge=0, le=255),
    line: int = Query(default=0, ge=0, le=4095),
    detail: str = Query(default="summary"),
    phase: str = Query(default="burn"),
    frame: int = Query(default=0, ge=0, le=255),
    exposure_start: int | None = Query(default=None, ge=1, le=255),
    exposure_end: int | None = Query(default=None, ge=1, le=255),
    x_min: float | None = Query(default=None),
    x_max: float | None = Query(default=None),
    reference_shift: float = Query(default=0.0),
    session: Session = Depends(require_permission("spectra.export")),
) -> Response:
    try:
        content, digest, point_count = spectrum_viewer_service().export_csv(
            record_id,
            ccd=ccd,
            line=line,
            detail=detail,
            phase=phase,
            frame=frame,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            x_min=x_min,
            x_max=x_max,
            reference_shift=reference_shift,
        )
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    with database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.export', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps({"record_id": record_id, "ccd": ccd, "line": line, "visible_x_min": x_min, "visible_x_max": x_max, "reference_shift": reference_shift, "point_count": point_count, "sha256": digest}, ensure_ascii=False), utc_now()),
        )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="spectrum-{quote(record_id, safe="")}.csv"', "X-Content-SHA256": digest},
    )


@app.post("/api/v1/spectra/{record_id}/print", tags=["spectra"])
def audit_spectrum_print(
    record_id: str,
    payload: SpectrumPrintRequest,
    session: Session = Depends(require_permission("spectra.export")),
) -> dict[str, Any]:
    if payload.visible_x_min > payload.visible_x_max or payload.visible_y_min > payload.visible_y_max:
        raise HTTPException(status_code=422, detail={"code": "spectrum_visible_range_invalid", "message": "visible ranges must be ordered", "details": {}})
    try:
        spectrum_viewer_service().get(record_id, ccd=payload.ccd, line=payload.line)
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    details = {"record_id": record_id, **payload.model_dump(mode="json")}
    with database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.print', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps(details, ensure_ascii=False), utc_now()),
        )
    return {"status": "ready", "visible_range": {"x_min": payload.visible_x_min, "x_max": payload.visible_x_max, "y_min": payload.visible_y_min, "y_max": payload.visible_y_max}}


@app.post("/api/v1/spectra/{record_id}/print-pdf", tags=["spectra"])
def print_spectrum_pdf(
    record_id: str,
    payload: SpectrumPrintRequest,
    session: Session = Depends(require_permission("spectra.export")),
) -> Response:
    try:
        content, result = spectrum_viewer_service().render_visible_pdf(
            record_id,
            selected_record_ids=payload.selected_record_ids,
            ccd=payload.ccd,
            line=payload.line,
            mode=payload.mode,
            reference_shift=payload.reference_shift,
            visible_x_min=payload.visible_x_min,
            visible_x_max=payload.visible_x_max,
            visible_y_min=payload.visible_y_min,
            visible_y_max=payload.visible_y_max,
            frame_phase=payload.frame_phase,
            frame_index=payload.frame_index,
            exposure_start=payload.exposure_start,
            exposure_end=payload.exposure_end,
            priority_record_id=payload.priority_record_id,
        )
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    details = {"record_id": record_id, **payload.model_dump(mode="json"), **result, "bytes": len(content), "output": "pdf"}
    with database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.print', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps(details, ensure_ascii=False), utc_now()),
        )
    filename = f"spectrum-{record_id.replace(':', '-')}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": result["sha256"],
            "X-Curve-Count": str(result["curve_count"]),
            "X-Visible-Point-Count": str(result["visible_point_count"]),
        },
    )


@app.get("/api/v1/sample-queues", tags=["sample-queues"])
def list_sample_queues(_: Session = Depends(require_permission("samples.read"))) -> list[dict]:
    return sample_queue_service().list()


@app.get("/api/v1/sample-queues/{queue_id}", tags=["sample-queues"])
def get_sample_queue(queue_id: int, _: Session = Depends(require_permission("samples.read"))) -> dict:
    try:
        return sample_queue_service().get(queue_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.post("/api/v1/sample-queues", status_code=201, tags=["sample-queues"])
def create_sample_queue(payload: SampleQueueCreate, session: Session = Depends(require_permission("samples.write"))) -> dict:
    try:
        return sample_queue_service().create(payload.name, [item.model_dump() for item in payload.items], session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.patch("/api/v1/sample-queues/{queue_id}", tags=["sample-queues"])
def update_sample_queue(queue_id: int, payload: SampleQueueUpdate, session: Session = Depends(require_permission("samples.write"))) -> dict:
    try:
        return sample_queue_service().update(queue_id, [item.model_dump() for item in payload.items], session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.post("/api/v1/sample-queues/{queue_id}/items/{item_id}/rename", tags=["sample-queues"])
def rename_sample_queue_item(queue_id: int, item_id: int, payload: SampleQueueRename, session: Session = Depends(require_permission("samples.write"))) -> dict:
    try:
        return sample_queue_service().rename(queue_id, item_id, payload.post_name, session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.delete("/api/v1/sample-queues/{queue_id}/items/{item_id}", tags=["sample-queues"])
def delete_sample_queue_item(queue_id: int, item_id: int, session: Session = Depends(require_permission("samples.write"))) -> dict:
    try:
        return sample_queue_service().delete_item(queue_id, item_id, session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.post("/api/v1/sample-queues/{queue_id}/clear", tags=["sample-queues"])
def clear_sample_queue(queue_id: int, session: Session = Depends(require_permission("samples.write"))) -> dict:
    try:
        return sample_queue_service().clear(queue_id, session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.post("/api/v1/sample-queues/import", status_code=201, tags=["sample-queues"])
def import_sample_queue(payload: SampleQueueImport, session: Session = Depends(require_permission("samples.write"))) -> dict:
    try:
        return sample_queue_service().import_bytes(payload.content.encode("utf-8"), session.user_id, payload.queue_name or Path(payload.filename).stem, payload.filename)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@app.get("/api/v1/sample-queues/{queue_id}/export", tags=["sample-queues"])
def export_sample_queue(queue_id: int, session: Session = Depends(require_permission("samples.write"))) -> Response:
    try:
        content, digest = sample_queue_service().export_sam(queue_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc
    with database.write() as db:
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'sample_queue.sam_export', 'sample_queue', ?, ?, ?)", (session.user_id, queue_id, json.dumps({"sha256": digest, "bytes": len(content)}, ensure_ascii=False), utc_now()))
    return Response(content=content, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="queue-{queue_id}.sam"', "X-Source-SHA256": digest})


@app.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session = auth_service.get_session(websocket.query_params.get("access_token"))
    if session is None:
        await websocket.close(code=4401, reason="authentication required")
        return
    if "runtime-events.read" not in session.permissions:
        await websocket.close(code=4403, reason="permission denied")
        return
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
    event_subscribers.add(queue)
    try:
        await websocket.send_text(json.dumps({"type": "ready", "api_version": "v1"}))
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps({"type": "runtime_event", "event": event}, ensure_ascii=False))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        event_subscribers.discard(queue)
