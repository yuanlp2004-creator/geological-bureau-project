"""Public, detached method snapshots bound to an existing read/write transaction.

Binding never opens or commits a connection. The caller owns its lifetime.
"""

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from typing import Any

from .errors import MethodDomainError


@dataclass(frozen=True)
class MethodIdentity:
    id: int
    name: str
    description: str
    work_type: str
    status: str


@dataclass(frozen=True)
class MethodSnapshot:
    method: MethodIdentity
    version_id: int
    version: int
    state: str
    payload: dict[str, Any]
    validation_errors: list[dict[str, Any]]
    content_sha256: str
    created_at: str

    def print_version(self) -> dict[str, Any]:
        from ..spectral_lines import canonical_lines

        conditions = self.payload.get("conditions", {})
        return {"id": self.version_id, "version": self.version, "state": self.state,
                "conditions": conditions, "lines": canonical_lines(self.payload.get("lines"), conditions),
                "validation_errors": self.validation_errors, "content_sha256": self.content_sha256,
                "created_at": self.created_at}


class MethodSnapshotReader:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> MethodSnapshot:
        return MethodSnapshot(
            MethodIdentity(row["method_id"], row["name"], row["description"], row["work_type"], row["status"]),
            row["id"], row["version"], row["state"], json.loads(row["payload_json"]),
            json.loads(row["validation_errors_json"] or "[]"),
            hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest(), row["created_at"],
        )

    _SELECT = ("SELECT v.*, m.name, m.description, m.work_type, m.status "
               "FROM method_versions v JOIN methods m ON m.id=v.method_id ")

    def identity(self, method_id: int) -> MethodIdentity | None:
        row = self._connection.execute(
            "SELECT id,name,description,work_type,status FROM methods WHERE id=?", (method_id,)
        ).fetchone()
        return MethodIdentity(**dict(row)) if row is not None else None

    def for_print(self, method_id: int, version: int | None = None) -> MethodSnapshot:
        method = self.identity(method_id)
        if method is None or method.status == "deleted":
            raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
        if version is None:
            row = self._connection.execute(self._SELECT + "WHERE v.method_id=? ORDER BY v.version DESC LIMIT 1", (method_id,)).fetchone()
        else:
            row = self._connection.execute(self._SELECT + "WHERE v.method_id=? AND v.version=?", (method_id, version)).fetchone()
        if row is None:
            raise MethodDomainError("method_version_not_found", "方法版本不存在", fields=["version"], status_code=404)
        return self._snapshot(row)

    def by_id(self, version_id: int, *, published_only: bool = False) -> MethodSnapshot | None:
        state = " AND v.state='published'" if published_only else ""
        row = self._connection.execute(self._SELECT + "WHERE v.id=?" + state, (version_id,)).fetchone()
        return self._snapshot(row) if row is not None else None

    def published(self) -> list[MethodSnapshot]:
        rows = self._connection.execute(self._SELECT + "WHERE v.state='published' ORDER BY m.name, v.version DESC").fetchall()
        return [self._snapshot(row) for row in rows]

    def by_ids(self, version_ids: list[int]) -> dict[int, MethodSnapshot]:
        ids = list(dict.fromkeys(version_ids))
        if not ids:
            return {}
        rows = self._connection.execute(self._SELECT + f"WHERE v.id IN ({','.join('?' for _ in ids)})", ids).fetchall()
        return {row["id"]: self._snapshot(row) for row in rows}
