"""Legacy Migration API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.legacy_migration import (
    LegacyMigrationStageRequest,
    LegacyMigrationCommitRequest,
)
from ..auth import Session
from ..modules.legacy_migration import LegacyMigrationError
from ..modules.legacy_sources import discover_sources
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def legacy_migration_error(exc: LegacyMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/legacy-migration/sources", tags=["legacy-migration"])
def discover_method_sources(
    root: str | None = Query(default=None, max_length=2048),
    _: Session = Depends(require_permission("migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return discover_sources("methods", root)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.get("/api/v1/legacy-migration/diagnostics", tags=["legacy-migration"])
def legacy_migration_diagnostics(
    _: Session = Depends(require_permission("migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.legacy_migration_service().diagnostics()


@router.post("/api/v1/legacy-migration/stage", tags=["legacy-migration"])
def stage_legacy_migration(
    payload: LegacyMigrationStageRequest,
    session: Session = Depends(require_permission("migration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.legacy_migration_service().stage(
            payload.mtd_path, payload.cfg_path, payload.opt_path, session.user_id
        )
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.get("/api/v1/legacy-migration/runs", tags=["legacy-migration"])
def list_legacy_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return {"runs": runtime.legacy_migration_service().list(limit)}


@router.get("/api/v1/legacy-migration/runs/{run_id}", tags=["legacy-migration"])
def get_legacy_migration_run(
    run_id: str,
    _: Session = Depends(require_permission("migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.legacy_migration_service().get(run_id)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.post("/api/v1/legacy-migration/commit", tags=["legacy-migration"])
def commit_legacy_migration(
    payload: LegacyMigrationCommitRequest,
    session: Session = Depends(require_permission("migration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.legacy_migration_service().commit(payload.run_id, session.user_id)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc
