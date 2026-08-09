from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from copy import deepcopy
from typing import Any

from ..db import Database, utc_now
from ..schemas import MethodCondition, MethodCreate, MethodUpdate


NAME_MAX_GB18030_BYTES = 20
METHOD_NAME_INVALID = set(r"\/:*?<>|")
DEFAULT_CONDITIONS = MethodCondition().model_dump(mode="json")


class MethodDomainError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        fields: list[str] | None = None,
        details: dict[str, Any] | None = None,
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or []
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_errors": self.fields,
            "details": self.details,
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _condition_patch(value: MethodCondition | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, MethodCondition):
        return value.model_dump(mode="json", exclude_unset=True)
    return deepcopy(value)


def _normalize_conditions(
    base: dict[str, Any], value: MethodCondition | dict[str, Any] | None
) -> dict[str, Any]:
    """Merge a draft patch while accepting names emitted by the abandoned S03 draft."""

    patch = _condition_patch(value)
    aliases = {
        "ccd_layout": "ccd_layout_id",
        "dispersion_reference": "dispersion_calibration_id",
        "real_reference_wavelength_nm": "actual_reference_wavelength_nm",
        "burn_cycle_seconds": "sampling_period_seconds",
        "dark_frames": "dark_frame_count",
        "standard_sample": "standard_sample_name",
        "id_threshold": "maximum_id_deviation",
    }
    for old, new in aliases.items():
        if old in patch and new not in patch:
            patch[new] = patch[old]
    if "repetition_count" in patch and "sample_repeats" not in patch:
        patch["sample_repeats"] = patch["repetition_count"]
    if "repeats" in patch and "sample_repeats" not in patch:
        patch["sample_repeats"] = patch["repeats"]
    if "ccd" in patch and "selected_ccds" not in patch:
        ccd = str(patch["ccd"]).upper().removeprefix("CCD")
        if ccd.isdigit():
            patch["selected_ccds"] = [int(ccd) - 1]
    if "line_width_nm" in patch and "reference_width_points" not in patch:
        width = patch["line_width_nm"]
        if isinstance(width, (int, float)) and width >= 11:
            patch["reference_width_points"] = width
    if "exposure_intervals" in patch and "angle_exposures" not in patch:
        intervals = patch["exposure_intervals"]
        if isinstance(intervals, list):
            patch["angle_exposures"] = [
                {
                    "angle_deg": item.get("angle_deg", item.get("angle", index)),
                    "storage_mode": {
                        "average": "averaged",
                        "full": "full_interval",
                    }.get(item.get("mode"), item.get("mode", "averaged")),
                    "start_frame": item.get("start", 1),
                    "end_frame": item.get("end", patch.get("frame_count", base.get("frame_count", 20))),
                }
                for index, item in enumerate(intervals)
                if isinstance(item, dict)
            ]

    merged = deepcopy(DEFAULT_CONDITIONS)
    merged.update(deepcopy(base))
    merged.update(patch)
    merged["storage_profile"] = "modern_v1"
    return merged


def validate_method_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise MethodDomainError("method_name_required", "方法名称不能为空", fields=["name"])
    try:
        byte_length = len(value.encode("gb18030"))
    except UnicodeEncodeError as exc:
        raise MethodDomainError(
            "method_name_encoding", "方法名称无法使用 GB18030 编码", fields=["name"]
        ) from exc
    if byte_length > NAME_MAX_GB18030_BYTES:
        raise MethodDomainError(
            "method_name_too_long",
            f"方法名称 GB18030 字节长度不能大于 {NAME_MAX_GB18030_BYTES}",
            fields=["name"],
            details={"gb18030_bytes": byte_length, "maximum": NAME_MAX_GB18030_BYTES},
        )
    if any(char in METHOD_NAME_INVALID for char in value):
        raise MethodDomainError(
            "method_name_invalid_character",
            "方法名称不能含有 \\ / : * ? < > |",
            fields=["name"],
        )
    return value


