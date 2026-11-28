import base64
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fastapi.testclient import TestClient

from backend.config import AppConfig
from backend.main import create_app
from backend.modules.activation import ActivationClaims, encode_signed_activation
from backend.modules.support_diagnostics import SupportSession
from backend.schemas.system import RuntimeEventCreate
from tests.test_s16_analysis import _seed as seed_analysis

PASSWORD = "Isolation-Test-Only!"
ACTIVATION = "/api/v1/activation"
SUPPORT = "/api/v1/support/session"
ACQUISITION = "/api/v1/acquisitions/tasks"
ANALYSIS = "/api/v1/analyses/runs"
METHODS = "/api/v1/methods"


def expect(response, status):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def login(client, username):
    result = expect(client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}), 200)
    return {"Authorization": f"Bearer {result['access_token']}"}


def bootstrap(client):
    expect(client.post("/api/v1/auth/bootstrap", json={"username": "isolated_admin", "password": PASSWORD}), 201)
    return login(client, "isolated_admin")


def add_user(client, administrator, username, role_id):
    expect(client.post("/api/v1/users", headers=administrator, json={
        "username": username, "password": PASSWORD, "role_ids": [role_id],
    }), 201)
    return login(client, username)


def create_acquisition(client, headers, name):
    return expect(client.post(ACQUISITION, headers=headers, json={
        "name": name, "task_kind": "sample", "ccd_indices": [0],
        "burn_frame_count": 2, "dark_frame_count": 1, "pre_excitation_seconds": 0,
    }), 201)


def test_four_builtin_roles_and_custom_operator_enforce_real_routes(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path))
    with TestClient(app) as client:
        admin = bootstrap(client)
        roles = {item["name"]: item for item in expect(client.get("/api/v1/roles", headers=admin), 200)}
        matrix = {
            "system_administrator": (True, True, True),
            "method_administrator": (True, False, False),
            "analyst": (False, True, True),
            "read_only_auditor": (False, False, False),
        }
        assert set(roles) == set(matrix)
        custom = expect(client.post("/api/v1/roles", headers=admin, json={
            "name": "measurement_operator",
            "permission_keys": ["methods.read", "methods.write", "analysis.read", "analysis.execute",
                                "acquisition.read", "acquisition.write", "acquisition.execute"],
        }), 201)
        roles[custom["name"]] = custom
        matrix[custom["name"]] = (True, True, True)
        version_id, sample_ids = seed_analysis(app.state.runtime.database)
        for index, (role, (methods, measurement, capture)) in enumerate(matrix.items()):
            actor = admin if role == "system_administrator" else add_user(client, admin, role, roles[role]["id"])
            method = expect(client.post(METHODS, headers=admin, json={"name": f"delete {index}"}), 201)
            expect(client.post(METHODS, headers=actor, json={"name": f"create {index}"}), 201 if methods else 403)
            expect(client.delete(f"{METHODS}/{method['id']}", headers=actor), 200 if methods else 403)
            run = expect(client.post(ANALYSIS, headers=admin, json={
                "name": role, "method_version_id": version_id, "acquisition_sample_ids": sample_ids[:1],
            }), 201)
            expect(client.post(f"{ANALYSIS}/{run['id']}/start", headers=actor), 200 if measurement else 403)
            task = create_acquisition(client, admin, role)
            expect(client.post(f"{ACQUISITION}/{task['id']}/start", headers=actor), 200 if capture else 403)
            if capture:
                expect(client.post(f"{ACQUISITION}/{task['id']}/stop", headers=actor), 200)
            if role != "system_administrator":
                expect(client.get(ACTIVATION, headers=actor), 403)
                expect(client.post(SUPPORT, headers=actor, json={"minutes": 5}), 403)

        assert expect(client.get(ACTIVATION, headers=admin), 200) == {"state": "unmanaged"}
        assert not (tmp_path / "activation-installation.id").exists()


