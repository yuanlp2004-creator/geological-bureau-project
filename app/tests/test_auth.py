from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = main_module.Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        yield client, main_module


def _admin_token(client: TestClient) -> str:
    result = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"})
    assert result.status_code == 200
    return result.json()["access_token"]


def test_bootstrap_uses_argon2id_and_seeds_roles(auth_client) -> None:
    client, main = auth_client
    assert client.get("/api/v1/auth/status").json() == {"bootstrapped": False}
    assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
    assert client.get("/api/v1/auth/status").json() == {"bootstrapped": True}
    assert client.post("/api/v1/auth/bootstrap", json={"username": "second", "password": "correct-horse"}).status_code == 409

    with main.database.read() as db:
        stored = db.execute("SELECT password_hash FROM users WHERE username='operator'").fetchone()[0]
        roles = {row[0] for row in db.execute("SELECT name FROM roles")}
        audit = db.execute("SELECT action, details_json FROM audit_events").fetchall()
    assert stored.startswith("$argon2id$")
    assert "correct-horse" not in stored
    assert roles == {"system_administrator", "method_administrator", "analyst", "read_only_auditor"}
    assert audit[0][0] == "bootstrap"
    assert json.loads(audit[0][1])["password_scheme"] == "argon2id"


def test_builtin_role_matrix_is_exact_and_stale_grants_are_revoked(auth_client) -> None:
    client, main = auth_client
    assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201

    expected = {name: set(keys) for name, _description, keys in main.BUILTIN_ROLES}
    with main.database.read() as db:
        actual = {
            role: {
                row[0]
                for row in db.execute(
                    "SELECT p.key FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id "
                    "JOIN roles r ON r.id=rp.role_id WHERE r.name=?",
                    (role,),
                ).fetchall()
            }
            for role in expected
        }
    assert actual == expected
    assert {"acquisition.execute", "hardware-acquisition.execute", "mercury-calibration.execute"}.isdisjoint(expected["method_administrator"])
    assert {"devices.write", "devices.execute"}.isdisjoint(expected["analyst"])
    assert {"acquisition.execute", "hardware-acquisition.execute", "analysis.execute", "analysis.intervene"}.issubset(expected["analyst"])

    with main.database.write() as db:
        for role, permission in (("method_administrator", "acquisition.execute"), ("analyst", "devices.execute")):
            db.execute(
                "INSERT INTO role_permissions(role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p WHERE r.name=? AND p.key=?",
                (role, permission),
            )
    assert main.auth_service.synchronize_builtin_permissions() == 2
    with main.database.read() as db:
        stale = db.execute(
            "SELECT r.name, p.key FROM role_permissions rp JOIN roles r ON r.id=rp.role_id "
            "JOIN permissions p ON p.id=rp.permission_id "
            "WHERE (r.name='method_administrator' AND p.key='acquisition.execute') "
            "OR (r.name='analyst' AND p.key='devices.execute')"
        ).fetchall()
        changes = json.loads(
            db.execute("SELECT details_json FROM audit_events WHERE action='role.permission.migrate' ORDER BY id DESC LIMIT 1").fetchone()[0]
        )["changes"]
    assert stale == []
    assert {item["operation"] for item in changes} == {"revoke"}


