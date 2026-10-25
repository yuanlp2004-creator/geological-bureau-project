"""Acquisition API boundary; business services retain their existing behavior."""

from __future__ import annotations
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from ..schemas.acquisition import AcquisitionTaskCreate, AcquisitionIntervalMark, AcquisitionRename, AcquisitionDiscard
from ..schemas.system import PreliminaryConditions
from ..auth import Session
from ..modules.sample_queues import SampleQueueError
from ..modules.acquisition import AcquisitionError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def acquisition_error(exc: AcquisitionError | SampleQueueError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/acquisitions/options", tags=["acquisition"])
def acquisition_options(
    _: Session = Depends(require_permission("acquisition.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    return {**runtime.acquisition_service().options(),
            "preliminary_defaults": runtime.service.get_settings()["preliminary"]}


@router.put("/api/v1/acquisitions/defaults", tags=["acquisition"])
def save_evaporation_defaults(payload: PreliminaryConditions,
    session: Session = Depends(require_permission("acquisition.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.service.save_preliminary_conditions("evaporation", payload, session.user_id)


@router.get("/api/v1/acquisitions/tasks", tags=["acquisition"])
def list_acquisition_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    task_kind: Literal["sample", "evaporation"] | None = Query(default=None),
    _: Session = Depends(require_permission("acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    return runtime.acquisition_service().list_tasks(limit, task_kind=task_kind)


@router.post("/api/v1/acquisitions/tasks", status_code=201, tags=["acquisition"])
def create_acquisition_task(
    payload: AcquisitionTaskCreate,
    session: Session = Depends(require_permission("acquisition.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().create_task(payload.model_dump(), session.user_id), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.get("/api/v1/acquisitions/tasks/{task_id}", tags=["acquisition"])
def get_acquisition_task(
    task_id: int,
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.acquisition_service().get_task(task_id, include_points=include_points)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/start", tags=["acquisition"])
def start_acquisition_task(
    task_id: int,
    session: Session = Depends(require_permission("acquisition.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().start(task_id, session.user_id), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/preheat", tags=["acquisition"])
def preheat_acquisition_task(
    task_id: int,
    session: Session = Depends(require_permission("acquisition.execute")),
    _: Session = Depends(require_permission("acquisition.write")),
    *, runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().preheat(task_id, session.user_id), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/step", tags=["acquisition"])
def step_acquisition_task(
    task_id: int,
    single_repeat: bool = Query(default=False),
    session: Session = Depends(require_permission("acquisition.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().step(task_id, session.user_id, single_repeat=single_repeat), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/pause", tags=["acquisition"])
def pause_acquisition_task(
    task_id: int,
    session: Session = Depends(require_permission("acquisition.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().pause(task_id, session.user_id), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/resume", tags=["acquisition"])
def resume_acquisition_task(
    task_id: int,
    session: Session = Depends(require_permission("acquisition.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().resume(task_id, session.user_id), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/stop", tags=["acquisition"])
def stop_acquisition_task(
    task_id: int,
    session: Session = Depends(require_permission("acquisition.execute")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.messages.task(runtime.acquisition_service().stop(task_id, session.user_id), source='acquisition', category='acquisition')
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.get("/api/v1/acquisitions/tasks/{task_id}/frames", tags=["acquisition"])
def acquisition_frames(
    task_id: int,
    repeat_index: int | None = Query(default=None, ge=0, le=10),
    phase: str | None = Query(default=None),
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    try:
        return runtime.acquisition_service().frames(
            task_id, repeat_index=repeat_index, phase=phase, ccd_index=ccd_index, include_points=include_points
        )
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/intervals", tags=["acquisition"])
def mark_acquisition_interval(
    task_id: int,
    payload: AcquisitionIntervalMark,
    session: Session = Depends(require_permission("acquisition.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.acquisition_service().mark_interval(task_id, payload.model_dump(), session.user_id)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.get("/api/v1/acquisitions/tasks/{task_id}/analysis", tags=["acquisition"])
def acquisition_analysis(
    task_id: int,
    repeat_index: int | None = Query(default=None, ge=0, le=10),
    _: Session = Depends(require_permission("acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        return runtime.acquisition_service().analysis(task_id, repeat_index)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.get("/api/v1/acquisitions/samples/{sample_id}/bands", tags=["acquisition"])
def acquisition_sample_bands(
    sample_id: int,
    ccd_index: int | None = Query(default=None, ge=0, le=255),
    include_points: bool = Query(default=False),
    _: Session = Depends(require_permission("acquisition.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[dict[str, Any]]:
    try:
        return runtime.acquisition_service().band(sample_id, ccd_index, include_points)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/samples/{sample_id}/rename", tags=["acquisition"])
def rename_acquisition_sample(
    task_id: int,
    sample_id: int,
    payload: AcquisitionRename,
    session: Session = Depends(require_permission("acquisition.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    try:
        if payload.name_length is None:
            return runtime.acquisition_service().rename(task_id, sample_id, payload.post_name, session.user_id)
        return runtime.acquisition_service().rename(task_id, sample_id, payload.post_name, session.user_id,
                                                    name_length=payload.name_length)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.post("/api/v1/acquisitions/tasks/{task_id}/discard", tags=["acquisition"])
def discard_acquisition_sample(
    task_id: int, payload: AcquisitionDiscard,
    session: Session = Depends(require_permission("acquisition.write")),
    *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        return runtime.acquisition_service().discard(task_id, payload.reason, session.user_id)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc


@router.get("/api/v1/acquisitions/tasks/{task_id}/measurements", tags=["acquisition"])
def acquisition_measurements(
    task_id: int, _: Session = Depends(require_permission("acquisition.read")),
    *, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        # 采集服务提供公开读快照，分析服务复用正式公式计算即时值；此读取不建立正式分析运行。
        snapshot = runtime.acquisition_service().measurement_snapshot(task_id)
        return runtime.analysis_service().measurement_results(snapshot)
    except (AcquisitionError, SampleQueueError) as exc:
        raise acquisition_error(exc) from exc
