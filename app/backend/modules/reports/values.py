from __future__ import annotations
import hashlib
import json
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class ReportError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status_code, self.details = code, message, status_code, details or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}