def test_authentication_and_permission_matrix(auth_client) -> None:
    client, _ = auth_client
    client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"})
    assert client.get("/api/v1/users").status_code == 401
    assert client.get("/api/v1/audit").status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "operator", "password": "bad-password"}).status_code == 401

    token = _admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert "users.write" in me.json()["permissions"]
    roles = client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200
    assert len(roles.json()) == 4

    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "viewer", "password": "viewer-pass", "role_ids": []},
    )
    assert created.status_code == 201
    viewer_token = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewer-pass"}).json()["access_token"]
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    assert client.get("/api/v1/users", headers=viewer_headers).status_code == 403
    assert client.get("/api/v1/audit", headers=viewer_headers).status_code == 403

    read_only_role = next(role for role in roles.json() if role["name"] == "read_only_auditor")
    changed = client.patch("/api/v1/users/2", headers=headers, json={"role_ids": [read_only_role["id"]]})
    assert changed.status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_permission_changes_are_audited_and_disabled_users_cannot_login(auth_client) -> None:
    client, main = auth_client
    client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"})
    admin = _admin_token(client)
    headers = {"Authorization": f"Bearer {admin}"}
    role = client.post("/api/v1/roles", headers=headers, json={"name": "qc_reviewer", "description": "QC", "permission_keys": ["results.read"]})
    assert role.status_code == 201
    role_id = role.json()["id"]
    assert client.patch("/api/v1/roles/%s" % role_id, headers=headers, json={"permission_keys": ["results.read", "audit.read"]}).status_code == 200
    user = client.post("/api/v1/users", headers=headers, json={"username": "reviewer", "password": "review-pass", "role_ids": [role_id]})
    assert user.status_code == 201
    user_id = user.json()["id"]
    assert client.patch("/api/v1/users/%s" % user_id, headers=headers, json={"enabled": False}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "reviewer", "password": "review-pass"}).status_code == 401

    audit = client.get("/api/v1/audit", headers=headers)
    assert audit.status_code == 200
    actions = [event["action"] for event in audit.json()]
    assert "role.permission.change" in actions
    assert "user.create" in actions
    assert "user.permission.change" in actions
    with main.database.read() as db:
        password_hash = db.execute("SELECT password_hash FROM users WHERE username='reviewer'").fetchone()[0]
    assert password_hash.startswith("$argon2id$")


def test_s02_core_permissions_audit_and_event_stream_scope(auth_client) -> None:
    client, _ = auth_client
    client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"})
    token = _admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/settings").status_code == 401
    assert client.get("/api/v1/logs").status_code == 401
    assert client.patch("/api/v1/settings", json={"display": {"density": "compact"}}).status_code == 401
    assert client.delete("/api/v1/logs").status_code == 401

    roles = client.get("/api/v1/roles", headers=headers).json()
    auditor_role = next(role for role in roles if role["name"] == "read_only_auditor")
    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "auditor", "password": "auditor-pass", "role_ids": [auditor_role["id"]]},
    )
    assert created.status_code == 201
    auditor_token = client.post("/api/v1/auth/login", json={"username": "auditor", "password": "auditor-pass"}).json()["access_token"]
    auditor_headers = {"Authorization": f"Bearer {auditor_token}"}
    assert client.get("/api/v1/settings", headers=auditor_headers).status_code == 200
    assert client.get("/api/v1/logs", headers=auditor_headers).status_code == 200
    assert client.patch("/api/v1/settings", headers=auditor_headers, json={"display": {"density": "compact"}}).status_code == 403
    assert client.post("/api/v1/logs", headers=auditor_headers, json={"category": "import", "severity": "info", "message": "denied"}).status_code == 403

    assert client.patch("/api/v1/settings", headers=headers, json={"display": {"density": "compact"}}).status_code == 200
    assert client.post("/api/v1/settings/reset", headers=headers).status_code == 200
    assert client.post("/api/v1/logs", headers=headers, json={"category": "action", "severity": "info", "message": "manual"}).status_code == 201
    assert client.delete("/api/v1/logs", headers=headers).status_code == 200
    actions = [event["action"] for event in client.get("/api/v1/audit", headers=headers).json()]
    assert {"settings.update", "settings.reset", "runtime_event.create", "runtime_event.clear"}.issubset(actions)

    with pytest.raises(WebSocketDisconnect) as unauthenticated:
        with client.websocket_connect("/ws/events") as websocket:
            websocket.receive_json()
    assert unauthenticated.value.code == 4401

    with client.websocket_connect(f"/ws/events?access_token={auditor_token}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "api_version": "v1"}
        assert client.post("/api/v1/logs", headers=headers, json={"category": "import", "severity": "info", "message": "imported"}).status_code == 201
        pushed = websocket.receive_json()
        assert pushed["event"]["message"] == "imported"
