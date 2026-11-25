"""Local administration of activation and explicitly shared support diagnostics."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth import Session
from ..modules.activation import MAX_LICENSE_BYTES, ActivationError, ActivationStatus
from ..modules.manifest import registered_manifests, validate_manifests
from ..modules.support_diagnostics import SupportConflict, diagnostic_snapshot
from ..runtime import Runtime
from ..schemas.system import RuntimeEventCreate
from .dependencies import get_runtime, require_permission
from .module_diagnostics import inspect_modules

router = APIRouter(prefix="/api/v1", tags=["deployment-access"])


def require_activation(runtime: Runtime, *, begins_new_work: Callable[[], bool] | None = None) -> None:
    if runtime.activation.managed:
        status = runtime.activation.status()
        if status.state != "active" and (begins_new_work is None or begins_new_work()):
            raise HTTPException(403, detail={
                "code": f"activation_{status.state}",
                "message": "软件授权不可用。请联系管理员在「关于软件」中导入有效授权后，再开始新任务。",
            })


class ActivationInstall(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_LICENSE_BYTES)


class SupportOpen(BaseModel):
    minutes: int = Field(ge=1, le=30, strict=True)


def _audit(runtime: Runtime, session: Session, action: str, message: str) -> None:
    runtime.service.append_event(
        RuntimeEventCreate(category="system", severity="info", message=message),
        actor_user_id=session.user_id, audit_action=action,
    )


async def _support_snapshot(request: Request, runtime: Runtime) -> tuple[datetime, bytes]:
    checked_at = datetime.now(timezone.utc)
    manifests = registered_manifests()
    manifest_error = None
    try:
        validate_manifests(manifests)
    except ValueError as exc:
        manifest_error = str(exc)
    modules = await inspect_modules(request, runtime, manifests, manifest_error)
    events = await run_in_threadpool(runtime.service.list_events, limit=40)
    return checked_at, diagnostic_snapshot(modules, events, checked_at)


@router.get("/activation", response_model=ActivationStatus, response_model_exclude_none=True)
def activation_status(
    _: Session = Depends(require_permission("activation.manage")), *, runtime: Runtime = Depends(get_runtime),
) -> ActivationStatus:
    return runtime.activation.status(initialize=True)


@router.put("/activation", response_model=ActivationStatus, response_model_exclude_none=True)
def install_activation(
    payload: ActivationInstall, session: Session = Depends(require_permission("activation.manage")), *,
    runtime: Runtime = Depends(get_runtime),
) -> ActivationStatus:
    try:
        result, changed = runtime.activation.install(payload.content.encode("utf-8"))
    except (ActivationError, UnicodeError) as exc:
        message = str(exc) if isinstance(exc, ActivationError) else "授权文件格式无效"
        raise HTTPException(422, detail={"code": "activation_file_rejected", "message": message}) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, detail={"code": "activation_store_unavailable", "message": "无法读取安装标识或保存授权文件"}) from exc
    if changed:
        _audit(runtime, session, "activation.install", f"已导入软件授权，到期时间 {result.expires_at.isoformat()}")
    return result


@router.get("/support/session")
def support_status(
    _: Session = Depends(require_permission("support.manage")), *, runtime: Runtime = Depends(get_runtime),
) -> dict:
    return runtime.support_diagnostics.status()


@router.post("/support/session", status_code=201)
async def open_support_session(
    payload: SupportOpen, request: Request, response: Response,
    session: Session = Depends(require_permission("support.manage")), *, runtime: Runtime = Depends(get_runtime),
) -> dict:
    if runtime.support_diagnostics.status()["active"]:
        raise HTTPException(409, detail="已有远程诊断会话，请先结束")
    snapshot = await _support_snapshot(request, runtime)
    operator_token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()

    def operator_authorized() -> bool:
        current = runtime.auth_service.get_session(operator_token)
        return current is not None and "support.manage" in current.permissions

    try:
        result = await run_in_threadpool(
            runtime.support_diagnostics.open, snapshot, payload.minutes, operator_authorized,
            lambda: _audit(runtime, session, "support.open", f"已开启模块远程诊断，有效期 {payload.minutes} 分钟"),
        )
    except SupportConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, detail="无法开启本机诊断端口") from exc
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/support/session/refresh")
async def refresh_support_session(
    request: Request, session: Session = Depends(require_permission("support.manage")), *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    sharing = runtime.support_diagnostics.active_session()
    if sharing is None:
        raise HTTPException(409, detail="诊断会话已结束，请重新开启")
    snapshot = await _support_snapshot(request, runtime)
    try:
        return await run_in_threadpool(
            runtime.support_diagnostics.refresh, sharing, snapshot,
            lambda: _audit(runtime, session, "support.refresh", "已刷新模块远程诊断快照"),
        )
    except SupportConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.delete("/support/session", status_code=204, response_class=Response)
def close_support_session(
    session: Session = Depends(require_permission("support.manage")), *, runtime: Runtime = Depends(get_runtime),
) -> Response:
    if runtime.support_diagnostics.close():
        _audit(runtime, session, "support.close", "已结束模块远程诊断")
    return Response(status_code=204)
