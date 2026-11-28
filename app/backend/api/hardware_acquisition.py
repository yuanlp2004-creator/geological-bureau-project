"""Historical turn acquisition queries and confirmed sample conversion."""

from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..auth import Session
from ..modules.acquisition import AcquisitionError, LegacyHardwareService
from ..runtime import Runtime
from ..schemas.hardware_acquisition import HardwareAnalysisSample
from .dependencies import get_runtime, require_permission

router = APIRouter()


@router.post('/api/v1/hardware-acquisitions/tasks/{task_id}/analysis-sample', tags=['hardware-acquisition'])
def save_hardware_analysis_sample(task_id: int, payload: HardwareAnalysisSample,
    session: Session = Depends(require_permission('hardware-acquisition.execute')),
    _: Session = Depends(require_permission('acquisition.write')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return LegacyHardwareService(runtime.database).save_analysis_sample(task_id, payload.model_dump(), session.user_id)
    except AcquisitionError as exc:
        raise hardware_error(exc) from exc


def hardware_error(exc: AcquisitionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/hardware-acquisitions/options", tags=["hardware-acquisition"])
def hardware_acquisition_options(
    _: Session = Depends(require_permission("hardware-acquisition.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    return LegacyHardwareService(runtime.database).options()


@router.get("/api/v1/hardware-acquisitions/tasks", tags=["hardware-acquisition"])
def list_hardware_acquisition_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("hardware-acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return LegacyHardwareService(runtime.database).list_tasks(limit)


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}", tags=["hardware-acquisition"])
def get_hardware_acquisition_task(
    task_id: int,
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("hardware-acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return LegacyHardwareService(runtime.database).get_task(task_id, include_points=include_points)
    except AcquisitionError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}/frames", tags=["hardware-acquisition"])
def hardware_acquisition_frames(
    task_id: int,
    step_id: int | None = Query(default=None, ge=1),
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("hardware-acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    try:
        return LegacyHardwareService(runtime.database).frames(task_id, step_id=step_id, include_points=include_points)
    except AcquisitionError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}/traces", tags=["hardware-acquisition"])
def hardware_acquisition_traces(
    task_id: int,
    _: Session = Depends(require_permission("hardware-acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    try:
        return LegacyHardwareService(runtime.database).traces(task_id)
    except AcquisitionError as exc:
        raise hardware_error(exc) from exc


@router.get("/api/v1/hardware-acquisitions/tasks/{task_id}/decisions", tags=["hardware-acquisition"])
def hardware_acquisition_decisions(
    task_id: int,
    _: Session = Depends(require_permission("hardware-acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    try:
        return LegacyHardwareService(runtime.database).decisions(task_id)
    except AcquisitionError as exc:
        raise hardware_error(exc) from exc
