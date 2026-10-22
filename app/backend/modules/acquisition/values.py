from __future__ import annotations
import json
import math
import re
from enum import Enum
from typing import Any


class AcquisitionState(str, Enum):
    DRAFT = "draft"
    COUNTDOWN = "countdown"
    PRE_EXCITATION = "pre_excitation"
    BURN = "burn"
    DARK = "dark"
    BETWEEN_REPEATS = "between_repeats"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AcquisitionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


_SAMPLE_KINDS = {"evaporation", "blank", "normal", "standard", "test", "preheat"}


_STORAGE_MODES = {"averaged", "full_interval"}


_TASK_KINDS = {"evaporation", "sample"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _finite(value: Any, field: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AcquisitionError(
            "acquisition_condition_invalid", f"{field} 必须是数字", details={"field": field}
        ) from exc
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise AcquisitionError("acquisition_condition_invalid", f"{field} 超出范围", details={"field": field})
    return result


def _sample_kind(name: str) -> str:
    if not name:
        return "blank"
    if re.fullmatch(r"S(?:[0-9]|1[0-5])", name.upper()):
        return "standard"
    return "normal"
