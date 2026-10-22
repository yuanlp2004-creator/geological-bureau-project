"""Postprocessing API boundary; business services retain their existing behavior."""

from __future__ import annotations
import json
from typing import Any
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from ..db import utc_now
from ..schemas.postprocessing import (
    PostProcessingConversionRequest,
    PostProcessingRecalculateRequest,
    PostProcessingExportRequest,
)
from ..auth import Session
from ..modules.postprocessing import PostProcessingError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


class LegacyIntensityOutputRequest(BaseModel):
    record_ids: list[int] = Field(min_length=1, max_length=200)
    format: Literal['excel', 'pdf', 'print'] | None = None
    printer_name: str | None = Field(default=None, max_length=255)


@router.post('/api/v1/postprocessing/legacy-intensity-output', tags=['postprocessing'])
def legacy_intensity_output(payload: LegacyIntensityOutputRequest,
                            session: Session = Depends(require_permission('postprocessing.export')),
                            runtime: Runtime = Depends(get_runtime)) -> dict:
    if len(set(payload.record_ids)) != len(payload.record_ids):
        raise HTTPException(422, detail={'code': 'intensity_sources_invalid', 'message': '请选择不重复的 PDT 来源'})
    try:
        return runtime.postprocessing_service().legacy_intensity_output(
            payload.record_ids, payload.format, payload.printer_name, session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={'code': 'intensity_output_invalid', 'message': str(exc)}) from exc


@router.post('/api/v1/postprocessing/intensity-table',tags=['postprocessing'])
def export_intensity_table(record_ids: list[int],format: str=Query(default='txt',pattern='^(txt|csv|excel|pdf|print)$'),
    session:Session=Depends(require_permission('postprocessing.export')),*,runtime:Runtime=Depends(get_runtime)):
    from fastapi.responses import Response
    if not record_ids or len(record_ids)>200 or len(record_ids)!=len(set(record_ids)):
        raise HTTPException(422,detail={'code':'intensity_sources_invalid','message':'请选择不重复的 PDT 来源'})
    try:content,media=runtime.postprocessing_service().intensity_table(record_ids,format,session.user_id)
    except PostProcessingError as exc:raise postprocessing_error(exc) from exc
    except ValueError as exc:raise HTTPException(422,detail=str(exc)) from exc
    return Response(content,media_type=media,headers={'Content-Disposition':'attachment; filename=pdt-intensity.'+('pdf' if format in {'pdf','print'} else 'xls' if format=='excel' else format)})


def postprocessing_error(exc: PostProcessingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/postprocessing/edt-records", tags=["postprocessing"])
def list_postprocessing_edt_records(
    limit: int = Query(default=200, ge=1, le=500),
    _: Session = Depends(require_permission("postprocessing.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return {"records": runtime.postprocessing_service().edt_records(limit)}


@router.get("/api/v1/postprocessing/recalculation-options", tags=["postprocessing"])
def get_postprocessing_recalculation_options(
    limit: int = Query(default=300, ge=1, le=500),
    _: Session = Depends(require_permission("postprocessing.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return runtime.postprocessing_service().recalculation_options(limit)


@router.get("/api/v1/postprocessing/raw/{record_id}/interval", tags=["postprocessing"])
def get_postprocessing_interval(
    record_id: str,
    ccd: int = Query(default=0, ge=0, le=255),
    start_frame: int = Query(default=1, ge=1, le=255),
    end_frame: int | None = Query(default=None, ge=1, le=255),
    phase: str = Query(default="burn"),
    session: Session = Depends(require_permission("postprocessing.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        result = runtime.postprocessing_service().interval(
            record_id, ccd=ccd, start_frame=start_frame, end_frame=end_frame, phase=phase
        )
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc
    with runtime.database.write() as db:
        db.execute(
            (
                "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                ",created_at) VALUES (?, 'postprocessing.interval.view', 'postprocessing', NULL, "
                "?, ?)"
            ),
            (
                session.user_id,
                json.dumps(
                    {
                        "record_id": record_id,
                        "ccd": ccd,
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "phase": phase,
                    },
                    ensure_ascii=False,
                ),
                utc_now(),
            ),
        )
    return result


@router.post("/api/v1/postprocessing/conversions", tags=["postprocessing"])
def convert_postprocessing_edt(
    payload: PostProcessingConversionRequest,
    session: Session = Depends(require_permission("postprocessing.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.postprocessing_service().convert_edt(payload.model_dump(), session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc


@router.get("/api/v1/postprocessing/conversions", tags=["postprocessing"])
def list_postprocessing_conversions(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("postprocessing.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return {"runs": runtime.postprocessing_service().conversions(limit)}


@router.post("/api/v1/postprocessing/recalculations", tags=["postprocessing"])
def recalculate_postprocessing(
    payload: PostProcessingRecalculateRequest,
    session: Session = Depends(require_permission("postprocessing.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.postprocessing_service().recalculate(payload.model_dump(), session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc


@router.get("/api/v1/postprocessing/recalculations", tags=["postprocessing"])
def list_postprocessing_recalculations(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("postprocessing.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return {"runs": runtime.postprocessing_service().recalculations(limit)}


@router.post("/api/v1/postprocessing/exports", tags=["postprocessing"])
def export_postprocessing_matrix(
    payload: PostProcessingExportRequest,
    session: Session = Depends(require_permission("postprocessing.export")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.postprocessing_service().export(payload.model_dump(), session.user_id)
    except PostProcessingError as exc:
        raise postprocessing_error(exc) from exc


@router.get("/api/v1/postprocessing/exports", tags=["postprocessing"])
def list_postprocessing_exports(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("postprocessing.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return {"exports": runtime.postprocessing_service().exports(limit)}
