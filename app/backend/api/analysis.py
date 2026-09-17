"""Analysis API boundary; business services retain their existing behavior."""
from __future__ import annotations
from typing import Any
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from ..schemas.analysis import (
    AnalysisRunCreate,
    AnalysisIntervention,
    AnalysisQcDecision,
    AnalysisCurveAction,
    AnalysisCurveFit,
    AnalysisCurvePublish,
    AnalysisMergeRequest,
)
from ..auth import Session
from ..modules.analysis import AnalysisError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def analysis_error(exc: AnalysisError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/analyses/options", tags=["analysis"])
def analysis_options(_: Session = Depends(require_permission("analysis.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return runtime.analysis_service().options()


@router.get("/api/v1/analyses/runs", tags=["analysis"])
def list_analysis_runs(limit: int = Query(default=50, ge=1, le=200), _: Session = Depends(require_permission("analysis.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    return runtime.analysis_service().list_runs(limit)


@router.post("/api/v1/analyses/runs", status_code=201, tags=["analysis"])
def create_analysis_run(payload: AnalysisRunCreate, session: Session = Depends(require_permission("analysis.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().create_run(payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.get("/api/v1/analyses/runs/{run_id}", tags=["analysis"])
def get_analysis_run(run_id: int, _: Session = Depends(require_permission("analysis.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().run(run_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/start", tags=["analysis"])
def start_analysis_run(run_id: int, session: Session = Depends(require_permission("analysis.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().start(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/step", tags=["analysis"])
def step_analysis_run(run_id: int, session: Session = Depends(require_permission("analysis.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().step(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/intervene", tags=["analysis"])
def intervene_analysis_run(run_id: int, payload: AnalysisIntervention, session: Session = Depends(require_permission("analysis.intervene")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().intervene(run_id, payload.action, payload.adjusted_position, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/cancel", tags=["analysis"])
def cancel_analysis_run(run_id: int, session: Session = Depends(require_permission("analysis.execute")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().cancel(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/quality/recalculate", tags=["analysis"])
def recalculate_analysis_quality(run_id: int, session: Session = Depends(require_permission("analysis.quality")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().build_quality(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/quality/decisions", tags=["analysis"])
def decide_analysis_quality(run_id: int, payload: AnalysisQcDecision, session: Session = Depends(require_permission("analysis.quality")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().decide_quality(run_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/actions", tags=["analysis"])
def apply_analysis_curve_action(run_id: int, line_id: str, payload: AnalysisCurveAction, session: Session = Depends(require_permission("analysis.curve")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().curve_action(run_id, line_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/fit", status_code=201, tags=["analysis"])
def fit_analysis_curve(run_id: int, line_id: str, payload: AnalysisCurveFit, session: Session = Depends(require_permission("analysis.curve")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().fit_standard_curve(run_id, line_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/publish", tags=["analysis"])
def publish_analysis_curve(run_id: int, line_id: str, payload: AnalysisCurvePublish, session: Session = Depends(require_permission("analysis.curve")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().publish_standard_curve(run_id, line_id, payload.curve_snapshot_id, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/results/merge", status_code=201, tags=["analysis"])
def merge_analysis_results(run_id: int, payload: AnalysisMergeRequest, session: Session = Depends(require_permission("analysis.curve")), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        return runtime.analysis_service().merge_results(run_id, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.get("/api/v1/analyses/runs/{run_id}/curves/{curve_snapshot_id}/preview", response_class=HTMLResponse, tags=["analysis"])
def preview_analysis_curve(run_id: int, curve_snapshot_id: int, mode: str = Query(default="image", pattern="^(image|text)$"), session: Session = Depends(require_permission("analysis.read")), *, runtime: Runtime = Depends(get_runtime)) -> HTMLResponse:
    try:
        return HTMLResponse(runtime.analysis_service().curve_preview(run_id, curve_snapshot_id, mode, session.user_id), headers={"Cache-Control": "no-store", "X-Curve-Snapshot-Id": str(curve_snapshot_id)})
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{curve_snapshot_id}/print", tags=["analysis"])
def print_analysis_curve(run_id: int, curve_snapshot_id: int, mode: str = Query(default="image", pattern="^(image|text)$"), session: Session = Depends(require_permission("analysis.print")), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    try:
        content, metadata = runtime.analysis_service().print_curve(run_id, curve_snapshot_id, mode, session.user_id)
        filename = quote(f"analysis-{run_id}-curve-{curve_snapshot_id}-{mode}.pdf")
        return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}", "X-Print-Job-Id": str(metadata["job_id"]), "X-Content-SHA256": metadata["sha256"]})
    except AnalysisError as exc:
        raise analysis_error(exc) from exc