class MethodService:
    """Application service for method lifecycle and immutable revisions."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _issue(field: str, code: str, message: str) -> dict[str, str]:
        return {"field": field, "code": code, "message": message}

    @staticmethod
    def _valid_actor(db: sqlite3.Connection, actor_user_id: int | None) -> int | None:
        if actor_user_id is None:
            return None
        row = db.execute("SELECT 1 FROM users WHERE id=?", (actor_user_id,)).fetchone()
        return actor_user_id if row else None

    @staticmethod
    def _next_version(db: sqlite3.Connection, method_id: int) -> int:
        row = db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM method_versions WHERE method_id=?",
            (method_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _latest_row(db: sqlite3.Connection, method_id: int) -> sqlite3.Row | None:
        return db.execute(
            "SELECT * FROM method_versions WHERE method_id=? ORDER BY version DESC LIMIT 1",
            (method_id,),
        ).fetchone()

    @staticmethod
    def _published_row(
        db: sqlite3.Connection, method_id: int, version: int | None = None
    ) -> sqlite3.Row | None:
        if version is not None:
            return db.execute(
                "SELECT * FROM method_versions WHERE method_id=? AND version=? AND state='published'",
                (method_id, version),
            ).fetchone()
        return db.execute(
            "SELECT * FROM method_versions WHERE method_id=? AND state='published' ORDER BY version DESC LIMIT 1",
            (method_id,),
        ).fetchone()

    @staticmethod
    def _layout(db: sqlite3.Connection, reference: str | int) -> sqlite3.Row | None:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            return db.execute("SELECT * FROM ccd_layouts WHERE id=?", (int(reference),)).fetchone()
        return db.execute("SELECT * FROM ccd_layouts WHERE name=?", (str(reference),)).fetchone()

    @staticmethod
    def _dispersion(db: sqlite3.Connection, reference: str | int) -> sqlite3.Row | None:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            return db.execute(
                "SELECT * FROM dispersion_calibrations WHERE id=? AND enabled=1", (int(reference),)
            ).fetchone()
        return db.execute(
            "SELECT * FROM dispersion_calibrations WHERE name=? AND enabled=1", (str(reference),)
        ).fetchone()

    @staticmethod
    def _layout_geometry(layout: sqlite3.Row) -> list[dict[str, float | int]]:
        indices = [int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")]
        gaps = [float(value) for value in json.loads(layout["gap_points_json"] or "[]")]
        points = int(layout["points_per_ccd"])
        result: list[dict[str, float | int]] = []
        for ccd_index in indices:
            left = ccd_index * points + sum(gaps[:ccd_index])
            result.append(
                {
                    "ccd_index": ccd_index,
                    "left_step": left,
                    "right_step": left + points - 1,
                }
            )
        return result

    @staticmethod
    def _wave_to_step(wave: float, coefficients: list[float]) -> float:
        if len(coefficients) < 3:
            raise ValueError("dispersion coefficients are incomplete")
        a, b, c = coefficients[:3]
        return wave * (a * wave + b) + c

    @staticmethod
    def _step_to_wave(step: float, coefficients: list[float]) -> float:
        a, b, c = coefficients[:3]
        if math.isclose(a, 0.0):
            if math.isclose(b, 0.0):
                raise ValueError("dispersion coefficients are invalid")
            return (step - c) / b
        discriminant = b * b - 4.0 * a * (c - step)
        if discriminant < 0:
            raise ValueError("dispersion step is outside the calibrated domain")
        return (math.sqrt(discriminant) - b) / (2.0 * a)

    def _reference_position(
        self, wave: float, layout: sqlite3.Row, dispersion: sqlite3.Row
    ) -> tuple[int, float, bool] | None:
        coefficients = [float(value) for value in json.loads(dispersion["coefficients_json"] or "[]")]
        try:
            step = self._wave_to_step(wave, coefficients)
        except ValueError:
            return None
        margin = 2.0 * float(layout["allow_drift_um"]) / float(layout["point_width"])
        for item in self._layout_geometry(layout):
            left = float(item["left_step"])
            right = float(item["right_step"])
            if left <= step <= right:
                return int(item["ccd_index"]), step - left, left + margin <= step <= right - margin
        return None

    def validate_conditions(
        self, conditions: dict[str, Any], db: sqlite3.Connection | None = None
    ) -> list[dict[str, str]]:
        if db is None:
            with self.database.read() as connection:
                return self.validate_conditions(conditions, connection)

        errors: list[dict[str, str]] = []

        def add(field: str, code: str, message: str) -> None:
            errors.append(self._issue(field, code, message))

        def number(
            field: str,
            minimum: float | None = None,
            maximum: float | None = None,
            *,
            integer: bool = False,
        ) -> float | None:
            value = conditions.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                add(field, "number_required", "必须是有限数字")
                return None
            numeric = float(value)
            if integer and not numeric.is_integer():
                add(field, "integer_required", "必须是整数")
            if minimum is not None and numeric < minimum:
                add(field, "below_minimum", f"不能小于 {minimum:g}")
            if maximum is not None and numeric > maximum:
                add(field, "above_maximum", f"不能大于 {maximum:g}")
            return numeric

        layout_reference = conditions.get("ccd_layout_id", "default")
        layout = self._layout(db, layout_reference)
        if layout is None:
            add("ccd_layout_id", "ccd_layout_not_found", "未找到 CCD 布局")

        selected = conditions.get("selected_ccds")
        selected_ccds: list[int] = []
        if not isinstance(selected, list) or not selected:
            add("selected_ccds", "ccd_selection_required", "至少选择一个 CCD")
        elif any(isinstance(value, bool) or not isinstance(value, int) for value in selected):
            add("selected_ccds", "ccd_selection_invalid", "CCD 编号必须是整数")
        else:
            selected_ccds = [int(value) for value in selected]
            if len(selected_ccds) != len(set(selected_ccds)):
                add("selected_ccds", "ccd_selection_duplicate", "CCD 不能重复选择")
            if layout is not None:
                available = {int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")}
                if not set(selected_ccds).issubset(available):
                    add("selected_ccds", "ccd_not_installed", "选择中包含未安装的 CCD")

        dispersion_reference = conditions.get("dispersion_calibration_id", "default")
        dispersion = self._dispersion(db, dispersion_reference)
        if dispersion is None:
            add("dispersion_calibration_id", "dispersion_not_found", "未找到已启用的色散引用")
        elif layout is not None and int(dispersion["ccd_layout_id"]) != int(layout["id"]):
            add(
                "dispersion_calibration_id",
                "dispersion_layout_mismatch",
                "色散引用与 CCD 布局不匹配",
            )

        reference = number("reference_wavelength_nm", 160, 800)
        actual = number("actual_reference_wavelength_nm", 160, 800)
        if reference is not None and actual is not None and abs(actual - reference) > 0.3:
            add(
                "actual_reference_wavelength_nm",
                "reference_offset_too_large",
                "实际参考波长与理论值的偏差不能大于 0.3 nm",
            )
        if layout is not None and dispersion is not None and int(dispersion["ccd_layout_id"]) == int(layout["id"]):
            reference_positions: dict[str, tuple[int, float, bool] | None] = {}
            for field, wave in (
                ("reference_wavelength_nm", reference),
                ("actual_reference_wavelength_nm", actual),
            ):
                if wave is None:
                    continue
                position = self._reference_position(wave, layout, dispersion)
                reference_positions[field] = position
                if position is None:
                    add(field, "reference_not_on_ccd", "参考波长不在当前 CCD/色散覆盖范围内")
                elif position[0] not in selected_ccds:
                    add(field, "reference_ccd_not_selected", f"参考波长位于 CCD{position[0] + 1}，但该 CCD 未选中")
                elif not position[2]:
                    add(field, "reference_outside_safe_boundary", "参考波长超出 CCD 安全边界")
            theoretical = reference_positions.get("reference_wavelength_nm")
            measured = reference_positions.get("actual_reference_wavelength_nm")
            if theoretical and measured and theoretical[0] != measured[0]:
                add(
                    "actual_reference_wavelength_nm",
                    "reference_ccd_changed",
                    "理论与实际参考波长必须位于同一 CCD",
                )

        number("reference_width_points", 11, 50, integer=True)
        if conditions.get("analysis_unit") not in {"ug/g", "mg/g", "%"}:
            add("analysis_unit", "analysis_unit_invalid", "分析单位只能是 ug/g、mg/g 或 %")
        number("pre_excitation_seconds", 1, 10)
        number("sampling_period_seconds", 1, 2)
        frame_count = number("frame_count", 1, 255, integer=True)
        number("dark_frame_count", 0, 20, integer=True)
        for field in ("sample_repeats", "standard_repeats", "control_repeats"):
            number(field, 1, 10, integer=True)
        number("maximum_id_deviation", 0, 20)
        if not isinstance(conditions.get("rsd_enabled"), bool):
            add("rsd_enabled", "boolean_required", "必须是布尔值")
        number("rsd_threshold", 0, 20)
        for field in ("calibration_threshold", "qc_threshold", "abnormal_threshold"):
            number(field, 0, 100)
        sample_name = conditions.get("standard_sample_name")
        if not isinstance(sample_name, str) or len(sample_name) > 100:
            add("standard_sample_name", "standard_sample_invalid", "标准样品名称不能超过 100 个字符")

        exposures = conditions.get("angle_exposures")
        if not isinstance(exposures, list) or not exposures:
            add("angle_exposures", "angle_exposure_required", "至少配置一个转角曝光区间")
        else:
            seen_angles: set[float] = set()
            for index, exposure in enumerate(exposures):
                prefix = f"angle_exposures.{index}"
                if not isinstance(exposure, dict):
                    add(prefix, "angle_exposure_invalid", "转角曝光配置必须是对象")
                    continue
                angle = exposure.get("angle_deg")
                if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(float(angle)):
                    add(f"{prefix}.angle_deg", "angle_invalid", "转角必须是有限数字")
                elif not 0 <= float(angle) <= 360:
                    add(f"{prefix}.angle_deg", "angle_out_of_range", "转角必须在 0–360° 范围内")
                elif float(angle) in seen_angles:
                    add(f"{prefix}.angle_deg", "angle_duplicate", "同一转角只能配置一次")
                else:
                    seen_angles.add(float(angle))
                if exposure.get("storage_mode") not in {"averaged", "full_interval"}:
                    add(
                        f"{prefix}.storage_mode",
                        "storage_mode_invalid",
                        "保存方式只能是区间平均或全区间保存",
                    )
                start = exposure.get("start_frame")
                end = exposure.get("end_frame")
                if isinstance(start, bool) or not isinstance(start, int):
                    add(f"{prefix}.start_frame", "integer_required", "起始帧必须是整数")
                if isinstance(end, bool) or not isinstance(end, int):
                    add(f"{prefix}.end_frame", "integer_required", "结束帧必须是整数")
                if isinstance(start, int) and not isinstance(start, bool) and isinstance(end, int) and not isinstance(end, bool):
                    if start < 1:
                        add(f"{prefix}.start_frame", "frame_out_of_range", "起始帧不能小于 1")
                    if frame_count is not None and end > int(frame_count):
                        add(f"{prefix}.end_frame", "frame_out_of_range", "结束帧不能超过采样帧数")
                    if end - start + 1 < 2:
                        add(prefix, "exposure_too_short", "曝光区间必须至少包含两帧")
        return errors

    @staticmethod
    def _version_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        from .spectral_lines import canonical_lines

        payload = json.loads(row["payload_json"])
        conditions = payload.get("conditions", {})
        return {
            "id": row["id"],
            "version": row["version"],
            "state": row["state"],
            "conditions": conditions,
            "lines": canonical_lines(payload.get("lines"), conditions),
            "validation_errors": json.loads(row["validation_errors_json"] or "[]"),
            "content_sha256": hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest(),
            "created_at": row["created_at"],
        }

    def _method_dict(
        self, db: sqlite3.Connection, row: sqlite3.Row, *, current_id: int | None = None
    ) -> dict[str, Any]:
        latest = self._latest_row(db, int(row["id"]))
        published = self._published_row(db, int(row["id"]), row["current_version"])
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "work_type": row["work_type"],
            "status": row["status"],
            "current_version": row["current_version"],
            "latest_version": latest["version"] if latest else None,
            "version": self._version_dict(latest),
            "published_version": self._version_dict(published),
            "is_current": current_id == row["id"] if current_id is not None else False,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _duplicate_name(db: sqlite3.Connection, name: str, exclude_id: int | None = None) -> bool:
        if exclude_id is None:
            row = db.execute("SELECT 1 FROM methods WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        else:
            row = db.execute(
                "SELECT 1 FROM methods WHERE name=? COLLATE NOCASE AND id<>?", (name, exclude_id)
            ).fetchone()
        return row is not None

    def list(self, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        with self.database.read() as db:
            state = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            current_id = state[0] if state else None
            where = "" if include_deleted else " WHERE status <> 'deleted'"
            rows = db.execute(
                f"SELECT * FROM methods{where} ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
            return [self._method_dict(db, row, current_id=current_id) for row in rows]

    def get(self, method_id: int, *, include_deleted: bool = False) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            if row is None or (row["status"] == "deleted" and not include_deleted):
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            state = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self._method_dict(db, row, current_id=state[0] if state else None)

    def _canonical_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        from .spectral_lines import canonical_lines

        result = deepcopy(payload)
        conditions = result.get("conditions", deepcopy(DEFAULT_CONDITIONS))
        result["conditions"] = conditions
        result["lines"] = canonical_lines(result.get("lines"), conditions)
        result["payload_schema"] = "method-v2-lines"
        return result

    def _validate_payload(
        self, payload: dict[str, Any], db: sqlite3.Connection
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        from .spectral_lines import validate_spectral_lines

        canonical = self._canonical_payload(payload)
        errors = self.validate_conditions(canonical["conditions"], db)
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
        version = self._next_version(db, method_id)
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
                self._valid_actor(db, actor_user_id),
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
            if self._duplicate_name(db, name):
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
            self._audit(
                db,
                self._valid_actor(db, actor_user_id),
                "method.create",
                method_id,
                {"name": name, "version": version, "validation_issue_count": len(errors)},
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            return self._method_dict(db, row)

    def update(self, method_id: int, payload: MethodUpdate, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            if row is None or row["status"] == "deleted":
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            now = utc_now()
            actor_id = self._valid_actor(db, actor_user_id)
            if payload.name is not None:
                name = validate_method_name(payload.name)
                if self._duplicate_name(db, name, method_id):
                    raise MethodDomainError("method_name_exists", "方法名称已存在", status_code=409)
                if name != row["name"]:
                    db.execute("UPDATE methods SET name=?, updated_at=? WHERE id=?", (name, now, method_id))
                    self._audit(
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
                self._audit(db, actor_id, "method.metadata.update", method_id, metadata)
            if payload.conditions is not None:
                latest = self._latest_row(db, method_id)
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
                self._audit(
                    db,
                    actor_id,
                    "method.update",
                    method_id,
                    {"version": version, "validation_issue_count": len(errors)},
                )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self._method_dict(db, row, current_id=current[0] if current else None)

    def publish(self, method_id: int, actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            if row is None or row["status"] == "deleted":
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            latest = self._latest_row(db, method_id)
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
            version = self._next_version(db, method_id)
            now = utc_now()
            actor_id = self._valid_actor(db, actor_user_id)
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
            self._audit(db, actor_id, "method.publish", method_id, {"version": version})
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self._method_dict(db, row, current_id=current[0] if current else None)

    def copy(self, method_id: int, name: str, actor_user_id: int) -> dict[str, Any]:
        name = validate_method_name(name)
        with self.database.write() as db:
            source = db.execute(
                "SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)
            ).fetchone()
            if source is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            if self._duplicate_name(db, name):
                raise MethodDomainError("method_name_exists", "方法名称已存在", status_code=409)
            latest = self._latest_row(db, method_id)
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
            self._audit(
                db,
                self._valid_actor(db, actor_user_id),
                "method.copy",
                new_id,
                {
                    "source_method_id": method_id,
                    "version": version,
                    "validation_issue_count": len(errors),
                },
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (new_id,)).fetchone()
            return self._method_dict(db, row)

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
            self._audit(
                db,
                self._valid_actor(db, actor_user_id),
                "method.open",
                method_id,
                {"version": row["current_version"]},
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            return self._method_dict(db, row, current_id=method_id)

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
            self._audit(
                db,
                self._valid_actor(db, actor_user_id),
                "method.pause" if paused else "method.resume",
                method_id,
                {"status": status},
            )
            row = db.execute("SELECT * FROM methods WHERE id=?", (method_id,)).fetchone()
            current = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
            return self._method_dict(db, row, current_id=current[0] if current else None)

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
            self._audit(
                db,
                self._valid_actor(db, actor_user_id),
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
            referenced = self._published_row(db, int(row["id"]), state["current_version"]) if row else None
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
                "method": self._method_dict(db, row, current_id=row["id"]),
                "referenced_version": self._version_dict(referenced),
            }

    def versions(self, method_id: int) -> list[dict[str, Any]]:
        with self.database.read() as db:
            if not db.execute("SELECT 1 FROM methods WHERE id=?", (method_id,)).fetchone():
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            rows = db.execute(
                "SELECT * FROM method_versions WHERE method_id=? ORDER BY version DESC", (method_id,)
            ).fetchall()
            return [self._version_dict(row) for row in rows if row is not None]

    def _calibration_option(
        self, layout: sqlite3.Row, calibration: sqlite3.Row
    ) -> dict[str, Any]:
        coefficients = [float(value) for value in json.loads(calibration["coefficients_json"] or "[]")]
        margin = 2.0 * float(layout["allow_drift_um"]) / float(layout["point_width"])
        ranges: list[dict[str, Any]] = []
        for item in self._layout_geometry(layout):
            left = float(item["left_step"])
            right = float(item["right_step"])
            try:
                ranges.append(
                    {
                        "ccd_index": int(item["ccd_index"]),
                        "wavelength_start_nm": self._step_to_wave(left, coefficients),
                        "wavelength_end_nm": self._step_to_wave(right, coefficients),
                        "safe_start_nm": self._step_to_wave(left + margin, coefficients),
                        "safe_end_nm": self._step_to_wave(right - margin, coefficients),
                    }
                )
            except ValueError:
                continue
        return {
            "id": calibration["id"],
            "name": calibration["name"],
            "ccd_layout_id": calibration["ccd_layout_id"],
            "wavelength_min": calibration["wavelength_min"],
            "wavelength_max": calibration["wavelength_max"],
            "enabled": bool(calibration["enabled"]),
            "ccd_ranges": ranges,
        }

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            layouts: list[dict[str, Any]] = []
            layout_rows = db.execute("SELECT * FROM ccd_layouts ORDER BY name").fetchall()
            layout_map = {int(row["id"]): row for row in layout_rows}
            for row in layout_rows:
                indices = [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]
                layouts.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "frame_count": row["frame_count"],
                        "ccds_per_frame": row["ccds_per_frame"],
                        "points_per_ccd": row["points_per_ccd"],
                        "point_width_um": row["point_width"],
                        "allow_drift_um": row["allow_drift_um"],
                        "ccd_indices": indices,
                        "ccd_labels": [f"CCD{index + 1}" for index in indices],
                    }
                )
            calibrations = []
            rows = db.execute(
                "SELECT * FROM dispersion_calibrations WHERE enabled=1 ORDER BY name"
            ).fetchall()
            for row in rows:
                layout = layout_map.get(int(row["ccd_layout_id"]))
                if layout is not None:
                    calibrations.append(self._calibration_option(layout, row))
            return {
                "ccd_layouts": layouts,
                "dispersion_calibrations": calibrations,
                "storage_modes": [
                    {"value": "averaged", "label": "区间平均"},
                    {"value": "full_interval", "label": "全区间保存"},
                ],
                "limits": {
                    "name_gb18030_bytes": 20,
                    "pre_excitation_seconds": [1, 10],
                    "sampling_period_seconds": [1, 2],
                    "frame_count": [1, 255],
                    "dark_frame_count": [0, 20],
                    "repeats": [1, 10],
                    "reference_width_points": [11, 50],
                    "maximum_id_deviation": [0, 20],
                    "rsd_threshold": [0, 20],
                },
            }

    @staticmethod
    def _audit(
        db: sqlite3.Connection,
        actor_user_id: int | None,
        action: str,
        target_id: int,
        details: dict[str, Any],
    ) -> None:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
            "VALUES (?, ?, 'method', ?, ?, ?)",
            (actor_user_id, action, target_id, _json(details), utc_now()),
        )
