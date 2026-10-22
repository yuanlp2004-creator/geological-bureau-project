from __future__ import annotations
import json
import uuid
from typing import Any
from ...db import Database, utc_now
from .profiles import screen_conversion, validate_profile
from .simulator import AcqSimulatorAdapter
from .values import DeviceError


class DeviceService:
    def __init__(self, database: Database):
        self.database = database
        self.adapter = AcqSimulatorAdapter()


    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["ccd_indices"] = json.loads(result.pop("ccd_indices_json"))
        result["mirror"] = bool(result["mirror"])
        result["enabled"] = bool(result["enabled"])
        result["screen_conversion"] = screen_conversion(result)
        return result

    def profiles(self) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._serialize(row) for row in db.execute("SELECT * FROM device_profiles ORDER BY id").fetchall()]

    def profile(self, profile_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM device_profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            raise DeviceError(
                "device_profile_not_found",
                "Device profile was not found",
                details={"profile_id": profile_id},
                status_code=404,
            )
        return self._serialize(row)

    def create_profile(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        normalized = validate_profile(payload)
        now = utc_now()
        try:
            with self.database.write() as db:
                cursor = db.execute(
                    (
                        "INSERT INTO device_profiles(name, transport, port, baud_rate, mirror, "
                        "frame_count, ccds_per_frame, points_per_ccd, ccd_indices_json, point_width_um, "
                        "protection_time_ms, screen_width_mm, screen_resolution_px, enabled, created_at, "
                        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    (
                        normalized["name"],
                        normalized["transport"],
                        normalized["port"],
                        normalized["baud_rate"],
                        int(normalized["mirror"]),
                        normalized["frame_count"],
                        normalized["ccds_per_frame"],
                        normalized["points_per_ccd"],
                        json.dumps(normalized["ccd_indices"], separators=(",", ":")),
                        normalized["point_width_um"],
                        normalized["protection_time_ms"],
                        normalized["screen_width_mm"],
                        normalized["screen_resolution_px"],
                        int(normalized["enabled"]),
                        now,
                        now,
                    ),
                )
                profile_id = int(cursor.lastrowid)
                db.execute(
                    (
                        "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                        "details_json, created_at) VALUES (?, 'device_profile.create', 'device_profile', "
                        "?, ?, ?)"
                    ),
                    (actor_user_id, profile_id, json.dumps({"name": normalized["name"]}, ensure_ascii=False), now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DeviceError(
                    "device_profile_duplicate", "A device profile with this name already exists", status_code=409
                ) from exc
            raise
        return self.profile(profile_id)

    def update_profile(
        self, profile_id: int, payload: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        current = self.profile(profile_id)
        merged = {**current, **payload}
        normalized = validate_profile(merged)
        now = utc_now()
        try:
            with self.database.write() as db:
                db.execute(
                    (
                        "UPDATE device_profiles SET name=?, transport=?, port=?, baud_rate=?, mirror=?, "
                        "frame_count=?, ccds_per_frame=?, points_per_ccd=?, ccd_indices_json=?, "
                        "point_width_um=?, protection_time_ms=?, screen_width_mm=?, "
                        "screen_resolution_px=?, enabled=?, updated_at=? WHERE id=?"
                    ),
                    (
                        normalized["name"],
                        normalized["transport"],
                        normalized["port"],
                        normalized["baud_rate"],
                        int(normalized["mirror"]),
                        normalized["frame_count"],
                        normalized["ccds_per_frame"],
                        normalized["points_per_ccd"],
                        json.dumps(normalized["ccd_indices"], separators=(",", ":")),
                        normalized["point_width_um"],
                        normalized["protection_time_ms"],
                        normalized["screen_width_mm"],
                        normalized["screen_resolution_px"],
                        int(normalized["enabled"]),
                        now,
                        profile_id,
                    ),
                )
                db.execute(
                    (
                        "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                        "details_json, created_at) VALUES (?, 'device_profile.update', 'device_profile', "
                        "?, ?, ?)"
                    ),
                    (actor_user_id, profile_id, json.dumps({"changed": sorted(payload)}, ensure_ascii=False), now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DeviceError(
                    "device_profile_duplicate", "A device profile with this name already exists", status_code=409
                ) from exc
            raise
        return self.profile(profile_id)

    def connect(self, profile_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        profile = self.profile(profile_id)
        correlation_id = str(uuid.uuid4())
        try:
            event = self.adapter.connect(profile, correlation_id=correlation_id)
        except DeviceError as exc:
            exc.details.setdefault("correlation_id", correlation_id)
            self._audit(
                actor_user_id, "device.connect.failed", profile_id, {**exc.detail(), "correlation_id": correlation_id}
            )
            raise
        self._audit(
            actor_user_id,
            "device.connect",
            profile_id,
            {"state": event.state.value, "correlation_id": correlation_id, "transport": profile["transport"]},
        )
        return {"profile": profile, "diagnostics": self.adapter.diagnostics(), "event": event.to_dict()}

    def disconnect(self, actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        event = self.adapter.disconnect(correlation_id=correlation_id)
        self._audit(
            actor_user_id, "device.disconnect", None, {"state": event.state.value, "correlation_id": correlation_id}
        )
        return {"diagnostics": self.adapter.diagnostics(), "event": event.to_dict()}

    def start_debug(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        try:
            event = self.adapter.start_debug(
                sample=str(payload.get("sample", "280-288.acq")),
                seed=int(payload.get("seed", 0)),
                fault_frame=payload.get("fault_frame"),
                correlation_id=correlation_id,
            )
        except DeviceError as exc:
            exc.details.setdefault("correlation_id", correlation_id)
            self._audit(actor_user_id, "device.debug.failed", None, {**exc.detail(), "correlation_id": correlation_id})
            raise
        self._audit(
            actor_user_id,
            "device.debug.start",
            None,
            {
                "session_id": self.adapter.session_id,
                "sample": payload.get("sample", "280-288.acq"),
                "seed": int(payload.get("seed", 0)),
                "correlation_id": correlation_id,
            },
        )
        return {
            "session_id": self.adapter.session_id,
            "event": event.to_dict(),
            "diagnostics": self.adapter.diagnostics(),
            "sample_records_created": 0,
            "spectrum_records_created": 0,
        }

    def step_debug(self, actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        event = self.adapter.step_debug(correlation_id=correlation_id)
        if event.event_type == "fault":
            self._audit(actor_user_id, "device.debug.fault", None, {**event.details, "correlation_id": correlation_id})
        else:
            self._audit(
                actor_user_id,
                "device.debug.step",
                None,
                {"frame_index": event.frame_index, "correlation_id": correlation_id},
            )
        return {
            "session_id": self.adapter.session_id,
            "event": event.to_dict(),
            "diagnostics": self.adapter.diagnostics(),
            "sample_records_created": 0,
            "spectrum_records_created": 0,
        }

    def stop_debug(self, actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        event = self.adapter.stop_debug(correlation_id=correlation_id)
        self._audit(
            actor_user_id, "device.debug.stop", None, {"state": event.state.value, "correlation_id": correlation_id}
        )
        return {
            "event": event.to_dict(),
            "diagnostics": self.adapter.diagnostics(),
            "sample_records_created": 0,
            "spectrum_records_created": 0,
        }

    def _audit(self, actor_user_id: int | None, action: str, target_id: int | None, details: dict[str, Any]) -> None:
        with self.database.write() as db:
            db.execute(
                (
                    "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, "
                    "details_json, created_at) VALUES (?, ?, 'device', ?, ?, ?)"
                ),
                (
                    actor_user_id,
                    action,
                    target_id,
                    json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                    utc_now(),
                ),
            )
