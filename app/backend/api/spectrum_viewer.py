"""Spectrum Viewer API boundary; business services retain their existing behavior."""
from __future__ import annotations
import json
from typing import Any
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from ..db import utc_now
from ..schemas.spectrum_viewer import (
    SpectrumPrintRequest,
)
from ..auth import Session
from ..modules.spectrum_viewer import SpectrumViewerError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def spectrum_viewer_error(exc: SpectrumViewerError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/spectra/records", tags=["spectra"])
def list_spectrum_records(
    kind: str = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=200),
    angle_deg: float | None = Query(default=None),
    _: Session = Depends(require_permission("spectra.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict]:
    try:
        return runtime.spectrum_viewer_service().list(kind=kind, limit=limit, angle_deg=angle_deg)
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc


@router.get("/api/v1/spectra/{record_id}", tags=["spectra"])
def get_spectrum_record(
    record_id: str,
    ccd: int = Query(default=0, ge=0, le=255),
    line: int = Query(default=0, ge=0, le=4095),
    detail: str = Query(default="summary"),
    phase: str = Query(default="burn"),
    frame: int = Query(default=0, ge=0, le=255),
    exposure_start: int | None = Query(default=None, ge=1, le=255),
    exposure_end: int | None = Query(default=None, ge=1, le=255),
    session: Session = Depends(require_permission("spectra.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        result = runtime.spectrum_viewer_service().get(record_id, ccd=ccd, line=line, detail=detail, phase=phase, frame=frame, exposure_start=exposure_start, exposure_end=exposure_end)
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    with runtime.database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.view', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps({"record_id": record_id, "ccd": ccd, "line": line, "detail": detail, "phase": phase, "frame": frame, "exposure_start": exposure_start, "exposure_end": exposure_end}, ensure_ascii=False), utc_now()),
        )
    return result


@router.get("/api/v1/spectra/{record_id}/export", tags=["spectra"])
def export_spectrum_record(
    record_id: str,
    ccd: int = Query(default=0, ge=0, le=255),
    line: int = Query(default=0, ge=0, le=4095),
    detail: str = Query(default="summary"),
    phase: str = Query(default="burn"),
    frame: int = Query(default=0, ge=0, le=255),
    exposure_start: int | None = Query(default=None, ge=1, le=255),
    exposure_end: int | None = Query(default=None, ge=1, le=255),
    x_min: float | None = Query(default=None),
    x_max: float | None = Query(default=None),
    reference_shift: float = Query(default=0.0),
    session: Session = Depends(require_permission("spectra.export")), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    try:
        content, digest, point_count = runtime.spectrum_viewer_service().export_csv(
            record_id,
            ccd=ccd,
            line=line,
            detail=detail,
            phase=phase,
            frame=frame,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
            x_min=x_min,
            x_max=x_max,
            reference_shift=reference_shift,
        )
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    with runtime.database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.export', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps({"record_id": record_id, "ccd": ccd, "line": line, "visible_x_min": x_min, "visible_x_max": x_max, "reference_shift": reference_shift, "point_count": point_count, "sha256": digest}, ensure_ascii=False), utc_now()),
        )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="spectrum-{quote(record_id, safe="")}.csv"', "X-Content-SHA256": digest},
    )


@router.post("/api/v1/spectra/{record_id}/print", tags=["spectra"])
def audit_spectrum_print(
    record_id: str,
    payload: SpectrumPrintRequest,
    session: Session = Depends(require_permission("spectra.export")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    if payload.visible_x_min > payload.visible_x_max or payload.visible_y_min > payload.visible_y_max:
        raise HTTPException(status_code=422, detail={"code": "spectrum_visible_range_invalid", "message": "visible ranges must be ordered", "details": {}})
    try:
        runtime.spectrum_viewer_service().get(record_id, ccd=payload.ccd, line=payload.line)
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    details = {"record_id": record_id, **payload.model_dump(mode="json")}
    with runtime.database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.print', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps(details, ensure_ascii=False), utc_now()),
        )
    return {"status": "ready", "visible_range": {"x_min": payload.visible_x_min, "x_max": payload.visible_x_max, "y_min": payload.visible_y_min, "y_max": payload.visible_y_max}}


@router.post("/api/v1/spectra/{record_id}/print-pdf", tags=["spectra"])
def print_spectrum_pdf(
    record_id: str,
    payload: SpectrumPrintRequest,
    session: Session = Depends(require_permission("spectra.export")), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    try:
        content, result = runtime.spectrum_viewer_service().render_visible_pdf(
            record_id,
            selected_record_ids=payload.selected_record_ids,
            ccd=payload.ccd,
            line=payload.line,
            mode=payload.mode,
            reference_shift=payload.reference_shift,
            visible_x_min=payload.visible_x_min,
            visible_x_max=payload.visible_x_max,
            visible_y_min=payload.visible_y_min,
            visible_y_max=payload.visible_y_max,
            frame_phase=payload.frame_phase,
            frame_index=payload.frame_index,
            exposure_start=payload.exposure_start,
            exposure_end=payload.exposure_end,
            priority_record_id=payload.priority_record_id,
        )
    except SpectrumViewerError as exc:
        raise spectrum_viewer_error(exc) from exc
    details = {"record_id": record_id, **payload.model_dump(mode="json"), **result, "bytes": len(content), "output": "pdf"}
    with runtime.database.write() as db:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'spectrum.print', 'spectrum', NULL, ?, ?)",
            (session.user_id, json.dumps(details, ensure_ascii=False), utc_now()),
        )
    filename = f"spectrum-{record_id.replace(':', '-')}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": result["sha256"],
            "X-Curve-Count": str(result["curve_count"]),
            "X-Visible-Point-Count": str(result["visible_point_count"]),
        },
    )
