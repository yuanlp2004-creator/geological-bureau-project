from __future__ import annotations

import hashlib
import json
import math
import struct
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Iterator, Protocol

from ..db import Database, utc_now


ACQ_FRAME_COUNT = 3
ACQ_CCDS_PER_FRAME = 2
ACQ_POINTS_PER_CCD = 2048
ACQ_FRAME_BYTES = 1 + ACQ_CCDS_PER_FRAME * ACQ_POINTS_PER_CCD * 2
ACQ_BYTES = ACQ_FRAME_COUNT * ACQ_FRAME_BYTES
ACQ_HEADER_GOOD = 0
DEFAULT_CCD_INDICES = [0, 1, 2, 4, 5]
DEFAULT_BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]


class AcquisitionState(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEBUGGING = "debugging"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class DeviceEvent:
    """Versioned event emitted by a device adapter.

    The event deliberately contains no sample identifiers.  Debug sessions are
    an instrument diagnostic stream and must never become sample records.
    """

    event_type: str
    state: AcquisitionState
    occurred_at: str = field(default_factory=utc_now)
    correlation_id: str = ""
    frame_index: int | None = None
    frame_count: int | None = None
    ccds: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "state": self.state.value,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
            "frame_index": self.frame_index,
            "frame_count": self.frame_count,
            "ccds": self.ccds,
            "message": self.message,
            "details": self.details,
        }


