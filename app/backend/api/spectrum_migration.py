"""Spectrum Migration API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.spectrum_migration import (
    SpectrumMigrationStageRequest,
    SpectrumMigrationCommitRequest,
)
from ..auth import Session
from ..modules.legacy_migration import LegacyMigrationError
from ..modules.legacy_sources import discover_sources
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def spectrum_migration_error(exc: LegacyMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/spectrum-migration/sources", tags=["spectrum-migration"])
def discover_spectrum_sources(
    root: str | None = Query(default=None, max_length=2048),
    _: Session = Depends(require_permission("spectrum-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return discover_sources("spectra", root)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc


@router.get("/api/v1/spectrum-migration/diagnostics", tags=["spectrum-migration"])
def spectrum_migration_diagnostics(
    _: Session = Depends(require_permission("spectrum-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.spectrum_migration_service().diagnostics()


@router.post("/api/v1/spectrum-migration/stage", tags=["spectrum-migration"])
def stage_spectrum_migration(
    payload: SpectrumMigrationStageRequest,
    session: Session = Depends(require_permission("spectrum-migration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.spectrum_migration_service().stage(payload.path, session.user_id)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc


@router.get("/api/v1/spectrum-migration/runs", tags=["spectrum-migration"])
def list_spectrum_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("spectrum-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return {"runs": runtime.spectrum_migration_service().list(limit)}


@router.get("/api/v1/spectrum-migration/runs/{run_id}", tags=["spectrum-migration"])
def get_spectrum_migration_run(
    run_id: str,
    _: Session = Depends(require_permission("spectrum-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.spectrum_migration_service().get(run_id)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc


@router.post("/api/v1/spectrum-migration/commit", tags=["spectrum-migration"])
def commit_spectrum_migration(
    payload: SpectrumMigrationCommitRequest,
    session: Session = Depends(require_permission("spectrum-migration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.spectrum_migration_service().commit(payload.run_id, session.user_id)
    except LegacyMigrationError as exc:
        raise spectrum_migration_error(exc) from exc
