"""Devices API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from ..schemas.devices import (
    DeviceProfileCreate,
    DeviceProfileUpdate,
    DeviceConnectRequest,
    DeviceDebugStartRequest,
)
from ..auth import Session
from ..modules.devices import DeviceError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def device_error(exc: DeviceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/devices/profiles", tags=["devices"])
def list_device_profiles(_: Session = Depends(require_permission("devices.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.devices_service().profiles()


@router.get("/api/v1/devices/profiles/{profile_id}", tags=["devices"])
def get_device_profile(profile_id: int, _: Session = Depends(require_permission("devices.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().profile(profile_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/profiles", status_code=201, tags=["devices"])
def create_device_profile(payload: DeviceProfileCreate, session: Session = Depends(require_permission("devices.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().create_profile(payload.model_dump(), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.patch("/api/v1/devices/profiles/{profile_id}", tags=["devices"])
def update_device_profile(profile_id: int, payload: DeviceProfileUpdate, session: Session = Depends(require_permission("devices.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().update_profile(profile_id, payload.model_dump(exclude_none=True), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.get("/api/v1/devices/diagnostics", tags=["devices"])
def device_diagnostics(_: Session = Depends(require_permission("devices.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    current = runtime.devices_service()
    return {"profiles": current.profiles(), "adapter": current.adapter.diagnostics()}


@router.post("/api/v1/devices/connect", tags=["devices"])
def connect_device(payload: DeviceConnectRequest, session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().connect(payload.profile_id, actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/disconnect", tags=["devices"])
def disconnect_device(session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().disconnect(actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/debug/start", tags=["devices"])
def start_device_debug(payload: DeviceDebugStartRequest, session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().start_debug(payload.model_dump(), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/debug/step", tags=["devices"])
def step_device_debug(session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().step_debug(actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/debug/stop", tags=["devices"])
def stop_device_debug(session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.devices_service().stop_debug(actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc
