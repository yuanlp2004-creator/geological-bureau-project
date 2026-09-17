"""方法查询、版本序号和事务内审计辅助。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any
from ...db import Database, utc_now
from .values import _json
from .errors import MethodDomainError
from .geometry import MethodGeometry

class MethodRepository:
    def __init__(self, database: Database, geometry: MethodGeometry):
        self.database = database
        self.geometry = geometry

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
    def _version_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        from ..spectral_lines import canonical_lines

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
        for item in self.geometry._layout_geometry(layout):
            left = float(item["left_step"])
            right = float(item["right_step"])
            try:
                ranges.append(
                    {
                        "ccd_index": int(item["ccd_index"]),
                        "wavelength_start_nm": self.geometry._step_to_wave(left, coefficients),
                        "wavelength_end_nm": self.geometry._step_to_wave(right, coefficients),
                        "safe_start_nm": self.geometry._step_to_wave(left + margin, coefficients),
                        "safe_end_nm": self.geometry._step_to_wave(right - margin, coefficients),
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

