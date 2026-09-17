"""Identity HTTP boundary; account transactions belong to AuthService."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from ..auth import AuthError, Session
from ..runtime import Runtime
from ..schemas.auth import BootstrapRequest, LoginRequest, UserCreate, UserUpdate, RoleCreate, RoleUpdate
from .dependencies import get_runtime, require_permission, require_session

router = APIRouter()


@router.post("/api/v1/auth/bootstrap", status_code=201, tags=["auth"])
def bootstrap(payload: BootstrapRequest, *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.auth_service.bootstrap(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/v1/auth/status", tags=["auth"])
def auth_status(*, runtime: Runtime = Depends(get_runtime)) -> dict:
    """Public status used by the first-run UI; it never exposes account data."""
    return {"bootstrapped": runtime.auth_service.is_bootstrapped()}


@router.post("/api/v1/auth/login", tags=["auth"])
def login(payload: LoginRequest, *, runtime: Runtime = Depends(get_runtime)) -> dict:
    result = runtime.auth_service.login(payload.username, payload.password)
    if not result:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_invalid_credentials", "message": "用户名或密码错误"},
        )
    token, session = result
    return {"access_token": token, "token_type": "bearer", "expires_at": session.expires_at, "user": {"id": session.user_id, "username": session.username, "roles": session.roles, "permissions": sorted(session.permissions)}}


@router.get("/api/v1/auth/me", tags=["auth"])
def me(session: Session = Depends(require_session), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return {"id": session.user_id, "username": session.username, "roles": session.roles, "permissions": sorted(session.permissions), "expires_at": session.expires_at}


@router.post("/api/v1/auth/logout", status_code=204, response_class=Response, tags=["auth"])
def logout(authorization: str | None = Header(default=None), session: Session = Depends(require_session), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    if token:
        runtime.auth_service.logout(token)
    return Response(status_code=204)


@router.get("/api/v1/users", tags=["auth"])
def users(_: Session = Depends(require_permission("users.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict]:
    try:
        return runtime.auth_service.list_users()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/users", status_code=201, tags=["auth"])
def create_user(payload: UserCreate, session: Session = Depends(require_permission("users.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.auth_service.create_user(payload, session.user_id)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/api/v1/users/{user_id}", tags=["auth"])
def update_user(user_id: int, payload: UserUpdate, session: Session = Depends(require_permission("users.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.auth_service.update_user(user_id, payload, session.user_id)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/v1/roles", tags=["auth"])
def roles(_: Session = Depends(require_permission("users.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict]:
    try:
        return runtime.auth_service.list_roles()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/v1/roles", status_code=201, tags=["auth"])
def create_role(payload: RoleCreate, session: Session = Depends(require_permission("roles.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.auth_service.create_role(payload, session.user_id)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.patch("/api/v1/roles/{role_id}", tags=["auth"])
def update_role(role_id: int, payload: RoleUpdate, session: Session = Depends(require_permission("roles.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.auth_service.update_role(role_id, payload, session.user_id)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/api/v1/audit", tags=["auth"])
def audit(_: Session = Depends(require_permission("audit.read")), limit: int = Query(default=100, ge=1, le=500), *, runtime: Runtime = Depends(get_runtime)) -> list[dict]:
    try:
        return runtime.auth_service.list_audit(limit)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
