"""Historical mercury calibration queries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from typing import Any

from ...db import Database
from .values import DeviceError


def _unpack_points(blob: bytes, count: int, sha256: str) -> list[int]:
    if len(blob) != count * 2:
        raise DeviceError("mercury_frame_invalid", "stored mercury frame length is inconsistent", status_code=409)
    if hashlib.sha256(blob).hexdigest() != sha256:
        raise DeviceError("mercury_frame_invalid", "stored mercury frame hash is inconsistent", status_code=409)
    return list(struct.unpack(f"<{count}H", blob))


class LegacyMercuryService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _layout(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["ccd_indices"] = [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]
        result["gap_points"] = json.loads(row["gap_points_json"] or "[]")
        return result

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            lines = [
                dict(row) | {"enabled": bool(row["enabled"])}
                for row in db.execute(
                    "SELECT * FROM mercury_reference_lines WHERE enabled=1 ORDER BY wavelength_nm"
                ).fetchall()
            ]
            profiles = [
                dict(row)
                for row in db.execute(
                    (
                        "SELECT id, name, transport, port, baud_rate, points_per_ccd, ccd_indices_json "
                        "FROM device_profiles WHERE enabled=1 ORDER BY id"
                    )
                ).fetchall()
            ]
            for profile in profiles:
                profile["ccd_indices"] = json.loads(profile.pop("ccd_indices_json") or "[]")
                profile["mercury_protocol_available"] = profile["transport"] == "simulator"
                profile["protocol_status"] = (
                    "synthetic_spectrum_only" if profile["transport"] == "simulator" else "deferred_external"
                )
            layouts = [self._layout(row) for row in db.execute("SELECT * FROM ccd_layouts ORDER BY id").fetchall()]
            active = [
                dict(row)
                for row in db.execute(
                    (
                        "SELECT a.device_profile_id, a.ccd_layout_id, a.version_id, v.version, "
                        "v.offset_points, v.snapshot_sha256, a.updated_at FROM mercury_active_alignments "
                        "a JOIN mercury_alignment_versions v ON v.id=a.version_id ORDER BY "
                        "a.device_profile_id, a.ccd_layout_id"
                    )
                ).fetchall()
            ]
        return {
            "reference_lines": lines,
            "profiles": profiles,
            "layouts": layouts,
            "active_alignments": active,
            "faults": ["none", "switch_failure", "stability_failure", "capture_failure"],
            "real_protocol_available": False,
            "protocol_notice": "真实汞灯协议与抓包缺失；串口入口不发送任何命令。",
        }

    def _context(
        self, session_id: int, db: sqlite3.Connection
    ) -> tuple[sqlite3.Row, sqlite3.Row, dict[str, Any]]:
        session = db.execute("SELECT * FROM mercury_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None:
            raise DeviceError(
                "mercury_session_not_found",
                "mercury calibration session was not found",
                details={"session_id": session_id},
                status_code=404,
            )
        profile = db.execute("SELECT * FROM device_profiles WHERE id=?", (session["device_profile_id"],)).fetchone()
        layout_row = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (session["ccd_layout_id"],)).fetchone()
        if profile is None or layout_row is None:
            raise DeviceError(
                "mercury_configuration_missing", "mercury session references missing device or layout", status_code=409
            )
        return session, profile, self._layout(layout_row)

    def _lines(self, db: sqlite3.Connection, session_id: int) -> list[dict[str, Any]]:
        rows = db.execute(
            (
                "SELECT l.*, r.label, r.relative_intensity, r.source_name, r.source_url FROM "
                "mercury_session_lines l JOIN mercury_reference_lines r ON "
                "r.id=l.reference_line_id WHERE l.session_id=? ORDER BY l.wavelength_nm"
            ),
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _version_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json") or "{}")
        return result

    def session(self, session_id: int, *, include_points: bool = False) -> dict[str, Any]:
        with self.database.read() as db:
            row, profile, layout = self._context(session_id, db)
            result = dict(row)
            for field, default in (("simulator_json", {}), ("analysis_json", None), ("last_event_json", None)):
                raw = result.pop(field, None)
                result[field.removesuffix("_json")] = json.loads(raw) if raw else default
            result["safe_off"] = bool(result["safe_off"])
            result["profile"] = {
                "id": profile["id"],
                "name": profile["name"],
                "transport": profile["transport"],
                "port": profile["port"],
                "baud_rate": profile["baud_rate"],
            }
            result["layout"] = {
                key: layout[key]
                for key in ("id", "name", "points_per_ccd", "ccd_indices", "wavelength_min", "wavelength_max")
            }
            result["lines"] = self._lines(db, session_id)
            result["messages"] = []
            for message in db.execute(
                "SELECT * FROM mercury_messages WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall():
                item = dict(message)
                item["details"] = json.loads(item.pop("details_json") or "{}")
                result["messages"].append(item)
            result["traces"] = []
            for trace in db.execute(
                "SELECT * FROM mercury_traces WHERE session_id=? ORDER BY sequence_no", (session_id,)
            ).fetchall():
                item = dict(trace)
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
                result["traces"].append(item)
            result["frames"] = []
            columns = (
                "id, session_id, phase, frame_index, ccd_index, points_count, points_sha256, "
                "frame_sha256, virtual_time_ms, captured_at"
            )
            if include_points:
                columns += ", points_blob"
            for frame in db.execute(
                f"SELECT {columns} FROM mercury_frames WHERE session_id=? ORDER BY phase, frame_index, ccd_index",
                (session_id,),
            ):
                item = dict(frame)
                if include_points:
                    item["points"] = _unpack_points(
                        item.pop("points_blob"), int(item["points_count"]), item["points_sha256"]
                    )
                result["frames"].append(item)
            before = db.execute(
                "SELECT * FROM mercury_alignment_versions WHERE id=?", (row["before_version_id"],)
            ).fetchone()
            candidate = (
                db.execute(
                    "SELECT * FROM mercury_alignment_versions WHERE id=?", (row["candidate_version_id"],)
                ).fetchone()
                if row["candidate_version_id"]
                else None
            )
            active = db.execute(
                (
                    "SELECT v.* FROM mercury_active_alignments a JOIN mercury_alignment_versions v "
                    "ON v.id=a.version_id WHERE a.device_profile_id=? AND a.ccd_layout_id=?"
                ),
                (row["device_profile_id"], row["ccd_layout_id"]),
            ).fetchone()
            result["before_version"] = self._version_dict(before)
            result["candidate_version"] = self._version_dict(candidate)
            result["active_version"] = self._version_dict(active)
            result["progress"] = round(
                min(
                    100.0,
                    int(row["stabilized_frames"]) / max(1, int(row["stabilization_frames"])) * 60.0
                    + (40.0 if row["candidate_version_id"] else 0.0),
                ),
                2,
            )
            if not include_points and result["last_event"] and "ccds" in result["last_event"]:
                compact = dict(result["last_event"])
                compact["ccds"] = [
                    {key: value for key, value in ccd.items() if key != "points"} for ccd in compact["ccds"]
                ]
                result["last_event"] = compact
        return result

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [
                int(row[0])
                for row in db.execute(
                    "SELECT id FROM mercury_sessions ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)
                ).fetchall()
            ]
        return [self.session(session_id) for session_id in ids]
