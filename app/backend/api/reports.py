"""Reports API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from ..schemas.reports import (
    ReportCreate,
    ReportExport,
)
from ..auth import Session
from ..modules.reports import ReportError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def report_error(exc: ReportError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/reports/templates", tags=["reports"])
def list_report_templates(_: Session = Depends(require_permission("reports.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.reports_service().templates()


@router.get("/api/v1/reports", tags=["reports"])
def list_reports(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("reports.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.reports_service().list(limit)


@router.get("/api/v1/reports/printers", tags=["reports"])
def list_report_printers(_: Session = Depends(require_permission("reports.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {"printers": runtime.reports_service().printers()}


@router.post("/api/v1/reports", status_code=201, tags=["reports"])
def create_report(payload: ReportCreate, session: Session = Depends(require_permission("reports.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.reports_service().create(payload.model_dump(mode="json"), session.user_id)
    except ReportError as exc:
        raise report_error(exc) from exc


@router.get("/api/v1/reports/{report_id}", tags=["reports"])
def get_report(report_id: int, _: Session = Depends(require_permission("reports.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.reports_service().get(report_id)
    except ReportError as exc:
        raise report_error(exc) from exc


@router.get("/api/v1/reports/{report_id}/preview", response_class=HTMLResponse, tags=["reports"])
def preview_report(report_id: int, session: Session = Depends(require_permission("reports.read")), *, runtime: Runtime = Depends(get_runtime)) -> HTMLResponse:
    try:
        return HTMLResponse(runtime.reports_service().preview(report_id, session.user_id), headers={"Cache-Control": "no-store"})
    except ReportError as exc:
        raise report_error(exc) from exc


@router.post("/api/v1/reports/{report_id}/confirm", tags=["reports"])
def confirm_report(report_id: int, session: Session = Depends(require_permission("reports.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.reports_service().confirm(report_id, session.user_id)
    except ReportError as exc:
        raise report_error(exc) from exc


@router.post("/api/v1/reports/{report_id}/exports", tags=["reports"])
def export_report(report_id: int, payload: ReportExport, session: Session = Depends(require_permission("reports.export")), *, runtime: Runtime = Depends(get_runtime)) -> Any:
    try:
        result = runtime.reports_service().export(report_id, payload.model_dump(mode="json"), session.user_id)
    except ReportError as exc:
        raise report_error(exc) from exc
    return result


@router.get("/api/v1/reports/{report_id}/exports", tags=["reports"])
def list_report_exports(report_id: int, limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("reports.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.reports_service().exports(report_id, limit)
