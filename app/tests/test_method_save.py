"""Single-action method save: immutable history, rollback and stale-edit protection."""
import sqlite3

import pytest

from backend.schemas.methods import MethodSave
from tests.test_methods import method_client, _create, _publish


def dump(runtime):
    with runtime.database.read() as db:
        return list(db.iterdump())


def test_save_updates_current_but_preserves_history_and_task_reference(method_client):
    client, runtime, headers = method_client
    method = _publish(client, headers, _create(client, headers)["id"])
    mid = method["id"]
    assert client.post(f"/api/v1/methods/{mid}/open", headers=headers).status_code == 200
    versions = client.get(f"/api/v1/methods/{mid}/versions", headers=headers).json()
    task = runtime.acquisition_service().create_task({"method_id": mid, "method_version": method["current_version"]})
    response = client.post(f"/api/v1/methods/{mid}/save", headers=headers, json={
        "expected_latest_version": method["latest_version"], "name": "保存新版本",
        "conditions": {"pre_excitation_seconds": 4},
    })
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["version"]["state"] == "published"
    assert saved["version"]["validation_errors"] == []
    assert saved["published_version"] == saved["version"]
    assert saved["version"]["conditions"]["pre_excitation_seconds"] == 4
    current = client.get("/api/v1/methods/current", headers=headers).json()
    assert current["version"] == saved["current_version"] > method["current_version"]
    assert saved["is_current"]
    after = client.get(f"/api/v1/methods/{mid}/versions", headers=headers).json()
    assert [version for version in after if version["version"] <= method["latest_version"]] == versions
    task_after = runtime.acquisition_service().get_task(task["id"])
    assert task_after["method_version_id"] == task["method_version_id"] == method["published_version"]["id"]
    with runtime.database.read() as db:
        actions = {row[0] for row in db.execute("SELECT action FROM audit_events WHERE target_type='method' AND target_id=?", (mid,))}
        assert {"method.update", "method.publish"} <= actions


def test_invalid_save_rolls_back_metadata_versions_and_current(method_client):
    client, runtime, headers = method_client
    method = _publish(client, headers, _create(client, headers)["id"])
    mid = method["id"]
    client.post(f"/api/v1/methods/{mid}/open", headers=headers)
    before = dump(runtime)
    response = client.post(f"/api/v1/methods/{mid}/save", headers=headers, json={
        "expected_latest_version": method["latest_version"], "name": "不能部分保存",
        "description": "必须随失败一起回滚", "conditions": {"sample_repeats": 0},
    })
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_method_save"
    assert response.json()["detail"]["details"]["validation_errors"]
    assert dump(runtime) == before


def test_save_rejects_stale_editor_without_overwriting_newer_draft(method_client):
    client, runtime, headers = method_client
    method = _create(client, headers)
    mid = method["id"]
    newer = client.patch(f"/api/v1/methods/{mid}", headers=headers, json={"conditions": {"frame_count": 21}})
    assert newer.status_code == 200
    before = dump(runtime)
    response = client.post(f"/api/v1/methods/{mid}/save", headers=headers, json={
        "expected_latest_version": method["latest_version"], "conditions": {"frame_count": 20},
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "method_version_changed"
    assert dump(runtime) == before


def test_save_publish_audit_failure_rolls_back_entire_edit(method_client, monkeypatch):
    client, runtime, headers = method_client
    mid = _publish(client, headers, _create(client, headers)["id"])["id"]
    service = runtime.methods_service()
    original = service.repository._audit
    def audit(db, actor, action, *args):
        if action == "method.publish":
            raise sqlite3.IntegrityError("save publish audit failure")
        return original(db, actor, action, *args)
    with runtime.database.read() as db:
        actor = db.execute("SELECT id FROM users WHERE username='operator'").fetchone()[0]
    before = dump(runtime)
    monkeypatch.setattr(service.repository, "_audit", audit)
    with pytest.raises(sqlite3.IntegrityError, match="save publish audit failure"):
        service.save(mid, MethodSave(name="应回滚", conditions={"pre_excitation_seconds": 5}), actor)
    assert dump(runtime) == before


def test_explicit_open_reenables_legacy_paused_method_and_keeps_versions(method_client):
    client, runtime, headers = method_client
    method = _publish(client, headers, _create(client, headers)["id"])
    mid = method["id"]
    versions = client.get(f"/api/v1/methods/{mid}/versions", headers=headers).json()
    client.post(f"/api/v1/methods/{mid}/pause", headers=headers)
    assert client.post(f"/api/v1/methods/{mid}/open", headers=headers).status_code == 409
    opened = client.post(f"/api/v1/methods/{mid}/open?resume_paused=true", headers=headers)
    assert opened.status_code == 200
    assert opened.json()["status"] == "active" and opened.json()["is_current"]
    assert client.get(f"/api/v1/methods/{mid}/versions", headers=headers).json() == versions
    unsaved = _create(client, headers, "未保存方法")["id"]
    client.post(f"/api/v1/methods/{unsaved}/pause", headers=headers)
    before = dump(runtime)
    assert client.post(f"/api/v1/methods/{unsaved}/open?resume_paused=true", headers=headers).status_code == 409
    assert dump(runtime) == before


def test_save_requires_write_permission_and_does_not_select_another_method(method_client):
    client, runtime, headers = method_client
    current = _publish(client, headers, _create(client, headers)["id"])
    client.post(f"/api/v1/methods/{current['id']}/open", headers=headers)
    other = _create(client, headers, "另一个方法")
    url = f"/api/v1/methods/{other['id']}/save"
    assert client.post(url, json={}).status_code == 401
    role = next(row for row in client.get("/api/v1/roles", headers=headers).json() if row["name"] == "read_only_auditor")
    assert client.post("/api/v1/users", headers=headers, json={"username": "readonly", "password": "correct-horse", "role_ids": [role["id"]]}).status_code == 201
    token = client.post("/api/v1/auth/login", json={"username": "readonly", "password": "correct-horse"}).json()["access_token"]
    before = dump(runtime)
    assert client.post(url, headers={"Authorization": f"Bearer {token}"}, json={}).status_code == 403
    assert dump(runtime) == before
    saved = client.post(url, headers=headers, json={"expected_latest_version": other["latest_version"]})
    assert saved.status_code == 200, saved.text
    assert not saved.json()["is_current"]
    assert client.get("/api/v1/methods/current", headers=headers).json()["method_id"] == current["id"]
