"""方法模块业务错误。"""

from __future__ import annotations

from typing import Any


class MethodDomainError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        fields: list[str] | None = None,
        details: dict[str, Any] | None = None,
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or []
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field_errors": self.fields,
            "details": self.details,
        }