class DeviceError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _finite_number(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DeviceError("device_profile_invalid", f"{field_name} must be numeric", details={"field": field_name}) from exc
    if not math.isfinite(number):
        raise DeviceError("device_profile_invalid", f"{field_name} must be finite", details={"field": field_name})
    return number


def validate_profile(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Normalize and validate profile values at the domain boundary."""

    result = dict(payload)
    if not partial or "name" in result:
        name = str(result.get("name", "")).strip()
        if not 1 <= len(name) <= 100:
            raise DeviceError("device_profile_invalid", "name must contain 1 to 100 characters", details={"field": "name"})
        result["name"] = name
    if not partial or "transport" in result:
        transport = str(result.get("transport", "simulator")).lower()
        if transport not in {"simulator", "serial"}:
            raise DeviceError("device_profile_invalid", "transport must be simulator or serial", details={"field": "transport"})
        result["transport"] = transport
    if not partial or "port" in result:
        port = int(result.get("port", 3))
        if not 1 <= port <= 256:
            raise DeviceError("device_profile_invalid", "port must be between 1 and 256", details={"field": "port"})
        result["port"] = port
    if not partial or "baud_rate" in result:
        baud = int(result.get("baud_rate", 460800))
        if baud not in DEFAULT_BAUD_RATES:
            raise DeviceError("device_profile_invalid", "unsupported baud rate", details={"field": "baud_rate", "allowed": DEFAULT_BAUD_RATES})
        result["baud_rate"] = baud
    if not partial or "frame_count" in result:
        frame_count = int(result.get("frame_count", ACQ_FRAME_COUNT))
        if not 1 <= frame_count <= 32:
            raise DeviceError("device_profile_invalid", "frame_count must be between 1 and 32", details={"field": "frame_count"})
        result["frame_count"] = frame_count
    if not partial or "ccds_per_frame" in result:
        ccds_per_frame = int(result.get("ccds_per_frame", ACQ_CCDS_PER_FRAME))
        if not 1 <= ccds_per_frame <= 8:
            raise DeviceError("device_profile_invalid", "ccds_per_frame must be between 1 and 8", details={"field": "ccds_per_frame"})
        result["ccds_per_frame"] = ccds_per_frame
    if not partial or "points_per_ccd" in result:
        points = int(result.get("points_per_ccd", ACQ_POINTS_PER_CCD))
        if not 1 <= points <= 4096:
            raise DeviceError("device_profile_invalid", "points_per_ccd must be between 1 and 4096", details={"field": "points_per_ccd"})
        result["points_per_ccd"] = points
    volume = int(result.get("frame_count", ACQ_FRAME_COUNT)) * int(result.get("ccds_per_frame", ACQ_CCDS_PER_FRAME))
    if not partial or "ccd_indices" in result or "selected_ccds" in result:
        if "ccd_indices" in result:
            raw_indices = result["ccd_indices"]
        elif "selected_ccds" in result:
            raw_indices = result["selected_ccds"]
        else:
            raw_indices = DEFAULT_CCD_INDICES if volume >= len(DEFAULT_CCD_INDICES) + 1 else list(range(volume))
        try:
            indices = [int(item) for item in raw_indices]
        except (TypeError, ValueError) as exc:
            raise DeviceError("device_profile_invalid", "ccd_indices must be integers", details={"field": "ccd_indices"}) from exc
        if len(indices) != len(set(indices)) or not indices or any(item < 0 or item >= volume for item in indices):
            raise DeviceError("device_profile_invalid", "ccd_indices contains a duplicate or out-of-range index", details={"field": "ccd_indices", "volume": volume})
        result["ccd_indices"] = indices
    for field_name, default, minimum, maximum in (
        ("point_width_um", 14.0, 0.001, 1000.0),
        ("protection_time_ms", 200.0, 0.0, 60_000.0),
        ("screen_width_mm", 40.92, 1.0, 10_000.0),
    ):
        if not partial or field_name in result:
            number = _finite_number(result.get(field_name, default), field_name)
            if number < minimum or number > maximum:
                raise DeviceError("device_profile_invalid", f"{field_name} is outside the supported range", details={"field": field_name})
            result[field_name] = number
    if not partial or "screen_resolution_px" in result:
        resolution = int(result.get("screen_resolution_px", 1920))
        if not 320 <= resolution <= 16_000:
            raise DeviceError("device_profile_invalid", "screen_resolution_px is outside the supported range", details={"field": "screen_resolution_px"})
        result["screen_resolution_px"] = resolution
    if not partial or "mirror" in result:
        result["mirror"] = bool(result.get("mirror", False))
    if not partial or "enabled" in result:
        result["enabled"] = bool(result.get("enabled", True))
    return result


def screen_conversion(profile: dict[str, Any]) -> dict[str, float]:
    profile = validate_profile(profile)
    pixels_per_mm = profile["screen_resolution_px"] / profile["screen_width_mm"]
    return {
        "pixels_per_mm": pixels_per_mm,
        "um_per_pixel": 1000.0 / pixels_per_mm,
        "point_width_px": profile["point_width_um"] / 1000.0 * pixels_per_mm,
    }


def _ccd_points(raw_frames: list[list[int]], ccd_index: int, *, frame_count: int, ccds_per_frame: int, points_per_ccd: int, mirror: bool) -> list[int]:
    volume = frame_count * ccds_per_frame
    if ccd_index < 0 or ccd_index >= volume:
        raise DeviceError("ccd_index_invalid", "CCD index is outside the frame layout", details={"ccd_index": ccd_index, "volume": volume})
    if mirror:
        frame_index = ccd_index // ccds_per_frame
        slot = ccd_index % ccds_per_frame
        values = [raw_frames[frame_index][ccds_per_frame * point + slot] for point in range(points_per_ccd)]
        return list(reversed(values))
    frame_index = (volume - (ccd_index + 1)) // ccds_per_frame
    slot = (ccds_per_frame - 1) - ccd_index % ccds_per_frame
    return [raw_frames[frame_index][ccds_per_frame * point + slot] for point in range(points_per_ccd)]


def parse_acq_frame(
    payload: bytes,
    *,
    frame_count: int = ACQ_FRAME_COUNT,
    ccds_per_frame: int = ACQ_CCDS_PER_FRAME,
    points_per_ccd: int = ACQ_POINTS_PER_CCD,
    mirror: bool = False,
    ccd_indices: list[int] | None = None,
) -> dict[str, Any]:
    """Parse one legacy ACQ transfer without allocating an unbounded buffer."""

    if frame_count < 1 or ccds_per_frame < 1 or points_per_ccd < 1:
        raise DeviceError("acq_layout_invalid", "ACQ layout dimensions must be positive")
    frame_size = 1 + ccds_per_frame * points_per_ccd * 2
    expected = frame_count * frame_size
    if len(payload) != expected:
        offset = min(len(payload), expected)
        raw_header = payload[offset] if offset < len(payload) else None
        raise DeviceError("acq_frame_incomplete", "ACQ frame length does not match the selected layout", details={"offset": offset, "expected": expected, "actual": len(payload), "raw_header": raw_header})
    raw_frames: list[list[int]] = []
    headers: list[int] = []
    for frame_index in range(frame_count):
        offset = frame_index * frame_size
        header = payload[offset]
        headers.append(header)
        if header != ACQ_HEADER_GOOD:
            raise DeviceError("acq_frame_header_invalid", "ACQ frame header indicates a CCD checksum/fault error", details={"offset": offset, "frame_index": frame_index, "raw_header": header})
        count = ccds_per_frame * points_per_ccd
        raw_frames.append(list(struct.unpack_from(f"<{count}H", payload, offset + 1)))
    volume = frame_count * ccds_per_frame
    selected = ccd_indices if ccd_indices is not None else list(range(volume))
    normalized = validate_profile({"name": "_acq", "frame_count": frame_count, "ccds_per_frame": ccds_per_frame, "points_per_ccd": points_per_ccd, "ccd_indices": selected, "mirror": mirror}, partial=False)
    ccds: list[dict[str, Any]] = []
    for ccd_index in normalized["ccd_indices"]:
        points = _ccd_points(raw_frames, ccd_index, frame_count=frame_count, ccds_per_frame=ccds_per_frame, points_per_ccd=points_per_ccd, mirror=mirror)
        peak = max(points)
        ccds.append({"ccd_index": ccd_index, "points": points, "peak": peak, "peak_position": points.index(peak)})
    return {
        "frame_count": frame_count,
        "ccds_per_frame": ccds_per_frame,
        "points_per_ccd": points_per_ccd,
        "frame_size": frame_size,
        "byte_length": len(payload),
        "headers": headers,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mirror": mirror,
        "ccd_indices": normalized["ccd_indices"],
        "ccds": ccds,
        "raw_frames": raw_frames,
    }


class DeviceAdapter(Protocol):
    def connect(self, profile: dict[str, Any], *, correlation_id: str) -> DeviceEvent: ...
    def disconnect(self, *, correlation_id: str) -> DeviceEvent: ...
    def start_debug(self, *, sample: str, seed: int, fault_frame: int | None, correlation_id: str) -> DeviceEvent: ...
    def step_debug(self, *, correlation_id: str) -> DeviceEvent: ...
    def stop_debug(self, *, correlation_id: str) -> DeviceEvent: ...


def _bundled_sample(name: str) -> Traversable:
    safe_name = Path(name).name
    if safe_name not in {"280-288.acq", "291-299.acq", "303-310.acq"}:
        raise DeviceError("acq_sample_not_allowed", "Only bundled ACQ simulator samples are available", details={"sample": safe_name})
    resource = files("backend.app.resources.simulator").joinpath(safe_name)
    if not resource.is_file():
        raise DeviceError("acq_sample_missing", "Bundled ACQ simulator sample is missing", details={"sample": safe_name})
    return resource


class AcqSimulatorAdapter:
    """Deterministic adapter for the legacy 24,579 byte CCD frame."""

    def __init__(self) -> None:
        self.state = AcquisitionState.IDLE
        self.profile: dict[str, Any] | None = None
        self.session_id: str | None = None
        self._payload: bytes | None = None
        self._frame: dict[str, Any] | None = None
        self._frame_index = 0
        self._fault_frame: int | None = None
        self._seed = 0
        self._lock = threading.Lock()

    def connect(self, profile: dict[str, Any], *, correlation_id: str) -> DeviceEvent:
        with self._lock:
            normalized = validate_profile(profile)
            if normalized["transport"] != "simulator":
                raise DeviceError("device_transport_unavailable", "The S11 simulator cannot open a real serial port", status_code=409)
            self.state = AcquisitionState.CONNECTED
            self.profile = normalized
            return DeviceEvent("connected", self.state, correlation_id=correlation_id, message="模拟设备已连接", details={"profile_id": normalized.get("id")})

    def disconnect(self, *, correlation_id: str) -> DeviceEvent:
        with self._lock:
            self.state = AcquisitionState.IDLE
            self.session_id = None
            self._payload = None
            self._frame = None
            return DeviceEvent("disconnected", self.state, correlation_id=correlation_id, message="设备已断开")

    def start_debug(self, *, sample: str, seed: int, fault_frame: int | None, correlation_id: str) -> DeviceEvent:
        with self._lock:
            if self.state not in {AcquisitionState.CONNECTED, AcquisitionState.DEBUGGING} or self.profile is None:
                raise DeviceError("device_not_connected", "Connect a simulator profile before starting debug", status_code=409)
            path = _bundled_sample(sample)
            payload = path.read_bytes()
            profile = self.profile
            parsed = parse_acq_frame(payload, frame_count=profile["frame_count"], ccds_per_frame=profile["ccds_per_frame"], points_per_ccd=profile["points_per_ccd"], mirror=profile["mirror"], ccd_indices=profile["ccd_indices"])
            self.session_id = str(uuid.uuid4())
            self._payload = payload
            self._frame = parsed
            self._frame_index = 0
            self._fault_frame = fault_frame
            self._seed = int(seed)
            self.state = AcquisitionState.DEBUGGING
            return self._frame_event("frame", correlation_id=correlation_id, message="实时调试已开始")

    def _frame_event(self, event_type: str, *, correlation_id: str, message: str = "") -> DeviceEvent:
        assert self._frame is not None
        details = {key: self._frame[key] for key in ("sha256", "frame_size", "byte_length", "headers", "mirror", "ccd_indices")}
        details["seed"] = self._seed
        details["virtual_time_ms"] = self._frame_index * 1000
        return DeviceEvent(event_type, self.state, correlation_id=correlation_id, frame_index=self._frame_index, frame_count=self._frame["frame_count"], ccds=self._frame["ccds"], message=message, details=details)

    def step_debug(self, *, correlation_id: str) -> DeviceEvent:
        with self._lock:
            if self.state != AcquisitionState.DEBUGGING or self._frame is None:
                raise DeviceError("debug_session_not_running", "No active real-time debug session", status_code=409)
            if self._fault_frame is not None and self._frame_index >= self._fault_frame:
                self.state = AcquisitionState.ERROR
                return DeviceEvent("fault", self.state, correlation_id=correlation_id, frame_index=self._frame_index, message="模拟 CCD 传输故障", details={"code": "simulated_fault", "frame_index": self._frame_index})
            self._frame_index += 1
            return self._frame_event("frame", correlation_id=correlation_id)

    def stop_debug(self, *, correlation_id: str) -> DeviceEvent:
        with self._lock:
            if self.state in {AcquisitionState.IDLE, AcquisitionState.CONNECTED}:
                return DeviceEvent("stopped", self.state, correlation_id=correlation_id, message="调试已停止")
            self.state = AcquisitionState.STOPPING
            event = DeviceEvent("stopped", AcquisitionState.CONNECTED, correlation_id=correlation_id, frame_index=self._frame_index, message="实时调试已停止")
            self.state = AcquisitionState.CONNECTED
            self.session_id = None
            self._payload = None
            self._frame = None
            return event

    def diagnostics(self) -> dict[str, Any]:
        return {"adapter": "acq-simulator", "state": self.state.value, "session_id": self.session_id, "connected": self.state in {AcquisitionState.CONNECTED, AcquisitionState.DEBUGGING}, "contract": {"frame_count": ACQ_FRAME_COUNT, "ccds_per_frame": ACQ_CCDS_PER_FRAME, "points_per_ccd": ACQ_POINTS_PER_CCD, "frame_size": ACQ_FRAME_BYTES, "byte_length": ACQ_BYTES}}


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
            raise DeviceError("device_profile_not_found", "Device profile was not found", details={"profile_id": profile_id}, status_code=404)
        return self._serialize(row)

    def create_profile(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        normalized = validate_profile(payload)
        now = utc_now()
        try:
            with self.database.write() as db:
                cursor = db.execute("INSERT INTO device_profiles(name, transport, port, baud_rate, mirror, frame_count, ccds_per_frame, points_per_ccd, ccd_indices_json, point_width_um, protection_time_ms, screen_width_mm, screen_resolution_px, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (normalized["name"], normalized["transport"], normalized["port"], normalized["baud_rate"], int(normalized["mirror"]), normalized["frame_count"], normalized["ccds_per_frame"], normalized["points_per_ccd"], json.dumps(normalized["ccd_indices"], separators=(",", ":")), normalized["point_width_um"], normalized["protection_time_ms"], normalized["screen_width_mm"], normalized["screen_resolution_px"], int(normalized["enabled"]), now, now))
                profile_id = int(cursor.lastrowid)
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'device_profile.create', 'device_profile', ?, ?, ?)", (actor_user_id, profile_id, json.dumps({"name": normalized["name"]}, ensure_ascii=False), now))
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DeviceError("device_profile_duplicate", "A device profile with this name already exists", status_code=409) from exc
            raise
        return self.profile(profile_id)

    def update_profile(self, profile_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        current = self.profile(profile_id)
        merged = {**current, **payload}
        normalized = validate_profile(merged)
        now = utc_now()
        try:
            with self.database.write() as db:
                db.execute("UPDATE device_profiles SET name=?, transport=?, port=?, baud_rate=?, mirror=?, frame_count=?, ccds_per_frame=?, points_per_ccd=?, ccd_indices_json=?, point_width_um=?, protection_time_ms=?, screen_width_mm=?, screen_resolution_px=?, enabled=?, updated_at=? WHERE id=?", (normalized["name"], normalized["transport"], normalized["port"], normalized["baud_rate"], int(normalized["mirror"]), normalized["frame_count"], normalized["ccds_per_frame"], normalized["points_per_ccd"], json.dumps(normalized["ccd_indices"], separators=(",", ":")), normalized["point_width_um"], normalized["protection_time_ms"], normalized["screen_width_mm"], normalized["screen_resolution_px"], int(normalized["enabled"]), now, profile_id))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'device_profile.update', 'device_profile', ?, ?, ?)", (actor_user_id, profile_id, json.dumps({"changed": sorted(payload)}, ensure_ascii=False), now))
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise DeviceError("device_profile_duplicate", "A device profile with this name already exists", status_code=409) from exc
            raise
        return self.profile(profile_id)

    def connect(self, profile_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        profile = self.profile(profile_id)
        correlation_id = str(uuid.uuid4())
        try:
            event = self.adapter.connect(profile, correlation_id=correlation_id)
        except DeviceError as exc:
            exc.details.setdefault("correlation_id", correlation_id)
            self._audit(actor_user_id, "device.connect.failed", profile_id, {**exc.detail(), "correlation_id": correlation_id})
            raise
        self._audit(actor_user_id, "device.connect", profile_id, {"state": event.state.value, "correlation_id": correlation_id, "transport": profile["transport"]})
        return {"profile": profile, "diagnostics": self.adapter.diagnostics(), "event": event.to_dict()}

    def disconnect(self, actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        event = self.adapter.disconnect(correlation_id=correlation_id)
        self._audit(actor_user_id, "device.disconnect", None, {"state": event.state.value, "correlation_id": correlation_id})
        return {"diagnostics": self.adapter.diagnostics(), "event": event.to_dict()}

    def start_debug(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        try:
            event = self.adapter.start_debug(sample=str(payload.get("sample", "280-288.acq")), seed=int(payload.get("seed", 0)), fault_frame=payload.get("fault_frame"), correlation_id=correlation_id)
        except DeviceError as exc:
            exc.details.setdefault("correlation_id", correlation_id)
            self._audit(actor_user_id, "device.debug.failed", None, {**exc.detail(), "correlation_id": correlation_id})
            raise
        self._audit(actor_user_id, "device.debug.start", None, {"session_id": self.adapter.session_id, "sample": payload.get("sample", "280-288.acq"), "seed": int(payload.get("seed", 0)), "correlation_id": correlation_id})
        return {"session_id": self.adapter.session_id, "event": event.to_dict(), "diagnostics": self.adapter.diagnostics(), "sample_records_created": 0, "spectrum_records_created": 0}

    def step_debug(self, actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        event = self.adapter.step_debug(correlation_id=correlation_id)
        if event.event_type == "fault":
            self._audit(actor_user_id, "device.debug.fault", None, {**event.details, "correlation_id": correlation_id})
        else:
            self._audit(actor_user_id, "device.debug.step", None, {"frame_index": event.frame_index, "correlation_id": correlation_id})
        return {"session_id": self.adapter.session_id, "event": event.to_dict(), "diagnostics": self.adapter.diagnostics(), "sample_records_created": 0, "spectrum_records_created": 0}

    def stop_debug(self, actor_user_id: int | None = None) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        event = self.adapter.stop_debug(correlation_id=correlation_id)
        self._audit(actor_user_id, "device.debug.stop", None, {"state": event.state.value, "correlation_id": correlation_id})
        return {"event": event.to_dict(), "diagnostics": self.adapter.diagnostics(), "sample_records_created": 0, "spectrum_records_created": 0}

    def _audit(self, actor_user_id: int | None, action: str, target_id: int | None, details: dict[str, Any]) -> None:
        with self.database.write() as db:
            db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'device', ?, ?, ?)", (actor_user_id, action, target_id, json.dumps(details, ensure_ascii=False, separators=(",", ":")), utc_now()))
