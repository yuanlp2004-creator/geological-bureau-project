from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def method_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = main_module.Database(config_module.config.database_path)
    main_module.service = main_module.AppService(
        main_module.database, tmp_path / "logs" / "runtime.jsonl"
    )
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert (
            client.post(
                "/api/v1/auth/bootstrap",
                json={"username": "operator", "password": "correct-horse"},
            ).status_code
            == 201
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct-horse"},
        )
        token = login.json()["access_token"]
        yield client, main_module, {"Authorization": f"Bearer {token}"}


def _create(client: TestClient, headers: dict[str, str], name: str = "测试方法") -> dict:
    response = client.post("/api/v1/methods", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _publish(client: TestClient, headers: dict[str, str], method_id: int) -> dict:
    response = client.post(f"/api/v1/methods/{method_id}/publish", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_method_permissions_name_boundary_and_layout_options(method_client) -> None:
    client, _, headers = method_client
    assert client.get("/api/v1/methods").status_code == 401

    options = client.get("/api/v1/methods/options", headers=headers)
    assert options.status_code == 200
    payload = options.json()
    assert payload["ccd_layouts"][0]["ccd_indices"] == [0, 1, 2, 4, 5]
    ranges = payload["dispersion_calibrations"][0]["ccd_ranges"]
    assert len(ranges) == 5
    assert ranges[0]["safe_start_nm"] < 253.65 < ranges[0]["safe_end_nm"]

    boundary = _create(client, headers, "测" * 10)
    assert boundary["version"]["validation_errors"] == []
    too_long = client.post("/api/v1/methods", headers=headers, json={"name": "测" * 11})
    assert too_long.status_code == 422
    assert too_long.json()["detail"]["code"] == "method_name_too_long"
    invalid = client.post("/api/v1/methods", headers=headers, json={"name": "非法/名称"})
    assert invalid.status_code == 422

    duplicate = client.post("/api/v1/methods", headers=headers, json={"name": "测" * 10})
    assert duplicate.status_code == 409


def test_invalid_draft_is_retained_without_rewriting_current_version(method_client) -> None:
    client, main, headers = method_client
    method = _create(client, headers)
    method_id = method["id"]
    published = _publish(client, headers, method_id)
    assert published["current_version"] == 2
    opened = client.post(f"/api/v1/methods/{method_id}/open", headers=headers)
    assert opened.status_code == 200
    current_before = client.get("/api/v1/methods/current", headers=headers).json()
    assert current_before["version"] == 2
    immutable_hash = current_before["referenced_version"]["content_sha256"]

    invalid = client.patch(
        f"/api/v1/methods/{method_id}",
        headers=headers,
        json={
            "conditions": {
                "pre_excitation_seconds": 0,
                "sampling_period_seconds": 3,
                "frame_count": 8,
                "dark_frame_count": 21,
                "sample_repeats": 0,
                "maximum_id_deviation": 21,
                "rsd_threshold": 21,
                "abnormal_threshold": 101,
                "selected_ccds": [4],
                "angle_exposures": [
                    {
                        "angle_deg": 15,
                        "storage_mode": "full_interval",
                        "start_frame": 8,
                        "end_frame": 8,
                    }
                ],
            }
        },
    )
    assert invalid.status_code == 200
    draft = invalid.json()["version"]
    assert draft["state"] == "draft" and draft["version"] == 3
    codes = {issue["code"] for issue in draft["validation_errors"]}
    assert {
        "below_minimum",
        "above_maximum",
        "reference_ccd_not_selected",
        "exposure_too_short",
    }.issubset(codes)

    rejected = client.post(f"/api/v1/methods/{method_id}/publish", headers=headers)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "invalid_method_draft"
    current_after = client.get("/api/v1/methods/current", headers=headers).json()
    assert current_after["version"] == 2
    assert current_after["referenced_version"]["content_sha256"] == immutable_hash

    versions = client.get(f"/api/v1/methods/{method_id}/versions", headers=headers).json()
    assert [revision["version"] for revision in versions] == [3, 2, 1]
    with main.database.write() as db:
        revision_id = db.execute(
            "SELECT id FROM method_versions WHERE method_id=? AND version=2", (method_id,)
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE method_versions SET payload_json='{}' WHERE id=?", (revision_id,))
    with main.database.write() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM method_versions WHERE id=?", (revision_id,))


def test_reference_ccd_dispersion_and_angle_rules_are_field_specific(method_client) -> None:
    client, _, headers = method_client
    method = _create(client, headers, "条件校验")
    method_id = method["id"]
    response = client.patch(
        f"/api/v1/methods/{method_id}",
        headers=headers,
        json={
            "conditions": {
                "reference_wavelength_nm": 300,
                "actual_reference_wavelength_nm": 301,
                "reference_width_points": 10,
                "angle_exposures": [
                    {
                        "angle_deg": 10,
                        "storage_mode": "unknown",
                        "start_frame": 0,
                        "end_frame": 30,
                    },
                    {
                        "angle_deg": 10,
                        "storage_mode": "averaged",
                        "start_frame": 1,
                        "end_frame": 2,
                    },
                ],
            }
        },
    )
    assert response.status_code == 200
    issues = response.json()["version"]["validation_errors"]
    by_field = {issue["field"]: issue["code"] for issue in issues}
    assert by_field["reference_wavelength_nm"] == "reference_not_on_ccd"
    assert by_field["actual_reference_wavelength_nm"] in {
        "reference_not_on_ccd",
        "reference_offset_too_large",
    }
    assert by_field["reference_width_points"] == "below_minimum"
    assert by_field["angle_exposures.0.storage_mode"] == "storage_mode_invalid"
    assert by_field["angle_exposures.0.start_frame"] == "frame_out_of_range"
    assert by_field["angle_exposures.0.end_frame"] == "frame_out_of_range"
    assert by_field["angle_exposures.1.angle_deg"] == "angle_duplicate"


def test_lifecycle_current_actions_soft_delete_and_atomic_duplicate_failure(method_client) -> None:
    client, main, headers = method_client
    source = _create(client, headers, "生命周期")
    method_id = source["id"]
    _publish(client, headers, method_id)
    assert client.post(f"/api/v1/methods/{method_id}/open", headers=headers).status_code == 200

    renamed = client.patch(
        f"/api/v1/methods/{method_id}", headers=headers, json={"name": "生命周期-重命名"}
    )
    assert renamed.status_code == 200
    current = client.get("/api/v1/workspace/state", headers=headers).json()
    assert current["title"] == "生命周期-重命名"
    assert current["actions"]["can_acquire"] is True

    copied = client.post(
        f"/api/v1/methods/{method_id}/copy", headers=headers, json={"name": "生命周期-副本"}
    )
    assert copied.status_code == 201
    assert copied.json()["current_version"] is None

    with main.database.read() as db:
        method_count = db.execute("SELECT COUNT(*) FROM methods").fetchone()[0]
        version_count = db.execute("SELECT COUNT(*) FROM method_versions").fetchone()[0]
    duplicate = client.post(
        f"/api/v1/methods/{method_id}/copy", headers=headers, json={"name": "生命周期-副本"}
    )
    assert duplicate.status_code == 409
    with main.database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM methods").fetchone()[0] == method_count
        assert db.execute("SELECT COUNT(*) FROM method_versions").fetchone()[0] == version_count

    paused = client.post(f"/api/v1/methods/{method_id}/pause", headers=headers)
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    current = client.get("/api/v1/methods/current", headers=headers).json()
    assert current["action_state"] == "paused"
    assert current["actions"]["can_acquire"] is False
    assert client.post(f"/api/v1/methods/{method_id}/open", headers=headers).status_code == 409

    resumed = client.post(f"/api/v1/methods/{method_id}/resume", headers=headers)
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"
    assert client.get("/api/v1/methods/current", headers=headers).json()["actions"]["can_acquire"] is True

    deleted = client.delete(f"/api/v1/methods/{method_id}", headers=headers)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert client.get("/api/v1/methods/current", headers=headers).json()["method_id"] is None
    assert client.get(f"/api/v1/methods/{method_id}", headers=headers).status_code == 404
    assert any(item["id"] == method_id for item in client.get("/api/v1/methods?include_deleted=true", headers=headers).json())

    audit = client.get("/api/v1/audit", headers=headers).json()
    actions = {event["action"] for event in audit}
    assert {
        "method.create",
        "method.publish",
        "method.open",
        "method.rename",
        "method.copy",
        "method.pause",
        "method.resume",
        "method.delete",
    }.issubset(actions)


def test_analyst_can_read_methods_but_cannot_change_them(method_client) -> None:
    client, _, headers = method_client
    roles = client.get("/api/v1/roles", headers=headers).json()
    analyst = next(role for role in roles if role["name"] == "analyst")
    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "analyst", "password": "analyst-pass", "role_ids": [analyst["id"]]},
    )
    assert created.status_code == 201
    token = client.post(
        "/api/v1/auth/login", json={"username": "analyst", "password": "analyst-pass"}
    ).json()["access_token"]
    analyst_headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/methods", headers=analyst_headers).status_code == 200
    assert client.get("/api/v1/methods/current", headers=analyst_headers).status_code == 200
    assert (
        client.post("/api/v1/methods", headers=analyst_headers, json={"name": "越权"}).status_code
        == 403
    )
