"""Analysis API boundary; business services retain their existing behavior."""

from __future__ import annotations
import base64
import binascii
from typing import Any, Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from ..schemas.analysis import (
    AnalysisRunCreate,
    AnalysisSampleNumbersFile,
    AnalysisSampleNumbersExport,
    AnalysisIntervention,
    AnalysisQcDecision,
    AnalysisCurveAction,
    AnalysisCurveFit,
    AnalysisCurvePublish,
    AnalysisMergeRequest,
    AnalysisCalibrationRequest,
    AnalysisTimeSeriesRequest,
    AnalysisIntensityOutputRequest,
    AnalysisSpectrumPrintRequest,
)
from ..auth import Session
from ..schemas.system import SettingsIntensityOutput,SettingsPatch
from ..modules.analysis import AnalysisError
from ..modules.sample_queues import SampleQueueError, read_sample_numbers, write_sample_numbers
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()
RunStatus = Literal["draft", "running", "paused", "completed", "cancelled", "failed"]


@router.post("/api/v1/analyses/sample-numbers/read", tags=["analysis"])
def read_analysis_sample_numbers(payload: AnalysisSampleNumbersFile,
    _: Session = Depends(require_permission("analysis.execute"))) -> dict[str, Any]:
    try:
        return {"entries": read_sample_numbers(base64.b64decode(payload.content_base64, validate=True), payload.encoding)}
    except binascii.Error as exc:
        raise HTTPException(422, detail={"code": "sam_payload_invalid", "message": "无法读取样号文件"}) from exc
    except SampleQueueError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.post("/api/v1/analyses/sample-numbers/write", tags=["analysis"])
def write_analysis_sample_numbers(payload: AnalysisSampleNumbersExport,
    _: Session = Depends(require_permission("analysis.execute"))) -> Response:
    try:
        content = write_sample_numbers([item.model_dump() for item in payload.entries])
        return Response(content=content, media_type="application/octet-stream")
    except SampleQueueError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post('/api/v1/analyses/runs/{run_id}/intensity-output', tags=['analysis'])
def output_intensity(run_id: int,payload: AnalysisIntensityOutputRequest,
    session: Session = Depends(require_permission('analysis.read')), *,runtime: Runtime=Depends(get_runtime)) -> dict:
    if payload.print_intensity and 'analysis.print' not in session.permissions:
        raise HTTPException(403,detail={'code':'permission_denied','message':'需要强度打印权限'})
    if payload.save_positions and 'methods.write' not in session.permissions:
        raise HTTPException(403,detail={'code':'permission_denied','message':'保存校正波长需要方法编辑权限'})
    try:return runtime.analysis_service().intensity_output(run_id,payload.model_dump(),session.user_id)
    except AnalysisError as exc:raise analysis_error(exc) from exc
    except ValueError as exc:raise HTTPException(422,detail={'code':'analysis_intensity_output_failed','message':str(exc)}) from exc


@router.get('/api/v1/analyses/printers', tags=['analysis'])
def intensity_printers(_: Session = Depends(require_permission('analysis.read'))) -> dict:
    from ..printing import SystemPrinters
    return {'printers': SystemPrinters().printers()}


@router.put('/api/v1/analyses/intensity-output/defaults',tags=['analysis'])
def save_intensity_defaults(payload: SettingsIntensityOutput,session:Session=Depends(require_permission('analysis.execute')),*,runtime:Runtime=Depends(get_runtime)) -> dict:
    return runtime.service.update_settings(SettingsPatch(intensity_output=payload),session.user_id)['intensity_output']


