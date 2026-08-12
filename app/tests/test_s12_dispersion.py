from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.dispersion import DispersionError, DispersionService, _evaluate, _fit_polynomial


def test_s12_polynomial_fit_reproduces_golden_probe() -> None:
    wavelengths = [250.0, 260.0, 270.0, 280.0, 300.0]
    positions = [0.08 * wave * wave + 5.5 * wave - 4200.0 for wave in wavelengths]
    coefficients = _fit_polynomial(wavelengths, positions, 2)
    assert coefficients == pytest.approx([0.08, 5.5, -4200.0], abs=1e-8)
    assert _evaluate(coefficients, 265.0) == pytest.approx(0.08 * 265.0**2 + 5.5 * 265.0 - 4200.0, abs=1e-7)


def test_s12_duplicate_insufficient_and_residual_failures_keep_draft(tmp_path: Path) -> None:
    database = Database(tmp_path / "dispersion.sqlite3")
    database.initialize()
    service = DispersionService(database)
    task = service.create_task(
        {
            "name": "residual-boundary",
            "device_profile_id": 1,
            "ccd_layout_id": "default",
            "frame_count": 1,
            "dark_frame_count": 0,
            "pre_excitation_seconds": 0,
            "sampling_period_seconds": 1,
            "residual_limit_points": 1,
            "sample": "280-288.acq",
            "seed": 12,
            "lines": [
                {"element": "A", "wavelength_nm": 250.0, "ccd_index": 0, "actual_position": 100.0},
                {"element": "B", "wavelength_nm": 260.0, "ccd_index": 0, "actual_position": 200.0},
                {"element": "C", "wavelength_nm": 270.0, "ccd_index": 0, "actual_position": 300.0},
                {"element": "D", "wavelength_nm": 280.0, "ccd_index": 0, "actual_position": 1800.0},
            ],
        }
    )
    with pytest.raises(DispersionError) as duplicate:
        service.add_line(task["id"], {"element": "A2", "wavelength_nm": 250.005, "ccd_index": 0})
    assert duplicate.value.code == "dispersion_line_duplicate"
    draft = service.fit_calibration(task["id"], {"name": "bad-residual", "degree": 2})
    assert draft["state"] == "draft"
    assert draft["residual_max"] > draft["residual_limit_points"]
    with pytest.raises(DispersionError) as rejected:
        service.publish_calibration(draft["id"])
    assert rejected.value.code == "calibration_residual_exceeded"
    assert service.calibration(draft["id"])["state"] == "draft"

    two_point_task = service.create_task(
        {
            "name": "insufficient",
            "device_profile_id": 1,
            "ccd_layout_id": "default",
            "frame_count": 1,
            "dark_frame_count": 0,
            "lines": [
                {"element": "A", "wavelength_nm": 250.0, "ccd_index": 0, "actual_position": 100.0},
                {"element": "B", "wavelength_nm": 260.0, "ccd_index": 0, "actual_position": 200.0},
            ],
        }
    )
    with pytest.raises(DispersionError) as insufficient:
        service.fit_calibration(two_point_task["id"], {"degree": 2})
    assert insufficient.value.code == "calibration_points_insufficient"


@pytest.fixture()
def dispersion_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    main_module._device_service_instance = None
    main_module._dispersion_service_instance = None
    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        yield client, main_module, {"Authorization": f"Bearer {token}"}


