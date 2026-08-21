from __future__ import annotations

import asyncio
import json
import os
import platform
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

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
    PostProcessingIntervalRequest, PostProcessingConversionRequest,
    PostProcessingRecalculateRequest, PostProcessingExportRequest,
    SampleQueueCreate, SampleQueueUpdate, SampleQueueRename, SampleQueueImport,
    DeviceProfileCreate, DeviceProfileUpdate, DeviceConnectRequest, DeviceDebugStartRequest,
    DispersionTaskCreate, DispersionLineInput, DispersionLineMoveRequest,
    DispersionCalibrationFitRequest, DispersionCalibrationBindRequest,
    AcquisitionTaskCreate, AcquisitionIntervalMark, AcquisitionRename,
    HardwareTaskCreate, HardwareIntervention, MercurySessionCreate,
    AnalysisRunCreate, AnalysisIntervention, AnalysisQcDecision, AnalysisCurveAction,
    AnalysisCurveFit, AnalysisCurvePublish, AnalysisMergeRequest,
    ReportCreate, ReportExport,
    BackupCreate, MaintenanceActionRequest, HelpTopicResponse,
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
from .modules.devices import DeviceError, DeviceService
from .modules.dispersion import DispersionError, DispersionService
from .modules.acquisition import AcquisitionError, AcquisitionService
from .modules.hardware_acquisition import HardwareError, HardwareAcquisitionService
from .modules.mercury_calibration import MercuryError, MercuryCalibrationService
from .modules.analysis import AnalysisError, AnalysisService
from .modules.postprocessing import PostProcessingError, PostProcessingService
from .modules.reports import ReportError, ReportService
from .modules.maintenance import MaintenanceError, MaintenanceService
from .modules.extensions import ExtensionManifest, discover_test_extensions

database = Database(config.database_path)
service = AppService(database, config.runtime_log_path)
auth_service = AuthService(database)
event_subscribers: set[asyncio.Queue[dict]] = set()
PROCESS_KEY = ""


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


def postprocessing_service() -> PostProcessingService:
    return PostProcessingService(database)


_device_service_instance: DeviceService | None = None


def devices_service() -> DeviceService:
    global _device_service_instance
    if _device_service_instance is None or _device_service_instance.database is not database:
        _device_service_instance = DeviceService(database)
    return _device_service_instance


_dispersion_service_instance: DispersionService | None = None


def dispersion_service() -> DispersionService:
    global _dispersion_service_instance
    if _dispersion_service_instance is None or _dispersion_service_instance.database is not database:
        _dispersion_service_instance = DispersionService(database)
    return _dispersion_service_instance


_acquisition_service_instance: AcquisitionService | None = None


def acquisition_service() -> AcquisitionService:
    global _acquisition_service_instance
    if _acquisition_service_instance is None or _acquisition_service_instance.database is not database:
        _acquisition_service_instance = AcquisitionService(database)
    return _acquisition_service_instance


_hardware_acquisition_service_instance: HardwareAcquisitionService | None = None


def hardware_acquisition_service() -> HardwareAcquisitionService:
    global _hardware_acquisition_service_instance
    if _hardware_acquisition_service_instance is None or _hardware_acquisition_service_instance.database is not database:
        _hardware_acquisition_service_instance = HardwareAcquisitionService(database)
    return _hardware_acquisition_service_instance


_mercury_calibration_service_instance: MercuryCalibrationService | None = None


def mercury_calibration_service() -> MercuryCalibrationService:
    global _mercury_calibration_service_instance
    if _mercury_calibration_service_instance is None or _mercury_calibration_service_instance.database is not database:
        _mercury_calibration_service_instance = MercuryCalibrationService(database)
    return _mercury_calibration_service_instance


def analysis_service() -> AnalysisService:
    return AnalysisService(database)


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


