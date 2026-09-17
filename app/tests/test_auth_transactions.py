from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import AppConfig
from backend.main import create_app
from backend.runtime import Runtime
from backend.schemas.auth import RoleCreate, RoleUpdate, UserCreate, UserUpdate


def snapshot(runtime: Runtime) -> dict[str, list[tuple]]:
    with runtime.database.read() as db:
        return {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("users", "roles", "permissions", "user_roles", "role_permissions", "audit_events")
        }


@pytest.mark.parametrize("operation", ["create_user", "update_user", "create_role", "update_role"])
def test_account_changes_rollback_if_audit_insert_fails(tmp_path: Path, operation: str) -> None:
    runtime = Runtime(AppConfig(data_dir=tmp_path))
    runtime.database.initialize()
    service = runtime.auth_service
    service.bootstrap("admin", "correct-horse")
    _, admin_session = service.login("admin", "correct-horse")
    admin = admin_session.user_id
    role = service.create_role(RoleCreate(name="custom", permission_keys=["methods.read"]), admin)
    user = service.create_user(UserCreate(username="viewer", password="viewer-pass", role_ids=[role["id"]]), admin)
    token, session = service.login("viewer", "viewer-pass")
    # Deliberately fail at the final write, after the account/association mutations.
    with runtime.database.write() as db:
        db.execute("CREATE TRIGGER fail_auth_audit BEFORE INSERT ON audit_events BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END")
    before = snapshot(runtime)
    with pytest.raises(sqlite3.IntegrityError, match="injected audit failure"):
        if operation == "create_user":
            service.create_user(UserCreate(username="new-user", password="new-password", role_ids=[role["id"]]), admin)
        elif operation == "update_user":
            service.update_user(user["id"], UserUpdate(enabled=False, role_ids=[]), admin)
        elif operation == "create_role":
            service.create_role(RoleCreate(name="new-role", permission_keys=["new.permission"]), admin)
        else:
            service.update_role(role["id"], RoleUpdate(description="changed", permission_keys=["new.permission"]), admin)
    assert snapshot(runtime) == before
    assert service.get_session(token) == session


def test_account_api_preserves_validation_errors_without_partial_writes(tmp_path: Path) -> None:
    app = create_app(AppConfig(data_dir=tmp_path))
    runtime = app.state.runtime
    with TestClient(app) as client:
        client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "correct-horse"})
        token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        admin_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
        roles = client.get("/api/v1/roles", headers=headers).json()
        role = next(item for item in roles if item["name"] == "system_administrator")
        cases = [
            ("post", "/api/v1/users", {"username": "admin", "password": "correct-horse"}, 409, "username already exists"),
            ("post", "/api/v1/users", {"username": "new", "password": "correct-horse", "role_ids": [role["id"], role["id"]]}, 422, "duplicate role"),
            ("post", "/api/v1/users", {"username": "new", "password": "correct-horse", "role_ids": [999999]}, 422, "unknown role"),
            ("patch", f"/api/v1/users/{admin_id}", {"enabled": False}, 422, "cannot disable the current user"),
            ("patch", "/api/v1/users/999999", {"enabled": False}, 404, "user not found"),
            ("patch", f"/api/v1/roles/{role['id']}", {"description": "changed"}, 422, "built-in role cannot be changed"),
            ("post", "/api/v1/roles", {"name": role["name"]}, 409, "role already exists"),
            ("patch", "/api/v1/roles/999999", {"description": "changed"}, 404, "role not found"),
        ]
        for method, path, payload, status, detail in cases:
            before = snapshot(runtime)
            response = client.request(method, path, headers=headers, json=payload)
            assert response.status_code == status, response.text
            assert response.json() == {"detail": detail}
            assert snapshot(runtime) == before
