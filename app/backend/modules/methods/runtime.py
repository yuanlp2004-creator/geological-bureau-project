"""当前方法打开、暂停、删除及运行状态。"""

from __future__ import annotations

from typing import Any
from ...db import Database, utc_now
from .errors import MethodDomainError
from .repository import MethodRepository

class MethodRuntime:
    def __init__(self, database: Database, repository: MethodRepository):
        self.database = database
        self.repository = repository

    def open(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)
            ).fetchone()
            if row is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            if row["status"] == "paused":
                raise MethodDomainError("method_paused", "方法已停用，请先启用", status_code=409)
            if row["current_version"] is None:
                raise MethodDomainError(
                    "method_not_published", "方法尚未发布，不能设为当前方法", status_code=409
                )
            now = utc_now()
            db.execute(
                "UPDATE method_runtime_state SET current_method_id=?, current_version=?, action_state='idle', updated_at=? WHERE id=1",
                (method_id, row["current_version"], now),
            )
            self.repository._audit(
                db,
                self.repository._valid_actor(db, actor_user_id),
                "method.open",
                method_id,
                {"version": row["current_version"]},
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            return self.repository._method_dict(db, row, current_id=method_id)

    def pause(
        self, method_id: int, actor_user_id: int, *, paused: bool = True
    ) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)
            ).fetchone()
            if row is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            status = "paused" if paused else "active"
            now = utc_now()
            db.execute("UPDATE methods SET status=?, updated_at=? WHERE id=?", (status, now, method_id))
            db.execute(
                "UPDATE method_runtime_state SET action_state=?, updated_at=? WHERE id=1 AND current_method_id=?",
                ("paused" if paused else "idle", now, method_id),
            )
            self.repository._audit(
                db,
                self.repository._valid_actor(db, actor_user_id),
                "method.pause" if paused else "method.resume",
                method_id,
                {"status": status},
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self.repository._method_dict(db, row, current_id=current[0] if current else None)

    def delete(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)
            ).fetchone()
            if row is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            now = utc_now()
            db.execute("UPDATE methods SET status='deleted', updated_at=? WHERE id=?", (now, method_id))
            db.execute(
                "UPDATE method_runtime_state SET current_method_id=NULL, current_version=NULL, action_state='idle', updated_at=? "
                "WHERE id=1 AND current_method_id=?",
                (now, method_id),
            )
            self.repository._audit(
                db,
                self.repository._valid_actor(db, actor_user_id),
                "method.delete",
                method_id,
                {"name": row["name"]},
            )
            return {"id": method_id, "deleted": True}

    def current(self) -> dict[str, Any]:
        empty_actions = {
            "can_acquire": False,
            "can_analyze": False,
            "can_pause": False,
            "can_resume": False,
            "can_delete": False,
        }
        with self.database.read() as db:
            state = db.execute("SELECT * FROM method_runtime_state WHERE id=1").fetchone()
            if state is None or state["current_method_id"] is None:
                return {
                    "method_id": None,
                    "version": None,
                    "work_type": None,
                    "title": None,
                    "status": None,
                    "action_state": state["action_state"] if state else "idle",
                    "actions": empty_actions,
                    "method": None,
                    "referenced_version": None,
                }
            row = db.execute("SELECT * FROM methods WHERE id=?", (state["current_method_id"],)).fetchone()
            referenced = self.repository._published_row(db, int(row["id"]), state["current_version"]) if row else None
            if row is None or row["status"] == "deleted" or referenced is None:
                return {
                    "method_id": None,
                    "version": None,
                    "work_type": None,
                    "title": None,
                    "status": None,
                    "action_state": "idle",
                    "actions": empty_actions,
                    "method": None,
                    "referenced_version": None,
                }
            active = row["status"] == "active" and state["action_state"] == "idle"
            actions = {
                "can_acquire": active,
                "can_analyze": active,
                "can_pause": row["status"] == "active",
                "can_resume": row["status"] == "paused",
                "can_delete": True,
            }
            return {
                "method_id": row["id"],
                "version": state["current_version"],
                "work_type": row["work_type"],
                "title": row["name"],
                "status": row["status"],
                "action_state": state["action_state"],
                "actions": actions,
                "method": self.repository._method_dict(db, row, current_id=row["id"]),
                "referenced_version": self.repository._version_dict(referenced),
            }

