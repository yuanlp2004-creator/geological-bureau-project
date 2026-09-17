"""Maintenance API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.maintenance import (
    BackupCreate,
    MaintenanceActionRequest,
    HelpTopicResponse,
)
from ..auth import Session
from ..modules.maintenance import MaintenanceError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def maintenance_error(exc: MaintenanceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/maintenance/status", tags=["maintenance"])
def maintenance_status(_: Session = Depends(require_permission("maintenance.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.maintenance_service().status()


@router.get("/api/v1/backups", tags=["maintenance"])
def list_backups(_: Session = Depends(require_permission("maintenance.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.maintenance_service().list_backups()


@router.post("/api/v1/backups", tags=["maintenance"])
def create_backup(payload: BackupCreate, session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().backup(payload.output_directory, payload.filename, payload.retention_days, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/backups/retention", tags=["maintenance"])
def run_retention(session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().retention(session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/backups/{backup_id}/verify", tags=["maintenance"])
def verify_backup(backup_id: str, _: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().verify_backup(backup_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/backups/{backup_id}/restore-rehearsal", tags=["maintenance"])
def restore_rehearsal(backup_id: str, session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().restore_rehearsal(backup_id, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/maintenance/checkpoint", tags=["maintenance"])
def checkpoint(payload: MaintenanceActionRequest, session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().checkpoint(payload.mode, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/maintenance/optimize", tags=["maintenance"])
def optimize(session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().optimize(session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/maintenance/reclaim", tags=["maintenance"])
def reclaim(session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().reclaim(session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/maintenance/logs/cleanup", tags=["maintenance"])
def cleanup_logs(payload: MaintenanceActionRequest, session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().cleanup_logs(payload.retention_days, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.post("/api/v1/maintenance/temp/cleanup", tags=["maintenance"])
def cleanup_temp(payload: MaintenanceActionRequest, session: Session = Depends(require_permission("maintenance.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().cleanup_temp(payload.retention_days, session.user_id)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.get("/api/v1/help/topics", response_model=list[HelpTopicResponse], tags=["help"])
def help_topics(q: str | None = Query(default=None, max_length=120), _: Session = Depends(require_permission("help.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.maintenance_service().help_topics(q)


@router.get("/api/v1/help/error-codes/{code}", tags=["help"])
def help_error_code(code: str, _: Session = Depends(require_permission("help.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().help_topic_for_error(code)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc


@router.get("/api/v1/help/topics/{slug}", response_model=HelpTopicResponse, tags=["help"])
def help_topic(slug: str, _: Session = Depends(require_permission("help.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.maintenance_service().help_topic(slug)
    except MaintenanceError as exc:
        raise maintenance_error(exc) from exc
