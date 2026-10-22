"""方法版本业务事务和对外兼容服务入口。"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from typing import Any
from ...db import Database, utc_now
from ...schemas.methods import MethodCreate, MethodSave, MethodUpdate
from .values import _json, _normalize_conditions, validate_method_name, DEFAULT_CONDITIONS
from .errors import MethodDomainError
from .geometry import MethodGeometry, MethodLineLocator
from .repository import MethodRepository
from .runtime import MethodRuntime
from .validation import MethodValidator
from .snapshots import MethodSnapshotReader
from .line_editing import MethodLineEditor
from .units import convert_line_unit


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

    def bind_line_editor(self, connection: sqlite3.Connection) -> MethodLineEditor:
        return MethodLineEditor(connection, self)

    def reference_offset(self, conditions: dict[str, Any]) -> dict[str, Any]:
        with self.database.read() as db:
            geometry = self.bind_geometry(db, conditions)
            theory = float(conditions['reference_wavelength_nm'])
            actual = float(conditions['actual_reference_wavelength_nm'])
            left, right = geometry.locate(theory), geometry.locate(actual)
            if left is None or right is None or left.ccd_index != right.ccd_index:
                raise MethodDomainError('reference_offset_outside_ccd', '实际与理论参考线必须位于同一 CCD')
            return {'wavelength_delta_nm': actual - theory, 'point_delta': round(right.point) - round(left.point),
                    'ccd_index': left.ccd_index}

    def save_calibrated_positions(self, preview: dict, actor_user_id: int) -> dict:
        with self.database.write() as db:
            source = self.bind_snapshots(db).by_id(preview['method_version_id'], published_only=True)
            if source is None:
                raise MethodDomainError('method_version_not_found', '校正来源方法不存在')
            editor = self.bind_line_editor(db)
            draft = editor.load(source.method.id)
            if draft.payload.get('daily_calibration', {}).get('source_key') == preview['source_key']:
                return self.repository._method_dict(db, db.execute('SELECT * FROM methods WHERE id=?', (source.method.id,)).fetchone())
            previous = draft.payload.get('daily_calibration', {})
            if draft.version != source.version and not (draft.state == 'draft' and previous.get('source_version_id') == source.version_id and previous.get('saved_version') == draft.version):
                raise MethodDomainError('method_calibration_version_changed', '方法已有更新，请使用最新发布版本重新校正；现有草稿已保留', status_code=409)
            positions = {row['line_id']: row for row in preview['positions']}
            for line in draft.payload['lines']:
                row = positions.get(line['id'])
                if row is None:
                    continue
                wave = row['measured_wavelength_nm']
                if not row['found'] or abs(wave - line['wavelength_nm']) > 0.3:
                    raise MethodDomainError('method_calibration_offset_invalid', '实测波长偏移超限或没有有效峰')
                line['actual_wavelength_nm'] = wave
                if line['line_type'] == 'baseline':
                    draft.payload['conditions']['actual_reference_wavelength_nm'] = wave
            draft.payload['daily_calibration'] = {'source_key': preview['source_key'], 'run_id': preview['run_id'],
                                                 'sample_position': preview['sample_position'], 'source_version_id': source.version_id,
                                                 'mode': preview.get('mode', 'measured'), 'scope': preview.get('scope', 'all'),
                                                 'saved_version': self.repository._next_version(db, source.method.id)}
            canonical, errors = self._validate_payload(draft.payload, db)
            if errors:
                raise MethodDomainError('method_calibration_validation_failed', '校正后的方法未通过校验', details={'validation_errors': errors})
            draft.payload = canonical
            return editor.save(draft, actor_user_id, 'method.daily_calibration.save', None, draft.payload['daily_calibration'])

    def upgrade_legacy_semantics(self, method_id: int, expected_hash: str, source: dict, source_hash: str, actor: int) -> dict:
        with self.database.write() as db:
            latest = self.bind_snapshots(db).for_print(method_id)
            if latest.content_sha256 != expected_hash:
                raise MethodDomainError('legacy_method_changed', '方法已更新，请刷新后重试', status_code=409)
            editor = self.bind_line_editor(db)
            draft = editor.load(method_id)
            if draft.payload.get('legacy_migration', {}).get('semantics_revision') == 'spec-gap-20261008':
                return self.repository._method_dict(db, db.execute('SELECT * FROM methods WHERE id=?', (method_id,)).fetchone())
            conditions = draft.payload['conditions']
            for key in ('legacy_exposure_mode', 'legacy_exposure_interval'):
                conditions.setdefault(key, source['conditions'][key])
            original_lines = {line['id']: line for line in source['lines']}
            for line in draft.payload['lines']:
                raw = original_lines.get(line['id'])
                if raw and line['element'] == raw['element'] and abs(line['wavelength_nm'] - raw['wavelength_nm']) < 1e-7:
                    for key in ('exposure_start_frame', 'exposure_end_frame'):
                        line.setdefault(key, raw[key])
            draft.payload['legacy_migration'].update(evidence=source['evidence'], modified_at=source['modified_at'], semantics_revision='spec-gap-20261008')
            from .legacy_values import legacy_payload
            draft.payload = legacy_payload(draft.payload)
            canonical, errors = self._validate_payload(draft.payload, db)
            if errors:
                raise MethodDomainError('legacy_method_upgrade_invalid', '补全后的方法未通过校验，原版本已保留', details={'validation_errors': errors})
            draft.payload = canonical
            return editor.save(draft, actor, 'method.legacy_semantics.upgrade', None, {'source_sha256': source_hash})

    def bind_geometry(self, connection: sqlite3.Connection, conditions: dict[str, Any]) -> MethodLineLocator:
        """使用调用方事务读取方法几何快照，不另开连接或提交。"""
        layout = self.repository._layout(connection, conditions.get("ccd_layout_id", "default"))
        dispersion = self.repository._dispersion(connection, conditions.get("dispersion_calibration_id", "default"))
        if layout is None or dispersion is None:
            raise MethodDomainError("method_geometry_missing", "方法引用的 CCD 布局或色散校准不存在")
        return MethodLineLocator(layout, dispersion, self.geometry)

    def _canonical_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        from ..spectral_lines import canonical_lines

        from .legacy_values import legacy_payload
        result = legacy_payload(payload)
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
        errors.extend(validate_spectral_lines(self, db, canonical["conditions"], canonical["lines"]))
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
        if conditions.get('exposure_mode') is None:
            conditions['exposure_mode'] = 'line_interval' if conditions.get('legacy_exposure_mode') else 'simple_mean'
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
            version, errors = self._insert_payload_draft(db, method_id, {"conditions": conditions}, actor_user_id, now)
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
            return self._update_in_transaction(db, method_id, payload, actor_user_id)

    def _update_in_transaction(
        self, db: sqlite3.Connection, method_id: int, payload: MethodUpdate, actor_user_id: int
    ) -> dict[str, Any]:
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
                self.repository._audit(db, actor_id, "method.rename", method_id, {"from": row["name"], "to": name})
        metadata: dict[str, Any] = {}
        if payload.description is not None:
            metadata["description"] = payload.description.strip()
        if payload.work_type is not None:
            work_type = payload.work_type.strip()
            if not work_type:
                raise MethodDomainError("work_type_required", "工作类型不能为空", fields=["work_type"])
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
                json.loads(latest["payload_json"]) if latest else {"conditions": deepcopy(DEFAULT_CONDITIONS)}
            )
            from .legacy_values import legacy_payload
            latest_payload = legacy_payload(latest_payload, db, method_id)
            current = latest_payload.get("conditions", {})
            conditions = _normalize_conditions(current, payload.conditions)
            # 一次草稿事务内换算谱线，标准强度和已发布版本保持原样。
            unit_changes = []
            if conditions.get("analysis_unit") != current.get("analysis_unit"):
                for index, line in enumerate(latest_payload.get("lines", [])):
                    converted = convert_line_unit(line, conditions.get("analysis_unit", ""))
                    if converted.get("unit") != line.get("unit"):
                        unit_changes.append({"line_id": line.get("id"), "from": line.get("unit"), "to": converted["unit"]})
                    latest_payload["lines"][index] = converted
            latest_payload["conditions"] = conditions
            version, errors = self._insert_payload_draft(db, method_id, latest_payload, actor_user_id, now)
            db.execute("UPDATE methods SET updated_at=? WHERE id=?", (now, method_id))
            self.repository._audit(
                db,
                actor_id,
                "method.update",
                method_id,
                {"version": version, "validation_issue_count": len(errors), "unit_changes": unit_changes},
            )
        row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
        current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
        return self.repository._method_dict(db, row, current_id=current[0] if current else None)

    def publish(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            return self._publish_in_transaction(db, method_id, actor_user_id)

    def _publish_in_transaction(
        self, db: sqlite3.Connection, method_id: int, actor_user_id: int
    ) -> dict[str, Any]:
        row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
        if row is None or row["status"] == "deleted":
            raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
        latest = self.repository._latest_row(db, method_id)
        if latest is None or latest["state"] != "draft":
            raise MethodDomainError("method_draft_missing", "没有待发布的方法草稿", status_code=409)
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

    def save(self, method_id: int, payload: MethodSave, actor_user_id: int) -> dict[str, Any]:
        """Validate and publish the edited method in one rollback boundary."""
        with self.database.write() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            if row is None or row["status"] == "deleted":
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            latest = self.repository._latest_row(db, method_id)
            if payload.expected_latest_version is not None and (
                latest is None or latest["version"] != payload.expected_latest_version
            ):
                raise MethodDomainError(
                    "method_version_changed", "方法已有更新，本次未保存；请先保留输入并刷新核对", status_code=409
                )
            try:
                updated = self._update_in_transaction(db, method_id, payload, actor_user_id)
                latest = self.repository._latest_row(db, method_id)
                if latest is not None and latest["state"] == "published":
                    return updated
                return self._publish_in_transaction(db, method_id, actor_user_id)
            except MethodDomainError as exc:
                if exc.code != "invalid_method_draft":
                    raise
                errors = exc.details.get("validation_errors", [])
                message = errors[0]["message"] if errors else "方法条件或谱线未通过校验"
                raise MethodDomainError(
                    "invalid_method_save", f"方法未保存：{message}", fields=exc.fields, details=exc.details
                ) from exc

    def copy(self, method_id: int, name: str, actor_user_id: int) -> dict[str, Any]:
        name = validate_method_name(name)
        with self.database.write() as db:
            source = db.execute("SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)).fetchone()
            if source is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            if self.repository._duplicate_name(db, name):
                raise MethodDomainError("method_name_exists", "方法名称已存在", status_code=409)
            latest = self.repository._latest_row(db, method_id)
            source_payload = (
                json.loads(latest["payload_json"]) if latest else {"conditions": deepcopy(DEFAULT_CONDITIONS)}
            )
            now = utc_now()
            cursor = db.execute(
                "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) "
                "VALUES (?, ?, ?, 'active', NULL, ?, ?)",
                (name, source["description"], source["work_type"], now, now),
            )
            new_id = int(cursor.lastrowid)
            version, errors = self._insert_payload_draft(db, new_id, deepcopy(source_payload), actor_user_id, now)
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

    def _reference_position(
        self, wave: float, layout: sqlite3.Row, dispersion: sqlite3.Row
    ) -> tuple[int, float, bool] | None:
        return self.geometry._reference_position(wave, layout, dispersion)

    _valid_actor = staticmethod(MethodRepository._valid_actor)

    _next_version = staticmethod(MethodRepository._next_version)

    _latest_row = staticmethod(MethodRepository._latest_row)

    _published_row = staticmethod(MethodRepository._published_row)

    _layout = staticmethod(MethodRepository._layout)

    _dispersion = staticmethod(MethodRepository._dispersion)

    _version_dict = staticmethod(MethodRepository._version_dict)

    def _method_dict(
        self, db: sqlite3.Connection, row: sqlite3.Row, *, current_id: int | None = None
    ) -> dict[str, Any]:
        return self.repository._method_dict(db, row, current_id=current_id)

    _duplicate_name = staticmethod(MethodRepository._duplicate_name)

    def list(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        return self.repository.list(include_deleted=include_deleted)

    def get(self, method_id: int, *, include_deleted: bool = False) -> dict[str, Any]:
        return self.repository.get(method_id, include_deleted=include_deleted)

    def versions(self, method_id: int) -> list[dict[str, Any]]:
        return self.repository.versions(method_id)

    def _calibration_option(self, layout: sqlite3.Row, calibration: sqlite3.Row) -> dict[str, Any]:
        return self.repository._calibration_option(layout, calibration)

    def options(self) -> dict[str, Any]:
        return self.repository.options()

    _audit = staticmethod(MethodRepository._audit)

    _issue = staticmethod(MethodValidator._issue)

    def validate_conditions(
        self, conditions: dict[str, Any], db: sqlite3.Connection | None = None
    ) -> list[dict[str, str]]:
        return self.validation.validate_conditions(conditions, db)

    def open(self, method_id: int, actor_user_id: int, *, resume_paused: bool = False) -> dict[str, Any]:
        return self.runtime.open(method_id, actor_user_id, resume_paused=resume_paused)

    def pause(self, method_id: int, actor_user_id: int, *, paused: bool = True) -> dict[str, Any]:
        return self.runtime.pause(method_id, actor_user_id, paused=paused)

    def delete(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        return self.runtime.delete(method_id, actor_user_id)

    def current(self) -> dict[str, Any]:
        return self.runtime.current()
