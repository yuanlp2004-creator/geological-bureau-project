"""方法拥有的谱线草稿编辑边界；绑定调用方事务，不打开连接或提交。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...db import utc_now
from .errors import MethodDomainError
from .values import _json

if TYPE_CHECKING:
    from .service import MethodService


@dataclass
class MethodLineDraft:
    method_id: int
    version: int
    state: str
    payload: dict[str, Any]


class MethodLineEditor:
    def __init__(self, connection: sqlite3.Connection, methods: MethodService):
        self._connection = connection
        self._methods = methods

    def load(self, method_id: int) -> MethodLineDraft:
        from ..spectral_lines import canonical_lines

        db = self._connection
        row = db.execute("SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)).fetchone()
        if row is None:
            raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
        latest = self._methods.repository._latest_row(db, method_id)
        if latest is None:
            raise MethodDomainError("method_version_not_found", "方法版本不存在", status_code=404)
        from .legacy_values import legacy_payload
        payload = legacy_payload(json.loads(latest["payload_json"]), db, method_id)
        payload["lines"] = canonical_lines(payload.get("lines"), payload.get("conditions", {}))
        return MethodLineDraft(method_id, latest["version"], latest["state"], payload)

    def save(
        self,
        draft: MethodLineDraft,
        actor_user_id: int | None,
        action: str,
        line_id: str | None,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """创建方法版本、更新时间和谱线审计，按原顺序返回方法视图。"""
        db, methods = self._connection, self._methods
        now = utc_now()
        version, errors = methods._insert_payload_draft(db, draft.method_id, draft.payload, actor_user_id, now)
        db.execute("UPDATE methods SET updated_at=? WHERE id=?", (now, draft.method_id))
        actor = methods.repository._valid_actor(db, actor_user_id)
        audit = {
            "method_id": draft.method_id,
            "line_id": line_id,
            "version": version,
            "validation_issue_count": len(errors),
            **details,
        }
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
            "details_json, created_at) VALUES (?, ?, 'spectral_line', ?, ?, ?)",
            (actor, action, draft.method_id, _json(audit), utc_now()),
        )
        updated = db.execute("SELECT * FROM methods WHERE id=?", (draft.method_id,)).fetchone()
        state = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
        result = methods.repository._method_dict(db, updated, current_id=state[0] if state else None)
        result["changed_line_id"] = line_id
        return result
