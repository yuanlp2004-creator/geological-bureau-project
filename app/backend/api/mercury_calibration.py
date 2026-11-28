"""Read-only access to historical mercury calibration sessions."""

from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from ..auth import Session
from ..modules.devices import DeviceError, LegacyMercuryService
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def mercury_error(exc: DeviceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/mercury-calibrations/options", tags=["mercury-calibration"])
def mercury_calibration_options(
    _: Session = Depends(require_permission("mercury-calibration.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    return LegacyMercuryService(runtime.database).options()


@router.get("/api/v1/mercury-calibrations/sessions", tags=["mercury-calibration"])
def list_mercury_calibration_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("mercury-calibration.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return LegacyMercuryService(runtime.database).list_sessions(limit)


@router.get("/api/v1/mercury-calibrations/sessions/{session_id}", tags=["mercury-calibration"])
def get_mercury_calibration_session(
    session_id: int,
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("mercury-calibration.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return LegacyMercuryService(runtime.database).session(session_id, include_points=include_points)
    except DeviceError as exc:
        raise mercury_error(exc) from exc
