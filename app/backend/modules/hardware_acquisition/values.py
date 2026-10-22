from __future__ import annotations
import hashlib
import json
import math
from enum import Enum
from typing import Any


class HardwareTaskState(str, Enum):
    DRAFT = "draft"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    PRE_EXCITATION = "pre_excitation"
    TURNING = "turning"
    COLLECTING = "collecting"
    ANOMALY = "anomaly"
    MANUAL_INTERVENTION = "manual_intervention"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    SAFETY_STOPPED = "safety_stopped"
    DEFERRED_EXTERNAL = "deferred_external"


class HardwareError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = 422,
        deferred_external: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        self.deferred_external = deferred_external

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


_STRATEGIES = {"short_to_long", "key_first"}


_POLICIES = {"retry_then_stop", "manual"}


_ANOMALIES = {"baseline_low", "baseline_high", "baseline_shift", "peak_shift", "frame_fault", "turn_timeout"}


_DECISION_STATES = {
    "draft",
    "connected",
    "pre_excitation",
    "turning",
    "collecting",
    "anomaly",
    "manual_intervention",
    "paused",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _finite(value: Any, field: str, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise HardwareError("hardware_value_invalid", f"{field} must be numeric", details={"field": field}) from exc
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise HardwareError(
            "hardware_value_invalid",
            f"{field} is outside the supported range",
            details={"field": field, "minimum": minimum, "maximum": maximum},
        )
    return result
