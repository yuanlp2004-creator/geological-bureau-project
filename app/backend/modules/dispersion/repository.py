from __future__ import annotations
import hashlib
import json
import math
import sqlite3
import struct
import zlib
from typing import Any
from ...db import Database, utc_now
from .codec import _pack_points, _unpack_points
from .fitting import _calibration_position
from .values import DispersionError, DispersionState, _TaskContext, _json


class DispersionRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for field in ("ccd_indices_json", "condition_json", "last_event_json"):
            value = result.pop(field, None)
            output = field.removesuffix("_json")
            if value in (None, ""):
                result[output] = None if field == "last_event_json" else ({} if field == "condition_json" else [])
            else:
                result[output] = json.loads(value)
        result["status"] = str(result["status"])
        return result

    @staticmethod
    def _line_decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["position_state"] = str(result["position_state"])
        return result

    @staticmethod
    def _calibration_decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for field in ("coefficients_json", "residuals_json"):
            value = result.pop(field, "[]")
            result[field.removesuffix("_json")] = json.loads(value or "[]")
        result["publishable"] = (
            result["state"] == "published" or result["residual_max"] < result["residual_limit_points"]
        )
        return result

    def _context(self, task_id: int, db: sqlite3.Connection | None = None) -> _TaskContext:
        if db is None:
            with self.database.read() as connection:
                return self._context(task_id, connection)
        task = db.execute("SELECT * FROM dispersion_tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise DispersionError(
                "dispersion_task_not_found", "色散采集任务不存在", details={"task_id": task_id}, status_code=404
            )
        layout = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (task["ccd_layout_id"],)).fetchone()
        profile = db.execute("SELECT * FROM device_profiles WHERE id=?", (task["device_profile_id"],)).fetchone()
        if layout is None or profile is None:
            raise DispersionError(
                "dispersion_configuration_missing", "采集任务引用的布局或设备档案不存在", status_code=409
            )
        condition = json.loads(task['condition_json'] or '{}')
        if 'reference_coefficients' in condition:
            layout = dict(layout) | {'reference_coefficients': condition['reference_coefficients']}
        return _TaskContext(task, layout, profile)

    @staticmethod
    def _resolve_layout(db: sqlite3.Connection, reference: str | int) -> sqlite3.Row:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            row = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (int(reference),)).fetchone()
        else:
            row = db.execute("SELECT * FROM ccd_layouts WHERE name=?", (str(reference),)).fetchone()
        if row is None:
            raise DispersionError(
                "ccd_layout_not_found", "未找到 CCD 布局", details={"ccd_layout_id": reference}, status_code=404
            )
        return row

    @staticmethod
    def _profile(db: sqlite3.Connection, profile_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
        if row is None:
            raise DispersionError(
                "device_profile_not_found", "未找到启用的设备档案", details={"profile_id": profile_id}, status_code=404
            )
        if row["transport"] != "simulator":
            raise DispersionError("dispersion_transport_unavailable", "S12 当前仅支持确定性模拟器", status_code=409)
        return row

    @staticmethod
    def _layout_indices(layout: sqlite3.Row) -> list[int]:
        return [int(value) for value in json.loads(layout["ccd_indices_json"] or "[]")]

    @staticmethod
    def _profile_dict(profile: sqlite3.Row) -> dict[str, Any]:
        result = dict(profile)
        result["ccd_indices"] = json.loads(result.pop("ccd_indices_json") or "[]")
        result["mirror"] = bool(result["mirror"])
        result["enabled"] = bool(result["enabled"])
        return result

    @staticmethod
    def _geometry(layout: sqlite3.Row, ccd_index: int) -> tuple[float, int]:
        indices = DispersionRepository._layout_indices(layout)
        if ccd_index not in indices:
            raise DispersionError(
                "ccd_index_invalid", "CCD 不在当前布局中", details={"ccd_index": ccd_index, "allowed": indices}
            )
        points = int(layout["points_per_ccd"])
        gaps = [float(value) for value in json.loads(layout["gap_points_json"] or "[]")]
        return ccd_index * points + sum(gaps[:ccd_index]), points

    @staticmethod
    def _default_coefficients(db: sqlite3.Connection, layout_id: int) -> list[float]:
        row = db.execute(
            "SELECT coefficients_json FROM dispersion_calibrations WHERE ccd_layout_id=? AND enabled=1 ORDER BY id LIMIT 1",
            (layout_id,),
        ).fetchone()
        coefficients = json.loads(row[0]) if row else []
        if len(coefficients) >= 3:
            return [float(value) for value in coefficients[:3]]
        layout = db.execute(
            "SELECT wavelength_min, wavelength_max, points_per_ccd, ccd_indices_json FROM ccd_layouts WHERE id=?",
            (layout_id,),
        ).fetchone()
        if layout is None or layout["wavelength_max"] <= layout["wavelength_min"]:
            raise DispersionError("calibration_reference_missing", "当前布局没有可用的色散参考")
        total = len(json.loads(layout["ccd_indices_json"] or "[]")) * int(layout["points_per_ccd"])
        slope = total / (float(layout["wavelength_max"]) - float(layout["wavelength_min"]))
        return [0.0, slope, -float(layout["wavelength_min"]) * slope]

    def _expected_position(
        self, db: sqlite3.Connection, layout: sqlite3.Row, wavelength: float, ccd_index: int
    ) -> float | None:
        coefficients = self._reference_coefficients(db, layout)
        global_position = _calibration_position(wavelength, coefficients)
        left, points = self._geometry(layout, ccd_index)
        local = global_position - left
        return local if 0 <= local <= points - 1 else None

    def _reference_coefficients(self, db, layout):
        return layout['reference_coefficients'] if 'reference_coefficients' in layout.keys() else self._default_coefficients(db, int(layout['id']))

    def _task_dict(self, task_id: int, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        if db is None:
            with self.database.read() as connection:
                return self._task_dict(task_id, connection)
        context = self._context(task_id, db)
        task = self._decode(context.task)
        task["layout"] = {
            "id": context.layout["id"],
            "name": context.layout["name"],
            "frame_count": context.layout["frame_count"],
            "ccds_per_frame": context.layout["ccds_per_frame"],
            "points_per_ccd": context.layout["points_per_ccd"],
            "ccd_indices": self._layout_indices(context.layout),
            "point_width_um": context.layout['point_width'],
            "gap_points": json.loads(context.layout['gap_points_json']),
        }
        task["profile"] = {
            "id": context.profile["id"],
            "name": context.profile["name"],
            "transport": context.profile["transport"],
            "screen_width_mm": context.profile["screen_width_mm"],
            "screen_resolution_px": context.profile["screen_resolution_px"],
        }
        task["lines"] = [
            self._line_decode(row)
            for row in db.execute(
                "SELECT * FROM dispersion_task_lines WHERE task_id=? ORDER BY wavelength_nm, id", (task_id,)
            ).fetchall()
        ]
        task["frame_summary"] = [
            dict(row)
            for row in db.execute(
                (
                    "SELECT phase, COUNT(DISTINCT frame_index) AS frame_count, MAX(frame_index) AS "
                    "last_frame_index FROM dispersion_task_frames WHERE task_id=? GROUP BY phase"
                ),
                (task_id,),
            ).fetchall()
        ]
        task["calibrations"] = [
            self._calibration_view(db, row)
            for row in db.execute(
                "SELECT * FROM dispersion_calibration_versions WHERE source_task_id=? ORDER BY version DESC, id DESC",
                (task_id,),
            ).fetchall()
        ]
        return task

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [
                int(row[0])
                for row in db.execute("SELECT id FROM dispersion_tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            ]
            return [self._task_dict(task_id, db) for task_id in ids]

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            layouts = []
            for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall():
                layouts.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "frame_count": row["frame_count"],
                        "ccds_per_frame": row["ccds_per_frame"],
                        "points_per_ccd": row["points_per_ccd"],
                        "point_width_um": row["point_width"],
                        "ccd_indices": self._layout_indices(row),
                        "wavelength_min": row["wavelength_min"],
                        "wavelength_max": row["wavelength_max"],
                    }
                )
            calibrations = [
                self._calibration_view(db, row)
                for row in db.execute(
                    "SELECT * FROM dispersion_calibration_versions WHERE state='published' ORDER BY created_at DESC"
                ).fetchall()
            ]
            from ..spectrum_migration import SpectrumMigrationService

            legacy_sources = SpectrumMigrationService.source_records(db, ("wdt",))
            profiles = [
                dict(row) | {"ccd_indices": json.loads(row["ccd_indices_json"] or "[]")}
                for row in db.execute(
                    (
                        "SELECT id, name, transport, frame_count, ccds_per_frame, points_per_ccd, "
                        "ccd_indices_json FROM device_profiles WHERE enabled=1 ORDER BY id"
                    )
                ).fetchall()
            ]
            return {
                "legacy_sources": legacy_sources,
                "ccd_layouts": layouts,
                "calibration_versions": calibrations,
                "device_profiles": profiles,
                "states": [state.value for state in DispersionState],
            }

    def _import_wdt(self, db, task_id: int, layout, source_id: int, actor) -> None:
        from ..spectrum_migration import SpectrumMigrationService
        from ..legacy_migration import LegacyMigrationError

        try:
            source = SpectrumMigrationService.source_record(db, source_id)
        except LegacyMigrationError as exc:
            raise DispersionError(exc.code, str(exc), status_code=404) from exc
        geometry = json.loads(source["layout_json"])
        if source["format"] != "wdt":
            raise DispersionError("dispersion_wdt_required", "旧色散再校准只接受 WDT")
        indices = geometry["ccd_indices"]
        gaps = json.loads(layout["gap_points_json"])
        if (
            geometry["points_per_ccd"] != layout["points_per_ccd"]
            or any(index not in self._layout_indices(layout) for index in indices)
            or len(gaps) != len(geometry["gap_points"])
            or any(not math.isclose(a, b, abs_tol=1e-4) for a, b in zip(gaps, geometry["gap_points"]))
        ):
            raise DispersionError("dispersion_source_layout_mismatch", "旧 WDT 与目标 CCD 布局不一致，禁止隐式重采样")
        ignition = json.loads(source["ignition_json"])
        per_ccd = geometry["points_per_ccd"]
        last = []
        for phase in ("burn", "dark"):
            count = int(ignition.get(phase + "_count") or 0)
            blob = bytes(source[phase + "_adcs_blob"] or b"")
            if len(blob) != count * len(indices) * per_ccd * 2 or (phase == "burn" and count < 1):
                raise DispersionError("dispersion_source_frames_invalid", "旧 WDT 原始帧不完整")
            for frame in range(count):
                event_ccds = []
                for slot, index in enumerate(indices):
                    start = (frame * len(indices) + slot) * per_ccd * 2
                    raw = blob[start : start + per_ccd * 2]
                    values = list(struct.unpack(f"<{per_ccd}H", raw))
                    peak = max(values)
                    db.execute(
                        (
                            "INSERT INTO dispersion_task_frames(task_id,phase,frame_index,ccd_index,points_bl"
                            "ob,points_count,compression,points_sha256,raw_transfer_sha256,raw_byte_length,he"
                            "aders_json,virtual_time_ms,captured_at) VALUES (?,?,?,?,?,?,'zlib',?,?,?,?,0,?)"
                        ),
                        (
                            task_id,
                            phase,
                            frame,
                            index,
                            zlib.compress(raw),
                            per_ccd,
                            hashlib.sha256(raw).hexdigest(),
                            source["source_sha256"],
                            len(raw),
                            _json({"source_record_id": source_id, "source_frame_index": frame}),
                            source["measure_time"] or utc_now(),
                        ),
                    )
                    event_ccds.append(
                        {
                            "ccd_index": index,
                            "points": values,
                            "peak": peak,
                            "peak_position": values.index(peak),
                            "integral": sum(values),
                        }
                    )
                if phase == "burn":
                    last = event_ccds
        condition = {
            "source_record_id": source_id,
            "source_sha256": source["source_sha256"],
            "source_format": "wdt",
            "source_layout": geometry,
            "ignition": ignition,
        }
        event = {
            "ccds": last,
            "details": {"sha256": source["source_sha256"], "source": "legacy_wdt"},
            "message": "旧 WDT 原始帧快照",
        }
        db.execute(
            (
                "UPDATE dispersion_tasks SET status='completed',ccd_indices_json=?,frame_count=?,"
                "dark_frame_count=?,burn_frames_captured=?,dark_frames_captured=?,condition_json="
                "?,last_event_json=?,completed_at=? WHERE id=?"
            ),
            (
                _json(indices),
                ignition["burn_count"],
                ignition["dark_count"],
                ignition["burn_count"],
                ignition["dark_count"],
                _json(condition),
                _json(event),
                utc_now(),
                task_id,
            ),
        )
        self._audit(db, actor, "dispersion.task.create", task_id, condition)

    def _store_event(
        self,
        db: sqlite3.Connection,
        task_id: int,
        phase: str,
        phase_index: int,
        event: Any,
        selected: list[int],
        virtual_time_ms: float,
    ) -> None:
        details = event.details or {}
        ccd_by_index = {int(item["ccd_index"]): item for item in event.ccds}
        now = utc_now()
        for ccd_index in selected:
            ccd = ccd_by_index.get(ccd_index)
            if ccd is None:
                raise DispersionError(
                    "ccd_frame_missing",
                    "采集帧缺少已选择的 CCD",
                    details={"ccd_index": ccd_index, "frame_index": phase_index},
                )
            raw_points = _pack_points(ccd["points"])
            points_blob = zlib.compress(raw_points, level=9)
            db.execute(
                (
                    "INSERT INTO dispersion_task_frames(task_id, phase, frame_index, ccd_index, "
                    "points_blob, points_count, dtype, endianness, compression, points_sha256, "
                    "raw_transfer_sha256, headers_json, raw_byte_length, virtual_time_ms, "
                    "captured_at) VALUES (?, ?, ?, ?, ?, ?, 'uint16', 'little', 'zlib', ?, ?, ?, ?, "
                    "?, ?)"
                ),
                (
                    task_id,
                    phase,
                    phase_index,
                    ccd_index,
                    points_blob,
                    len(ccd["points"]),
                    hashlib.sha256(raw_points).hexdigest(),
                    details.get("sha256", ""),
                    _json(details.get("headers", [])),
                    int(details.get("byte_length", 0)),
                    virtual_time_ms,
                    now,
                ),
            )

    def frames(self, task_id: int, *, phase: str | None = None, ccd_index: int | None = None) -> list[dict[str, Any]]:
        self._context(task_id)
        if phase is not None and phase not in {"burn", "dark"}:
            raise DispersionError("dispersion_phase_invalid", "帧阶段必须是 burn 或 dark", details={"phase": phase})
        with self.database.read() as db:
            query = "SELECT * FROM dispersion_task_frames WHERE task_id=?"
            args: list[Any] = [task_id]
            if phase:
                query += " AND phase=?"
                args.append(phase)
            if ccd_index is not None:
                query += " AND ccd_index=?"
                args.append(ccd_index)
            query += " ORDER BY phase, frame_index, ccd_index"
            rows = []
            for row in db.execute(query, args).fetchall():
                item = dict(row)
                item["points"] = _unpack_points(
                    item.pop("points_blob"), int(item["points_count"]), item["points_sha256"], item["compression"]
                )
                item["sha256"] = item["raw_transfer_sha256"]
                item["byte_length"] = item["raw_byte_length"]
                item["headers"] = json.loads(item.pop("headers_json") or "[]")
                rows.append(item)
            return rows

    def _calibration_view(self, db, row) -> dict[str, Any]:
        result = self._calibration_decode(row)
        result['inputs_current'] = row['state'] == 'published' or self.calibration_inputs_current(db, row)
        result['publishable'] = result['publishable'] and result['inputs_current']
        metadata = db.execute(
            "SELECT * FROM dispersion_calibration_metadata WHERE calibration_version_id=?", (row["id"],)
        ).fetchone()
        result["display_name"] = metadata["display_name"] if metadata and metadata["display_name"] else result["name"]
        result["archived"] = bool(metadata["archived"]) if metadata else False
        return result

    def calibration_inputs_current(self, db, row) -> bool:
        if row['source_task_id'] is None:
            return True
        context = self._context(row['source_task_id'], db)
        if context.layout['id'] != row['ccd_layout_id']:
            return False
        current = {}
        for line in db.execute('SELECT * FROM dispersion_task_lines WHERE task_id=?', (row['source_task_id'],)):
            position = line['located_position'] if line['located_position'] is not None else line['saved_position']
            if position is not None:
                left, _ = self._geometry(context.layout, line['ccd_index'])
                current[line['id']] = (line['wavelength_nm'], line['ccd_index'], left + position)
        fitted = json.loads(row['residuals_json'])
        return len(current) == len(fitted) and all(
            point['line_id'] in current and current[point['line_id']][1] == point['ccd_index']
            and math.isclose(current[point['line_id']][0], point['wavelength_nm'], abs_tol=1e-9, rel_tol=0)
            and math.isclose(current[point['line_id']][2], point['measured_position'], abs_tol=1e-7, rel_tol=0)
            for point in fitted)

    def _audit(
        self,
        db: sqlite3.Connection,
        actor_user_id: int | None,
        action: str,
        target_id: int | None,
        details: dict[str, Any],
    ) -> None:
        db.execute(
            (
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                "details_json, created_at) VALUES (?, ?, 'dispersion', ?, ?, ?)"
            ),
            (actor_user_id, action, target_id, _json(details), utc_now()),
        )
