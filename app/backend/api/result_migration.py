"""Result Migration API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.result_migration import (
    ResultMigrationStageRequest,
    ResultMigrationCommitRequest,
)
from ..auth import Session
from ..modules.legacy_migration import LegacyMigrationError
from ..modules.legacy_sources import discover_sources
from ..modules.result_migration import ResultMigrationError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def legacy_migration_error(exc: LegacyMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


def result_migration_error(exc: ResultMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/result-migration/sources", tags=["result-migration"])
def discover_result_sources(
    root: str | None = Query(default=None, max_length=2048),
    _: Session = Depends(require_permission("result-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return discover_sources("results", root)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.get("/api/v1/result-migration/diagnostics", tags=["result-migration"])
def result_migration_diagnostics(
    _: Session = Depends(require_permission("result-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.result_migration_service().diagnostics()


@router.post("/api/v1/result-migration/stage", tags=["result-migration"])
def stage_result_migration(
    payload: ResultMigrationStageRequest,
    session: Session = Depends(require_permission("result-migration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.result_migration_service().stage(payload.path, session.user_id)
    except ResultMigrationError as exc:
        raise result_migration_error(exc) from exc


@router.get("/api/v1/result-migration/runs", tags=["result-migration"])
def list_result_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("result-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return {"runs": runtime.result_migration_service().list(limit)}


@router.get("/api/v1/result-migration/runs/{run_id}", tags=["result-migration"])
def get_result_migration_run(
    run_id: str,
    _: Session = Depends(require_permission("result-migration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.result_migration_service().get(run_id)
    except ResultMigrationError as exc:
        raise result_migration_error(exc) from exc


@router.post("/api/v1/result-migration/commit", tags=["result-migration"])
def commit_result_migration(
    payload: ResultMigrationCommitRequest,
    session: Session = Depends(require_permission("result-migration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.result_migration_service().commit(payload.run_id, session.user_id)
    except ResultMigrationError as exc:
        raise result_migration_error(exc) from exc
