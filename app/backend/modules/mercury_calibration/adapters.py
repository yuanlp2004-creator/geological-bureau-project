from __future__ import annotations
import math
import random
import uuid
from typing import Any, Protocol
from .codec import _pack
from .values import MercuryError, _sha


class MercuryAdapter(Protocol):
    session_id: str | None

    def start(self, *, correlation_id: str) -> dict[str, Any]: ...

    def frame(self, *, frame_index: int, phase: str, correlation_id: str) -> dict[str, Any]: ...

    def close(self, *, correlation_id: str) -> dict[str, Any]: ...


class MercurySpectrumSimulatorAdapter:
    """Synthetic spectral source; it never represents a physical lamp switch."""

    def __init__(
        self,
        *,
        layout: dict[str, Any],
        lines: list[dict[str, Any]],
        active_offset: float,
        physical_offset: float,
        seed: int,
        fault: str,
    ) -> None:
        self.layout = layout
        self.lines = lines
        self.active_offset = active_offset
        self.physical_offset = physical_offset
        self.seed = seed
        self.fault = fault
        self.session_id: str | None = None
        self.running = False

    def start(self, *, correlation_id: str) -> dict[str, Any]:
        if self.fault == "switch_failure":
            raise MercuryError(
                "mercury_simulation_start_failed", "synthetic mercury spectrum source failed to start", status_code=409
            )
        self.session_id = f"mercury-sim-{uuid.uuid4().hex}"
        self.running = True
        return {
            "event_type": "simulation_spectrum_started",
            "session_id": self.session_id,
            "correlation_id": correlation_id,
            "physical_lamp_command": False,
            "physical_lamp_state": "not_controlled",
        }

    def frame(self, *, frame_index: int, phase: str, correlation_id: str) -> dict[str, Any]:
        if not self.running:
            raise MercuryError(
                "mercury_session_not_running", "synthetic spectrum session is not active", status_code=409
            )
        if self.fault == "stability_failure" and phase == "stabilization":
            raise MercuryError("mercury_stability_failed", "synthetic mercury peak did not stabilize", status_code=409)
        if self.fault == "capture_failure" and phase == "measurement":
            raise MercuryError("mercury_capture_failed", "synthetic mercury spectrum capture failed", status_code=409)

        points_per_ccd = int(self.layout["points_per_ccd"])
        indices = [int(value) for value in self.layout["ccd_indices"]]
        rng = random.Random(self.seed + frame_index * 1009 + (0 if phase == "stabilization" else 100_003))
        spectra = {index: [rng.randint(35, 65) for _ in range(points_per_ccd)] for index in indices}
        for line in self.lines:
            ccd_index = int(line["expected_ccd_index"])
            if ccd_index not in spectra:
                continue
            # expected_position includes the active correction. Recover the
            # nominal instrument position before applying the simulated offset.
            nominal = float(line["expected_position"]) + self.active_offset
            center = int(round(nominal + self.physical_offset))
            amplitude = min(60_000, 4_000 + int(line["relative_intensity"]) * 45)
            for position in range(max(0, center - 10), min(points_per_ccd, center + 11)):
                gaussian = amplitude * math.exp(-0.5 * ((position - center) / 2.0) ** 2)
                spectra[ccd_index][position] = min(65_535, spectra[ccd_index][position] + int(round(gaussian)))
        ccds = []
        hashes = []
        for ccd_index in indices:
            packed = _pack(spectra[ccd_index])
            digest = _sha(packed)
            hashes.append(digest)
            ccds.append({"ccd_index": ccd_index, "points": spectra[ccd_index], "points_sha256": digest})
        return {
            "event_type": "simulated_mercury_frame",
            "session_id": self.session_id,
            "phase": phase,
            "frame_index": frame_index,
            "virtual_time_ms": float(frame_index * 1000),
            "frame_sha256": _sha("".join(hashes)),
            "ccds": ccds,
            "correlation_id": correlation_id,
            "physical_lamp_command": False,
        }

    def close(self, *, correlation_id: str) -> dict[str, Any]:
        self.running = False
        previous = self.session_id
        self.session_id = None
        return {
            "event_type": "simulation_spectrum_stopped",
            "session_id": previous,
            "correlation_id": correlation_id,
            "physical_lamp_command": False,
            "physical_lamp_state": "not_controlled",
        }


class SerialMercuryAdapter:
    """Hard protocol gate. It cannot construct or transmit command bytes."""

    session_id: str | None = None

    def start(self, *, correlation_id: str) -> dict[str, Any]:
        raise MercuryError(
            "mercury_protocol_unavailable",
            "real mercury lamp protocol documentation or capture is unavailable",
            details={"correlation_id": correlation_id, "commands_sent": False},
            status_code=409,
        )

    def frame(self, *, frame_index: int, phase: str, correlation_id: str) -> dict[str, Any]:
        raise MercuryError("mercury_protocol_unavailable", "real mercury lamp protocol is unavailable", status_code=409)

    def close(self, *, correlation_id: str) -> dict[str, Any]:
        return {
            "event_type": "serial_close_skipped",
            "correlation_id": correlation_id,
            "reason": "protocol_unavailable",
            "commands_sent": False,
        }
