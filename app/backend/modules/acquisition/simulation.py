from __future__ import annotations
import hashlib
import struct
from typing import Any
from ..devices import DeviceEvent
from .codec import _pack_uint16


def _mix32(value: int) -> int:
    """Stable integer mixer used by the acquisition simulator.

    This deliberately avoids Python's process-randomized hash and the global
    random generator so a saved seed remains replayable across processes.
    """

    mixed = int(value) & 0xFFFFFFFF
    mixed ^= mixed >> 16
    mixed = (mixed * 0x7FEB352D) & 0xFFFFFFFF
    mixed ^= mixed >> 15
    mixed = (mixed * 0x846CA68B) & 0xFFFFFFFF
    mixed ^= mixed >> 16
    return mixed & 0xFFFFFFFF


def _seeded_acquisition_event(
    event: DeviceEvent,
    *,
    repeat_index: int,
    phase: str,
    frame_index: int,
    sample_kind: str,
) -> DeviceEvent:
    """Create a deterministic simulated acquisition frame from a real ACQ shape.

    S11 replays the bundled ACQ transfer byte-for-byte.  S13 needs temporal
    burn/dark frames and sample-to-sample variation, so it derives those frames
    here while retaining the source transfer hash in the event details.
    """

    details = dict(event.details or {})
    if details.get("simulation_model") == "seeded-acq-v1":
        return event
    effective_seed = int(details.get("seed", 0))
    seed_fraction = _mix32(effective_seed ^ 0xA5A5A5A5) / 0xFFFFFFFF
    if sample_kind == "blank":
        signal_gain = 0.025 + seed_fraction * 0.015
    else:
        signal_gain = 0.55 + seed_fraction * 0.35
    if phase == "dark":
        phase_gain = 0.0125 + (_mix32(effective_seed ^ 0xD4A4C0DE) % 1251) / 100_000
    else:
        jitter_key = effective_seed ^ ((repeat_index + 1) * 0x9E3779B9) ^ ((frame_index + 1) * 0x85EBCA6B)
        phase_gain = signal_gain * (0.995 + (_mix32(jitter_key) % 1001) / 100_000)

    phase_key = 0xB07F1A6E if phase == "burn" else 0xDA4B5EED
    transformed_ccds: list[dict[str, Any]] = []
    generated_hash = hashlib.sha256()
    for ccd in event.ccds or []:
        ccd_index = int(ccd["ccd_index"])
        points: list[int] = []
        for point_index, raw_value in enumerate(ccd.get("points", [])):
            noise_key = (
                effective_seed
                ^ phase_key
                ^ ((repeat_index + 1) * 0x27D4EB2D)
                ^ ((frame_index + 1) * 0x165667B1)
                ^ ((ccd_index + 1) * 0x9E3779B9)
                ^ ((point_index + 1) * 0x85EBCA6B)
            )
            noise = int(_mix32(noise_key) % 7) - 3
            value = max(0, min(65_535, int(round(int(raw_value) * phase_gain)) + noise))
            points.append(value)
        packed = _pack_uint16(points)
        generated_hash.update(struct.pack("<I", ccd_index))
        generated_hash.update(packed)
        peak = max(points) if points else 0
        transformed_ccds.append(
            dict(ccd)
            | {
                "points": points,
                "peak": peak,
                "peak_position": points.index(peak) if points else 0,
            }
        )

    details.update(
        {
            "simulation_model": "seeded-acq-v1",
            "source_sha256": details.get("sha256"),
            "simulated_points_sha256": generated_hash.hexdigest(),
            "repeat_index": int(repeat_index),
            "phase": phase,
            "phase_frame_index": int(frame_index),
            "signal_gain": round(phase_gain, 9),
        }
    )
    return DeviceEvent(
        event_type=event.event_type,
        state=event.state,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        frame_index=event.frame_index,
        frame_count=event.frame_count,
        ccds=transformed_ccds,
        message=event.message,
        details=details,
    )
