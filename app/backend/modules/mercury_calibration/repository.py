from __future__ import annotations
import json
import sqlite3
from typing import Any
from ...db import Database, utc_now
from .calculation import offset_statistics, _expected_position, _locate
from .codec import _pack, _unpack
from .values import MercuryError, _json, _sha


class MercuryRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _layout(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["ccd_indices"] = [int(value) for value in json.loads(row["ccd_indices_json"] or "[]")]
        result["gap_points"] = json.loads(row["gap_points_json"] or "[]")
        return result

    @staticmethod
    def _trace(
        db: sqlite3.Connection,
        session_id: int,
        direction: str,
        kind: str,
        name: str,
        payload: dict[str, Any],
        correlation_id: str,
        safe_state: str,
    ) -> None:
        sequence = int(
            db.execute(
                "SELECT COALESCE(MAX(sequence_no), -1) + 1 FROM mercury_traces WHERE session_id=?", (session_id,)
            ).fetchone()[0]
        )
        payload_json = _json(payload)
        db.execute(
            (
                "INSERT INTO mercury_traces(session_id, sequence_no, direction, kind, name, "
                "payload_json, payload_sha256, correlation_id, safe_state, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            (
                session_id,
                sequence,
                direction,
                kind,
                name,
                payload_json,
                _sha(payload_json),
                correlation_id,
                safe_state,
                utc_now(),
            ),
        )

    @staticmethod
    def _message(
        db: sqlite3.Connection,
        session_id: int,
        level: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO mercury_messages(session_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, level, code, message, _json(details or {}), utc_now()),
        )

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: int | None, action: str, target_id: int, details: dict[str, Any]) -> None:
        db.execute(
            (
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                "details_json, created_at) VALUES (?, ?, 'mercury_calibration', ?, ?, ?)"
            ),
            (actor, action, target_id, _json(details), utc_now()),
        )

    def _ensure_active(self, db: sqlite3.Connection, profile_id: int, layout_id: int, actor: int | None) -> sqlite3.Row:
        active = db.execute(
            (
                "SELECT v.* FROM mercury_active_alignments a JOIN mercury_alignment_versions v "
                "ON v.id=a.version_id WHERE a.device_profile_id=? AND a.ccd_layout_id=?"
            ),
            (profile_id, layout_id),
        ).fetchone()
        if active is not None:
            return active
        now = utc_now()
        snapshot = {
            "kind": "baseline",
            "device_profile_id": profile_id,
            "ccd_layout_id": layout_id,
            "version": 1,
            "offset_points": 0.0,
        }
        snapshot_json = _json(snapshot)
        cursor = db.execute(
            (
                "INSERT INTO mercury_alignment_versions(device_profile_id, ccd_layout_id, "
                "version, source_session_id, parent_version_id, offset_points, before_rms, "
                "after_rms, max_before_offset, max_after_offset, point_count, snapshot_json, "
                "snapshot_sha256, created_by, created_at) VALUES (?, ?, 1, NULL, NULL, 0, 0, 0, "
                "0, 0, 0, ?, ?, ?, ?)"
            ),
            (profile_id, layout_id, snapshot_json, _sha(snapshot_json), actor, now),
        )
        version_id = int(cursor.lastrowid)
        db.execute(
            (
                "INSERT INTO mercury_active_alignments(device_profile_id, ccd_layout_id, "
                "version_id, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)"
            ),
            (profile_id, layout_id, version_id, actor, now),
        )
        return db.execute("SELECT * FROM mercury_alignment_versions WHERE id=?", (version_id,)).fetchone()

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

    def create_session(self, payload: dict[str, Any], actor: int | None = None) -> dict[str, Any]:
        line_ids = [int(value) for value in payload.get("line_ids") or []]
        if len(line_ids) < 2 or len(line_ids) != len(set(line_ids)):
            raise MercuryError("mercury_line_selection_invalid", "select at least two distinct mercury lines")
        fault = str(payload.get("simulator_fault", "none"))
        if fault not in {"none", "switch_failure", "stability_failure", "capture_failure"}:
            raise MercuryError("mercury_simulator_fault_invalid", "unknown mercury simulator fault")
        with self.database.write() as db:
            profile_id = int(payload.get("device_profile_id", 1))
            profile = db.execute("SELECT * FROM device_profiles WHERE id=? AND enabled=1", (profile_id,)).fetchone()
            if profile is None:
                raise MercuryError("device_profile_not_found", "device profile was not found", status_code=404)
            layout_key = payload.get("ccd_layout_id", "default")
            layout_row = db.execute(
                "SELECT * FROM ccd_layouts WHERE id=? OR name=?",
                (layout_key if str(layout_key).isdigit() else -1, str(layout_key)),
            ).fetchone()
            if layout_row is None:
                raise MercuryError("ccd_layout_not_found", "CCD layout was not found", status_code=404)
            if int(profile["points_per_ccd"]) != int(layout_row["points_per_ccd"]):
                raise MercuryError(
                    "ccd_layout_profile_mismatch", "device profile and CCD layout point counts differ", status_code=409
                )
            placeholders = ",".join("?" for _ in line_ids)
            references = db.execute(
                f"SELECT * FROM mercury_reference_lines WHERE enabled=1 AND id IN ({placeholders}) ORDER BY wavelength_nm",
                line_ids,
            ).fetchall()
            if len(references) != len(line_ids):
                raise MercuryError(
                    "mercury_reference_line_not_found",
                    "one or more selected mercury lines were not found",
                    status_code=404,
                )
            active = self._ensure_active(db, int(profile["id"]), int(layout_row["id"]), actor)
            layout = self._layout(layout_row)
            now = utc_now()
            simulator = {
                "offset_points": float(payload.get("simulator_offset_points", 6.0)),
                "seed": int(payload.get("simulator_seed", 0)),
                "fault": fault,
            }
            cursor = db.execute(
                (
                    "INSERT INTO mercury_sessions(name, status, device_profile_id, ccd_layout_id, "
                    "transport, stabilization_frames, tolerance_points, search_radius_points, "
                    "correction_limit_points, simulator_json, before_version_id, safe_off, "
                    "created_by, created_at, updated_at) VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, 1, ?, ?, ?)"
                ),
                (
                    str(payload.get("name", "S15 汞灯调试与光学校准")).strip(),
                    profile["id"],
                    layout_row["id"],
                    profile["transport"],
                    int(payload.get("stabilization_frames", 2)),
                    float(payload.get("tolerance_points", 1.0)),
                    int(payload.get("search_radius_points", 40)),
                    float(payload.get("correction_limit_points", 25.0)),
                    _json(simulator),
                    active["id"],
                    actor,
                    now,
                    now,
                ),
            )
            session_id = int(cursor.lastrowid)
            for reference in references:
                ccd_index, expected = _expected_position(
                    layout, float(reference["wavelength_nm"]), float(active["offset_points"])
                )
                db.execute(
                    (
                        "INSERT INTO mercury_session_lines(session_id, reference_line_id, wavelength_nm, "
                        "expected_ccd_index, expected_position, created_at) VALUES (?, ?, ?, ?, ?, ?)"
                    ),
                    (session_id, reference["id"], reference["wavelength_nm"], ccd_index, expected, now),
                )
            self._message(
                db,
                session_id,
                "info",
                "session.created",
                "mercury calibration session created",
                {"line_count": len(references), "transport": profile["transport"]},
            )
            self._audit(
                db,
                actor,
                "mercury.session.create",
                session_id,
                {"line_ids": line_ids, "before_version_id": active["id"], "transport": profile["transport"]},
            )
        return self.session(session_id)

    def _context(
        self, session_id: int, db: sqlite3.Connection | None = None
    ) -> tuple[sqlite3.Row, sqlite3.Row, dict[str, Any]]:
        if db is None:
            with self.database.read() as connection:
                return self._context(session_id, connection)
        session = db.execute("SELECT * FROM mercury_sessions WHERE id=?", (session_id,)).fetchone()
        if session is None:
            raise MercuryError(
                "mercury_session_not_found",
                "mercury calibration session was not found",
                details={"session_id": session_id},
                status_code=404,
            )
        profile = db.execute("SELECT * FROM device_profiles WHERE id=?", (session["device_profile_id"],)).fetchone()
        layout_row = db.execute("SELECT * FROM ccd_layouts WHERE id=?", (session["ccd_layout_id"],)).fetchone()
        if profile is None or layout_row is None:
            raise MercuryError(
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
            for frame in db.execute(
                "SELECT * FROM mercury_frames WHERE session_id=? ORDER BY phase, frame_index, ccd_index", (session_id,)
            ).fetchall():
                item = dict(frame)
                blob = item.pop("points_blob")
                if include_points:
                    item["points"] = _unpack(blob, int(item["points_count"]))
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

    @staticmethod
    def _store_frame(db: sqlite3.Connection, session_id: int, event: dict[str, Any]) -> None:
        for ccd in event["ccds"]:
            points = [int(value) for value in ccd["points"]]
            blob = _pack(points)
            db.execute(
                (
                    "INSERT INTO mercury_frames(session_id, phase, frame_index, ccd_index, "
                    "points_blob, points_count, points_sha256, frame_sha256, virtual_time_ms, "
                    "captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    session_id,
                    event["phase"],
                    event["frame_index"],
                    ccd["ccd_index"],
                    blob,
                    len(points),
                    _sha(blob),
                    event["frame_sha256"],
                    event["virtual_time_ms"],
                    utc_now(),
                ),
            )

    def _analyze(
        self, db: sqlite3.Connection, session: sqlite3.Row, event: dict[str, Any], actor: int | None
    ) -> dict[str, Any]:
        by_ccd = {int(item["ccd_index"]): item["points"] for item in event["ccds"]}
        offsets: list[float] = []
        located: list[dict[str, Any]] = []
        for line in self._lines(db, int(session["id"])):
            points = by_ccd.get(int(line["expected_ccd_index"]), [])
            peak = _locate(points, float(line["expected_position"]), int(session["search_radius_points"]))
            if peak is None:
                db.execute("UPDATE mercury_session_lines SET state='not_found' WHERE id=?", (line["id"],))
                continue
            position, value = peak
            offset = float(position) - float(line["expected_position"])
            offsets.append(offset)
            located.append(
                {
                    "line_id": line["id"],
                    "wavelength_nm": line["wavelength_nm"],
                    "expected_position": line["expected_position"],
                    "observed_position": position,
                    "offset_points": offset,
                }
            )
            db.execute(
                (
                    "UPDATE mercury_session_lines SET observed_ccd_index=?, observed_position=?, "
                    "peak_value=?, offset_points=?, state='located' WHERE id=?"
                ),
                (line["expected_ccd_index"], position, value, offset, line["id"]),
            )
        total = int(
            db.execute("SELECT COUNT(*) FROM mercury_session_lines WHERE session_id=?", (session["id"],)).fetchone()[0]
        )
        if len(offsets) != total:
            raise MercuryError(
                "mercury_peak_not_found",
                "one or more selected mercury peaks were not located",
                details={"located": len(offsets), "selected": total},
                status_code=409,
            )
        median, suggestion, before_rms, after_offsets, after_rms, maximum_before, maximum_after = offset_statistics(offsets, float(session["correction_limit_points"]))
        before = db.execute(
            "SELECT * FROM mercury_alignment_versions WHERE id=?", (session["before_version_id"],)
        ).fetchone()
        if before is None:
            raise MercuryError("mercury_alignment_missing", "before alignment version was not found", status_code=409)
        candidate_offset = float(before["offset_points"]) + suggestion
        next_version = int(
            db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM mercury_alignment_versions WHERE device_profile_id=? AND ccd_layout_id=?",
                (session["device_profile_id"], session["ccd_layout_id"]),
            ).fetchone()[0]
        )
        snapshot = {
            "kind": "mercury_optical_alignment",
            "session_id": session["id"],
            "parent_version_id": before["id"],
            "offset_points": candidate_offset,
            "suggestion_points": suggestion,
            "before_rms": before_rms,
            "after_rms": after_rms,
            "max_before_offset": maximum_before,
            "max_after_offset": maximum_after,
            "lines": located,
        }
        snapshot_json = _json(snapshot)
        cursor = db.execute(
            (
                "INSERT INTO mercury_alignment_versions(device_profile_id, ccd_layout_id, "
                "version, source_session_id, parent_version_id, offset_points, before_rms, "
                "after_rms, max_before_offset, max_after_offset, point_count, snapshot_json, "
                "snapshot_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?)"
            ),
            (
                session["device_profile_id"],
                session["ccd_layout_id"],
                next_version,
                session["id"],
                before["id"],
                candidate_offset,
                before_rms,
                after_rms,
                maximum_before,
                maximum_after,
                len(offsets),
                snapshot_json,
                _sha(snapshot_json),
                actor,
                utc_now(),
            ),
        )
        candidate_id = int(cursor.lastrowid)
        for item, after_offset in zip(located, after_offsets, strict=True):
            db.execute(
                "UPDATE mercury_session_lines SET after_offset_points=? WHERE id=?", (after_offset, item["line_id"])
            )
        analysis = {
            "line_count": len(offsets),
            "median_offset_points": median,
            "suggestion_points": suggestion,
            "before_rms": before_rms,
            "after_rms": after_rms,
            "max_before_offset": maximum_before,
            "max_after_offset": maximum_after,
            "within_tolerance": maximum_after <= float(session["tolerance_points"]),
            "candidate_version_id": candidate_id,
        }
        db.execute(
            (
                "UPDATE mercury_sessions SET status='ready', candidate_version_id=?, "
                "analysis_json=?, last_message=?, updated_at=? WHERE id=?"
            ),
            (candidate_id, _json(analysis), "峰位分析完成，等待应用或停止", utc_now(), session["id"]),
        )
        self._message(
            db,
            int(session["id"]),
            "success",
            "calibration.suggested",
            "mercury peak offset and optical correction suggestion calculated",
            analysis,
        )
        self._audit(db, actor, "mercury.calibration.suggest", int(session["id"]), analysis)
        return analysis