def analysis_error(exc: AnalysisError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/calibration', tags=['analysis'])
def preview_daily_calibration(run_id: int, sample_position: int,
    _: Session = Depends(require_permission('analysis.read')), runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.analysis_service().calibration_preview(run_id, sample_position)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/calibration', tags=['analysis'])
def save_daily_calibration(run_id: int, sample_position: int, payload: AnalysisCalibrationRequest,
    session: Session = Depends(require_permission('methods.write')),
    _: Session = Depends(require_permission('analysis.read')), runtime: Runtime = Depends(get_runtime)) -> dict:
    from ..modules.methods import MethodDomainError
    try:
        return runtime.analysis_service().save_calibration(run_id, sample_position, session.user_id, **payload.model_dump())
    except (AnalysisError, MethodDomainError) as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.post('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/time-series', tags=['analysis'])
def export_line_time_series(run_id: int, sample_position: int, payload: AnalysisTimeSeriesRequest,
    session: Session = Depends(require_permission('analysis.read')), runtime: Runtime = Depends(get_runtime)) -> Response:
    try:
        content, digest = runtime.analysis_service().export_time_series(run_id, sample_position, runtime.acquisition_service(), payload.include_mean, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc
    return Response(content, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="analysis-{run_id}-time-series.csv"', 'X-Content-SHA256': digest})


@router.get("/api/v1/analyses/options", tags=["analysis"])
def analysis_options(
    _: Session = Depends(require_permission("analysis.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    settings=runtime.service.get_settings()
    return {**runtime.analysis_service().options(),'preferences':settings['analysis'],'intensity_output_defaults':settings['intensity_output']}




@router.get("/api/v1/analyses/runs", tags=["analysis"])
def list_analysis_runs(
    limit: int = Query(default=50, ge=1, le=200),
    _: Session = Depends(require_permission("analysis.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return runtime.analysis_service().list_runs(limit)


@router.post("/api/v1/analyses/runs", status_code=201, tags=["analysis"])
def create_analysis_run(
    payload: AnalysisRunCreate,
    session: Session = Depends(require_permission("analysis.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.analysis_service().create_run(payload.model_dump(mode="json"), session.user_id), source='analysis', category='analysis')
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.get("/api/v1/analyses/runs/{run_id}", tags=["analysis"])
def get_analysis_run(
    run_id: int, _: Session = Depends(require_permission("analysis.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().run(run_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/start", tags=["analysis"])
def start_analysis_run(
    run_id: int,
    session: Session = Depends(require_permission("analysis.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.analysis_service().start(run_id, session.user_id), source='analysis', category='analysis')
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/step", tags=["analysis"])
def step_analysis_run(
    run_id: int,
    session: Session = Depends(require_permission("analysis.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.analysis_service().step(run_id, session.user_id), source='analysis', category='analysis')
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/intervene", tags=["analysis"])
def intervene_analysis_run(
    run_id: int,
    payload: AnalysisIntervention,
    session: Session = Depends(require_permission("analysis.intervene")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().intervene(
            run_id, payload.action, payload.adjusted_position, payload.reason, session.user_id
        )
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/cancel", tags=["analysis"])
def cancel_analysis_run(
    run_id: int,
    session: Session = Depends(require_permission("analysis.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.analysis_service().cancel(run_id, session.user_id), source='analysis', category='analysis')
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/quality/recalculate", tags=["analysis"])
def recalculate_analysis_quality(
    run_id: int,
    session: Session = Depends(require_permission("analysis.quality")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().build_quality(run_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/quality/decisions", tags=["analysis"])
def decide_analysis_quality(
    run_id: int,
    payload: AnalysisQcDecision,
    session: Session = Depends(require_permission("analysis.quality")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().decide_quality(run_id, payload.model_dump(mode="json"), session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/actions", tags=["analysis"])
def apply_analysis_curve_action(
    run_id: int,
    line_id: str,
    payload: AnalysisCurveAction,
    session: Session = Depends(require_permission("analysis.curve")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().curve_action(
            run_id, line_id, payload.model_dump(mode="json"), session.user_id
        )
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/fit", status_code=201, tags=["analysis"])
def fit_analysis_curve(
    run_id: int,
    line_id: str,
    payload: AnalysisCurveFit,
    session: Session = Depends(require_permission("analysis.curve")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().fit_standard_curve(
            run_id, line_id, payload.model_dump(mode="json"), session.user_id
        )
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{line_id}/publish", tags=["analysis"])
def publish_analysis_curve(
    run_id: int,
    line_id: str,
    payload: AnalysisCurvePublish,
    session: Session = Depends(require_permission("analysis.curve")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().publish_standard_curve(
            run_id, line_id, payload.curve_snapshot_id, payload.reason, session.user_id
        )
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/results/merge", status_code=201, tags=["analysis"])
def merge_analysis_results(
    run_id: int,
    payload: AnalysisMergeRequest,
    session: Session = Depends(require_permission("analysis.curve")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().merge_results(run_id, payload.reason, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.get(
    "/api/v1/analyses/runs/{run_id}/curves/{curve_snapshot_id}/preview", response_class=HTMLResponse, tags=["analysis"]
)
def preview_analysis_curve(
    run_id: int,
    curve_snapshot_id: int,
    mode: str = Query(default="image", pattern="^(image|text)$"),
    session: Session = Depends(require_permission("analysis.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> HTMLResponse:
    try:
        return HTMLResponse(
            runtime.analysis_service().curve_preview(run_id, curve_snapshot_id, mode, session.user_id),
            headers={"Cache-Control": "no-store", "X-Curve-Snapshot-Id": str(curve_snapshot_id)},
        )
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/runs/{run_id}/curves/{curve_snapshot_id}/print", tags=["analysis"])
def print_analysis_curve(
    run_id: int,
    curve_snapshot_id: int,
    mode: str = Query(default="image", pattern="^(image|text)$"),
    session: Session = Depends(require_permission("analysis.print")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    try:
        content, metadata = runtime.analysis_service().print_curve(run_id, curve_snapshot_id, mode, session.user_id)
        filename = quote(f"analysis-{run_id}-curve-{curve_snapshot_id}-{mode}.pdf")
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "X-Print-Job-Id": str(metadata["job_id"]),
                "X-Content-SHA256": metadata["sha256"],
            },
        )
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post("/api/v1/analyses/legacy-sources", tags=["analysis"])
def import_legacy_analysis_sources(
    record_ids: list[int],
    method_version_id: int = Query(gt=0),
    session: Session = Depends(require_permission("analysis.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.analysis_service().import_legacy_sources(record_ids, method_version_id, session.user_id)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


def observation_exposure(start: int | None, end: int | None) -> tuple[int, int] | None:
    if start is None and end is None:
        return None
    if start is None or end is None or end < start:
        raise HTTPException(status_code=422, detail='请选择有效的观察曝光区间')
    return start, end


@router.get('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}', tags=['analysis'])
def analysis_spectrum(
    run_id: int, sample_position: int,
    line_id: str | None = Query(default=None, min_length=1, max_length=100),
    band_position: int | None = Query(default=None, ge=0),
    exposure_start: int | None = Query(default=None, ge=1),
    exposure_end: int | None = Query(default=None, ge=1),
    _: Session = Depends(require_permission('analysis.read')), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        return runtime.analysis_service().spectrum(run_id, sample_position, runtime.acquisition_service(), line_id,
            band_position=band_position, observation_interval=observation_exposure(exposure_start, exposure_end))
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/print', tags=['analysis'])
def print_analysis_spectrum(run_id: int, sample_position: int, payload: AnalysisSpectrumPrintRequest,
    session: Session = Depends(require_permission('analysis.print')), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    from ..modules.spectrum_pdf import render_spectrum_pdf
    if payload.x_min >= payload.x_max or payload.y_min >= payload.y_max:
        raise HTTPException(status_code=422, detail='请选择有效的谱图打印范围')
    try:
        service = runtime.analysis_service()
        interval = observation_exposure(payload.exposure_start, payload.exposure_end)
        spectrum = service.spectrum(run_id, sample_position, runtime.acquisition_service(), payload.line_id,
                                    band_position=payload.band_position, observation_interval=interval)
        if payload.band_position is not None:
            band = spectrum['bands'][payload.band_position] if payload.band_position < len(spectrum['bands']) else None
            if band is not None and band['ccd_index'] != payload.ccd:
                raise AnalysisError('analysis_ccd_invalid', '打印谱带与CCD不匹配')
        else:
            matching = [item for item in spectrum['bands'] if item['ccd_index'] == payload.ccd]
            band = matching[0] if len(matching) == 1 else None
        if band is None:
            raise AnalysisError('analysis_ccd_invalid', '所选 CCD 不在当前分析样品中')
        # Print exactly the verified, exposure-normalized values used by the analysis view.
        curve = {'id': f'analysis:{run_id}:{sample_position}', 'label': spectrum['sample_name'],
                 'color': '#f12222', 'priority': True,
                 'points': [(index + 1, value) for index, value in enumerate(band['mean_points'])]}
        content, metadata = render_spectrum_pdf([curve], curve['id'], 'mean', payload.ccd, 0, 0,
            payload.x_min, payload.x_max, payload.y_min, payload.y_max, layers=['grayscale', 'curve'])
        service.record_observation_print(run_id, {'output': 'analysis-spectrum', 'sample_position': sample_position,
            'ccd': payload.ccd, 'turn_index': band.get('turn_index'), 'angle_deg': band.get('angle_deg'), 'line_id': payload.line_id,
            'exposure_interval': spectrum['exposure_interval'], 'mean_sha256': band['mean_sha256'], **metadata}, session.user_id)
        return Response(content, media_type='application/pdf', headers={
            'Content-Disposition': f'attachment; filename="analysis-{run_id}-sample-{sample_position + 1}.pdf"'})
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


def _analysis_point_details(runtime: Runtime, run_id: int, sample_position: int, ccd: int, point: int | None,
                            band_position: int | None = None) -> dict:
    from ..modules.spectrum_viewer import SpectrumViewerError
    try:
        spectrum = runtime.analysis_service().spectrum(run_id, sample_position, runtime.acquisition_service())
        bands = spectrum['bands']
        if band_position is None:
            band_position = next((index for index, band in enumerate(bands) if band['ccd_index'] == ccd), -1)
        if not 0 <= band_position < len(bands) or bands[band_position]['ccd_index'] != ccd:
            raise AnalysisError('analysis_ccd_invalid', '所选 CCD 不在当前分析样品中')
        return runtime.spectrum_viewer_service().point_details(f"sample:{spectrum['acquisition_sample_id']}", ccd=band_position, point=point)
    except SpectrumViewerError as exc:
        raise AnalysisError(exc.code, exc.message, status_code=exc.status_code) from exc


@router.get('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/point-details', tags=['analysis'])
def analysis_point_details(run_id: int, sample_position: int, ccd: int = Query(ge=0), point: int = Query(ge=0), all_points: bool = False,
    band_position: int | None = Query(default=None, ge=0),
    _: Session = Depends(require_permission('analysis.read')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return _analysis_point_details(runtime, run_id, sample_position, ccd, None if all_points else point, band_position)
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/point-details/copy', tags=['analysis'])
def copy_analysis_point_details(run_id: int, sample_position: int, ccd: int = Query(ge=0), point: int = Query(ge=0),
    band_position: int | None = Query(default=None, ge=0),
    orientation: str = Query(pattern='^(vertical|horizontal)$'), session: Session = Depends(require_permission('analysis.print')),
    *, runtime: Runtime = Depends(get_runtime)) -> dict:
    from ..modules.spectrum_viewer import point_details_text
    try:
        details = _analysis_point_details(runtime, run_id, sample_position, ccd, point, band_position)
        text = point_details_text(details, orientation)
        runtime.analysis_service().record_observation_export(run_id,
            {'sample_position': sample_position, 'ccd': ccd, 'point': point,
             'orientation': orientation, 'sha256': details['sha256'], 'output': 'clipboard'}, session.user_id)
        return {'text': text, 'sha256': details['sha256']}
    except AnalysisError as exc:
        raise analysis_error(exc) from exc


@router.post('/api/v1/analyses/runs/{run_id}/spectra/{sample_position}/point-details/print', tags=['analysis'])
def print_analysis_point_details(run_id: int, sample_position: int, ccd: int = Query(ge=0), point: int = Query(ge=0),
    band_position: int | None = Query(default=None, ge=0),
    session: Session = Depends(require_permission('analysis.print')), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    from ..modules.spectrum_pdf import render_point_details_pdf
    try:
        details = _analysis_point_details(runtime, run_id, sample_position, ccd, point, band_position)
        content = render_point_details_pdf(details)
        runtime.analysis_service().record_observation_print(run_id,
            {'output': 'raw-point-details', 'sample_position': sample_position, 'ccd': ccd, 'point': point, 'sha256': details['sha256']}, session.user_id)
        return Response(content, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="analysis-{run_id}-point-{point + 1}.pdf"'})
    except AnalysisError as exc:
        raise analysis_error(exc) from exc