def test_s12_api_state_frames_calibration_binding_and_audit(dispersion_client) -> None:
    client, main_module, headers = dispersion_client
    assert client.get("/api/v1/dispersion/tasks").status_code == 401
    options = client.get("/api/v1/dispersion/options", headers=headers)
    assert options.status_code == 200
    assert options.json()["states"] == ["draft", "pre_excitation", "burn", "dark", "paused", "stopping", "completed", "failed", "stopped"]

    method = client.post("/api/v1/methods", headers=headers, json={"name": "S12方法"})
    assert method.status_code == 201, method.text
    method_id = method.json()["id"]
    published_method = client.post(f"/api/v1/methods/{method_id}/publish", headers=headers)
    assert published_method.status_code == 200, published_method.text
    method_version = published_method.json()["current_version"]

    task_response = client.post(
        "/api/v1/dispersion/tasks",
        headers=headers,
        json={
            "name": "S12 API task",
            "device_profile_id": options.json()["device_profiles"][0]["id"],
            "ccd_layout_id": options.json()["ccd_layouts"][0]["id"],
            "method_id": method_id,
            "method_version": method_version,
            "frame_count": 2,
            "dark_frame_count": 1,
            "pre_excitation_seconds": 2,
            "sampling_period_seconds": 1,
            "residual_limit_points": 2,
            "sample": "280-288.acq",
            "seed": 12,
            "lines": [
                {"element": "A", "wavelength_nm": 250.0, "ccd_index": 0, "actual_position": 100.0},
                {"element": "B", "wavelength_nm": 270.0, "ccd_index": 1, "actual_position": 500.0},
                {"element": "C", "wavelength_nm": 300.0, "ccd_index": 2, "actual_position": 1500.0},
            ],
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = task_response.json()["id"]
    assert task_response.json()["status"] == "draft"

    started = client.post(f"/api/v1/dispersion/tasks/{task_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "pre_excitation"
    repeated_start = client.post(f"/api/v1/dispersion/tasks/{task_id}/start", headers=headers)
    assert repeated_start.status_code == 200
    assert repeated_start.json()["burn_frames_captured"] == 0

    first = client.post(f"/api/v1/dispersion/tasks/{task_id}/step", headers=headers)
    assert first.json()["status"] == "burn"
    assert first.json()["burn_frames_captured"] == 1
    paused = client.post(f"/api/v1/dispersion/tasks/{task_id}/pause", headers=headers)
    assert paused.json()["status"] == "paused"
    assert client.post(f"/api/v1/dispersion/tasks/{task_id}/pause", headers=headers).json()["status"] == "paused"
    blocked_step = client.post(f"/api/v1/dispersion/tasks/{task_id}/step", headers=headers)
    assert blocked_step.status_code == 409
    assert blocked_step.json()["detail"]["code"] == "dispersion_task_not_running"
    resumed = client.post(f"/api/v1/dispersion/tasks/{task_id}/resume", headers=headers)
    assert resumed.json()["status"] == "burn"
    assert client.post(f"/api/v1/dispersion/tasks/{task_id}/resume", headers=headers).json()["status"] == "burn"
    second = client.post(f"/api/v1/dispersion/tasks/{task_id}/step", headers=headers)
    assert second.json()["status"] == "dark"
    completed = client.post(f"/api/v1/dispersion/tasks/{task_id}/step", headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["burn_frames_captured"] == 2
    assert completed.json()["dark_frames_captured"] == 1
    assert client.post(f"/api/v1/dispersion/tasks/{task_id}/stop", headers=headers).json()["status"] == "completed"

    frames = client.get(f"/api/v1/dispersion/tasks/{task_id}/frames", headers=headers)
    assert frames.status_code == 200
    assert len(frames.json()) == 15
    assert all(len(frame["points"]) == 2048 and frame["byte_length"] == 24579 for frame in frames.json())
    assert all(frame["dtype"] == "uint16" and frame["endianness"] == "little" and frame["compression"] == "zlib" for frame in frames.json())
    assert all(frame["points_sha256"] == hashlib.sha256(bytes().join(int(point).to_bytes(2, "little") for point in frame["points"])).hexdigest() for frame in frames.json())
    timings = {(frame["phase"], frame["frame_index"], frame["virtual_time_ms"]) for frame in frames.json()}
    assert timings == {("burn", 0, 2000.0), ("burn", 1, 3000.0), ("dark", 0, 4000.0)}
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with main_module.database.write() as db:
            db.execute("UPDATE dispersion_task_frames SET points_count=1 WHERE task_id=?", (task_id,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with main_module.database.write() as db:
            db.execute("DELETE FROM dispersion_task_frames WHERE task_id=?", (task_id,))

    added_line = client.post(f"/api/v1/dispersion/tasks/{task_id}/lines", headers=headers, json={"element": "Hg", "wavelength_nm": 253.65, "ccd_index": 0})
    assert added_line.status_code == 201, added_line.text
    line_id = added_line.json()["id"]
    located = client.post(f"/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/locate", headers=headers)
    assert located.status_code == 200, located.text
    assert located.json()["located_position"] is not None
    moved = client.post(f"/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/move", headers=headers, json={"direction": "short", "steps": 1})
    assert moved.json()["located_position"] == pytest.approx(located.json()["located_position"] - 1)
    saved = client.post(f"/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/save", headers=headers)
    assert saved.json()["position_state"] == "saved"
    client.post(f"/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/move", headers=headers, json={"direction": "long", "steps": 3})
    restored = client.post(f"/api/v1/dispersion/tasks/{task_id}/lines/{line_id}/position/restore", headers=headers)
    assert restored.json()["located_position"] == pytest.approx(saved.json()["saved_position"])
    located_all = client.post(f"/api/v1/dispersion/tasks/{task_id}/lines/locate-all", headers=headers)
    assert located_all.status_code == 200
    assert any(line["id"] == line_id for line in located_all.json()["located"])
    assert client.delete(f"/api/v1/dispersion/tasks/{task_id}/lines/{line_id}", headers=headers).status_code == 200

    fitted = client.post(f"/api/v1/dispersion/tasks/{task_id}/calibrations/fit", headers=headers, json={"name": "S12 API calibration", "degree": 2})
    assert fitted.status_code == 201, fitted.text
    assert fitted.json()["publishable"] is True
    calibration_version_id = fitted.json()["id"]
    published = client.post(f"/api/v1/dispersion/calibrations/{calibration_version_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"
    binding = client.post(f"/api/v1/dispersion/calibrations/{calibration_version_id}/bind", headers=headers, json={"method_id": method_id, "method_version": method_version})
    assert binding.status_code == 200, binding.text
    repeated_binding = client.post(f"/api/v1/dispersion/calibrations/{calibration_version_id}/bind", headers=headers, json={"method_id": method_id, "method_version": method_version})
    assert repeated_binding.status_code == 200
    assert repeated_binding.json()["id"] == binding.json()["id"]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with main_module.database.write() as db:
            db.execute("UPDATE dispersion_calibration_versions SET name='mutated' WHERE id=?", (calibration_version_id,))
    with main_module.database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM sample_queues").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM spectrum_bands").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM method_calibration_bindings").fetchone()[0] == 1
        actions = {row[0] for row in db.execute("SELECT action FROM audit_events WHERE target_type='dispersion'")}
    assert {"dispersion.task.create", "dispersion.task.start", "dispersion.task.pause", "dispersion.task.resume", "dispersion.frame.capture", "dispersion.calibration.fit", "dispersion.calibration.publish", "dispersion.calibration.bind"}.issubset(actions)
