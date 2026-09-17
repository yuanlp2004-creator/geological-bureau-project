from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .db import Database, utc_now
from .schemas.auth import UserCreate, UserUpdate, RoleCreate, RoleUpdate


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
            "devices.read",
            "devices.write",
            "devices.execute",
            "dispersion.read",
            "dispersion.write",
            "dispersion.execute",
            "acquisition.read",
            "acquisition.write",
            "acquisition.execute",
            "hardware-acquisition.read",
            "hardware-acquisition.write",
            "hardware-acquisition.execute",
            "mercury-calibration.read",
            "mercury-calibration.write",
            "mercury-calibration.execute",
            "analysis.read",
            "analysis.execute",
            "analysis.intervene",
            "analysis.quality",
            "analysis.curve",
            "analysis.print",
            "postprocessing.read",
            "postprocessing.write",
            "postprocessing.execute",
            "postprocessing.export",
            "reports.read",
            "reports.write",
            "reports.export",
            "maintenance.read",
            "maintenance.write",
            "help.read",
            "about.read",
        ),
    ),
    (
        "method_administrator",
        "Method administrator",
        ("settings.read", "runtime-events.read", "methods.read", "methods.write", "migration.read", "migration.write", "devices.read", "dispersion.read", "dispersion.write", "dispersion.execute", "reports.read", "help.read", "about.read"),
    ),
    (
        "analyst",
        "Analyst",
        ("settings.read", "runtime-events.read", "methods.read", "samples.read", "samples.write", "spectra.read", "spectra.export", "devices.read", "dispersion.read", "acquisition.read", "acquisition.write", "acquisition.execute", "hardware-acquisition.read", "hardware-acquisition.write", "hardware-acquisition.execute", "mercury-calibration.read", "analysis.read", "analysis.execute", "analysis.intervene", "analysis.quality", "analysis.curve", "analysis.print", "postprocessing.read", "postprocessing.write", "postprocessing.execute", "postprocessing.export", "reports.read", "reports.write", "reports.export", "help.read", "about.read"),
    ),
    (
        "read_only_auditor",
        "Read-only auditor",
        ("settings.read", "runtime-events.read", "audit.read", "results.read", "results.export", "spectra.read", "spectra.export", "devices.read", "dispersion.read", "acquisition.read", "hardware-acquisition.read", "mercury-calibration.read", "analysis.read", "postprocessing.read", "postprocessing.export", "reports.read", "reports.export", "maintenance.read", "help.read", "about.read"),
    ),
)


def _role_permissions(role_name: str, permission_keys: tuple[str, ...]) -> tuple[str, ...]:
    if role_name != "system_administrator":
        return permission_keys
    from .modules.manifest import registered_manifests

    extension_permissions = {
        permission
        for manifest in registered_manifests()
        if manifest.key.startswith("s21-")
        for permission in manifest.permissions
    }
    return tuple(sorted(set(permission_keys).union(extension_permissions)))


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


