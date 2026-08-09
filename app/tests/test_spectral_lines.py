from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def line_client(tmp_path, monkeypatch):
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
        bootstrap = client.post(
            "/api/v1/auth/bootstrap",
            json={"username": "line-admin", "password": "correct-horse"},
        )
        assert bootstrap.status_code == 201
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "line-admin", "password": "correct-horse"},
        )
        token = login.json()["access_token"]
        yield client, main_module, {"Authorization": f"Bearer {token}"}


def _method(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/methods", headers=headers, json={"name": "S04 谱线方法"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _line(
    wavelength_nm: float,
    *,
    line_type: str = "analysis",
    element: str = "Fe",
    **overrides,
) -> dict:
    value = {
        "line_type": line_type,
        "element": element,
        "wavelength_nm": wavelength_nm,
        "actual_wavelength_nm": wavelength_nm,
        "enabled": True,
        "critical_band": False,
        "priority": 0,
        "background_line_id": None,
        "alignment_line_id": None,
        "internal_standard_mode": "none",
        "internal_standard_line_id": None,
        "scan_width_points": 9,
        "background_offset_points": 0,
        "peak_mode": "maximum",
        "peak_width_points": 1,
        "fit_mode": "linear",
        "coordinate_type": "linear",
        "unit": "ug/g",
        "value_kind": "content",
        "decimal_places": 2,
        "lower_peak": 300,
        "minimum_peak_ratio": 1.5,
        "valid_range_min": 0,
        "valid_range_max": 1000,
        "over_limit_tolerance_percent": 5,
        "standard_points": (
            [
                {"name": "S1", "value": 1, "active": True},
                {"name": "S2", "value": 2, "active": True},
                {"name": "S3", "value": 3, "active": True},
                {"name": "S4", "value": 4, "active": True},
            ]
            if line_type == "analysis"
            else []
        ),
    }
    value.update(overrides)
    return value


