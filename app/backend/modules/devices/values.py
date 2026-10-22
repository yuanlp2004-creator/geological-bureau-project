from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from ...db import utc_now


ACQ_FRAME_COUNT = 3


ACQ_CCDS_PER_FRAME = 2


ACQ_POINTS_PER_CCD = 2048


ACQ_FRAME_BYTES = 1 + ACQ_CCDS_PER_FRAME * ACQ_POINTS_PER_CCD * 2


ACQ_BYTES = ACQ_FRAME_COUNT * ACQ_FRAME_BYTES


ACQ_HEADER_GOOD = 0


DEFAULT_CCD_INDICES = [0, 1, 2, 4, 5]


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
