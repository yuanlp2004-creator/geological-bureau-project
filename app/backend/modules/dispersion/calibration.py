from __future__ import annotations
import json
import math
import sqlite3
from typing import Any
from ...db import Database, utc_now
from .codec import _unpack_points
from .fitting import _evaluate, _fit_polynomial
from .repository import DispersionRepository
from .values import DispersionError, _finite, _json


class CalibrationService:
    def __init__(self, database: Database):
        self.database = database
        self.repository = DispersionRepository(database)

    def _insert_line(
        self, db: sqlite3.Connection, task_id: int, layout: sqlite3.Row, payload: dict[str, Any], now: str | None = None
    ) -> int:
        element = str(payload.get("element", "")).strip()
        wavelength = _finite(payload.get("wavelength_nm"), "wavelength_nm")
        ccd_index = int(payload.get("ccd_index", 0))
        if not element or not 1 <= len(element) <= 20:
            raise DispersionError("dispersion_line_invalid", "谱线元素不能为空或过长", details={"field": "element"})
        if wavelength < float(layout["wavelength_min"]) or wavelength > float(layout["wavelength_max"]):
            raise DispersionError(
                "line_wavelength_out_of_range",
                "谱线波长超出当前布局范围",
                details={
                    "wavelength_nm": wavelength,
                    "minimum": layout["wavelength_min"],
                    "maximum": layout["wavelength_max"],
                },
            )
        left, points = self.repository._geometry(layout, ccd_index)
        expected = self.repository._expected_position(db, layout, wavelength, ccd_index)
        actual = payload.get("actual_position")
        if actual is not None:
            actual = _finite(actual, "actual_position")
            if actual < 0 or actual > points - 1:
                raise DispersionError(
                    "line_position_out_of_range",
                    "实测位置超出 CCD 范围",
                    details={"position": actual, "points": points},
                )
        now = now or utc_now()
        duplicate = db.execute(
            (
                "SELECT id, wavelength_nm FROM dispersion_task_lines WHERE task_id=? AND "
                "ccd_index=? AND ABS(wavelength_nm - ?) <= 0.01 LIMIT 1"
            ),
            (task_id, ccd_index, wavelength),
        ).fetchone()
        if duplicate is not None:
            raise DispersionError(
                "dispersion_line_duplicate",
                "同一 CCD 中 ±0.01 nm 内不能重复添加校准谱线",
                details={"existing_line_id": duplicate["id"], "existing_wavelength_nm": duplicate["wavelength_nm"]},
                status_code=409,
            )
        try:
            cursor = db.execute(
                (
                    "INSERT INTO dispersion_task_lines(task_id, element, wavelength_nm, ccd_index, "
                    "expected_position, located_position, saved_position, position_state, "
                    "position_source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?)"
                ),
                (
                    task_id,
                    element,
                    wavelength,
                    ccd_index,
                    expected,
                    actual,
                    actual,
                    "saved" if actual is not None else "pending",
                    "manual" if actual is not None else None,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DispersionError(
                "dispersion_line_duplicate", "同一任务中不能重复添加相同 CCD 的谱线", status_code=409
            ) from exc
        return int(cursor.lastrowid)

    def add_line(self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        with self.database.write() as db:
            line_id = self._insert_line(db, task_id, context.layout, payload)
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.line.create",
                line_id,
                {
                    "task_id": task_id,
                    "wavelength_nm": payload.get("wavelength_nm"),
                    "ccd_index": payload.get("ccd_index", 0),
                },
            )
            return self.repository._line_decode(
                db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone()
            )

    def delete_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)
            ).fetchone()
            if row is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            db.execute("DELETE FROM dispersion_task_lines WHERE id=?", (line_id,))
            self.repository._audit(db, actor_user_id, "dispersion.line.delete", line_id, {"task_id": task_id})
            return {"id": line_id, "deleted": True}

    def locate_line(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        context = self.repository._context(task_id)
        with self.database.write() as db:
            line = db.execute(
                "SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)
            ).fetchone()
            if line is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            expected = line["expected_position"]
            if expected is None:
                raise DispersionError("line_wavelength_out_of_range", "谱线没有落入当前 CCD 的有效范围")
            frames = db.execute(
                (
                    "SELECT * FROM dispersion_task_frames WHERE task_id=? AND "
                    "ccd_index=? ORDER BY phase, frame_index, id"
                ),
                (task_id, line["ccd_index"]),
            ).fetchall()
            burns = [frame for frame in frames if frame['phase'] == 'burn']
            if not burns:
                raise DispersionError("dispersion_frames_missing", "至少采集一帧燃烧帧后才能定位谱线", status_code=409)
            ignition = json.loads(context.task['condition_json'] or '{}').get('ignition', {})
            burn_period = float(ignition.get('burn_cyc') or context.task['sampling_period_seconds'])
            dark_period = float(ignition.get('dark_cyc') or context.task['sampling_period_seconds'])
            if not all(math.isfinite(value) and value>0 for value in (burn_period,dark_period)):
                raise DispersionError('dispersion_condition_invalid','原始谱带采样周期无效')
            points = [0.0] * int(context.layout['points_per_ccd'])
            darks = [frame for frame in frames if frame['phase'] == 'dark']
            for frame in frames:
                values = _unpack_points(frame['points_blob'], int(frame['points_count']), frame['points_sha256'], frame['compression'])
                if len(values) != len(points):
                    raise DispersionError('dispersion_frame_shape_invalid', '原始帧长度与 CCD 布局不一致')
                scale = 1 / (len(burns) * burn_period) if frame['phase'] == 'burn' else -1 / (len(darks) * dark_period)
                for index, value in enumerate(values):
                    points[index] += value * scale
            frame = burns[-1]
            # uCcdBand.CalMinAvgs floors the dark-subtracted average at LowAvg=0.1.
            points = [max(0.1,value) for value in points]
            start = max(0, int(round(expected)) - 24)
            end = min(len(points), int(round(expected)) + 25)
            if start >= end:
                raise DispersionError("line_position_out_of_range", "定位窗口超出 CCD 范围")
            peak = max(range(start, end), key=lambda index: points[index])
            adjustment = float(line["adjustment_points"] or 0)
            located = max(0.0, min(len(points) - 1.0, float(peak) + adjustment))
            db.execute(
                (
                    "UPDATE dispersion_task_lines SET located_position=?, position_state='located', "
                    "position_source='frame', position_frame_id=?, updated_at=? WHERE id=?"
                ),
                (located, frame["id"], utc_now(), line_id),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.line.locate",
                line_id,
                {"task_id": task_id, "frame_ids": [frame['id'] for frame in frames], "position": located,
                 "source": "normalized_mean_minus_dark", "burn_period": burn_period, "dark_period": dark_period},
            )
            return self.repository._line_decode(
                db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone()
            )

    def locate_all(self, task_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        self.repository._context(task_id)
        with self.database.read() as db:
            line_ids = [
                int(row[0])
                for row in db.execute(
                    "SELECT id FROM dispersion_task_lines WHERE task_id=? ORDER BY id", (task_id,)
                ).fetchall()
            ]
        located: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for line_id in line_ids:
            try:
                located.append(self.locate_line(task_id, line_id, actor_user_id))
            except DispersionError as exc:
                errors.append({"line_id": line_id, **exc.detail()})
        return {"task_id": task_id, "located": located, "errors": errors, "all_succeeded": not errors}

    def update_line_wavelength(self, task_id: int, line_id: int, wavelength: float, actor=None) -> dict[str, Any]:
        with self.database.write() as db:
            context = self.repository._context(task_id, db)
            line = db.execute('SELECT * FROM dispersion_task_lines WHERE task_id=? AND id=?', (task_id,line_id)).fetchone()
            if line is None:
                raise DispersionError('dispersion_line_not_found', '任务谱线不存在', status_code=404)
            wavelength = _finite(wavelength, 'wavelength_nm')
            if not context.layout['wavelength_min'] <= wavelength <= context.layout['wavelength_max']:
                raise DispersionError('line_wavelength_out_of_range', '谱线波长超出当前布局范围')
            if db.execute('SELECT 1 FROM dispersion_task_lines WHERE task_id=? AND ccd_index=? AND id!=? AND ABS(wavelength_nm-?)<=0.01',
                          (task_id,line['ccd_index'],line_id,wavelength)).fetchone():
                raise DispersionError('dispersion_line_duplicate', '同一 CCD 中 ±0.01 nm 内不能重复添加校准谱线', status_code=409)
            expected = self.repository._expected_position(db,context.layout,wavelength,line['ccd_index'])
            db.execute('UPDATE dispersion_task_lines SET wavelength_nm=?,expected_position=?,updated_at=? WHERE id=?',
                       (wavelength,expected,utc_now(),line_id))
            self.repository._audit(db,actor,'dispersion.line.update',line_id,{'task_id':task_id,'previous_wavelength':line['wavelength_nm'],'wavelength_nm':wavelength})
            return self.repository._line_decode(db.execute('SELECT * FROM dispersion_task_lines WHERE id=?',(line_id,)).fetchone())

    def update_gap(self, task_id: int, gap_index: int, gap_um: float, actor=None) -> dict[str, Any]:
        """Create a new geometry for this task; referenced layouts/calibrations remain immutable."""
        with self.database.write() as db:
            context = self.repository._context(task_id, db)
            if context.task['status'] not in {'draft','completed','stopped','failed'}:
                raise DispersionError('dispersion_task_busy', '采集中不能修改 CCD 间隔', status_code=409)
            gaps = json.loads(context.layout['gap_points_json'])
            gap_um = _finite(gap_um, 'gap_um')
            if not 0 <= gap_index < len(gaps) or not 0 <= gap_um <= 10000:
                raise DispersionError('dispersion_gap_invalid','CCD 间隔或序号超出范围')
            if float(context.layout['point_width']) <= 0:
                raise DispersionError('dispersion_gap_invalid','CCD 点宽必须大于零')
            reference = self.repository._reference_coefficients(db, context.layout)
            previous = gaps[gap_index]; gaps[gap_index] = gap_um / float(context.layout['point_width'])
            row = dict(db.execute('SELECT * FROM ccd_layouts WHERE id=?',(context.layout['id'],)).fetchone())
            import uuid
            row.pop('id'); row.update(name=f"色散任务{task_id}间隔修正 {uuid.uuid4().hex[:12]}",gap_points_json=_json(gaps),created_at=utc_now())
            cursor = db.execute(f"INSERT INTO ccd_layouts({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
            condition = json.loads(context.task['condition_json'] or '{}')
            condition['reference_coefficients'] = reference
            condition.setdefault('original_layout_id',context.layout['id'])
            db.execute('UPDATE dispersion_tasks SET ccd_layout_id=?,condition_json=?,updated_at=? WHERE id=?',
                       (cursor.lastrowid,_json(condition),utc_now(),task_id))
            updated = self.repository._context(task_id,db)
            for line in db.execute('SELECT * FROM dispersion_task_lines WHERE task_id=?',(task_id,)).fetchall():
                expected = self.repository._expected_position(db,updated.layout,line['wavelength_nm'],line['ccd_index'])
                db.execute('UPDATE dispersion_task_lines SET expected_position=?,updated_at=? WHERE id=?',(expected,utc_now(),line['id']))
            self.repository._audit(db,actor,'dispersion.gap.update',task_id,{'gap_index':gap_index,'previous_points':previous,'gap_um':gap_um,'layout_id':cursor.lastrowid})
            return self.repository._task_dict(task_id,db)

    def move_line(
        self, task_id: int, line_id: int, direction: str, steps: float, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        sign = -1.0 if direction == "short" else 1.0 if direction == "long" else 0.0
        if sign == 0:
            raise DispersionError("line_move_invalid", "方向必须是 short 或 long")
        with self.database.write() as db:
            line = db.execute(
                "SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)
            ).fetchone()
            if line is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            current = line["located_position"] if line["located_position"] is not None else line["expected_position"]
            if current is None:
                raise DispersionError("line_position_missing", "谱线尚未定位")
            _, points = self.repository._geometry(self.repository._context(task_id, db).layout, int(line["ccd_index"]))
            position = max(0.0, min(points - 1.0, float(current) + sign * _finite(steps, "steps")))
            adjustment = float(line["adjustment_points"] or 0) + sign * float(steps)
            db.execute(
                (
                    "UPDATE dispersion_task_lines SET located_position=?, position_state='located', "
                    "position_source='manual_adjustment', adjustment_points=?, updated_at=? WHERE "
                    "id=?"
                ),
                (position, adjustment, utc_now(), line_id),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.line.move",
                line_id,
                {"task_id": task_id, "direction": direction, "steps": steps, "position": position},
            )
            return self.repository._line_decode(
                db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone()
            )

    def set_line_position(
        self, task_id: int, line_id: int, position: float, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        with self.database.write() as db:
            context = self.repository._context(task_id, db)
            line = db.execute(
                "SELECT * FROM dispersion_task_lines WHERE task_id=? AND id=?", (task_id, line_id)
            ).fetchone()
            if line is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            _, points = self.repository._geometry(context.layout, line["ccd_index"])
            position = _finite(position, "position")
            if not 0 <= position <= points - 1:
                raise DispersionError("line_position_out_of_range", "人工点位超出当前 CCD 范围")
            db.execute(
                (
                    "UPDATE dispersion_task_lines SET located_position=?,position_state='located',pos"
                    "ition_source='manual_adjustment',updated_at=? WHERE id=?"
                ),
                (position, utc_now(), line_id),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.line.move",
                line_id,
                {
                    "task_id": task_id,
                    "position": position,
                    "previous": line["located_position"],
                    "source": "manual_point",
                },
            )
            return self.repository._line_decode(
                db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone()
            )

    def save_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._save_or_restore_position(task_id, line_id, restore=False, actor_user_id=actor_user_id)

    def restore_line_position(self, task_id: int, line_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self._save_or_restore_position(task_id, line_id, restore=True, actor_user_id=actor_user_id)

    def _save_or_restore_position(
        self, task_id: int, line_id: int, *, restore: bool, actor_user_id: int | None
    ) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM dispersion_task_lines WHERE id=? AND task_id=?", (line_id, task_id)
            ).fetchone()
            if row is None:
                raise DispersionError("dispersion_line_not_found", "任务谱线不存在", status_code=404)
            if restore:
                if row["saved_position"] is None:
                    raise DispersionError("line_saved_position_missing", "该谱线没有可恢复的实测位置", status_code=409)
                position = float(row["saved_position"])
                action = "dispersion.line.position.restore"
            else:
                if row["located_position"] is None:
                    raise DispersionError("line_position_missing", "谱线尚未定位", status_code=409)
                position = float(row["located_position"])
                action = "dispersion.line.position.save"
            if restore:
                db.execute(
                    "UPDATE dispersion_task_lines SET located_position=?, position_state='saved', updated_at=? WHERE id=?",
                    (position, utc_now(), line_id),
                )
            else:
                db.execute(
                    "UPDATE dispersion_task_lines SET saved_position=?, position_state='saved', updated_at=? WHERE id=?",
                    (position, utc_now(), line_id),
                )
            self.repository._audit(db, actor_user_id, action, line_id, {"task_id": task_id, "position": position})
            return self.repository._line_decode(
                db.execute("SELECT * FROM dispersion_task_lines WHERE id=?", (line_id,)).fetchone()
            )

    def fit_calibration(
        self, task_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        context = self.repository._context(task_id)
        if json.loads(context.task["condition_json"] or "{}").get("preheat"):
            raise DispersionError("preheat_not_calibration_source", "预热谱图仅供观察，不能制作正式色散曲线", status_code=409)
        degree = int(payload.get("degree", 2))
        with self.database.read() as db:
            rows = db.execute(
                "SELECT * FROM dispersion_task_lines WHERE task_id=? ORDER BY wavelength_nm, id", (task_id,)
            ).fetchall()
            values: list[tuple[sqlite3.Row, float, float]] = []
            seen_wavelengths: list[float] = []
            for row in rows:
                # The old RealStep is the current measured position; saved values are restore points.
                position = row["located_position"] if row["located_position"] is not None else row["saved_position"]
                if position is None:
                    continue
                wavelength = float(row["wavelength_nm"])
                if any(math.isclose(wavelength, old, abs_tol=0.01) for old in seen_wavelengths):
                    raise DispersionError(
                        "calibration_duplicate_wavelength",
                        "校准谱线不能有重复波长",
                        details={"wavelength_nm": wavelength},
                    )
                seen_wavelengths.append(wavelength)
                left, _ = self.repository._geometry(context.layout, int(row["ccd_index"]))
                values.append((row, wavelength, left + float(position)))
            coefficients = _fit_polynomial([item[1] for item in values], [item[2] for item in values], degree)
            residuals = []
            errors = []
            for row, wavelength, actual in values:
                predicted = _evaluate(coefficients, wavelength)
                residual = predicted - actual
                residuals.append(
                    {
                        "line_id": row["id"],
                        "element": row["element"],
                        "wavelength_nm": wavelength,
                        "ccd_index": row["ccd_index"],
                        "measured_position": actual,
                        "predicted_position": predicted,
                        "residual_points": residual,
                    }
                )
                errors.append(residual)
        rms = math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else math.inf
        maximum = max((abs(error) for error in errors), default=math.inf)
        residual_limit = float(payload.get("residual_limit_points") or context.task["residual_limit_points"])
        if payload.get('use_legacy_limit'):
            from ...services import AppService
            gap_error = AppService(self.database).get_settings()['analysis']['dispersion_allow_gap_error_um']
            residual_limit = float(gap_error) / float(context.layout['point_width'])
        name = str(payload.get("name") or f"S12 task {task_id}").strip()
        with self.database.write() as db:
            version_row = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM dispersion_calibration_versions WHERE name=?", (name,)
            ).fetchone()
            version = int(version_row[0])
            now = utc_now()
            cursor = db.execute(
                (
                    "INSERT INTO dispersion_calibration_versions(name, version, state, "
                    "calibration_id, ccd_layout_id, source_task_id, coefficients_json, "
                    "residuals_json, wavelength_min, wavelength_max, residual_rms, residual_max, "
                    "point_count, residual_limit_points, created_by, created_at) VALUES (?, ?, "
                    "'draft', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    name,
                    version,
                    context.layout["id"],
                    task_id,
                    _json(coefficients),
                    _json(residuals),
                    min(item[1] for item in values),
                    max(item[1] for item in values),
                    rms,
                    maximum,
                    len(values),
                    residual_limit,
                    actor_user_id,
                    now,
                ),
            )
            calibration_id = int(cursor.lastrowid)
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.calibration.fit",
                calibration_id,
                {
                    "task_id": task_id,
                    "degree": degree,
                    "point_count": len(values),
                    "residual_rms": rms,
                    "residual_max": maximum,
                },
            )
            return self.repository._calibration_decode(
                db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_id,)).fetchone()
            )

    def publish_calibration(self, calibration_version_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute(
                "SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_version_id,)
            ).fetchone()
            if row is None:
                raise DispersionError("calibration_version_not_found", "校准版本不存在", status_code=404)
            if row["state"] == "published":
                return self.repository._calibration_decode(row)
            if row["state"] != "draft":
                raise DispersionError("calibration_version_not_publishable", "当前校准版本不能发布", status_code=409)
            if int(row["point_count"]) < 3:
                raise DispersionError("calibration_points_insufficient", "至少需要三个不同定位点才能发布")
            if not self.repository.calibration_inputs_current(db, row):
                raise DispersionError('calibration_inputs_changed', '谱线或布局已修改，请按当前实测位置重新拟合', status_code=409)
            if float(row["residual_max"]) >= float(row["residual_limit_points"]):
                raise DispersionError(
                    "calibration_residual_exceeded",
                    "校准残差超过发布阈值",
                    details={"residual_max": row["residual_max"], "limit": row["residual_limit_points"]},
                )
            base_name = str(row["name"])
            name = base_name
            if db.execute("SELECT 1 FROM dispersion_calibrations WHERE name=?", (name,)).fetchone():
                name = f"{base_name} · v{row['version']}"
            cursor = db.execute(
                (
                    "INSERT INTO dispersion_calibrations(name, ccd_layout_id, wavelength_min, "
                    "wavelength_max, coefficients_json, enabled, created_at) VALUES (?, ?, ?, ?, ?, "
                    "1, ?)"
                ),
                (
                    name,
                    row["ccd_layout_id"],
                    row["wavelength_min"],
                    row["wavelength_max"],
                    row["coefficients_json"],
                    utc_now(),
                ),
            )
            parent_id = int(cursor.lastrowid)
            db.execute(
                "UPDATE dispersion_calibration_versions SET state='published', calibration_id=? WHERE id=?",
                (parent_id, calibration_version_id),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.calibration.publish",
                calibration_version_id,
                {"calibration_id": parent_id, "name": name, "version": row["version"]},
            )
            return self.repository._calibration_decode(
                db.execute(
                    "SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_version_id,)
                ).fetchone()
            )

    def calibration(self, calibration_version_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute(
                "SELECT * FROM dispersion_calibration_versions WHERE id=?", (calibration_version_id,)
            ).fetchone()
            if row is None:
                raise DispersionError("calibration_version_not_found", "校准版本不存在", status_code=404)
            return self.repository._calibration_decode(row)

    def bind_calibration(
        self, calibration_version_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        method_id = int(payload["method_id"])
        with self.database.write() as db:
            calibration = db.execute(
                "SELECT * FROM dispersion_calibration_versions WHERE id=? AND state='published'",
                (calibration_version_id,),
            ).fetchone()
            if calibration is None:
                raise DispersionError("calibration_not_published", "只有已发布校准版本才能绑定方法", status_code=409)
            metadata = db.execute(
                "SELECT archived FROM dispersion_calibration_metadata WHERE calibration_version_id=?",
                (calibration_version_id,),
            ).fetchone()
            if metadata and metadata["archived"]:
                raise DispersionError("calibration_archived", "校准已归档，恢复后才可新增绑定", status_code=409)
            version = payload.get("method_version")
            if version is None:
                method_row = db.execute("SELECT current_version FROM methods WHERE id=?", (method_id,)).fetchone()
                version = method_row[0] if method_row else None
            if version is None:
                raise DispersionError("method_revision_not_found", "方法没有可绑定的当前修订", status_code=404)
            method_version = db.execute(
                "SELECT * FROM method_versions WHERE method_id=? AND version=? AND state='published'",
                (method_id, int(version)),
            ).fetchone()
            if method_version is None:
                raise DispersionError("method_revision_not_found", "未找到已发布方法修订", status_code=404)
            method_payload = json.loads(method_version["payload_json"] or "{}")
            layout_reference = method_payload.get("conditions", {}).get("ccd_layout_id", "default")
            method_layout = self.repository._resolve_layout(db, layout_reference)
            if int(method_layout["id"]) != int(calibration["ccd_layout_id"]):
                raise DispersionError(
                    "method_calibration_layout_mismatch",
                    "方法修订与校准版本的 CCD 布局不一致",
                    details={
                        "method_layout_id": method_layout["id"],
                        "calibration_layout_id": calibration["ccd_layout_id"],
                    },
                )
            existing = db.execute(
                "SELECT * FROM method_calibration_bindings WHERE method_version_id=?", (method_version["id"],)
            ).fetchone()
            if existing is not None:
                if int(existing["calibration_version_id"]) == calibration_version_id:
                    return dict(existing)
                raise DispersionError(
                    "method_calibration_already_bound", "方法修订已经绑定其他校准版本", status_code=409
                )
            now = utc_now()
            cursor = db.execute(
                (
                    "INSERT INTO method_calibration_bindings(method_version_id, method_id, "
                    "method_version, calibration_version_id, created_by, created_at) VALUES (?, ?, "
                    "?, ?, ?, ?)"
                ),
                (method_version["id"], method_id, int(version), calibration_version_id, actor_user_id, now),
            )
            self.repository._audit(
                db,
                actor_user_id,
                "dispersion.calibration.bind",
                calibration_version_id,
                {"method_id": method_id, "method_version": int(version), "binding_id": cursor.lastrowid},
            )
            return dict(
                db.execute("SELECT * FROM method_calibration_bindings WHERE id=?", (cursor.lastrowid,)).fetchone()
            )

    def manage_calibration(self, identifier: int, action: str, name: str | None, actor: int | None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT * FROM dispersion_calibration_versions WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise DispersionError("calibration_version_not_found", "校准版本不存在", status_code=404)
            if action == "delete":
                if (
                    row["state"] != "draft"
                    or db.execute(
                        "SELECT 1 FROM method_calibration_bindings WHERE calibration_version_id=?", (identifier,)
                    ).fetchone()
                ):
                    raise DispersionError(
                        "calibration_in_use", "仅可删除未引用的草稿；已发布版本可归档", status_code=409
                    )
                db.execute("DELETE FROM dispersion_calibration_versions WHERE id=?", (identifier,))
            elif action in {"rename", "archive", "restore"}:
                if action == "rename" and (
                    not name or not name.strip() or len(name) > 120 or any(ord(char) < 32 for char in name)
                ):
                    raise DispersionError("calibration_name_invalid", "校准名称须为 1–120 个可见字符")
                db.execute(
                    "INSERT OR IGNORE INTO dispersion_calibration_metadata(calibration_version_id,updated_at) VALUES (?,?)",
                    (identifier, utc_now()),
                )
                if action == "rename":
                    db.execute(
                        "UPDATE dispersion_calibration_metadata SET display_name=?,updated_at=? WHERE calibration_version_id=?",
                        (name.strip(), utc_now(), identifier),
                    )
                else:
                    db.execute(
                        "UPDATE dispersion_calibration_metadata SET archived=?,updated_at=? WHERE calibration_version_id=?",
                        (int(action == "archive"), utc_now(), identifier),
                    )
            else:
                raise DispersionError("calibration_action_invalid", "校准管理动作无效")
            self.repository._audit(
                db,
                actor,
                "dispersion.calibration." + action,
                identifier,
                {"name": name, "coefficients_preserved": True},
            )
        return {"id": identifier, "action": action}

    def bindings(self, method_id: int | None = None) -> list[dict[str, Any]]:
        with self.database.read() as db:
            query = (
                "SELECT b.*, c.name AS calibration_name, c.version AS calibration_version, "
                "c.state AS calibration_state FROM method_calibration_bindings b JOIN "
                "dispersion_calibration_versions c ON c.id=b.calibration_version_id"
            )
            args: tuple[Any, ...] = ()
            if method_id is not None:
                query += " WHERE b.method_id=?"
                args = (method_id,)
            query += " ORDER BY b.created_at DESC"
            return [dict(row) for row in db.execute(query, args).fetchall()]
