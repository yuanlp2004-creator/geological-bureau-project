"""Extensions API boundary; business services retain their existing behavior."""
from __future__ import annotations
import asyncio
import json
from typing import Any
from fastapi import Depends, FastAPI
from ..db import utc_now
from ..auth import Session
from ..modules.extensions import ExtensionManifest, discover_test_extensions
from ..runtime import Runtime
from .dependencies import get_runtime, require_permission


def _extension_endpoint(extension: ExtensionManifest):
    async def execute_extension(
        session: Session = Depends(require_permission(extension.permission)), *, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
        created_at = utc_now()
        payload = {"event_type": extension.event_type, "event_version": 1, "module": extension.key, "created_at": created_at}
        table = extension.key.replace("-", "_") + "_records"
        with runtime.database.write() as connection:
            cursor = connection.execute(
                f"INSERT INTO {table}(event_version, payload_json, created_at) VALUES (1, ?, ?)",
                (json.dumps(payload, ensure_ascii=False), created_at),
            )
            record_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session.user_id, extension.audit_action, extension.key, record_id, json.dumps(payload, ensure_ascii=False), created_at),
            )
            event_cursor = connection.execute(
                "INSERT INTO runtime_events(category, severity, message, details_json, correlation_id, created_at) VALUES ('action', 'success', ?, ?, ?, ?)",
                (extension.title, json.dumps(payload, ensure_ascii=False), extension.event_type, created_at),
            )
        event = {"id": int(event_cursor.lastrowid), "category": "action", "severity": "success", "message": extension.title, "details": payload, "correlation_id": extension.event_type, "created_at": created_at}
        for queue in tuple(runtime.event_subscribers):
            try:
                queue.put_nowait({"type": extension.event_type, "version": 1, "event": event})
            except asyncio.QueueFull:
                pass
        return {"record_id": record_id, **payload}

    execute_extension.__name__ = f"execute_{extension.key.replace('-', '_')}"
    return execute_extension


def register_extensions(application: FastAPI) -> None:
    for extension in discover_test_extensions():
        application.add_api_route(
            f"/api/v1/extensions/{extension.key}/execute",
            _extension_endpoint(extension), methods=["POST"], tags=["test-extension"],
        )
