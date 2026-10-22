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
from .dependencies import get_runtime, require_permission, require_session
from ..schemas.legacy_open import LegacyOpenRequest
from ..modules.legacy_migration.opening import OPEN_RULES, open_legacy_file
from ..modules.result_migration import ResultMigrationError
from ..modules.dispersion import DispersionError

router = APIRouter()


@router.get('/api/v1/legacy-migration/open-options', tags=['legacy-migration'])
def workspace_open_options(session: Session = Depends(require_session)) -> dict:
    return {purpose: {'extensions': sorted(ext[1:] for ext in rules[0])}
            for purpose, rules in OPEN_RULES.items() if set(rules[1:]).issubset(session.permissions)}


@router.post('/api/v1/legacy-migration/open-file', tags=['legacy-migration'])
def open_workspace_file(payload: LegacyOpenRequest, session: Session = Depends(require_session),
                        runtime: Runtime = Depends(get_runtime)) -> dict:
    if not set(OPEN_RULES[payload.purpose][1:]).issubset(session.permissions):
        raise HTTPException(status_code=403, detail='permission denied')
    try:
        result = open_legacy_file(payload.path, payload.purpose, session.user_id,
                                methods=runtime.legacy_migration_service(), spectra=runtime.spectrum_migration_service(),
                                results=runtime.result_migration_service())
        if payload.purpose == 'dispersion':
            result['task_ids'] = [runtime.dispersion_service().open_legacy_record(identifier, session.user_id)['id']
                                  for identifier in result['record_ids']]
        return result
    except (LegacyMigrationError, ResultMigrationError, DispersionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail={'code': 'legacy_open_unreadable', 'message': '无法读取所选旧文件或同目录配置'}) from exc


@router.get('/api/v1/legacy-migration/runs/{run_id}/preferences', tags=['legacy-migration'])
def preview_preferences(run_id: str, _: Session = Depends(require_permission('migration.read')), *, runtime: Runtime=Depends(get_runtime)) -> dict:
    try:return runtime.legacy_migration_service().configuration_preferences(run_id)
    except LegacyMigrationError as exc:raise legacy_migration_error(exc) from exc


@router.post('/api/v1/legacy-migration/runs/{run_id}/preferences', tags=['legacy-migration'])
def apply_preferences(run_id: str, session: Session = Depends(require_permission('migration.write')),
    _: Session = Depends(require_permission('settings.write')), *, runtime: Runtime=Depends(get_runtime)) -> dict:
    try:return runtime.legacy_migration_service().configuration_preferences(run_id,session.user_id,apply=True)
    except LegacyMigrationError as exc:raise legacy_migration_error(exc) from exc


def legacy_migration_error(exc: LegacyMigrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/legacy-migration/sources", tags=["legacy-migration"])
def discover_method_sources(
    root: str | None = Query(default=None, max_length=2048),
    _: Session = Depends(require_permission("migration.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return discover_sources("methods", root)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.get("/api/v1/legacy-migration/diagnostics", tags=["legacy-migration"])
def legacy_migration_diagnostics(
    _: Session = Depends(require_permission("migration.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    return runtime.legacy_migration_service().diagnostics()


@router.post("/api/v1/legacy-migration/stage", tags=["legacy-migration"])
def stage_legacy_migration(
    payload: LegacyMigrationStageRequest,
    session: Session = Depends(require_permission("migration.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.legacy_migration_service().stage(
            payload.mtd_path, payload.cfg_path, payload.opt_path, session.user_id
        )
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.get("/api/v1/legacy-migration/runs", tags=["legacy-migration"])
def list_legacy_migration_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Session = Depends(require_permission("migration.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    return {"runs": runtime.legacy_migration_service().list(limit)}


@router.get("/api/v1/legacy-migration/runs/{run_id}", tags=["legacy-migration"])
def get_legacy_migration_run(
    run_id: str, _: Session = Depends(require_permission("migration.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    try:
        return runtime.legacy_migration_service().get(run_id)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc


@router.post("/api/v1/legacy-migration/commit", tags=["legacy-migration"])
def commit_legacy_migration(
    payload: LegacyMigrationCommitRequest,
    session: Session = Depends(require_permission("migration.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.legacy_migration_service().commit(payload.run_id, session.user_id)
    except LegacyMigrationError as exc:
        raise legacy_migration_error(exc) from exc
