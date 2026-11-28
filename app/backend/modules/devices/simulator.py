from __future__ import annotations
import threading
import time
import uuid
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any
from .profiles import validate_profile
from .protocol import parse_acq_frame
from .values import ACQ_BYTES, ACQ_CCDS_PER_FRAME, ACQ_FRAME_BYTES, ACQ_FRAME_COUNT, ACQ_POINTS_PER_CCD, AcquisitionState, DeviceError, DeviceEvent


def _bundled_sample(name: str) -> Traversable:
    safe_name = Path(name).name
    if safe_name not in {"280-288.acq", "291-299.acq", "303-310.acq"}:
        raise DeviceError(
            "acq_sample_not_allowed", "Only bundled ACQ simulator samples are available", details={"sample": safe_name}
        )
    resource = files("backend.resources.simulator").joinpath(safe_name)
    if not resource.is_file():
        raise DeviceError(
            "acq_sample_missing", "Bundled ACQ simulator sample is missing", details={"sample": safe_name}
        )
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
                raise DeviceError(
                    "device_transport_unavailable", "The S11 simulator cannot open a real serial port", status_code=409
                )
            self.state = AcquisitionState.CONNECTED
            self.profile = normalized
            return DeviceEvent(
                "connected",
                self.state,
                correlation_id=correlation_id,
                message="模拟设备已连接",
                details={"profile_id": normalized.get("id")},
            )

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
                raise DeviceError(
                    "device_not_connected", "Connect a simulator profile before starting debug", status_code=409
                )
            path = _bundled_sample(sample)
            receive_start_ms = time.perf_counter_ns() // 1_000_000
            payload = path.read_bytes()
            profile = self.profile
            parsed = parse_acq_frame(
                payload,
                frame_count=profile["frame_count"],
                ccds_per_frame=profile["ccds_per_frame"],
                points_per_ccd=profile["points_per_ccd"],
                mirror=profile["mirror"],
                ccd_indices=profile["ccd_indices"],
            )
            self.session_id = str(uuid.uuid4())
            self._payload = payload
            self._frame = parsed
            self._frame_index = 0
            self._fault_frame = fault_frame
            self._seed = int(seed)
            self.state = AcquisitionState.DEBUGGING
            return self._frame_event(receive_start_ms, correlation_id=correlation_id, message="实时调试已开始")

    def _frame_event(self, receive_start_ms: int, *, correlation_id: str, message: str = "") -> DeviceEvent:
        assert self._frame is not None
        details = {
            key: self._frame[key] for key in ("sha256", "frame_size", "byte_length", "headers", "mirror", "ccd_indices")
        }
        details["seed"] = self._seed
        details["virtual_time_ms"] = self._frame_index * 1000
        details["transport"] = "simulator"
        details["receive_start_ms"] = receive_start_ms
        details["receive_end_ms"] = time.perf_counter_ns() // 1_000_000
        return DeviceEvent(
            "frame",
            self.state,
            correlation_id=correlation_id,
            frame_index=self._frame_index,
            frame_count=self._frame["frame_count"],
            ccds=self._frame["ccds"],
            message=message,
            details=details,
        )

    def step_debug(self, *, correlation_id: str) -> DeviceEvent:
        with self._lock:
            if self.state != AcquisitionState.DEBUGGING or self._frame is None:
                raise DeviceError("debug_session_not_running", "No active real-time debug session", status_code=409)
            if self._fault_frame is not None and self._frame_index >= self._fault_frame:
                self.state = AcquisitionState.ERROR
                return DeviceEvent(
                    "fault",
                    self.state,
                    correlation_id=correlation_id,
                    frame_index=self._frame_index,
                    message="模拟 CCD 传输故障",
                    details={"code": "simulated_fault", "frame_index": self._frame_index},
                )
            receive_start_ms = time.perf_counter_ns() // 1_000_000
            self._frame_index += 1
            return self._frame_event(receive_start_ms, correlation_id=correlation_id)

    def stop_debug(self, *, correlation_id: str) -> DeviceEvent:
        with self._lock:
            if self.state in {AcquisitionState.IDLE, AcquisitionState.CONNECTED}:
                return DeviceEvent("stopped", self.state, correlation_id=correlation_id, message="调试已停止")
            self.state = AcquisitionState.STOPPING
            event = DeviceEvent(
                "stopped",
                AcquisitionState.CONNECTED,
                correlation_id=correlation_id,
                frame_index=self._frame_index,
                message="实时调试已停止",
            )
            self.state = AcquisitionState.CONNECTED
            self.session_id = None
            self._payload = None
            self._frame = None
            return event

    def position_angle(self, angle: float, correlation_id: str) -> dict[str, Any]:
        if self.state not in {AcquisitionState.CONNECTED, AcquisitionState.DEBUGGING}:
            raise DeviceError("device_not_connected", "请先连接调试设备", status_code=409)
        return {"event_type": "turn_complete", "angle_deg": angle, "correlation_id": correlation_id, "simulated": True}

    def diagnostics(self) -> dict[str, Any]:
        return {
            "adapter": "acq-simulator",
            "state": self.state.value,
            "session_id": self.session_id,
            "connected": self.state in {AcquisitionState.CONNECTED, AcquisitionState.DEBUGGING},
            "contract": {
                "frame_count": ACQ_FRAME_COUNT,
                "ccds_per_frame": ACQ_CCDS_PER_FRAME,
                "points_per_ccd": ACQ_POINTS_PER_CCD,
                "frame_size": ACQ_FRAME_BYTES,
                "byte_length": ACQ_BYTES,
            },
        }


def confirm_simulated_turn(adapter: AcqSimulatorAdapter, angle_deg: float, correlation_id: str) -> dict[str, Any]:
    """Require an active simulator debug session and confirm the exact simulated turn receipt."""
    if adapter.state != AcquisitionState.DEBUGGING:
        raise DeviceError("hardware_session_not_running", "simulator session is not active", status_code=409)
    response = adapter.position_angle(angle_deg, correlation_id)
    if response.get("event_type") != "turn_complete" or response.get("angle_deg") != angle_deg:
        raise DeviceError("sample_turn_unconfirmed", "转角到位未确认，已停止采集", status_code=409)
    return response
