"""Sample Queues API boundary; business services retain their existing behavior."""
from __future__ import annotations
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from ..db import utc_now
from ..schemas.sample_queues import (
    SampleQueueCreate,
    SampleQueueUpdate,
    SampleQueueRename,
    SampleQueueImport,
)
from ..auth import Session
from ..modules.sample_queues import SampleQueueError
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission

router = APIRouter()


def sample_queue_error(exc: SampleQueueError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.get("/api/v1/sample-queues", tags=["sample-queues"])
def list_sample_queues(_: Session = Depends(require_permission("samples.read")), *, runtime: Runtime = Depends(get_runtime)) -> list[dict]:
    return runtime.sample_queue_service().list()


@router.get("/api/v1/sample-queues/{queue_id}", tags=["sample-queues"])
def get_sample_queue(queue_id: int, _: Session = Depends(require_permission("samples.read")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().get(queue_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.post("/api/v1/sample-queues", status_code=201, tags=["sample-queues"])
def create_sample_queue(payload: SampleQueueCreate, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().create(payload.name, [item.model_dump() for item in payload.items], session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.patch("/api/v1/sample-queues/{queue_id}", tags=["sample-queues"])
def update_sample_queue(queue_id: int, payload: SampleQueueUpdate, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().update(queue_id, [item.model_dump() for item in payload.items], session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.post("/api/v1/sample-queues/{queue_id}/items/{item_id}/rename", tags=["sample-queues"])
def rename_sample_queue_item(queue_id: int, item_id: int, payload: SampleQueueRename, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().rename(queue_id, item_id, payload.post_name, session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.delete("/api/v1/sample-queues/{queue_id}/items/{item_id}", tags=["sample-queues"])
def delete_sample_queue_item(queue_id: int, item_id: int, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().delete_item(queue_id, item_id, session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.post("/api/v1/sample-queues/{queue_id}/clear", tags=["sample-queues"])
def clear_sample_queue(queue_id: int, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().clear(queue_id, session.user_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.post("/api/v1/sample-queues/import", status_code=201, tags=["sample-queues"])
def import_sample_queue(payload: SampleQueueImport, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> dict:
    try:
        return runtime.sample_queue_service().import_bytes(payload.content.encode("utf-8"), session.user_id, payload.queue_name or Path(payload.filename).stem, payload.filename)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc


@router.get("/api/v1/sample-queues/{queue_id}/export", tags=["sample-queues"])
def export_sample_queue(queue_id: int, session: Session = Depends(require_permission("samples.write")), *, runtime: Runtime = Depends(get_runtime)) -> Response:
    try:
        content, digest = runtime.sample_queue_service().export_sam(queue_id)
    except SampleQueueError as exc:
        raise sample_queue_error(exc) from exc
    with runtime.database.write() as db:
        db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'sample_queue.sam_export', 'sample_queue', ?, ?, ?)", (session.user_id, queue_id, json.dumps({"sha256": digest, "bytes": len(content)}, ensure_ascii=False), utc_now()))
    return Response(content=content, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="queue-{queue_id}.sam"', "X-Source-SHA256": digest})
