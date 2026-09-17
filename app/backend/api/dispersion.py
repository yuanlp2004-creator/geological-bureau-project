"""Dispersion API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.dispersion import (
    DispersionTaskCreate,
    DispersionLineInput,
    DispersionLineMoveRequest,
    DispersionCalibrationFitRequest,
    DispersionCalibrationBindRequest,
)
from ..auth import Session
from ..modules.dispersion import DispersionError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def dispersion_error(exc: DispersionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/dispersion/options", tags=["dispersion"])
def dispersion_options(_: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.dispersion_service().options()


@router.get("/api/v1/dispersion/tasks", tags=["dispersion"])
def list_dispersion_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.dispersion_service().list_tasks(limit)


@router.post("/api/v1/dispersion/tasks", status_code=201, tags=["dispersion"])
def create_dispersion_task(
    payload: DispersionTaskCreate,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().create_task(payload.model_dump(mode="json"), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/tasks/{task_id}", tags=["dispersion"])
def get_dispersion_task(
    task_id: int,
    _: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().get_task(task_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/start", tags=["dispersion"])
def start_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().start_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/step", tags=["dispersion"])
def step_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().step_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/pause", tags=["dispersion"])
def pause_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().pause_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/resume", tags=["dispersion"])
def resume_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().resume_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/stop", tags=["dispersion"])
def stop_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().stop_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/tasks/{task_id}/frames", tags=["dispersion"])
def dispersion_task_frames(
    task_id: int,
    phase: str | None = Query(default=None),
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    _: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    try:
        return runtime.dispersion_service().frames(task_id, phase=phase, ccd_index=ccd_index)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines", status_code=201, tags=["dispersion"])
def add_dispersion_line(
    task_id: int,
    payload: DispersionLineInput,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().add_line(task_id, payload.model_dump(mode="json"), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.delete("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}", tags=["dispersion"])
def delete_dispersion_line(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().delete_line(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/locate-all", tags=["dispersion"])
def locate_all_dispersion_lines(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.dispersion_service().locate_all(task_id, session.user_id)


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/locate", tags=["dispersion"])
def locate_dispersion_line(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().locate_line(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/move", tags=["dispersion"])
def move_dispersion_line(
    task_id: int,
    line_id: int,
    payload: DispersionLineMoveRequest,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().move_line(task_id, line_id, payload.direction, payload.steps, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/save", tags=["dispersion"])
def save_dispersion_line_position(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().save_line_position(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/restore", tags=["dispersion"])
def restore_dispersion_line_position(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().restore_line_position(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/calibrations/fit", status_code=201, tags=["dispersion"])
def fit_dispersion_calibration(
    task_id: int,
    payload: DispersionCalibrationFitRequest,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().fit_calibration(task_id, payload.model_dump(exclude_none=True), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/calibrations/{calibration_version_id}", tags=["dispersion"])
def get_dispersion_calibration(
    calibration_version_id: int,
    _: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().calibration(calibration_version_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/calibrations/{calibration_version_id}/publish", tags=["dispersion"])
def publish_dispersion_calibration(
    calibration_version_id: int,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().publish_calibration(calibration_version_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/calibrations/{calibration_version_id}/bind", tags=["dispersion"])
def bind_dispersion_calibration(
    calibration_version_id: int,
    payload: DispersionCalibrationBindRequest,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().bind_calibration(calibration_version_id, payload.model_dump(exclude_none=True), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/bindings", tags=["dispersion"])
def list_dispersion_bindings(
    method_id: int | None = Query(default=None, ge=1),
    _: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.dispersion_service().bindings(method_id)