def test_activation_expiry_renewal_signature_and_inflight_capture(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    config = AppConfig(data_dir=tmp_path, activation_public_key=public)
    app = create_app(config)
    activation = app.state.runtime.activation
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=5)
    monkeypatch.setattr(activation, "_now", lambda: now)

    with TestClient(app) as client:
        admin = bootstrap(client)
        expect(client.get(ACTIVATION), 401)
        status = expect(client.get(ACTIVATION, headers=admin), 200)
        assert status["state"] == "pending"
        identifier = status["installation_id"]

        def signed(date, *, subject=identifier, signing_key=key):
            return encode_signed_activation(ActivationClaims(installation_id=subject, expires_at=date), signing_key.sign)

        task = create_acquisition(client, admin, "启动后跨过到期时间")
        start = f"{ACQUISITION}/{task['id']}/start"
        assert expect(client.post(start, headers=admin), 403)["detail"]["code"] == "activation_pending"
        invalid = [
            signed(expiry, subject=uuid4()), signed(expiry, signing_key=Ed25519PrivateKey.generate()), signed(now),
        ]
        original = json.loads(signed(expiry))
        original["payload"] = json.loads(signed(expiry + timedelta(minutes=10)))["payload"]
        invalid.append(json.dumps(original))
        for value in invalid:
            expect(client.put(ACTIVATION, headers=admin, json={"content": value}), 422)
        assert not (tmp_path / "activation.json").exists()

        content = signed(expiry)
        assert expect(client.put(ACTIVATION, headers=admin, json={"content": content}), 200)["state"] == "active"
        assert expect(client.put(ACTIVATION, headers=admin, json={"content": content}), 200)["state"] == "active"
        expect(client.put(ACTIVATION, headers=admin, json={"content": signed(expiry - timedelta(minutes=1))}), 422)
        assert (tmp_path / "activation.json").read_text() == content
        expect(client.post(start, headers=admin), 200)

        monkeypatch.setattr(activation, "_now", lambda: expiry)
        assert expect(client.get(ACTIVATION, headers=admin), 200)["state"] == "expired"
        fresh = create_acquisition(client, admin, "到期后新任务")
        fresh_start = f"{ACQUISITION}/{fresh['id']}/start"
        assert expect(client.post(fresh_start, headers=admin), 403)["detail"]["code"] == "activation_expired"
        assert expect(client.post(f"{ACQUISITION}/{fresh['id']}/preheat", headers=admin), 403)["detail"]["code"] == "activation_expired"
        assert expect(client.post(f"{ANALYSIS}/1/start", headers=admin), 403)["detail"]["code"] == "activation_expired"
        expect(client.post(start, headers=admin), 200)
        expect(client.post(f"{ACQUISITION}/{task['id']}/step", headers=admin), 200)
        expect(client.post(f"{ACQUISITION}/{task['id']}/pause", headers=admin), 200)
        expect(client.post(f"{ACQUISITION}/{task['id']}/resume", headers=admin), 200)
        expect(client.post(f"{ACQUISITION}/{task['id']}/stop", headers=admin), 200)
        assert expect(client.get(f"{ACQUISITION}/{task['id']}/frames", headers=admin), 200) is not None

        # Exercise the offline signing entry point with a disposable test key only.
        private_file, renewal = tmp_path / "isolated-key.pem", tmp_path / "isolated-renewal.json"
        private_file.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        result = subprocess.run([
            sys.executable, str(Path(__file__).resolve().parents[1] / "tools" / "sign_activation.py"),
            "--private-key", str(private_file), "--installation-id", identifier,
            "--expires-at", (expiry + timedelta(days=1)).isoformat(), "--output", str(renewal),
        ], capture_output=True, text=True)
        private_file.unlink()
        assert result.returncode == 0, result.stderr
        assert expect(client.put(ACTIVATION, headers=admin, json={"content": renewal.read_text()}), 200)["state"] == "active"
        expect(client.post(fresh_start, headers=admin), 200)
        expect(client.post(f"{ACQUISITION}/{fresh['id']}/stop", headers=admin), 200)
        with app.state.runtime.database.read() as db:
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='activation.install'").fetchone()[0] == 2

    with TestClient(create_app(config)) as client:
        status = expect(client.get(ACTIVATION, headers=login(client, "isolated_admin")), 200)
        assert status["state"] == "active" and status["installation_id"] == identifier
    assert create_app(AppConfig(data_dir=tmp_path)).state.runtime.activation.status().state == "configuration_error"