def device_error(exc: DeviceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def dispersion_error(exc: DispersionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def acquisition_error(exc: AcquisitionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def hardware_error(exc: HardwareError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def mercury_error(exc: MercuryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def analysis_error(exc: AnalysisError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def postprocessing_error(exc: PostProcessingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def reports_service() -> ReportService:
    return ReportService(database)


def report_error(exc: ReportError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def maintenance_service() -> MaintenanceService:
    return MaintenanceService(database, config.runtime_log_path)


def maintenance_error(exc: MaintenanceError) -> HTTPException:
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


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part not in {"body", "query", "path"}),
            "code": str(error["type"]),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "request_validation_failed",
                "message": "输入数据无效，请检查字段格式和范围",
                "errors": errors,
            }
        },
    )


@app.middleware("http")
async def require_process_key(request: Request, call_next):
    if PROCESS_KEY and request.method != "OPTIONS":
        supplied = request.headers.get("X-GeoSpectrum-Process-Key", "")
        if not secrets.compare_digest(supplied, PROCESS_KEY):
            return JSONResponse(status_code=403, content={"detail": {"code": "PROCESS_KEY_REQUIRED", "message": "本地进程密钥无效"}})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-ID", "X-GeoSpectrum-Process-Key"],
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
            navigation_entries=[entry.to_dict() for entry in manifest.navigation_entries],
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


def _extension_endpoint(extension: ExtensionManifest):
    async def execute_extension(
        session: Session = Depends(require_permission(extension.permission)),
    ) -> dict[str, Any]:
        created_at = utc_now()
        payload = {"event_type": extension.event_type, "event_version": 1, "module": extension.key, "created_at": created_at}
        table = extension.key.replace("-", "_") + "_records"
        with database.write() as connection:
            cursor = connection.execute(
                f"INSERT INTO {table}(event_version, payload_json, created_at) VALUES (1, ?, ?)",
                (json.dumps(payload, ensure_ascii=False), created_at),
            )
            record_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session.user_id, extension.audit_action, extension.key, record_id, json.dumps(payload, ensure_ascii=False), created_at),
            )
            event_cursor = connection.execute(
                "INSERT INTO runtime_events(category, severity, message, details_json, correlation_id, created_at) VALUES ('action', 'success', ?, ?, ?, ?)",
                (extension.title, json.dumps(payload, ensure_ascii=False), extension.event_type, created_at),
            )
        event = {"id": int(event_cursor.lastrowid), "category": "action", "severity": "success", "message": extension.title, "details": payload, "correlation_id": extension.event_type, "created_at": created_at}
        for queue in tuple(event_subscribers):
            try:
                queue.put_nowait({"type": extension.event_type, "version": 1, "event": event})
            except asyncio.QueueFull:
                pass
        return {"record_id": record_id, **payload}

    execute_extension.__name__ = f"execute_{extension.key.replace('-', '_')}"
    return execute_extension


for _extension in discover_test_extensions():
    app.add_api_route(
        f"/api/v1/extensions/{_extension.key}/execute",
        _extension_endpoint(_extension),
        methods=["POST"],
        tags=["test-extension"],
    )


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(**service.health())


@app.get("/about", response_model=AboutResponse, tags=["system"])
@app.get("/api/v1/about", response_model=AboutResponse, include_in_schema=False)
def about(_: Session = Depends(require_permission("about.read"))) -> AboutResponse:
    return AboutResponse(
        name="geospectrum",
        display_name="GeoSpectrum 自动转角平面光栅光谱仪分析平台",
        version=__version__,
        api_version="v1",
        stage="S21 · Windows 内部测试发布",
        description="面向 SpecDirect 2.0.2 兼容重构的本地分析工作台。",
        runtime=f"Python {platform.python_version()} · {platform.system()}",
        database=str(config.database_path),
        modules=[manifest.to_dict() for manifest in registered_manifests()],
        license="内部测试包（未签名，不得作为正式发布）",
        build={"version": __version__, "schema_version": 20, "api_version": "v1", "python": platform.python_version(), "channel": "internal-test", "signed": False},
    )


@app.get("/api/v1/capabilities", response_model=CapabilitiesResponse, tags=["system"])
def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        api_version="v1",
        generated_at=datetime.now(timezone.utc),
        capabilities=_capabilities(),
    )


@app.get("/api/v1/diagnostics", response_model=DiagnosticsResponse, tags=["system"])
def diagnostics(_: Session = Depends(require_permission("about.read"))) -> DiagnosticsResponse:
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


@app.get("/api/v1/maintenance/status", tags=["maintenance"])
def maintenance_status(_: Session = Depends(require_permission("maintenance.read"))) -> dict[str, Any]:
    return maintenance_service().status()


@app.get("/api/v1/backups", tags=["maintenance"])
def list_backups(_: Session = Depends(require_permission("maintenance.read"))) -> list[dict[str, Any]]:
    return maintenance_service().list_backups()


@app.post("/api/v1/backups", tags=["maintenance"])
def create_backup(payload: BackupCreate, session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().backup(payload.output_directory, payload.filename, payload.retention_days, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/backups/retention", tags=["maintenance"])
def run_retention(session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().retention(session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/backups/{backup_id}/verify", tags=["maintenance"])
def verify_backup(backup_id: str, _: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().verify_backup(backup_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/backups/{backup_id}/restore-rehearsal", tags=["maintenance"])
def restore_rehearsal(backup_id: str, session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().restore_rehearsal(backup_id, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/maintenance/checkpoint", tags=["maintenance"])
def checkpoint(payload: MaintenanceActionRequest, session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().checkpoint(payload.mode, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/maintenance/optimize", tags=["maintenance"])
def optimize(session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().optimize(session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/maintenance/reclaim", tags=["maintenance"])
def reclaim(session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().reclaim(session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/maintenance/logs/cleanup", tags=["maintenance"])
def cleanup_logs(payload: MaintenanceActionRequest, session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().cleanup_logs(payload.retention_days, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.post("/api/v1/maintenance/temp/cleanup", tags=["maintenance"])
def cleanup_temp(payload: MaintenanceActionRequest, session: Session = Depends(require_permission("maintenance.write"))) -> dict[str, Any]:
    try:
        return maintenance_service().cleanup_temp(payload.retention_days, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.get("/api/v1/help/topics", response_model=list[HelpTopicResponse], tags=["help"])
def help_topics(q: str | None = Query(default=None, max_length=120), _: Session = Depends(require_permission("help.read"))) -> list[dict[str, Any]]:
    return maintenance_service().help_topics(q)


@app.get("/api/v1/help/error-codes/{code}", tags=["help"])
def help_error_code(code: str, _: Session = Depends(require_permission("help.read"))) -> dict[str, Any]:
    try:
        return maintenance_service().help_topic_for_error(code)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@app.get("/api/v1/help/topics/{slug}", response_model=HelpTopicResponse, tags=["help"])
def help_topic(slug: str, _: Session = Depends(require_permission("help.read"))) -> dict[str, Any]:
    try:
        return maintenance_service().help_topic(slug)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


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
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_invalid_credentials", "message": "用户名或密码错误"},
        )
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


@app.get("/api/v1/postprocessing/edt-records", tags=["postprocessing"])
def list_postprocessing_edt_records(
    limit: int = Query(default=200, ge=1, le=500),
    _: Session = Depends(require_permission("postprocessing.read")),
) -> dict[str, Any]:
    return {"records": postprocessing_service().edt_records(limit)}


@app.get("/api/v1/postprocessing/recalculation-options", tags=["postprocessing"])
def get_postprocessing_recalculation_options(
    limit: int = Query(default=300, ge=1, le=500),
    _: Session = Depends(require_permission("postprocessing.read")),
) -> dict[str, Any]:
    return postprocessing_service().recalculation_options(limit)


@app.get("/api/v1/postprocessing/raw/{record_id}/interval", tags=["postprocessing"])
def get_postprocessing_interval(
    record_id: str,
    ccd: int = Query(default=0, ge=0, le=255),
    start_frame: int = Query(default=1, ge=1, le=255),
    end_frame: int | None = Query(default=None, ge=1, le=255),
    phase: str = Query(default="burn"),
    session: Session = Depends(require_permission("postprocessing.read")),
) -> dict[str, Any]:
    try:
        result = postprocessing_service().interval(record_id, ccd=ccd, start_frame=start_frame, end_frame=end_frame, phase=phase)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc
    with database.write() as db:
        db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.interval.view', 'postprocessing', NULL, ?, ?)", (session.user_id, json.dumps({"record_id": record_id, "ccd": ccd, "start_frame": start_frame, "end_frame": end_frame, "phase": phase}, ensure_ascii=False), utc_now()))
    return result


@app.post("/api/v1/postprocessing/conversions", tags=["postprocessing"])
def convert_postprocessing_edt(
    payload: PostProcessingConversionRequest,
    session: Session = Depends(require_permission("postprocessing.write")),
) -> dict[str, Any]:
    try:
        return postprocessing_service().convert_edt(payload.model_dump(), session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc


@app.get("/api/v1/postprocessing/conversions", tags=["postprocessing"])
def list_postprocessing_conversions(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("postprocessing.read")),
) -> dict[str, Any]:
    return {"runs": postprocessing_service().conversions(limit)}


@app.post("/api/v1/postprocessing/recalculations", tags=["postprocessing"])
def recalculate_postprocessing(
    payload: PostProcessingRecalculateRequest,
    session: Session = Depends(require_permission("postprocessing.execute")),
) -> dict[str, Any]:
    try:
        return postprocessing_service().recalculate(payload.model_dump(), session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc


@app.get("/api/v1/postprocessing/recalculations", tags=["postprocessing"])
def list_postprocessing_recalculations(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("postprocessing.read")),
) -> dict[str, Any]:
    return {"runs": postprocessing_service().recalculations(limit)}


@app.post("/api/v1/postprocessing/exports", tags=["postprocessing"])
def export_postprocessing_matrix(
    payload: PostProcessingExportRequest,
    session: Session = Depends(require_permission("postprocessing.export")),
) -> dict[str, Any]:
    try:
        return postprocessing_service().export(payload.model_dump(), session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc


@app.get("/api/v1/postprocessing/exports", tags=["postprocessing"])
def list_postprocessing_exports(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("postprocessing.read")),
) -> dict[str, Any]:
    return {"exports": postprocessing_service().exports(limit)}


@app.get("/api/v1/reports/templates", tags=["reports"])
def list_report_templates(_: Session = Depends(require_permission("reports.read"))) -> list[dict[str, Any]]:
    return reports_service().templates()


@app.get("/api/v1/reports", tags=["reports"])
def list_reports(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("reports.read"))) -> list[dict[str, Any]]:
    return reports_service().list(limit)


@app.get("/api/v1/reports/printers", tags=["reports"])
def list_report_printers(_: Session = Depends(require_permission("reports.read"))) -> dict[str, Any]:
    return {"printers": reports_service().printers()}


@app.post("/api/v1/reports", status_code=201, tags=["reports"])
def create_report(payload: ReportCreate, session: Session = Depends(require_permission("reports.write"))) -> dict[str, Any]:
    try:
        return reports_service().create(payload.model_dump(mode="json"), session.user_id)
    except ReportError as exc:
        raise report_error(exc) from exc


@app.get("/api/v1/reports/{report_id}", tags=["reports"])
def get_report(report_id: int, _: Session = Depends(require_permission("reports.read"))) -> dict[str, Any]:
    try:
        return reports_service().get(report_id)
    except ReportError as exc:
        raise report_error(exc) from exc


@app.get("/api/v1/reports/{report_id}/preview", response_class=HTMLResponse, tags=["reports"])
def preview_report(report_id: int, session: Session = Depends(require_permission("reports.read"))) -> HTMLResponse:
    try:
        return HTMLResponse(reports_service().preview(report_id, session.user_id), headers={"Cache-Control": "no-store"})
    except ReportError as exc:
        raise report_error(exc) from exc


@app.post("/api/v1/reports/{report_id}/confirm", tags=["reports"])
def confirm_report(report_id: int, session: Session = Depends(require_permission("reports.write"))) -> dict[str, Any]:
    try:
        return reports_service().confirm(report_id, session.user_id)
    except ReportError as exc:
        raise report_error(exc) from exc


@app.post("/api/v1/reports/{report_id}/exports", tags=["reports"])
def export_report(report_id: int, payload: ReportExport, session: Session = Depends(require_permission("reports.export"))) -> Any:
    try:
        result = reports_service().export(report_id, payload.model_dump(mode="json"), session.user_id)
    except ReportError as exc:
        raise report_error(exc) from exc
    return result


@app.get("/api/v1/reports/{report_id}/exports", tags=["reports"])
def list_report_exports(report_id: int, limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("reports.read"))) -> list[dict[str, Any]]:
    return reports_service().exports(report_id, limit)


@app.get("/api/v1/devices/profiles", tags=["devices"])
def list_device_profiles(_: Session = Depends(require_permission("devices.read"))) -> list[dict[str, Any]]:
    return devices_service().profiles()


@app.get("/api/v1/devices/profiles/{profile_id}", tags=["devices"])
def get_device_profile(profile_id: int, _: Session = Depends(require_permission("devices.read"))) -> dict[str, Any]:
    try:
        return devices_service().profile(profile_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.post("/api/v1/devices/profiles", status_code=201, tags=["devices"])
def create_device_profile(payload: DeviceProfileCreate, session: Session = Depends(require_permission("devices.write"))) -> dict[str, Any]:
    try:
        return devices_service().create_profile(payload.model_dump(), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.patch("/api/v1/devices/profiles/{profile_id}", tags=["devices"])
def update_device_profile(profile_id: int, payload: DeviceProfileUpdate, session: Session = Depends(require_permission("devices.write"))) -> dict[str, Any]:
    try:
        return devices_service().update_profile(profile_id, payload.model_dump(exclude_none=True), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.get("/api/v1/devices/diagnostics", tags=["devices"])
def device_diagnostics(_: Session = Depends(require_permission("devices.read"))) -> dict[str, Any]:
    current = devices_service()
    return {"profiles": current.profiles(), "adapter": current.adapter.diagnostics()}


@app.post("/api/v1/devices/connect", tags=["devices"])
def connect_device(payload: DeviceConnectRequest, session: Session = Depends(require_permission("devices.execute"))) -> dict[str, Any]:
    try:
        return devices_service().connect(payload.profile_id, actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.post("/api/v1/devices/disconnect", tags=["devices"])
def disconnect_device(session: Session = Depends(require_permission("devices.execute"))) -> dict[str, Any]:
    try:
        return devices_service().disconnect(actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.post("/api/v1/devices/debug/start", tags=["devices"])
def start_device_debug(payload: DeviceDebugStartRequest, session: Session = Depends(require_permission("devices.execute"))) -> dict[str, Any]:
    try:
        return devices_service().start_debug(payload.model_dump(), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.post("/api/v1/devices/debug/step", tags=["devices"])
def step_device_debug(session: Session = Depends(require_permission("devices.execute"))) -> dict[str, Any]:
    try:
        return devices_service().step_debug(actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.post("/api/v1/devices/debug/stop", tags=["devices"])
def stop_device_debug(session: Session = Depends(require_permission("devices.execute"))) -> dict[str, Any]:
    try:
        return devices_service().stop_debug(actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@app.get("/api/v1/dispersion/options", tags=["dispersion"])
def dispersion_options(_: Session = Depends(require_permission("dispersion.read"))) -> dict[str, Any]:
    return dispersion_service().options()


@app.get("/api/v1/dispersion/tasks", tags=["dispersion"])
def list_dispersion_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("dispersion.read")),
) -> list[dict[str, Any]]:
    return dispersion_service().list_tasks(limit)


@app.post("/api/v1/dispersion/tasks", status_code=201, tags=["dispersion"])
def create_dispersion_task(
    payload: DispersionTaskCreate,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().create_task(payload.model_dump(mode="json"), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.get("/api/v1/dispersion/tasks/{task_id}", tags=["dispersion"])
def get_dispersion_task(
    task_id: int,
    _: Session = Depends(require_permission("dispersion.read")),
) -> dict[str, Any]:
    try:
        return dispersion_service().get_task(task_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/start", tags=["dispersion"])
def start_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
) -> dict[str, Any]:
    try:
        return dispersion_service().start_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/step", tags=["dispersion"])
def step_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
) -> dict[str, Any]:
    try:
        return dispersion_service().step_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/pause", tags=["dispersion"])
def pause_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
) -> dict[str, Any]:
    try:
        return dispersion_service().pause_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/resume", tags=["dispersion"])
def resume_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
) -> dict[str, Any]:
    try:
        return dispersion_service().resume_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/stop", tags=["dispersion"])
def stop_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
) -> dict[str, Any]:
    try:
        return dispersion_service().stop_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.get("/api/v1/dispersion/tasks/{task_id}/frames", tags=["dispersion"])
def dispersion_task_frames(
    task_id: int,
    phase: str | None = Query(default=None),
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    _: Session = Depends(require_permission("dispersion.read")),
) -> list[dict[str, Any]]:
    try:
        return dispersion_service().frames(task_id, phase=phase, ccd_index=ccd_index)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/lines", status_code=201, tags=["dispersion"])
def add_dispersion_line(
    task_id: int,
    payload: DispersionLineInput,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().add_line(task_id, payload.model_dump(mode="json"), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.delete("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}", tags=["dispersion"])
def delete_dispersion_line(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().delete_line(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/lines/locate-all", tags=["dispersion"])
def locate_all_dispersion_lines(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    return dispersion_service().locate_all(task_id, session.user_id)


@app.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/locate", tags=["dispersion"])
def locate_dispersion_line(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().locate_line(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/move", tags=["dispersion"])
def move_dispersion_line(
    task_id: int,
    line_id: int,
    payload: DispersionLineMoveRequest,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().move_line(task_id, line_id, payload.direction, payload.steps, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/save", tags=["dispersion"])
def save_dispersion_line_position(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().save_line_position(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/restore", tags=["dispersion"])
def restore_dispersion_line_position(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().restore_line_position(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/tasks/{task_id}/calibrations/fit", status_code=201, tags=["dispersion"])
def fit_dispersion_calibration(
    task_id: int,
    payload: DispersionCalibrationFitRequest,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().fit_calibration(task_id, payload.model_dump(exclude_none=True), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.get("/api/v1/dispersion/calibrations/{calibration_version_id}", tags=["dispersion"])
def get_dispersion_calibration(
    calibration_version_id: int,
    _: Session = Depends(require_permission("dispersion.read")),
) -> dict[str, Any]:
    try:
        return dispersion_service().calibration(calibration_version_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/calibrations/{calibration_version_id}/publish", tags=["dispersion"])
def publish_dispersion_calibration(
    calibration_version_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().publish_calibration(calibration_version_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.post("/api/v1/dispersion/calibrations/{calibration_version_id}/bind", tags=["dispersion"])
def bind_dispersion_calibration(
    calibration_version_id: int,
    payload: DispersionCalibrationBindRequest,
    session: Session = Depends(require_permission("dispersion.write")),
) -> dict[str, Any]:
    try:
        return dispersion_service().bind_calibration(calibration_version_id, payload.model_dump(exclude_none=True), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@app.get("/api/v1/dispersion/bindings", tags=["dispersion"])
def list_dispersion_bindings(
    method_id: int | None = Query(default=None, ge=1),
    _: Session = Depends(require_permission("dispersion.read")),
) -> list[dict[str, Any]]:
    return dispersion_service().bindings(method_id)


@app.get("/api/v1/acquisitions/options", tags=["acquisition"])
def acquisition_options(_: Session = Depends(require_permission("acquisition.read"))) -> dict[str, Any]:
    return acquisition_service().options()


@app.get("/api/v1/acquisitions/tasks", tags=["acquisition"])
def list_acquisition_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("acquisition.read")),
) -> list[dict[str, Any]]:
    return acquisition_service().list_tasks(limit)


@app.post("/api/v1/acquisitions/tasks", status_code=201, tags=["acquisition"])
def create_acquisition_task(
    payload: AcquisitionTaskCreate,
    session: Session = Depends(require_permission("acquisition.write")),
) -> dict[str, Any]:
    try:
        return acquisition_service().create_task(payload.model_dump(), session.user_id)
    except (AcquisitionError, SampleQueueError) as exc:
        if isinstance(exc, SampleQueueError):
            raise sample_queue_error(exc) from exc
        raise acquisition_error(exc) from exc


@app.get("/api/v1/acquisitions/tasks/{task_id}", tags=["acquisition"])
def get_acquisition_task(
    task_id: int,
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("acquisition.read")),
) -> dict[str, Any]:
    try:
        return acquisition_service()._task_dict(task_id, include_points=include_points)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/start", tags=["acquisition"])
def start_acquisition_task(task_id: int, session: Session = Depends(require_permission("acquisition.execute"))) -> dict[str, Any]:
    try:
        return acquisition_service().start(task_id, session.user_id)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/step", tags=["acquisition"])
def step_acquisition_task(task_id: int, session: Session = Depends(require_permission("acquisition.execute"))) -> dict[str, Any]:
    try:
        return acquisition_service().step(task_id, session.user_id)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/pause", tags=["acquisition"])
def pause_acquisition_task(task_id: int, session: Session = Depends(require_permission("acquisition.execute"))) -> dict[str, Any]:
    try:
        return acquisition_service().pause(task_id, session.user_id)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/resume", tags=["acquisition"])
def resume_acquisition_task(task_id: int, session: Session = Depends(require_permission("acquisition.execute"))) -> dict[str, Any]:
    try:
        return acquisition_service().resume(task_id, session.user_id)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/stop", tags=["acquisition"])
def stop_acquisition_task(task_id: int, session: Session = Depends(require_permission("acquisition.execute"))) -> dict[str, Any]:
    try:
        return acquisition_service().stop(task_id, session.user_id)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.get("/api/v1/acquisitions/tasks/{task_id}/frames", tags=["acquisition"])
def acquisition_frames(
    task_id: int,
    repeat_index: int | None = Query(default=None, ge=0, le=10),
    phase: str | None = Query(default=None),
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("acquisition.read")),
) -> list[dict[str, Any]]:
    try:
        return acquisition_service().frames(task_id, repeat_index=repeat_index, phase=phase, ccd_index=ccd_index, include_points=include_points)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/intervals", tags=["acquisition"])
def mark_acquisition_interval(
    task_id: int,
    payload: AcquisitionIntervalMark,
    session: Session = Depends(require_permission("acquisition.write")),
) -> dict[str, Any]:
    try:
        return acquisition_service().mark_interval(task_id, payload.model_dump(), session.user_id)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.get("/api/v1/acquisitions/tasks/{task_id}/analysis", tags=["acquisition"])
def acquisition_analysis(
    task_id: int,
    repeat_index: int | None = Query(default=None, ge=0, le=10),
    _: Session = Depends(require_permission("acquisition.read")),
) -> dict[str, Any]:
    try:
        return acquisition_service().analysis(task_id, repeat_index)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.get("/api/v1/acquisitions/samples/{sample_id}/bands", tags=["acquisition"])
def acquisition_sample_bands(
    sample_id: int,
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("acquisition.read")),
) -> list[dict[str, Any]]:
    try:
        return acquisition_service().band(sample_id, ccd_index, include_points)
    except AcquisitionError as exc:
        raise acquisition_error(exc) from exc


@app.post("/api/v1/acquisitions/tasks/{task_id}/samples/{sample_id}/rename", tags=["acquisition"])
def rename_acquisition_sample(
    task_id: int,
    sample_id: int,
    payload: AcquisitionRename,
    session: Session = Depends(require_permission("acquisition.write")),
) -> dict[str, Any]:
    try:
        return acquisition_service().rename(task_id, sample_id, payload.post_name, session.user_id)
    except (AcquisitionError, SampleQueueError) as exc:
        if isinstance(exc, SampleQueueError):
            raise sample_queue_error(exc) from exc
        raise acquisition_error(exc) from exc


@app.get("/api/v1/hardware-acquisitions/options", tags=["hardware-acquisition"])
def hardware_acquisition_options(_: Session = Depends(require_permission("hardware-acquisition.read"))) -> dict[str, Any]:
    return hardware_acquisition_service().options()


@app.get("/api/v1/hardware-acquisitions/tasks", tags=["hardware-acquisition"])
def list_hardware_acquisition_tasks(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("hardware-acquisition.read"))) -> list[dict[str, Any]]:
    return hardware_acquisition_service().list_tasks(limit)


@app.post("/api/v1/hardware-acquisitions/tasks", status_code=201, tags=["hardware-acquisition"])
def create_hardware_acquisition_task(payload: HardwareTaskCreate, session: Session = Depends(require_permission("hardware-acquisition.write"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().create_task(payload.model_dump(mode="json"), session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.get("/api/v1/hardware-acquisitions/tasks/{task_id}", tags=["hardware-acquisition"])
def get_hardware_acquisition_task(task_id: int, include_points: bool = Query(default=False), _: Session = Depends(require_permission("hardware-acquisition.read"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service()._task_dict(task_id, include_points=include_points)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.post("/api/v1/hardware-acquisitions/tasks/{task_id}/start", tags=["hardware-acquisition"])
def start_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().start(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.post("/api/v1/hardware-acquisitions/tasks/{task_id}/step", tags=["hardware-acquisition"])
def step_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().step(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.post("/api/v1/hardware-acquisitions/tasks/{task_id}/pause", tags=["hardware-acquisition"])
def pause_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().pause(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.post("/api/v1/hardware-acquisitions/tasks/{task_id}/resume", tags=["hardware-acquisition"])
def resume_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().resume(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.post("/api/v1/hardware-acquisitions/tasks/{task_id}/stop", tags=["hardware-acquisition"])
def stop_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().stop(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.post("/api/v1/hardware-acquisitions/tasks/{task_id}/intervene", tags=["hardware-acquisition"])
def intervene_hardware_acquisition_task(task_id: int, payload: HardwareIntervention, session: Session = Depends(require_permission("hardware-acquisition.execute"))) -> dict[str, Any]:
    try:
        return hardware_acquisition_service().intervene(task_id, payload.action, payload.note, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.get("/api/v1/hardware-acquisitions/tasks/{task_id}/frames", tags=["hardware-acquisition"])
def hardware_acquisition_frames(task_id: int, step_id: int | None = Query(default=None, ge=1), include_points: bool = Query(default=False), _: Session = Depends(require_permission("hardware-acquisition.read"))) -> list[dict[str, Any]]:
    try:
        return hardware_acquisition_service().frames(task_id, step_id=step_id, include_points=include_points)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.get("/api/v1/hardware-acquisitions/tasks/{task_id}/traces", tags=["hardware-acquisition"])
def hardware_acquisition_traces(task_id: int, _: Session = Depends(require_permission("hardware-acquisition.read"))) -> list[dict[str, Any]]:
    try:
        return hardware_acquisition_service().traces(task_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.get("/api/v1/hardware-acquisitions/tasks/{task_id}/decisions", tags=["hardware-acquisition"])
def hardware_acquisition_decisions(task_id: int, _: Session = Depends(require_permission("hardware-acquisition.read"))) -> list[dict[str, Any]]:
    try:
        return hardware_acquisition_service().decisions(task_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@app.get("/api/v1/mercury-calibrations/options", tags=["mercury-calibration"])
def mercury_calibration_options(_: Session = Depends(require_permission("mercury-calibration.read"))) -> dict[str, Any]:
    return mercury_calibration_service().options()


@app.get("/api/v1/mercury-calibrations/sessions", tags=["mercury-calibration"])
def list_mercury_calibration_sessions(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("mercury-calibration.read"))) -> list[dict[str, Any]]:
    return mercury_calibration_service().list_sessions(limit)


@app.post("/api/v1/mercury-calibrations/sessions", status_code=201, tags=["mercury-calibration"])
def create_mercury_calibration_session(payload: MercurySessionCreate, session: Session = Depends(require_permission("mercury-calibration.write"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().create_session(payload.model_dump(mode="json"), session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.get("/api/v1/mercury-calibrations/sessions/{session_id}", tags=["mercury-calibration"])
def get_mercury_calibration_session(session_id: int, include_points: bool = Query(default=False), _: Session = Depends(require_permission("mercury-calibration.read"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().session(session_id, include_points=include_points)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.post("/api/v1/mercury-calibrations/sessions/{session_id}/start", tags=["mercury-calibration"])
def start_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.execute"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().start(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.post("/api/v1/mercury-calibrations/sessions/{session_id}/step", tags=["mercury-calibration"])
def step_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.execute"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().step(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.post("/api/v1/mercury-calibrations/sessions/{session_id}/apply", tags=["mercury-calibration"])
def apply_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.write"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().apply(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.post("/api/v1/mercury-calibrations/sessions/{session_id}/rollback", tags=["mercury-calibration"])
def rollback_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.write"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().rollback(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.post("/api/v1/mercury-calibrations/sessions/{session_id}/stop", tags=["mercury-calibration"])
def stop_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.execute"))) -> dict[str, Any]:
    try:
        return mercury_calibration_service().stop(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@app.get("/api/v1/analyses/options", tags=["analysis"])
def analysis_options(_: Session = Depends(require_permission("analysis.read"))) -> dict[str, Any]:
    return analysis_service().options()


@app.get("/api/v1/analyses/runs", tags=["analysis"])
def list_analysis_runs(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("analysis.read"))) -> list[dict[str, Any]]:
    return analysis_service().list_runs(limit)


@app.post("/api/v1/analyses/runs", status_code=201, tags=["analysis"])
def create_analysis_run(payload: AnalysisRunCreate, session: Session = Depends(require_permission("analysis.execute"))) -> dict[str, Any]:
    try:
        return analysis_service().create_run(payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.get("/api/v1/analyses/runs/{run_id}", tags=["analysis"])
def get_analysis_run(run_id: int, _: Session = Depends(require_permission("analysis.read"))) -> dict[str, Any]:
    try:
        return analysis_service().run(run_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/start", tags=["analysis"])
def start_analysis_run(run_id: int, session: Session = Depends(require_permission("analysis.execute"))) -> dict[str, Any]:
    try:
        return analysis_service().start(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/step", tags=["analysis"])
def step_analysis_run(run_id: int, session: Session = Depends(require_permission("analysis.execute"))) -> dict[str, Any]:
    try:
        return analysis_service().step(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/intervene", tags=["analysis"])
def intervene_analysis_run(run_id: int, payload: AnalysisIntervention, session: Session = Depends(require_permission("analysis.intervene"))) -> dict[str, Any]:
    try:
        return analysis_service().intervene(run_id, payload.action, payload.adjusted_position, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/cancel", tags=["analysis"])
def cancel_analysis_run(run_id: int, session: Session = Depends(require_permission("analysis.execute"))) -> dict[str, Any]:
    try:
        return analysis_service().cancel(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/quality/recalculate", tags=["analysis"])
def recalculate_analysis_quality(run_id: int, session: Session = Depends(require_permission("analysis.quality"))) -> dict[str, Any]:
    try:
        return analysis_service().build_quality(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/quality/decisions", tags=["analysis"])
def decide_analysis_quality(run_id: int, payload: AnalysisQcDecision, session: Session = Depends(require_permission("analysis.quality"))) -> dict[str, Any]:
    try:
        return analysis_service().decide_quality(run_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/actions", tags=["analysis"])
def apply_analysis_curve_action(run_id: int, line_id: str, payload: AnalysisCurveAction, session: Session = Depends(require_permission("analysis.curve"))) -> dict[str, Any]:
    try:
        return analysis_service().curve_action(run_id, line_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/fit", status_code=201, tags=["analysis"])
def fit_analysis_curve(run_id: int, line_id: str, payload: AnalysisCurveFit, session: Session = Depends(require_permission("analysis.curve"))) -> dict[str, Any]:
    try:
        return analysis_service().fit_standard_curve(run_id, line_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/publish", tags=["analysis"])
def publish_analysis_curve(run_id: int, line_id: str, payload: AnalysisCurvePublish, session: Session = Depends(require_permission("analysis.curve"))) -> dict[str, Any]:
    try:
        return analysis_service().publish_standard_curve(run_id, line_id, payload.curve_snapshot_id, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/results/merge", status_code=201, tags=["analysis"])
def merge_analysis_results(run_id: int, payload: AnalysisMergeRequest, session: Session = Depends(require_permission("analysis.curve"))) -> dict[str, Any]:
    try:
        return analysis_service().merge_results(run_id, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.get("/api/v1/analyses/runs/{run_id}/curves/{curve_snapshot_id}/preview", response_class=HTMLResponse, tags=["analysis"])
def preview_analysis_curve(run_id: int, curve_snapshot_id: int, mode: str = Query(default="image", pattern="^(image|text)$"), session: Session = Depends(require_permission("analysis.read"))) -> HTMLResponse:
    try:
        return HTMLResponse(analysis_service().curve_preview(run_id, curve_snapshot_id, mode, session.user_id), headers={"Cache-Control": "no-store", "X-Curve-Snapshot-Id": str(curve_snapshot_id)})
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@app.post("/api/v1/analyses/runs/{run_id}/curves/{curve_snapshot_id}/print", tags=["analysis"])
def print_analysis_curve(run_id: int, curve_snapshot_id: int, mode: str = Query(default="image", pattern="^(image|text)$"), session: Session = Depends(require_permission("analysis.print"))) -> Response:
    try:
        content, metadata = analysis_service().print_curve(run_id, curve_snapshot_id, mode, session.user_id)
        filename = quote(f"analysis-{run_id}-curve-{curve_snapshot_id}-{mode}.pdf")
        return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}", "X-Print-Job-Id": str(metadata["job_id"]), "X-Content-SHA256": metadata["sha256"]})
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


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
    if PROCESS_KEY:
        supplied_key = websocket.headers.get("X-GeoSpectrum-Process-Key") or websocket.query_params.get("process_key", "")
        if not secrets.compare_digest(supplied_key, PROCESS_KEY):
            await websocket.close(code=4403, reason="process key required")
            return
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
