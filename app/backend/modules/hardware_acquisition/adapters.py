from __future__ import annotations
from typing import Any
from ..devices import AcqSimulatorAdapter, DeviceError
from .values import HardwareError
import math
import hashlib
import struct


class SimulatorTurnAdapter:
    """Turn adapter backed only by the S11 deterministic simulator."""

    def __init__(self) -> None:
        self.acquisition = AcqSimulatorAdapter()
        self.session_id: str | None = None
        self.profile: dict[str, Any] | None = None

    def connect(self, profile: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        try:
            event = self.acquisition.connect(profile, correlation_id=correlation_id)
        except DeviceError as exc:
            raise HardwareError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        self.profile = dict(profile)
        return event.to_dict()

    def pre_excitation(self, *, sample: str, seed: int, correlation_id: str) -> dict[str, Any]:
        try:
            event = self.acquisition.start_debug(
                sample=sample, seed=seed, fault_frame=None, correlation_id=correlation_id
            )
        except DeviceError as exc:
            raise HardwareError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        self.session_id = self.acquisition.session_id
        return event.to_dict()

    def turn(self, *, angle_deg: float, correlation_id: str) -> dict[str, Any]:
        if self.acquisition.state.value != "debugging":
            raise HardwareError("hardware_session_not_running", "simulator session is not active", status_code=409)
        return {
            "event_type": "turn_complete",
            "angle_deg": angle_deg,
            "correlation_id": correlation_id,
            "simulated": True,
        }

    def capture(self, *, correlation_id: str, observation: dict[str, Any] | None = None,
                anomalies: list[str] | None = None) -> dict[str, Any]:
        try:
            event = self.acquisition.step_debug(correlation_id=correlation_id)
        except DeviceError as exc:
            raise HardwareError(exc.code, exc.message, details=exc.detail(), status_code=exc.status_code) from exc
        result = event.to_dict()
        if observation is not None:
            # 转角模拟帧明确生成两条独立谱线，异常作用于点值，检测器不读取理想指标。
            faults = set(anomalies or [])
            baseline = float(observation.get('expected_baseline_position', 256)) + (50 if 'baseline_shift' in faults else 0)
            peak = float(observation['expected_peak_position']) + (50 if 'peak_shift' in faults else 0)
            amplitude = 0 if 'baseline_low' in faults else 65000 if 'baseline_high' in faults else 1000
            for ccd in result.get('ccds', []):
                ccd['points'] = [min(65535, round(amplitude * math.exp(-((i - baseline) / 3) ** 2)
                                               + 3000 * math.exp(-((i - peak) / 3) ** 2)))
                                 for i in range(len(ccd['points']))]
            generated = b''.join(struct.pack(f"<{len(ccd['points'])}H", *ccd['points']) for ccd in result.get('ccds', []))
            result['details'] = {'source': 'synthetic_turn_spectrum_v1', 'parent_acq_sha256': result.get('details', {}).get('sha256'),
                                 'sha256': hashlib.sha256(generated).hexdigest(), 'byte_length': len(generated)}
        return result

    def close(self, correlation_id: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            events.append(self.acquisition.stop_debug(correlation_id=correlation_id).to_dict())
            events.append(self.acquisition.disconnect(correlation_id=correlation_id).to_dict())
        except DeviceError as exc:
            events.append({"event_type": "close_error", "code": exc.code, "message": exc.message})
        self.session_id = None
        return events


class SerialTurnAdapter:
    """Explicit protocol gate. No guessed command bytes are ever emitted."""

    def connect(self, profile: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        raise HardwareError(
            "hardware_protocol_unavailable",
            "real serial/turn protocol documentation or capture is not available",
            details={
                "transport": "serial",
                "port": profile.get("port"),
                "baud_rate": profile.get("baud_rate"),
                "correlation_id": correlation_id,
            },
            status_code=409,
            deferred_external=True,
        )

    def close(self, correlation_id: str) -> list[dict[str, Any]]:
        return [
            {"event_type": "serial_close_skipped", "correlation_id": correlation_id, "reason": "protocol_unavailable"}
        ]
