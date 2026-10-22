from __future__ import annotations
import json
import math
import sqlite3
import threading
from functools import wraps
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DispersionState(str, Enum):
    DRAFT = "draft"
    PRE_EXCITATION = "pre_excitation"
    BURN = "burn"
    DARK = "dark"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class DispersionError(ValueError):
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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _finite(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DispersionError("dispersion_value_invalid", f"{field} must be numeric", details={"field": field}) from exc
    if not math.isfinite(result):
        raise DispersionError("dispersion_value_invalid", f"{field} must be finite", details={"field": field})
    return result


@dataclass
class _TaskContext:
    task: sqlite3.Row
    layout: sqlite3.Row
    profile: sqlite3.Row


def _task_command(operation):
    @wraps(operation)
    def command(self, task_id, *args, **kwargs):
        with self._locks_guard:
            lock = self._locks.setdefault(task_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise DispersionError("dispersion_task_busy", "当前色散任务正在执行另一项操作，请稍后重试", status_code=409)
        try:
            return operation(self, task_id, *args, **kwargs)
        finally:
            lock.release()

    return command