def _create_line(
    client: TestClient,
    headers: dict[str, str],
    method_id: int,
    payload: dict,
) -> dict:
    response = client.post(
        f"/api/v1/methods/{method_id}/lines", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _collection(client: TestClient, headers: dict[str, str], method_id: int) -> dict:
    response = client.get(f"/api/v1/methods/{method_id}/lines", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_options_baseline_and_live_detectability(line_client) -> None:
    client, _, headers = line_client
    method = _method(client, headers)
    method_id = method["id"]

    options = client.get("/api/v1/spectral-lines/options", headers=headers)
    assert options.status_code == 200
    assert options.json()["limits"]["line_count"] == 300
    assert {item["value"] for item in options.json()["line_types"]} == {
        "baseline",
        "analysis",
        "internal_standard",
        "alignment",
    }

    collection = _collection(client, headers, method_id)
    assert len(collection["lines"]) == 1
    baseline = collection["lines"][0]
    assert baseline["id"] == "reference-baseline"
    assert baseline["line_type"] == "baseline"
    assert baseline["detectability"]["detectable"] is True

    detectable = client.post(
        f"/api/v1/methods/{method_id}/lines/detect",
        headers=headers,
        json={"wavelength_nm": 254.0, "scan_width_points": 9},
    )
    assert detectable.status_code == 200
    assert detectable.json()["detectable"] is True
    assert detectable.json()["ccd_index"] == 0
    assert detectable.json()["angle_slot"] == 1

    outside = client.post(
        f"/api/v1/methods/{method_id}/lines/detect",
        headers=headers,
        json={"wavelength_nm": 159.0},
    )
    assert outside.json()["reason_code"] == "wavelength_out_of_global_range"
    uncovered = client.post(
        f"/api/v1/methods/{method_id}/lines/detect",
        headers=headers,
        json={"wavelength_nm": 500.0},
    )
    assert uncovered.json()["reason_code"] == "wavelength_not_on_ccd"


def test_atomic_validation_duplicate_width_and_standard_rules(line_client) -> None:
    client, _, headers = line_client
    method_id = _method(client, headers)["id"]
    first = _create_line(client, headers, method_id, _line(254.0))
    version_before = first["latest_version"]

    duplicate = client.post(
        f"/api/v1/methods/{method_id}/lines",
        headers=headers,
        json=_line(254.009),
    )
    assert duplicate.status_code == 422
    detail = duplicate.json()["detail"]
    assert detail["code"] == "invalid_spectral_line"
    codes = {
        item["code"] for item in detail["details"]["validation_errors"]
    }
    assert "line_wavelength_duplicate" in codes
    assert _method_version(client, headers, method_id) == version_before

    gaussian = _line(255.0, peak_mode="gaussian", peak_width_points=4)
    invalid_gaussian = client.post(
        f"/api/v1/methods/{method_id}/lines", headers=headers, json=gaussian
    )
    assert invalid_gaussian.status_code == 422
    assert "gaussian_points_invalid" in {
        item["code"]
        for item in invalid_gaussian.json()["detail"]["details"]["validation_errors"]
    }
    assert _method_version(client, headers, method_id) == version_before

    too_few = _line(255.0, standard_points=[{"name": "only", "value": 1}])
    invalid_points = client.post(
        f"/api/v1/methods/{method_id}/lines", headers=headers, json=too_few
    )
    assert invalid_points.status_code == 422
    assert "standard_point_count" in {
        item["code"]
        for item in invalid_points.json()["detail"]["details"]["validation_errors"]
    }

    second_baseline = client.post(
        f"/api/v1/methods/{method_id}/lines",
        headers=headers,
        json=_line(255.0, line_type="baseline", element="BL", standard_points=[]),
    )
    assert second_baseline.status_code == 422
    assert second_baseline.json()["detail"]["code"] == "reference_baseline_exists"


def _method_version(client: TestClient, headers: dict[str, str], method_id: int) -> int:
    response = client.get(f"/api/v1/methods/{method_id}", headers=headers)
    assert response.status_code == 200
    return response.json()["latest_version"]


def test_references_modes_and_referenced_line_protection(line_client) -> None:
    client, _, headers = line_client
    method_id = _method(client, headers)["id"]
    _create_line(
        client,
        headers,
        method_id,
        _line(254.0, line_type="internal_standard", element="Ar"),
    )
    internal = next(
        item
        for item in _collection(client, headers, method_id)["lines"]
        if item["line_type"] == "internal_standard"
    )
    _create_line(
        client,
        headers,
        method_id,
        _line(255.0, line_type="alignment", element="Ne"),
    )
    alignment = next(
        item
        for item in _collection(client, headers, method_id)["lines"]
        if item["line_type"] == "alignment"
    )
    _create_line(
        client,
        headers,
        method_id,
        _line(
            256.0,
            background_line_id="reference-baseline",
            alignment_line_id=alignment["id"],
            internal_standard_mode="line",
            internal_standard_line_id=internal["id"],
        ),
    )

    delete_in_use = client.delete(
        f"/api/v1/methods/{method_id}/lines/{internal['id']}", headers=headers
    )
    assert delete_in_use.status_code == 409
    assert delete_in_use.json()["detail"]["code"] == "spectral_line_in_use"

    disabled = deepcopy(internal)
    disabled.pop("id")
    disabled.pop("order")
    disabled.pop("reference_baseline")
    disabled.pop("detectability")
    disabled["enabled"] = False
    disable_in_use = client.patch(
        f"/api/v1/methods/{method_id}/lines/{internal['id']}",
        headers=headers,
        json=disabled,
    )
    assert disable_in_use.status_code == 422
    error_codes = {
        item["code"]
        for item in disable_in_use.json()["detail"]["details"]["validation_errors"]
    }
    assert "line_reference_disabled" in error_codes

    missing = client.post(
        f"/api/v1/methods/{method_id}/lines",
        headers=headers,
        json=_line(257.0, alignment_line_id="missing-line"),
    )
    assert missing.status_code == 422
    assert "line_reference_not_found" in {
        item["code"]
        for item in missing.json()["detail"]["details"]["validation_errors"]
    }


def test_reorder_priority_publish_and_version_immutability(line_client) -> None:
    client, _, headers = line_client
    method_id = _method(client, headers)["id"]
    _create_line(client, headers, method_id, _line(254.0, priority=10))
    _create_line(client, headers, method_id, _line(255.0, element="Cu", critical_band=True, priority=90))
    lines = _collection(client, headers, method_id)["lines"]
    movable = [item for item in lines if item["line_type"] != "baseline"]
    reversed_ids = [item["id"] for item in reversed(movable)]

    reordered = client.post(
        f"/api/v1/methods/{method_id}/lines/reorder",
        headers=headers,
        json={"line_ids": reversed_ids},
    )
    assert reordered.status_code == 200, reordered.text
    assert [
        item["id"]
        for item in reordered.json()["version"]["lines"]
        if item["line_type"] != "baseline"
    ] == reversed_ids

    published = client.post(f"/api/v1/methods/{method_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    published_version = published.json()["current_version"]
    published_hash = published.json()["published_version"]["content_sha256"]
    assert any(
        item["critical_band"] and item["priority"] == 90
        for item in published.json()["published_version"]["lines"]
    )
    assert client.post(f"/api/v1/methods/{method_id}/open", headers=headers).status_code == 200

    selected = next(
        item
        for item in _collection(client, headers, method_id)["lines"]
        if item["line_type"] == "analysis"
    )
    editable = {
        key: value
        for key, value in selected.items()
        if key not in {"id", "order", "reference_baseline", "detectability"}
    }
    editable["priority"] = 42
    updated = client.patch(
        f"/api/v1/methods/{method_id}/lines/{selected['id']}",
        headers=headers,
        json=editable,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version"] == published_version
    assert updated.json()["published_version"]["content_sha256"] == published_hash
    assert updated.json()["version"]["content_sha256"] != published_hash


def test_cycle_and_maximum_count_have_stable_codes(line_client) -> None:
    _, main, _ = line_client
    from backend.app.modules.methods import DEFAULT_CONDITIONS, MethodService
    from backend.app.modules.spectral_lines import (
        canonical_lines,
        validate_spectral_lines,
    )

    service = MethodService(main.database)
    first = _line(254.0, line_type="alignment", element="Ne")
    second = _line(255.0, line_type="alignment", element="Ar")
    first.update({"id": "first", "order": 1, "alignment_line_id": "second"})
    second.update({"id": "second", "order": 2, "alignment_line_id": "first"})
    with main.database.read() as db:
        cycle_errors = validate_spectral_lines(
            service, db, DEFAULT_CONDITIONS, canonical_lines([first, second], DEFAULT_CONDITIONS)
        )
        assert "line_reference_cycle" in {item["code"] for item in cycle_errors}

        excessive = canonical_lines([], DEFAULT_CONDITIONS)
        excessive.extend(deepcopy(first) for _ in range(300))
        count_errors = validate_spectral_lines(
            service, db, DEFAULT_CONDITIONS, excessive
        )
        assert "line_limit_exceeded" in {item["code"] for item in count_errors}


def test_spectral_line_permissions_follow_method_roles(line_client) -> None:
    client, _, admin_headers = line_client
    method_id = _method(client, admin_headers)["id"]
    assert client.get(f"/api/v1/methods/{method_id}/lines").status_code == 401

    roles = client.get("/api/v1/roles", headers=admin_headers).json()
    analyst = next(role for role in roles if role["name"] == "analyst")
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "spectral-analyst",
            "password": "analyst-pass",
            "role_ids": [analyst["id"]],
        },
    )
    assert created.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "spectral-analyst", "password": "analyst-pass"},
    )
    analyst_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (
        client.get(f"/api/v1/methods/{method_id}/lines", headers=analyst_headers).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/methods/{method_id}/lines",
            headers=analyst_headers,
            json=_line(254.0),
        ).status_code
        == 403
    )
