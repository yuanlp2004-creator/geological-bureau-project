"""Mercury Calibration API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.mercury_calibration import (
    MercurySessionCreate,
)
from ..auth import Session
from ..modules.mercury_calibration import MercuryError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def mercury_error(exc: MercuryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/mercury-calibrations/options", tags=["mercury-calibration"])
def mercury_calibration_options(_: Session = Depends(require_permission("mercury-calibration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.mercury_calibration_service().options()


@router.get("/api/v1/mercury-calibrations/sessions", tags=["mercury-calibration"])
def list_mercury_calibration_sessions(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("mercury-calibration.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.mercury_calibration_service().list_sessions(limit)


@router.post("/api/v1/mercury-calibrations/sessions", status_code=201, tags=["mercury-calibration"])
def create_mercury_calibration_session(payload: MercurySessionCreate, session: Session = Depends(require_permission("mercury-calibration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().create_session(payload.model_dump(mode="json"), session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@router.get("/api/v1/mercury-calibrations/sessions/{session_id}", tags=["mercury-calibration"])
def get_mercury_calibration_session(session_id: int, include_points: bool = Query(default=False), _: Session = Depends(require_permission("mercury-calibration.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().session(session_id, include_points=include_points)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@router.post("/api/v1/mercury-calibrations/sessions/{session_id}/start", tags=["mercury-calibration"])
def start_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().start(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@router.post("/api/v1/mercury-calibrations/sessions/{session_id}/step", tags=["mercury-calibration"])
def step_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().step(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@router.post("/api/v1/mercury-calibrations/sessions/{session_id}/apply", tags=["mercury-calibration"])
def apply_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().apply(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@router.post("/api/v1/mercury-calibrations/sessions/{session_id}/rollback", tags=["mercury-calibration"])
def rollback_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().rollback(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc


@router.post("/api/v1/mercury-calibrations/sessions/{session_id}/stop", tags=["mercury-calibration"])
def stop_mercury_calibration_session(session_id: int, session: Session = Depends(require_permission("mercury-calibration.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.mercury_calibration_service().stop(session_id, session.user_id)
    except MercuryError as exc:
        raise mercury_error(exc) from exc
