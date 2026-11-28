"""Dispersion API boundary; business services retain their existing behavior."""

from __future__ import annotations
from ..schemas.preliminary import PreliminaryCaptureCreate
from .preliminary import create_preliminary_session
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from ..schemas.dispersion import (
    DispersionTaskCreate,
    DispersionSpectrumPrintRequest,
    DispersionLineInput,
    DispersionPointInput,
    DispersionLineMoveRequest,
    DispersionCalibrationFitRequest,
    DispersionCalibrationBindRequest,
)
from ..auth import Session
from ..schemas.system import PreliminaryConditions
from ..modules.dispersion import DispersionError
from ..modules.devices import DeviceError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission
from .deployment_access import require_activation

router = APIRouter()


@router.post('/api/v1/dispersion/capture-sessions', status_code=201, tags=['dispersion'])
def create_dispersion_session(payload: PreliminaryCaptureCreate,
                              session: Session = Depends(require_permission('dispersion.write')), *,
                              runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return create_preliminary_session('dispersion', payload, runtime, session)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post('/api/v1/dispersion/tasks/{task_id}/positions/{action}', tags=['dispersion'])
def all_positions(task_id: int, action: str, session: Session = Depends(require_permission('dispersion.write')),
    *, runtime: Runtime = Depends(get_runtime)) -> dict:
    if action not in {'save','restore'}:
        raise HTTPException(status_code=422,detail='位置操作必须为save或restore')
    try:
        return runtime.dispersion_service().all_positions(task_id,action == 'restore',session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get('/api/v1/dispersion/tasks/{task_id}/coordinate', tags=['dispersion'])
def dispersion_coordinate(task_id: int, wavelength_nm: float = Query(gt=0, le=2000),
    _: Session = Depends(require_permission('dispersion.read')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.dispersion_service().coordinate(task_id, wavelength_nm)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post('/api/v1/dispersion/tasks/{task_id}/line-points', status_code=201, tags=['dispersion'])
def add_dispersion_point(task_id: int, payload: DispersionPointInput,
    session: Session = Depends(require_permission('dispersion.write')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.dispersion_service().add_point(task_id, payload.ccd_index, payload.point_index, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.patch('/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/wavelength', tags=['dispersion'])
def update_wavelength(task_id: int, line_id: int, wavelength_nm: float = Query(gt=0,le=2000),
    legacy_input: bool = False,
    session: Session = Depends(require_permission('dispersion.write')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.dispersion_service().update_line_wavelength(task_id,line_id,wavelength_nm,session.user_id,legacy_input=legacy_input)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.patch('/api/v1/dispersion/tasks/{task_id}/gaps/{gap_index}', tags=['dispersion'])
def update_gap(task_id: int, gap_index: int, gap_um: float = Query(ge=0,le=10000),
    legacy_limits: bool = False,
    session: Session = Depends(require_permission('dispersion.write')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.dispersion_service().update_gap(task_id,gap_index,gap_um,session.user_id,legacy_limits=legacy_limits)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


def dispersion_error(exc: DispersionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/dispersion/options", tags=["dispersion"])
def dispersion_options(
    _: Session = Depends(require_permission("dispersion.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    settings = runtime.service.get_settings()
    analysis = settings['analysis']
    nominal, error = analysis['dispersion_nominal_gap_um'], analysis['dispersion_allow_gap_error_um']
    return {**runtime.dispersion_service().options(),
            'gap_limits_um': [max(0, nominal-error), min(10000, nominal+error)],
            "preliminary_defaults": settings["preliminary"]["dispersion"]}


@router.put("/api/v1/dispersion/defaults", tags=["dispersion"])
def save_dispersion_defaults(payload: PreliminaryConditions,
    session: Session = Depends(require_permission("dispersion.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.service.save_preliminary_conditions("dispersion", payload, session.user_id)


@router.get("/api/v1/dispersion/tasks", tags=["dispersion"])
def list_dispersion_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Session = Depends(require_permission("dispersion.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return runtime.dispersion_service().list_tasks(limit, offset)


@router.post("/api/v1/dispersion/tasks", status_code=201, tags=["dispersion"])
def create_dispersion_task(
    payload: DispersionTaskCreate,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.dispersion_service().create_task(payload.model_dump(mode="json"), session.user_id), source='dispersion', category='acquisition')
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/tasks/{task_id}", tags=["dispersion"])
def get_dispersion_task(
    task_id: int,
    _: Session = Depends(require_permission("dispersion.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().get_task(task_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.delete("/api/v1/dispersion/tasks/{task_id}", status_code=204, response_class=Response, tags=["dispersion"])
def delete_dispersion_task(
    task_id: int, session: Session = Depends(require_permission("dispersion.write")),
    *, runtime: Runtime = Depends(get_runtime),
) -> Response:
    try:
        runtime.dispersion_service().discard_task(task_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc
    return Response(status_code=204)


@router.get('/api/v1/dispersion/tasks/{task_id}/observation-spectrum', tags=['dispersion'])
def dispersion_observation_spectrum(task_id: int, ccd: int = Query(ge=0, le=255),
    exposure_start: int = Query(ge=1, le=255), exposure_end: int = Query(ge=1, le=255),
    _: Session = Depends(require_permission('dispersion.read')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.dispersion_service().observation_spectrum(task_id, ccd, exposure_start, exposure_end)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post('/api/v1/dispersion/tasks/{task_id}/observation-spectrum/print-pdf', tags=['dispersion'])
def print_dispersion_observation(task_id: int, payload: DispersionSpectrumPrintRequest,
    _: Session = Depends(require_permission('dispersion.read')),
    session: Session = Depends(require_permission('spectra.export')), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    from ..modules.spectrum_pdf import render_spectrum_pdf

    if payload.x_min >= payload.x_max or payload.y_min >= payload.y_max:
        raise HTTPException(status_code=422, detail='请选择有效的谱图打印范围')
    service = runtime.dispersion_service()
    try:
        data = service.observation_spectrum(task_id, payload.ccd, payload.exposure_start, payload.exposure_end)
        record = f'dispersion:{task_id}'
        curve = {'id': record, 'label': data['label'], 'color': '#f12222', 'priority': True,
                 'points': list(enumerate(data['points']))}
        if not any(payload.x_min <= x <= payload.x_max for x, _ in curve['points']):
            raise DispersionError('dispersion_print_empty', '打印范围内没有谱图点')
        content, metadata = render_spectrum_pdf([curve], record, f'曝光 {payload.exposure_start}–{payload.exposure_end} 帧',
            payload.ccd, 0, 0, payload.x_min, payload.x_max, payload.y_min, payload.y_max, layers=['grayscale', 'curve'])
        service.record_observation_print(task_id, payload.model_dump() | {'frame_sha256': data['frame_sha256']} | metadata, session.user_id)
        return Response(content, media_type='application/pdf', headers={
            'Content-Disposition': f'attachment; filename="dispersion-{task_id}-ccd{payload.ccd + 1}.pdf"',
            'X-Visible-Point-Count': str(metadata['visible_point_count'])})
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/start", tags=["dispersion"])
def start_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
    continuous: bool = False,
) -> dict[str, Any]:
    try:
        service = runtime.dispersion_service()
        current = service.get_task(task_id)
        require_activation(runtime, begins_new_work=lambda: current["status"] == "draft" or (
            continuous and any(item["status"] == "draft" for item in current.get("capture_turns", []))))
        task = service.start_sequence(task_id, session.user_id) if continuous else service.start_task(task_id, session.user_id)
        return runtime.messages.task(task, source='dispersion', category='acquisition')
    except (DispersionError, DeviceError) as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/preheat", tags=["dispersion"])
def preheat_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
    _: Session = Depends(require_permission("dispersion.write")),
    *, runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_activation(runtime)
    try:
        service = runtime.dispersion_service()
        return runtime.messages.task(service.preheat_task(task_id, session.user_id), source='dispersion', category='acquisition')
    except (DispersionError, DeviceError) as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/step", tags=["dispersion"])
def step_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.dispersion_service().step_task(task_id, session.user_id), source='dispersion', category='acquisition')
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/pause", tags=["dispersion"])
def pause_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.dispersion_service().pause_task(task_id, session.user_id), source='dispersion', category='acquisition')
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/resume", tags=["dispersion"])
def resume_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.dispersion_service().resume_task(task_id, session.user_id), source='dispersion', category='acquisition')
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/stop", tags=["dispersion"])
def stop_dispersion_task(
    task_id: int,
    session: Session = Depends(require_permission("dispersion.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.dispersion_service().stop_task(task_id, session.user_id), source='dispersion', category='acquisition')
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/tasks/{task_id}/frames", tags=["dispersion"])
def dispersion_task_frames(
    task_id: int,
    phase: str | None = Query(default=None),
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    _: Session = Depends(require_permission("dispersion.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    try:
        return runtime.dispersion_service().frames(task_id, phase=phase, ccd_index=ccd_index)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get('/api/v1/dispersion/tasks/{task_id}/point-details', tags=['dispersion'])
def dispersion_point_details(task_id: int, ccd: int = Query(ge=0), point: int = Query(ge=0), all_points: bool = False,
    _: Session = Depends(require_permission('dispersion.read')), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.dispersion_service().point_details(task_id, ccd, None if all_points else point)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post('/api/v1/dispersion/tasks/{task_id}/point-details/copy', tags=['dispersion'])
def copy_dispersion_point_details(task_id: int, ccd: int = Query(ge=0), point: int = Query(ge=0),
    orientation: str = Query(pattern='^(vertical|horizontal)$'), session: Session = Depends(require_permission('spectra.export')),
    *, _: Session = Depends(require_permission('dispersion.read')), runtime: Runtime = Depends(get_runtime)) -> dict:
    from ..modules.spectrum_viewer import point_details_text

    try:
        service = runtime.dispersion_service()
        details = service.point_details(task_id, ccd, point)
        text = point_details_text(details, orientation)
        service.record_observation_copy(task_id,
            {'ccd': ccd, 'point': point, 'orientation': orientation, 'sha256': details['sha256']}, session.user_id)
        return {'text': text, 'sha256': details['sha256']}
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post('/api/v1/dispersion/tasks/{task_id}/point-details/print', tags=['dispersion'])
def print_dispersion_point_details(task_id: int, ccd: int = Query(ge=0), point: int = Query(ge=0),
    session: Session = Depends(require_permission('spectra.export')), *, _: Session = Depends(require_permission('dispersion.read')),
    runtime: Runtime = Depends(get_runtime)) -> Response:
    from ..modules.spectrum_pdf import render_point_details_pdf

    try:
        service = runtime.dispersion_service()
        details = service.point_details(task_id, ccd, point)
        content = render_point_details_pdf(details)
        service.record_observation_print(task_id,
            {'output': 'raw-point-details', 'ccd': ccd, 'point': point, 'sha256': details['sha256']}, session.user_id)
        return Response(content, media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="dispersion-{task_id}-point-{point + 1}.pdf"'})
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines", status_code=201, tags=["dispersion"])
def add_dispersion_line(
    task_id: int,
    payload: DispersionLineInput,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().add_line(task_id, payload.model_dump(mode="json"), session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.delete("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}", tags=["dispersion"])
def delete_dispersion_line(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().delete_line(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/locate-all", tags=["dispersion"])
def locate_all_dispersion_lines(
    task_id: int,
    legacy_window: bool = False,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return runtime.dispersion_service().locate_all(task_id, session.user_id, legacy_window=legacy_window)


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/locate", tags=["dispersion"])
def locate_dispersion_line(
    task_id: int,
    line_id: int,
    legacy_window: bool = False,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().locate_line(task_id, line_id, session.user_id, legacy_window=legacy_window)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/move", tags=["dispersion"])
def move_dispersion_line(
    task_id: int,
    line_id: int,
    payload: DispersionLineMoveRequest,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().move_line(
            task_id, line_id, payload.direction, payload.steps, session.user_id
        )
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/save", tags=["dispersion"])
def save_dispersion_line_position(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().save_line_position(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/restore", tags=["dispersion"])
def restore_dispersion_line_position(
    task_id: int,
    line_id: int,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().restore_line_position(task_id, line_id, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/tasks/{task_id}/calibrations/fit", status_code=201, tags=["dispersion"])
def fit_dispersion_calibration(
    task_id: int,
    payload: DispersionCalibrationFitRequest,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().fit_calibration(
            task_id, payload.model_dump(exclude_none=True), session.user_id
        )
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/calibrations/{calibration_version_id}", tags=["dispersion"])
def get_dispersion_calibration(
    calibration_version_id: int,
    _: Session = Depends(require_permission("dispersion.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().calibration(calibration_version_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/calibrations/{calibration_version_id}/publish", tags=["dispersion"])
@router.post("/api/v1/dispersion/calibrations/{calibration_version_id}/save", tags=["dispersion"])
def publish_dispersion_calibration(
    calibration_version_id: int,
    name: str | None = Query(default=None, min_length=1, max_length=120),
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().publish_calibration(calibration_version_id, session.user_id, name=name)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/calibrations/{calibration_version_id}/bind", tags=["dispersion"])
def bind_dispersion_calibration(
    calibration_version_id: int,
    payload: DispersionCalibrationBindRequest,
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.dispersion_service().bind_calibration(
            calibration_version_id, payload.model_dump(exclude_none=True), session.user_id
        )
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.get("/api/v1/dispersion/bindings", tags=["dispersion"])
def list_dispersion_bindings(
    method_id: int | None = Query(default=None, ge=1),
    _: Session = Depends(require_permission("dispersion.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return runtime.dispersion_service().bindings(method_id)


@router.post("/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position", tags=["dispersion"])
def set_dispersion_position(
    task_id: int,
    line_id: int,
    position: float = Query(ge=0, le=100000),
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.dispersion_service().set_line_position(task_id, line_id, position, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc


@router.post("/api/v1/dispersion/calibrations/{calibration_id}/manage", tags=["dispersion"])
def manage_dispersion_calibration(
    calibration_id: int,
    action: str = Query(),
    name: str | None = Query(default=None, max_length=120),
    session: Session = Depends(require_permission("dispersion.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.dispersion_service().manage_calibration(calibration_id, action, name, session.user_id)
    except DispersionError as exc:
        raise dispersion_error(exc) from exc
