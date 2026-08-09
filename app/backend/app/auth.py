from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException

from .db import Database, utc_now


PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# These are system roles, not domain accounts.  Domain permissions can be added
# by later modules without changing the session or password model.
BUILTIN_ROLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "system_administrator",
        "System administrator",
        (
            "users.read",
            "users.write",
            "roles.write",
            "audit.read",
            "settings.read",
            "settings.write",
            "runtime-events.read",
            "runtime-events.write",
            # The local administrator can bootstrap and maintain every
            # first-party module; narrower operators use domain roles.
            "methods.read",
            "methods.write",
            "migration.read",
            "migration.write",
            "spectrum-migration.read",
            "spectrum-migration.write",
            "result-migration.read",
            "result-migration.write",
            "spectra.read",
            "spectra.export",
            "samples.read",
            "samples.write",
        ),
    ),
    (
        "method_administrator",
        "Method administrator",
        ("settings.read", "runtime-events.read", "methods.read", "methods.write", "migration.read", "migration.write", "spectrum-migration.read", "spectrum-migration.write", "result-migration.read", "result-migration.write", "spectra.read", "spectra.export", "samples.read", "samples.write", "audit.read"),
    ),
    (
        "analyst",
        "Analyst",
        ("settings.read", "runtime-events.read", "methods.read", "samples.read", "samples.write", "spectra.read", "spectra.export", "acquisition.execute", "analysis.execute", "reports.write"),
    ),
    (
        "read_only_auditor",
        "Read-only auditor",
        ("settings.read", "runtime-events.read", "audit.read", "results.read", "results.export", "spectra.read", "spectra.export"),
    ),
)


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError, ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Session:
    user_id: int
    username: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    expires_at: datetime


class AuthService:
    def __init__(self, database: Database):
        self.database = database
        # Tokens are intentionally process-memory only. Tauri must not persist
        # them on disk, and a service restart invalidates every session.
        self.sessions: dict[str, Session] = {}

    def is_bootstrapped(self) -> bool:
        with self.database.read() as db:
            return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def synchronize_builtin_permissions(self) -> int:
        """Add permissions introduced by a new module to existing built-in roles."""

        with self.database.write() as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                return 0
            changes: list[dict[str, str]] = []
            for role_name, description, permission_keys in BUILTIN_ROLES:
                db.execute(
                    "INSERT OR IGNORE INTO roles(name, description) VALUES (?, ?)",
                    (role_name, description),
                )
                role_id = int(db.execute("SELECT id FROM roles WHERE name=?", (role_name,)).fetchone()[0])
                for permission_key in permission_keys:
                    db.execute(
                        "INSERT OR IGNORE INTO permissions(key, description) VALUES (?, ?)",
                        (permission_key, permission_key),
                    )
                    permission_id = int(
                        db.execute("SELECT id FROM permissions WHERE key=?", (permission_key,)).fetchone()[0]
                    )
                    cursor = db.execute(
                        "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                        (role_id, permission_id),
                    )
                    if cursor.rowcount:
                        changes.append({"role": role_name, "permission": permission_key})
            if changes:
                db.execute(
                    "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                    "VALUES (NULL, 'role.permission.migrate', 'role', NULL, ?, ?)",
                    (json.dumps({"changes": changes}, ensure_ascii=False), utc_now()),
                )
            return len(changes)

    def bootstrap(self, username: str, password: str) -> dict:
        username = username.strip()
        if not username:
            raise ValueError("username is required")
        password_hash = hash_password(password)
        with self.database.write() as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise ValueError("bootstrap is already completed")

            now = utc_now()
            cur = db.execute(
                "INSERT INTO users(username, password_hash, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                (username, password_hash, now, now),
            )
            user_id = cur.lastrowid
            role_ids: dict[str, int] = {}
            for role_name, description, permission_keys in BUILTIN_ROLES:
                role_cursor = db.execute(
                    "INSERT INTO roles(name, description) VALUES (?, ?)",
                    (role_name, description),
                )
                role_id = int(role_cursor.lastrowid)
                role_ids[role_name] = role_id
                for permission_key in permission_keys:
                    db.execute(
                        "INSERT OR IGNORE INTO permissions(key, description) VALUES (?, ?)",
                        (permission_key, permission_key),
                    )
                    db.execute(
                        "INSERT INTO role_permissions(role_id, permission_id) "
                        "SELECT ?, id FROM permissions WHERE key = ?",
                        (role_id, permission_key),
                    )

            db.execute(
                "INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)",
                (user_id, role_ids["system_administrator"]),
            )
            db.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, 'bootstrap', 'user', ?, ?, ?)",
                (
                    user_id,
                    user_id,
                    json.dumps(
                        {
                            "roles": [
                                {"name": role[0], "permission_keys": list(role[2])}
                                for role in BUILTIN_ROLES
                            ],
                            "password_scheme": "argon2id",
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        return {"username": username, "created": True}

    def login(self, username: str, password: str) -> tuple[str, Session] | None:
        with self.database.read() as db:
            row = db.execute(
                "SELECT id, username, password_hash, enabled FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
            if not row or not row["enabled"] or not verify_password(password, row["password_hash"]):
                return None
            roles = db.execute(
                "SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id WHERE ur.user_id = ? ORDER BY r.name",
                (row["id"],),
            ).fetchall()
            perms = db.execute(
                "SELECT DISTINCT p.key FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN user_roles ur ON ur.role_id = rp.role_id WHERE ur.user_id = ?",
                (row["id"],),
            ).fetchall()

        session = Session(
            row["id"],
            row["username"],
            tuple(r[0] for r in roles),
            frozenset(r[0] for r in perms),
            datetime.now(timezone.utc) + timedelta(hours=8),
        )
        token = secrets.token_urlsafe(32)
        self.sessions[token] = session
        with self.database.write() as db:
            db.execute(
                "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) "
                "VALUES (?, 'login', 'session', NULL, '{}', ?)",
                (session.user_id, utc_now()),
            )
        return token, session

    def get_session(self, token: str | None) -> Session | None:
        session = self.sessions.get(token or "")
        if session and session.expires_at > datetime.now(timezone.utc):
            return session
        if token:
            self.sessions.pop(token, None)
        return None


def require_session(authorization: str | None = Header(default=None)) -> Session:
    from .main import auth_service

    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    session = auth_service.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="authentication required")
    return session


def require_permission(permission: str):
    def dependency(session: Session = Depends(require_session)) -> Session:
        if permission not in session.permissions:
            raise HTTPException(status_code=403, detail="permission denied")
        return session

    return dependency
