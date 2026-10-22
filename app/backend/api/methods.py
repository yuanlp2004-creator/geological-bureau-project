"""Method, spectral-line and method-print HTTP endpoints."""

from __future__ import annotations
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from ..schemas.methods import (
    MethodActionRequest,
    MethodCreate,
    MethodCurrentResponse,
    MethodPrintRequest,
    MethodPrintSettings,
    MethodRenderRequest,
    MethodResponse,
    MethodSave,
    MethodUpdate,
    MethodVersion,
    SpectralLineDetectRequest,
    SpectralLineInput,
    SpectralLineReorder,
)
from ..auth import Session
from ..modules.methods import MethodDomainError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def method_error(exc: MethodDomainError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/methods", response_model=list[MethodResponse], tags=["methods"])
def list_methods(
    include_deleted: bool = Query(default=False),
    _: Session = Depends(require_permission("methods.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> list[MethodResponse]:
    return [MethodResponse(**item) for item in runtime.methods_service().list(include_deleted=include_deleted)]


@router.get("/api/v1/methods/options", tags=["methods"])
def method_options(
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    return {**runtime.methods_service().options(),
            "dark_round_time_seconds": runtime.service.get_settings()["analysis"]["dark_round_time_seconds"]}


@router.get("/api/v1/methods/current", response_model=MethodCurrentResponse, tags=["methods"])
def current_method(
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> MethodCurrentResponse:
    return MethodCurrentResponse(**runtime.methods_service().current())


@router.post('/api/v1/methods/reference-offset', tags=['methods'])
def reference_offset(payload: dict, _: Session = Depends(require_permission('methods.read')),
                     runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.methods_service().reference_offset(payload)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, detail={'code': 'reference_offset_invalid', 'message': '参考波长无效'})
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/current", response_model=MethodCurrentResponse, tags=["methods"])
def set_current_method(
    payload: MethodActionRequest,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodCurrentResponse:
    if payload.method_id is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "method_id_required", "message": "必须提供 method_id", "field_errors": ["method_id"]},
        )
    try:
        runtime.methods_service().open(payload.method_id, session.user_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    return MethodCurrentResponse(**runtime.methods_service().current())


@router.get("/api/v1/workspace/state", response_model=MethodCurrentResponse, tags=["methods"])
def workspace_state(
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> MethodCurrentResponse:
    return MethodCurrentResponse(**runtime.methods_service().current())


@router.post("/api/v1/methods", response_model=MethodResponse, status_code=201, tags=["methods"])
def create_method(
    payload: MethodCreate,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().create(payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/methods/{method_id}", response_model=MethodResponse, tags=["methods"])
def get_method(
    method_id: int, _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().get(method_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/methods/{method_id}/versions", response_model=list[MethodVersion], tags=["methods"])
def method_versions(
    method_id: int, _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> list[MethodVersion]:
    try:
        return [MethodVersion(**item) for item in runtime.methods_service().versions(method_id)]
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post('/api/v1/methods/{method_id}/legacy-semantics', response_model=MethodResponse, tags=['methods'])
def upgrade_legacy_method_semantics(method_id: int, session: Session = Depends(require_permission('methods.write')),
                                    runtime: Runtime = Depends(get_runtime)) -> MethodResponse:
    from ..modules.legacy_migration import LegacyMigrationError
    try:
        return MethodResponse(**runtime.legacy_migration_service().upgrade_method_semantics(method_id, session.user_id))
    except (MethodDomainError, LegacyMigrationError) as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.patch("/api/v1/methods/{method_id}", response_model=MethodResponse, tags=["methods"])
def update_method(
    method_id: int,
    payload: MethodUpdate,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().update(method_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/save", response_model=MethodResponse, tags=["methods"])
def save_method(
    method_id: int,
    payload: MethodSave,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().save(method_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/publish", response_model=MethodResponse, tags=["methods"])
def publish_method(
    method_id: int,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().publish(method_id, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/copy", response_model=MethodResponse, status_code=201, tags=["methods"])
def copy_method(
    method_id: int,
    payload: MethodCreate,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().copy(method_id, payload.name, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/open", response_model=MethodResponse, tags=["methods"])
def open_method(
    method_id: int,
    resume_paused: bool = Query(default=False),
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().open(method_id, session.user_id, resume_paused=resume_paused))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/pause", response_model=MethodResponse, tags=["methods"])
def pause_method(
    method_id: int,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().pause(method_id, session.user_id, paused=True))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/resume", response_model=MethodResponse, tags=["methods"])
def resume_method(
    method_id: int,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.methods_service().pause(method_id, session.user_id, paused=False))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.delete("/api/v1/methods/{method_id}", status_code=200, tags=["methods"])
def delete_method(
    method_id: int,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.methods_service().delete(method_id, session.user_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/spectral-lines/options", tags=["spectral-lines"])
def spectral_line_options(
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    return runtime.spectral_lines_service().options()


@router.get("/api/v1/methods/{method_id}/lines", tags=["spectral-lines"])
def list_spectral_lines(
    method_id: int, _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    try:
        return runtime.spectral_lines_service().list(method_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/lines/detect", tags=["spectral-lines"])
def detect_spectral_line(
    method_id: int,
    payload: SpectralLineDetectRequest,
    _: Session = Depends(require_permission("methods.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.spectral_lines_service().detect(
            method_id,
            payload.wavelength_nm,
            payload.actual_wavelength_nm,
            payload.scan_width_points,
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post(
    "/api/v1/methods/{method_id}/lines", response_model=MethodResponse, status_code=201, tags=["spectral-lines"]
)
def create_spectral_line(
    method_id: int,
    payload: SpectralLineInput,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.spectral_lines_service().create(method_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.patch("/api/v1/methods/{method_id}/lines/{line_id}", response_model=MethodResponse, tags=["spectral-lines"])
def update_spectral_line(
    method_id: int,
    line_id: str,
    payload: SpectralLineInput,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.spectral_lines_service().update(method_id, line_id, payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.delete("/api/v1/methods/{method_id}/lines/{line_id}", response_model=MethodResponse, tags=["spectral-lines"])
def delete_spectral_line(
    method_id: int,
    line_id: str,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.spectral_lines_service().delete(method_id, line_id, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/lines/reorder", response_model=MethodResponse, tags=["spectral-lines"])
def reorder_spectral_lines(
    method_id: int,
    payload: SpectralLineReorder,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodResponse:
    try:
        return MethodResponse(**runtime.spectral_lines_service().reorder(method_id, payload.line_ids, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/method-print/settings", response_model=MethodPrintSettings, tags=["method-print"])
def get_method_print_settings(
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> MethodPrintSettings:
    return MethodPrintSettings(**runtime.method_print_service().get_settings())


@router.patch("/api/v1/method-print/settings", response_model=MethodPrintSettings, tags=["method-print"])
def save_method_print_settings(
    payload: MethodPrintSettings,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> MethodPrintSettings:
    try:
        return MethodPrintSettings(**runtime.method_print_service().save_settings(payload, session.user_id))
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/method-print/printers", tags=["method-print"])
def list_method_printers(
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    return {"printers": runtime.method_print_service().printers()}


@router.get("/api/v1/method-print/papers", tags=["method-print"])
def list_printer_papers(
    printer_name: str = Query(min_length=1, max_length=255),
    _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    try:
        return {"papers": runtime.method_print_service().papers(printer_name)}
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/method-print/check-connection", tags=["method-print"])
def check_printer_connection(
    payload: MethodPrintSettings, _: Session = Depends(require_permission("methods.read")),
    *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    try:
        return runtime.method_print_service().check_connection(payload)
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.post("/api/v1/methods/{method_id}/preview", response_class=HTMLResponse, tags=["method-print"])
def preview_method(
    method_id: int,
    payload: MethodRenderRequest,
    session: Session = Depends(require_permission("methods.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> HTMLResponse:
    try:
        markup, document = runtime.method_print_service().preview(
            method_id, payload.version, payload.settings, session.user_id
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    return HTMLResponse(
        markup,
        headers={
            "X-Page-Count": str(document["page_count"]),
            "X-Field-Count": str(document["field_count"]),
            "X-Method-Version": str(document["snapshot"]["version"]["version"]),
        },
    )


@router.post("/api/v1/methods/{method_id}/pdf", tags=["method-print"])
def export_method_pdf(
    method_id: int,
    payload: MethodRenderRequest,
    session: Session = Depends(require_permission("methods.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    try:
        pdf_bytes, document = runtime.method_print_service().pdf(
            method_id, payload.version, payload.settings, session.user_id
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    method_name = document["snapshot"]["method"]["name"]
    version = document["snapshot"]["version"]["version"]
    filename = f"{method_name}-v{version}-方法参数.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=method-v{version}.pdf; filename*=UTF-8''{quote(filename)}",
            "X-Page-Count": str(document["page_count"]),
            "X-Field-Count": str(document["field_count"]),
            "X-Method-Version": str(version),
        },
    )


@router.post('/api/v1/methods/{method_id}/text', tags=['method-print'])
def export_method_text(method_id: int, payload: MethodRenderRequest,
    session: Session = Depends(require_permission('methods.read')), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    try:
        content = runtime.method_print_service().text(method_id,payload.version,session.user_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc
    return Response(content,media_type='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename=method-{method_id}.txt'})


@router.post("/api/v1/methods/{method_id}/print", tags=["method-print"])
def print_method(
    method_id: int,
    payload: MethodPrintRequest,
    session: Session = Depends(require_permission("methods.write")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return runtime.method_print_service().print_method(
            method_id,
            payload.version,
            payload.settings,
            payload.printer_name,
            session.user_id,
        )
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/methods/{method_id}/print-jobs", tags=["method-print"])
def list_method_print_jobs(
    method_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    _: Session = Depends(require_permission("methods.read")),
    *,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return {"jobs": runtime.method_print_service().jobs(method_id, limit)}
    except MethodDomainError as exc:
        raise method_error(exc) from exc


@router.get("/api/v1/method-print/jobs/{job_id}", tags=["method-print"])
def get_method_print_job(
    job_id: str, _: Session = Depends(require_permission("methods.read")), *, runtime: Runtime = Depends(get_runtime)
) -> dict:
    try:
        return runtime.method_print_service().job(job_id)
    except MethodDomainError as exc:
        raise method_error(exc) from exc