class AuthError(Exception):
    """Application error translated to HTTP only at the API boundary."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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
        """Make persisted built-in roles exactly match the locked role matrix."""

        with self.database.write() as db:
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                return 0
            changes: list[dict[str, str]] = []
            for role_name, description, permission_keys in BUILTIN_ROLES:
                permission_keys = _role_permissions(role_name, permission_keys)
                db.execute(
                    "INSERT OR IGNORE INTO roles(name, description) VALUES (?, ?)",
                    (role_name, description),
                )
                role_id = int(db.execute("SELECT id FROM roles WHERE name=?", (role_name,)).fetchone()[0])
                expected = set(permission_keys)
                current = {
                    str(row[0])
                    for row in db.execute(
                        "SELECT p.key FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id WHERE rp.role_id=?",
                        (role_id,),
                    ).fetchall()
                }
                for permission_key in sorted(current - expected):
                    db.execute(
                        "DELETE FROM role_permissions WHERE role_id=? AND permission_id=(SELECT id FROM permissions WHERE key=?)",
                        (role_id, permission_key),
                    )
                    changes.append({"operation": "revoke", "role": role_name, "permission": permission_key})
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
                        changes.append({"operation": "grant", "role": role_name, "permission": permission_key})
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
                permission_keys = _role_permissions(role_name, permission_keys)
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
                                {"name": role[0], "permission_keys": list(_role_permissions(role[0], role[2]))}
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

    def list_users(self) -> list[dict]:
        with self.database.read() as db:
            rows = db.execute("SELECT id, username, enabled, created_at, updated_at FROM users ORDER BY username").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                role_rows = db.execute(
                    "SELECT r.id, r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id WHERE ur.user_id = ? ORDER BY r.name",
                    (row["id"],),
                ).fetchall()
                item["role_ids"] = [role["id"] for role in role_rows]
                item["roles"] = [role["name"] for role in role_rows]
                result.append(item)
            return result

    def list_roles(self) -> list[dict]:
        with self.database.read() as db:
            rows = db.execute("SELECT id, name, description FROM roles ORDER BY name").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["permission_keys"] = [permission[0] for permission in db.execute("SELECT p.key FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id WHERE rp.role_id=? ORDER BY p.key", (row["id"],)).fetchall()]
                item["built_in"] = row["name"] in {role[0] for role in BUILTIN_ROLES}
                result.append(item)
            return result

    def list_audit(self, limit: int = 100) -> list[dict]:
        with self.database.read() as db:
                return [dict(row) for row in db.execute("SELECT id, actor_user_id, action, target_type, target_id, details_json, created_at FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def create_user(self, payload: UserCreate, actor_user_id: int) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        username = payload.username.strip()
        if not username:
            raise AuthError(status_code=422, detail="username is required")
        try:
            with self.database.write() as db:
                if len(payload.role_ids) != len(set(payload.role_ids)):
                    raise AuthError(status_code=422, detail="duplicate role")
                if payload.role_ids:
                    placeholders = ",".join("?" for _ in payload.role_ids)
                    role_count = db.execute(f"SELECT COUNT(*) FROM roles WHERE id IN ({placeholders})", payload.role_ids).fetchone()[0]
                    if role_count != len(set(payload.role_ids)):
                        raise AuthError(status_code=422, detail="unknown role")
                cur = db.execute("INSERT INTO users(username, password_hash, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)", (username, hash_password(payload.password), now, now))
                user_id = cur.lastrowid
                for role_id in payload.role_ids:
                    db.execute("INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role_id))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'user.create', 'user', ?, ?, ?)", (actor_user_id, user_id, json.dumps({"username": username, "role_ids": payload.role_ids}, ensure_ascii=False), now))
        except ValueError as exc:
            raise AuthError(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise AuthError(status_code=409, detail="username already exists") from exc
            raise
        return {"id": user_id, "username": username, "enabled": True, "role_ids": payload.role_ids}

    def update_user(self, user_id: int, payload: UserUpdate, actor_user_id: int) -> dict:
        with self.database.write() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise AuthError(status_code=404, detail="user not found")
            if payload.enabled is False and user_id == actor_user_id:
                raise AuthError(status_code=422, detail="cannot disable the current user")
            if payload.role_ids is not None and payload.role_ids:
                if len(payload.role_ids) != len(set(payload.role_ids)):
                    raise AuthError(status_code=422, detail="duplicate role")
                placeholders = ",".join("?" for _ in payload.role_ids)
                role_count = db.execute(f"SELECT COUNT(*) FROM roles WHERE id IN ({placeholders})", payload.role_ids).fetchone()[0]
                if role_count != len(set(payload.role_ids)):
                    raise AuthError(status_code=422, detail="unknown role")
            now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            if payload.enabled is not None:
                db.execute("UPDATE users SET enabled=?, updated_at=? WHERE id=?", (int(payload.enabled), now, user_id))
            if payload.role_ids is not None:
                db.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
                for role_id in payload.role_ids:
                    db.execute("INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)", (user_id, role_id))
            db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'user.permission.change', 'user', ?, ?, ?)", (actor_user_id, user_id, json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False), now))
        return {"id": user_id, "updated": True}

    def create_role(self, payload: RoleCreate, actor_user_id: int) -> dict:
        name = payload.name.strip()
        if not name:
            raise AuthError(status_code=422, detail="role name is required")
        try:
            with self.database.write() as db:
                cur = db.execute("INSERT INTO roles(name, description) VALUES (?, ?)", (name, payload.description.strip()))
                role_id = cur.lastrowid
                for key in sorted(set(payload.permission_keys)):
                    db.execute("INSERT OR IGNORE INTO permissions(key, description) VALUES (?, ?)", (key, key))
                    db.execute("INSERT INTO role_permissions(role_id, permission_id) SELECT ?, id FROM permissions WHERE key=?", (role_id, key))
                db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'role.permission.change', 'role', ?, ?, ?)", (actor_user_id, role_id, json.dumps({"permission_keys": sorted(set(payload.permission_keys))}, ensure_ascii=False), utc_now()))
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise AuthError(status_code=409, detail="role already exists") from exc
            raise
        return {"id": role_id, "name": name, "permission_keys": sorted(set(payload.permission_keys))}

    def update_role(self, role_id: int, payload: RoleUpdate, actor_user_id: int) -> dict:
        with self.database.write() as db:
            row = db.execute("SELECT name FROM roles WHERE id=?", (role_id,)).fetchone()
            if not row:
                raise AuthError(status_code=404, detail="role not found")
            if row["name"] in {"system_administrator", "method_administrator", "analyst", "read_only_auditor"}:
                raise AuthError(status_code=422, detail="built-in role cannot be changed")
            if payload.description is not None:
                db.execute("UPDATE roles SET description=? WHERE id=?", (payload.description.strip(), role_id))
            if payload.permission_keys is not None:
                db.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
                for key in sorted(set(payload.permission_keys)):
                    db.execute("INSERT OR IGNORE INTO permissions(key, description) VALUES (?, ?)", (key, key))
                    db.execute("INSERT INTO role_permissions(role_id, permission_id) SELECT ?, id FROM permissions WHERE key=?", (role_id, key))
            db.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, 'role.permission.change', 'role', ?, ?, ?)", (actor_user_id, role_id, json.dumps(payload.model_dump(exclude_none=True), ensure_ascii=False), utc_now()))
        return {"id": role_id, "updated": True}

    def logout(self, token: str) -> None:
        self.sessions.pop(token, None)