def test_two_http_clients_diagnostics_refresh_revocation_expiry_and_redaction(tmp_path, monkeypatch):
    app = create_app(AppConfig(data_dir=tmp_path))
    runtime = app.state.runtime
    runtime.process_key = "isolated-desktop-key"
    with (
        TestClient(app, headers={"X-GeoSpectrum-Process-Key": runtime.process_key}) as operator,
        httpx.Client(trust_env=False, timeout=2) as support,
        httpx.Client(trust_env=False, timeout=2) as other,
    ):
        admin = bootstrap(operator)
        assert expect(operator.get(SUPPORT, headers=admin), 200)["active"] is False
        expect(operator.post(SUPPORT, json={"minutes": 5}), 401)
        expect(operator.post(f"{SUPPORT}/refresh", headers=admin), 409)

        def open_session():
            result = expect(operator.post(SUPPORT, headers=admin, json={"minutes": 5}), 201)
            return (f"http://127.0.0.1:{result['port']}/api/v1/support/snapshot",
                    {"Authorization": f"Bearer {result['access_token']}"})

        url, ticket = open_session()
        expect(operator.post(SUPPORT, headers=admin, json={"minutes": 5}), 409)
        assert "access_token" not in expect(operator.get(SUPPORT, headers=admin), 200)
        old = expect(support.get(url, headers=ticket), 200)
        assert len(old["modules"]) == 16 and all(module["status"] == "active" for module in old["modules"])
        expect(other.get(url), 401)
        expect(other.get(url, headers=admin), 401)
        expect(other.get(url, headers=ticket | {"Origin": "https://some-site.invalid"}), 401)
        expect(other.get(url.replace("/support/snapshot", "/methods"), headers=ticket), 404)
        expect(other.post(url, headers=ticket), 405)
        expect(operator.get("/api/v1/methods", headers=ticket), 401)
        expect(operator.post(f"{SUPPORT}/refresh", headers=ticket), 401)

        runtime.service.append_event(RuntimeEventCreate(
            category="acquisition", severity="error", message="PRIVATE-SAMPLE-PATH",
            correlation_id="PRIVATE-TRACE", details={
                "path": "PRIVATE-FILE", "sample_name": "PRIVATE-SAMPLE", "token": "PRIVATE-TOKEN",
                "source": "devices", "event_type": "fault", "code": "CCD-transfer.timeout",
                "stage": "turn", "phase": "pre_excitation",
            },
        ))
        runtime.service.append_event(RuntimeEventCreate(
            category="acquisition", severity="error", message="PRIVATE-DETAILS",
            details={"code": r"C:\PRIVATE\FILES", "stage": "PRIVATE-SAMPLE", "phase": "PRIVATE-FREE-TEXT"},
        ))
        assert expect(support.get(url, headers=ticket), 200) == old
        refreshed = expect(operator.post(f"{SUPPORT}/refresh", headers=admin), 200)
        newer = support.get(url, headers=ticket)
        snapshot = expect(newer, 200)
        assert snapshot["checked_at"] != old["checked_at"] and refreshed["port"] == int(url.split(":")[2].split("/")[0])
        fault = next(event for event in snapshot["logs"] if event.get("source") == "devices")
        assert {key: fault[key] for key in ("event_type", "code", "stage", "phase")} == {
            "event_type": "fault", "code": "CCD-transfer.timeout", "stage": "turn", "phase": "pre_excitation",
        }
        assert "PRIVATE" not in newer.text and runtime.process_key not in newer.text
        expect(operator.delete(SUPPORT, headers=admin), 204)
        with pytest.raises(httpx.TransportError):
            support.get(url, headers=ticket)
        assert expect(operator.get(SUPPORT, headers=admin), 200)["active"] is False

        new_url, new_ticket = open_session()
        expect(other.get(new_url, headers=ticket), 401)
        expect(support.get(new_url, headers=new_ticket), 200)
        sharing = runtime.support_diagnostics.active_session()
        monkeypatch.setattr(sharing, "_deadline", 0)
        assert expect(operator.get(SUPPORT, headers=admin), 200)["active"] is False
        try:
            assert support.get(new_url, headers=new_ticket).status_code == 410
        except httpx.TransportError:
            pass

        logout_url, logout_ticket = open_session()
        another_login = login(operator, "isolated_admin")
        expect(operator.post("/api/v1/auth/logout", headers=another_login), 204)
        expect(support.get(logout_url, headers=logout_ticket), 200)
        expect(operator.post("/api/v1/auth/logout", headers=admin), 204)
        with pytest.raises(httpx.TransportError):
            support.get(logout_url, headers=logout_ticket)


def test_support_listener_checks_authorization_on_request_and_exits_on_revocation():
    checked = Event()

    def unauthorized():
        checked.set()
        return False

    now = datetime.now(timezone.utc)
    session = SupportSession((now, b"{}"), 1, unauthorized)
    session.start()
    try:
        assert not checked.wait(0.4), "idle listener checked operator authorization"
        url = f"http://127.0.0.1:{session.port}/api/v1/support/snapshot"
        with httpx.Client(trust_env=False, timeout=2) as client:
            expect(client.get(url, headers={"Authorization": f"Bearer {session.token}"}), 410)
        assert checked.is_set()
        session._thread.join(timeout=2)
        assert not session._thread.is_alive()
    finally:
        session.close()


def test_support_listener_closes_at_deadline_without_a_request():
    now = datetime.now(timezone.utc)
    session = SupportSession((now, b"{}"), 1, lambda: True, operator_expires_at=now + timedelta(milliseconds=200))
    session.start()
    try:
        session._thread.join(timeout=2)
        assert not session.active()
        assert not session._thread.is_alive()
    finally:
        session.close()
