"""方法版本业务事务和对外兼容服务入口。"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from typing import Any
from ...db import Database, utc_now
from ...schemas.methods import MethodCreate, MethodUpdate
from .values import _json, _normalize_conditions, validate_method_name, DEFAULT_CONDITIONS
from .errors import MethodDomainError
from .geometry import MethodGeometry
from .repository import MethodRepository
from .runtime import MethodRuntime
from .validation import MethodValidator
from .snapshots import MethodSnapshotReader

class MethodService:
    def __init__(self, database: Database):
        self.database = database
        self.geometry = MethodGeometry()
        self.repository = MethodRepository(database, self.geometry)
        self.validation = MethodValidator(database, self.repository, self.geometry)
        self.runtime = MethodRuntime(database, self.repository)

    def bind_snapshots(self, connection: sqlite3.Connection) -> MethodSnapshotReader:
        """Bind read operations to the caller's existing transaction; never commit."""
        return MethodSnapshotReader(connection)

    def _canonical_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        from ..spectral_lines import canonical_lines

        result = deepcopy(payload)
        conditions = result.get("conditions", deepcopy(DEFAULT_CONDITIONS))
        result["conditions"] = conditions
        result["lines"] = canonical_lines(result.get("lines"), conditions)
        result["payload_schema"] = "method-v2-lines"
        return result

    def _validate_payload(
        self, payload: dict[str, Any], db: sqlite3.Connection
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        from ..spectral_lines import validate_spectral_lines

        canonical = self._canonical_payload(payload)
        errors = self.validation.validate_conditions(canonical["conditions"], db)
        errors.extend(
            validate_spectral_lines(self, db, canonical["conditions"], canonical["lines"])
        )
        return canonical, errors

    def _insert_payload_draft(
        self,
        db: sqlite3.Connection,
        method_id: int,
        payload: dict[str, Any],
        actor_user_id: int | None,
        now: str,
    ) -> tuple[int, list[dict[str, str]]]:
        version = self.repository._next_version(db, method_id)
        canonical, errors = self._validate_payload(payload, db)
        db.execute(
            "INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at, created_by) "
            "VALUES (?, ?, 'draft', ?, ?, ?, ?)",
            (
                method_id,
                version,
                _json(canonical),
                _json(errors),
                now,
                self.repository._valid_actor(db, actor_user_id),
            ),
        )
        return version, errors

    def create(self, payload: MethodCreate, actor_user_id: int) -> dict[str, Any]:
        name = validate_method_name(payload.name)
        conditions = _normalize_conditions({}, payload.conditions)
        work_type = payload.work_type.strip()
        if not work_type:
            raise MethodDomainError("work_type_required", "工作类型不能为空", fields=["work_type"])
        with self.database.write() as db:
            if self.repository._duplicate_name(db, name):
                raise MethodDomainError("method_name_exists", "方法名称已存在", status_code=409)
            now = utc_now()
            cursor = db.execute(
                "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', NULL, ?, ?)",
                (name, payload.description.strip(), work_type, now, now),
            )
            method_id = int(cursor.lastrowid)
            version, errors = self._insert_payload_draft(
                db, method_id, {"conditions": conditions}, actor_user_id, now
            )
            self.repository._audit(
                db,
                self.repository._valid_actor(db, actor_user_id),
                "method.create",
                method_id,
                {"name": name, "version": version, "validation_issue_count": len(errors)},
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            return self.repository._method_dict(db, row)

    def update(self, method_id: int, payload: MethodUpdate, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            if row is None or row["status"] == "deleted":
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            now = utc_now()
            actor_id = self.repository._valid_actor(db, actor_user_id)
            if payload.name is not None:
                name = validate_method_name(payload.name)
                if self.repository._duplicate_name(db, name, method_id):
                    raise MethodDomainError("method_name_exists", "方法名称已存在", status_code=409)
                if name != row["name"]:
                    db.execute("UPDATE methods SET name=?, updated_at=? WHERE id=?", (name, now, method_id))
                    self.repository._audit(
                        db, actor_id, "method.rename", method_id, {"from": row["name"], "to": name}
                    )
            metadata: dict[str, Any] = {}
            if payload.description is not None:
                metadata["description"] = payload.description.strip()
            if payload.work_type is not None:
                work_type = payload.work_type.strip()
                if not work_type:
                    raise MethodDomainError(
                        "work_type_required", "工作类型不能为空", fields=["work_type"]
                    )
                metadata["work_type"] = work_type
            if metadata:
                db.execute(
                    "UPDATE methods SET description=COALESCE(?, description), work_type=COALESCE(?, work_type), updated_at=? WHERE id=?",
                    (metadata.get("description"), metadata.get("work_type"), now, method_id),
                )
                self.repository._audit(db, actor_id, "method.metadata.update", method_id, metadata)
            if payload.conditions is not None:
                latest = self.repository._latest_row(db, method_id)
                latest_payload = (
                    json.loads(latest["payload_json"])
                    if latest
                    else {"conditions": deepcopy(DEFAULT_CONDITIONS)}
                )
                current = latest_payload.get("conditions", {})
                conditions = _normalize_conditions(current, payload.conditions)
                latest_payload["conditions"] = conditions
                version, errors = self._insert_payload_draft(
                    db, method_id, latest_payload, actor_user_id, now
                )
                db.execute("UPDATE methods SET updated_at=? WHERE id=?", (now, method_id))
                self.repository._audit(
                    db,
                    actor_id,
                    "method.update",
                    method_id,
                    {"version": version, "validation_issue_count": len(errors)},
                )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self.repository._method_dict(db, row, current_id=current[0] if current else None)

    def publish(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            if row is None or row["status"] == "deleted":
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            latest = self.repository._latest_row(db, method_id)
            if latest is None or latest["state"] != "draft":
                raise MethodDomainError(
                    "method_draft_missing", "没有待发布的方法草稿", status_code=409
                )
            payload = json.loads(latest["payload_json"])
            payload, errors = self._validate_payload(payload, db)
            if errors:
                raise MethodDomainError(
                    "invalid_method_draft",
                    "方法草稿未通过发布校验",
                    fields=sorted({error["field"] for error in errors}),
                    details={"validation_errors": errors},
                )
            version = self.repository._next_version(db, method_id)
            now = utc_now()
            actor_id = self.repository._valid_actor(db, actor_user_id)
            db.execute(
                "INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at, created_by) "
                "VALUES (?, ?, 'published', ?, '[]', ?, ?)",
                (method_id, version, _json(payload), now, actor_id),
            )
            db.execute(
                "UPDATE methods SET current_version=?, updated_at=? WHERE id=?",
                (version, now, method_id),
            )
            db.execute(
                "UPDATE method_runtime_state SET current_version=?, action_state='idle', updated_at=? "
                "WHERE id=1 AND current_method_id=?",
                (version, now, method_id),
            )
            self.repository._audit(db, actor_id, "method.publish", method_id, {"version": version})
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self.repository._method_dict(db, row, current_id=current[0] if current else None)

    def copy(self, method_id: int, name: str, actor_user_id: int) -> dict[str, Any]:
        name = validate_method_name(name)
        with self.database.write() as db:
            source = db.execute(
                "SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)
            ).fetchone()
            if source is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            if self.repository._duplicate_name(db, name):
                raise MethodDomainError("method_name_exists", "方法名称已存在", status_code=409)
            latest = self.repository._latest_row(db, method_id)
            source_payload = (
                json.loads(latest["payload_json"])
                if latest
                else {"conditions": deepcopy(DEFAULT_CONDITIONS)}
            )
            now = utc_now()
            cursor = db.execute(
                "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', NULL, ?, ?)",
                (name, source["description"], source["work_type"], now, now),
            )
            new_id = int(cursor.lastrowid)
            version, errors = self._insert_payload_draft(
                db, new_id, deepcopy(source_payload), actor_user_id, now
            )
            self.repository._audit(
                db,
                self.repository._valid_actor(db, actor_user_id),
                "method.copy",
                new_id,
                {
                    "source_method_id": method_id,
                    "version": version,
                    "validation_issue_count": len(errors),
                },
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (new_id,)).fetchone()
            return self.repository._method_dict(db, row)

    _layout_geometry = staticmethod(MethodGeometry._layout_geometry)

    _wave_to_step = staticmethod(MethodGeometry._wave_to_step)

    _step_to_wave = staticmethod(MethodGeometry._step_to_wave)

    def _reference_position(self, wave: float, layout: sqlite3.Row, dispersion: sqlite3.Row) -> tuple[int, float, bool] | None:
        return self.geometry._reference_position(wave, layout, dispersion)

    _valid_actor = staticmethod(MethodRepository._valid_actor)

    _next_version = staticmethod(MethodRepository._next_version)

    _latest_row = staticmethod(MethodRepository._latest_row)

    _published_row = staticmethod(MethodRepository._published_row)

    _layout = staticmethod(MethodRepository._layout)

    _dispersion = staticmethod(MethodRepository._dispersion)

    _version_dict = staticmethod(MethodRepository._version_dict)

    def _method_dict(self, db: sqlite3.Connection, row: sqlite3.Row, *, current_id: int | None=None) -> dict[str, Any]:
        return self.repository._method_dict(db, row, current_id=current_id)

    _duplicate_name = staticmethod(MethodRepository._duplicate_name)

    def list(self, *, include_deleted: bool=False) -> list[dict[str, Any]]:
        return self.repository.list(include_deleted=include_deleted)

    def get(self, method_id: int, *, include_deleted: bool=False) -> dict[str, Any]:
        return self.repository.get(method_id, include_deleted=include_deleted)

    def versions(self, method_id: int) -> list[dict[str, Any]]:
        return self.repository.versions(method_id)

    def _calibration_option(self, layout: sqlite3.Row, calibration: sqlite3.Row) -> dict[str, Any]:
        return self.repository._calibration_option(layout, calibration)

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    _audit = staticmethod(MethodRepository._audit)

    _issue = staticmethod(MethodValidator._issue)

    def validate_conditions(self, conditions: dict[str, Any], db: sqlite3.Connection | None=None) -> list[dict[str, str]]:
        return self.validation.validate_conditions(conditions, db)

    def open(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        return self.runtime.open(method_id, actor_user_id)

    def pause(self, method_id: int, actor_user_id: int, *, paused: bool=True) -> dict[str, Any]:
        return self.runtime.pause(method_id, actor_user_id, paused=paused)

    def delete(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        return self.runtime.delete(method_id, actor_user_id)

    def current(self) -> dict[str, Any]:
        return self.runtime.current()

