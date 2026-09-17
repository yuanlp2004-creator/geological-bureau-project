"""Events API boundary; business services retain their existing behavior."""
from __future__ import annotations
import asyncio
import json
import secrets
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from ..runtime import Runtime
from .dependencies import get_runtime

router = APIRouter()


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket, *, runtime: Runtime = Depends(get_runtime)) -> None:
    await websocket.accept()
    if runtime.process_key:
        supplied_key = websocket.headers.get("X-GeoSpectrum-Process-Key") or websocket.query_params.get("process_key", "")
        if not secrets.compare_digest(supplied_key, runtime.process_key):
            await websocket.close(code=4403, reason="process key required")
            return
    session = runtime.auth_service.get_session(websocket.query_params.get("access_token"))
    if session is None:
        await websocket.close(code=4401, reason="authentication required")
        return
    if "runtime-events.read" not in session.permissions:
        await websocket.close(code=4403, reason="permission denied")
        return
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
    runtime.event_subscribers.add(queue)
    try:
        await websocket.send_text(json.dumps({"type": "ready", "api_version": "v1"}))
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps({"type": "runtime_event", "event": event}, ensure_ascii=False))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        runtime.event_subscribers.discard(queue)
