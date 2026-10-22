from __future__ import annotations
import hashlib
import json
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


class MercuryError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}
