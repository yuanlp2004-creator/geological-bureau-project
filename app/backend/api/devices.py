"""Devices API boundary; business services retain their existing behavior."""

from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from ..schemas.devices import (
    DeviceProfileCreate,
    DeviceProfileUpdate,
    DeviceConnectRequest,
    DevicePortSelection,
    DeviceDebugStartRequest,
    DeviceDebugTurnRequest,
)
from ..auth import Session
from ..modules.devices import DeviceError
from ..modules.devices.ports import available_serial_ports, validate_bluetooth_binding
from ..modules.devices.motor_turn import MotorBinding, motor_binding
from ..modules.methods import MethodDomainError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission, require_session

router = APIRouter()


@router.post("/api/v1/devices/prepare-exit", include_in_schema=False)
def prepare_device_exit(*, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    # Native lifecycle operation: process-key middleware authenticates the
    # owning desktop process; browser/development APIs cannot invoke it.
    if not runtime.process_key:
        raise HTTPException(status_code=403, detail="仅允许配对桌面进程停止设备后退出")
    errors = runtime.shutdown(resume_on_failure=True)
    return {"safe_to_exit": not errors, "errors": errors}


def device_error(exc: DeviceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/devices/ports", tags=["devices"])
def list_device_ports(_: Session = Depends(require_permission("devices.read"))) -> list[dict[str, Any]]:
    try:
        return available_serial_ports()
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.get('/api/v1/devices/bluetooth', tags=['devices'])
def list_bluetooth_connections(_: Session = Depends(require_permission('devices.read')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.devices_service().bluetooth_devices()
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.delete('/api/v1/devices/bluetooth/{address}', tags=['devices'])
def hide_bluetooth_device(address: str, session: Session = Depends(require_permission('devices.write')), *,
                          runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        if runtime.active_serial_captures():
            raise DeviceError('device_busy', '请先停止摄谱任务，再从列表删除', status_code=409)
        return runtime.devices_service().hide_bluetooth_device(address, session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/profiles/{profile_id}/connection-test", tags=["devices"])
def test_device_connection(profile_id: int, purpose: str = "devices",
                           session: Session = Depends(require_session), *,
                           runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    permissions = {"devices": "devices.execute", "acquisition": "acquisition.execute",
                   "dispersion": "dispersion.execute"}
    if purpose not in permissions or permissions[purpose] not in session.permissions:
        raise HTTPException(status_code=403, detail="permission denied")
    try:
        if purpose == 'devices':
            return runtime.devices_service().test_connection(profile_id, actor_user_id=session.user_id)
        owner = {'acquisition': 'sample-acquisition', 'dispersion': 'dispersion'}[purpose]
        return runtime.devices_service().test_connection(profile_id, session.user_id, handoff=True, owner=owner)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.get("/api/v1/devices/profiles", tags=["devices"])
def list_device_profiles(
    _: Session = Depends(require_permission("devices.read")), *, runtime: Runtime = Depends(get_runtime)
) -> list[dict[str, Any]]:
    return runtime.devices_service().profiles()


@router.get('/api/v1/devices/current', tags=['devices'])
def current_device_profile(_: Session = Depends(require_permission('devices.read')), *,
                           runtime: Runtime = Depends(get_runtime)) -> dict | None:
    return runtime.devices_service().current_profile()


@router.put('/api/v1/devices/current', tags=['devices'])
def select_device_profile(payload: DeviceConnectRequest,
                          session: Session = Depends(require_permission('devices.write')), *,
                          runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.devices_service().select_profile(payload.profile_id, session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.get("/api/v1/devices/profiles/{profile_id}", tags=["devices"])
def get_device_profile(
    profile_id: int,
    _: Session = Depends(require_permission("devices.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.devices_service().profile(profile_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.get("/api/v1/devices/profiles/{profile_id}/motor-binding", tags=["devices"])
def get_motor_binding(profile_id: int, _: Session = Depends(require_permission("devices.read")), *,
                      runtime: Runtime = Depends(get_runtime)) -> MotorBinding | None:
    try:
        runtime.devices_service().profile(profile_id)
        return motor_binding(runtime.database, profile_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.put("/api/v1/devices/profiles/{profile_id}/motor-binding", tags=["devices"])
def update_motor_binding(profile_id: int, payload: MotorBinding, session: Session = Depends(require_permission("devices.write")), *,
                         runtime: Runtime = Depends(get_runtime)) -> MotorBinding:
    try:
        if runtime.active_serial_captures():
            raise DeviceError("device_busy", "请先停止当前采集，再修改电机绑定", status_code=409)
        runtime.devices_service().update_motor_binding(profile_id, payload, session.user_id)
        return payload
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.put('/api/v1/devices/port', tags=['devices'])
def select_device_port(payload: DevicePortSelection,
                       session: Session = Depends(require_permission('devices.write')), *,
                       runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        if payload.bluetooth_address:
            if payload.transport != 'serial' or payload.port is None:
                raise DeviceError('bluetooth_port_mismatch', '蓝牙设备须选择对应的真实COM口', status_code=409)
            validate_bluetooth_binding(payload.bluetooth_address, payload.port)
        return runtime.devices_service().select_port(payload.transport, payload.port, session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/profiles", status_code=201, tags=["devices"])
def create_device_profile(
    payload: DeviceProfileCreate,
    session: Session = Depends(require_permission("devices.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.devices_service().create_profile(payload.model_dump(), actor_user_id=session.user_id)
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.patch("/api/v1/devices/profiles/{profile_id}", tags=["devices"])
def update_device_profile(
    profile_id: int,
    payload: DeviceProfileUpdate,
    session: Session = Depends(require_permission("devices.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.devices_service().update_profile(
            profile_id, payload.model_dump(exclude_none=True), actor_user_id=session.user_id
        )
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.get("/api/v1/devices/diagnostics", tags=["devices"])
def device_diagnostics(
    _: Session = Depends(require_permission("devices.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    current = runtime.devices_service()
    ownership = runtime.device_ownership.snapshot()
    return {"profiles": current.profiles(), "adapter": current.diagnostics(),
            "ownership": ownership, "active_captures": runtime.active_serial_captures(ownership=ownership)}


@router.get("/api/v1/devices/debug/turn", tags=["devices"])
def debug_turn_state(_: Session = Depends(require_permission("devices.read")), *,
                     runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.devices_service().turn_state(runtime.methods_service().current_working_angles())
    except (DeviceError, MethodDomainError) as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.post("/api/v1/devices/debug/turn", tags=["devices"])
def switch_debug_angle(payload: DeviceDebugTurnRequest, session: Session = Depends(require_permission("devices.execute")), *,
                       runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.devices_service().switch_debug_angle(payload.profile_id, payload.angle_deg,
                                                             runtime.methods_service().current_working_angles(), session.user_id)
    except (DeviceError, MethodDomainError) as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.post("/api/v1/devices/connect", tags=["devices"])
def connect_device(
    payload: DeviceConnectRequest,
    session: Session = Depends(require_permission("devices.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.device(runtime.devices_service().connect(payload.profile_id, actor_user_id=session.user_id))
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/disconnect", tags=["devices"])
def disconnect_device(
    session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        return runtime.messages.device(runtime.disconnect_devices(session.user_id))
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/debug/start", tags=["devices"])
def start_device_debug(
    payload: DeviceDebugStartRequest,
    session: Session = Depends(require_permission("devices.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.device(runtime.devices_service().start_debug(payload.model_dump(), actor_user_id=session.user_id))
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/debug/step", tags=["devices"])
def step_device_debug(
    session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        return runtime.messages.device(runtime.devices_service().step_debug(actor_user_id=session.user_id))
    except DeviceError as exc:
        raise device_error(exc) from exc


@router.post("/api/v1/devices/debug/stop", tags=["devices"])
def stop_device_debug(
    session: Session = Depends(require_permission("devices.execute")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        return runtime.messages.device(runtime.devices_service().stop_debug(actor_user_id=session.user_id))
    except DeviceError as exc:
        raise device_error(exc) from exc
