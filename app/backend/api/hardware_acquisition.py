"""Hardware Acquisition API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.hardware_acquisition import (
    HardwareTaskCreate,
    HardwareIntervention,
)
from ..auth import Session
from ..modules.hardware_acquisition import HardwareError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def hardware_error(exc: HardwareError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/hardware-acquisitions/options", tags=["hardware-acquisition"])
def hardware_acquisition_options(_: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.hardware_acquisition_service().options()


@router.get("/api/v1/hardware-acquisitions/tasks", tags=["hardware-acquisition"])
def list_hardware_acquisition_tasks(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.hardware_acquisition_service().list_tasks(limit)


@router.post("/api/v1/hardware-acquisitions/tasks", status_code=201, tags=["hardware-acquisition"])
def create_hardware_acquisition_task(payload: HardwareTaskCreate, session: Session = Depends(require_permission("hardware-acquisition.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().create_task(payload.model_dump(mode="json"), session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}", tags=["hardware-acquisition"])
def get_hardware_acquisition_task(task_id: int, include_points: bool = Query(default=False), _: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service()._task_dict(task_id, include_points=include_points)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.post("/api/v1/hardware-acquisitions/tasks/{task_id}/start", tags=["hardware-acquisition"])
def start_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().start(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.post("/api/v1/hardware-acquisitions/tasks/{task_id}/step", tags=["hardware-acquisition"])
def step_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().step(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.post("/api/v1/hardware-acquisitions/tasks/{task_id}/pause", tags=["hardware-acquisition"])
def pause_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().pause(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.post("/api/v1/hardware-acquisitions/tasks/{task_id}/resume", tags=["hardware-acquisition"])
def resume_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().resume(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.post("/api/v1/hardware-acquisitions/tasks/{task_id}/stop", tags=["hardware-acquisition"])
def stop_hardware_acquisition_task(task_id: int, session: Session = Depends(require_permission("hardware-acquisition.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().stop(task_id, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.post("/api/v1/hardware-acquisitions/tasks/{task_id}/intervene", tags=["hardware-acquisition"])
def intervene_hardware_acquisition_task(task_id: int, payload: HardwareIntervention, session: Session = Depends(require_permission("hardware-acquisition.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.hardware_acquisition_service().intervene(task_id, payload.action, payload.note, session.user_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}/frames", tags=["hardware-acquisition"])
def hardware_acquisition_frames(task_id: int, step_id: int | None = Query(default=None, ge=1), include_points: bool = Query(default=False), _: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    try:
        return runtime.hardware_acquisition_service().frames(task_id, step_id=step_id, include_points=include_points)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}/traces", tags=["hardware-acquisition"])
def hardware_acquisition_traces(task_id: int, _: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    try:
        return runtime.hardware_acquisition_service().traces(task_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}/decisions", tags=["hardware-acquisition"])
def hardware_acquisition_decisions(task_id: int, _: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    try:
        return runtime.hardware_acquisition_service().decisions(task_id)
    except HardwareError as exc:
        raise hardware_error(exc) from exc
