from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.hardware_acquisition import HardwareAcquisitionService, HardwareError


def _advance(service: HardwareAcquisitionService, task_id: int, limit: int = 100) -> dict:
    task = service._task_dict(task_id)
    for _ in range(limit):
        if task["status"] in {"completed", "failed", "stopped", "safety_stopped", "deferred_external", "manual_intervention"}:
            return task
        task = service.step(task_id)
    raise AssertionError(f"task did not settle: {task['status']}")


def test_s14_plan_ordering_duplicate_guard_and_simulator_completion(tmp_path: Path) -> None:
    database = Database(tmp_path / "hardware.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)

    task = service.create_task(
        {
            "name": "key-band order",
            "strategy": "key_first",
            "turns": [
                {"angle_deg": 30, "wavelength_nm": 310, "priority": 2, "key_band": False},
                {"angle_deg": 10, "wavelength_nm": 250, "priority": 0, "key_band": True},
                {"angle_deg": 20, "wavelength_nm": 280, "priority": 8, "key_band": True},
            ],
        }
    )
    assert [(step["key_band"], step["priority"]) for step in task["steps"]] == [(True, 8), (True, 0), (False, 2)]

    with pytest.raises(HardwareError) as duplicate:
        service.create_task({"turns": [{"angle_deg": 1, "wavelength_nm": 270}, {"angle_deg": 2, "wavelength_nm": 270.005}]})
    assert duplicate.value.code == "turn_duplicate_wavelength"

    started = service.start(task["id"])
    assert started["status"] == "pre_excitation"
    completed = _advance(service, task["id"])
    assert completed["status"] == "completed"
    assert completed["completed_steps"] == 3
    assert completed["result_sha256"]
    assert len(completed["frames"]) == 15
    assert any(trace["name"] == "turn.request" for trace in completed["traces"])
    assert any(decision["decision"] == "accept" for decision in completed["decisions"])


def test_s14_peak_correction_retry_and_retry_exhausted_safety_stop(tmp_path: Path) -> None:
    database = Database(tmp_path / "anomalies.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)

    corrected = service.create_task({"name": "peak correction", "retry_limit": 1, "turns": [{"angle_deg": 5, "wavelength_nm": 280}], "simulator_anomalies": [{"step_index": 0, "kind": "peak_shift", "count": 1}]})
    service.start(corrected["id"])
    first = service.step(corrected["id"])
    assert first["status"] == "turning"
    collecting = service.step(corrected["id"])
    assert collecting["status"] == "collecting"
    retried = service.step(corrected["id"])
    assert retried["status"] == "turning"
    assert retried["steps"][0]["correction_offset"] < 0
    assert retried["latest_decision"]["decision"] == "correct"
    assert _advance(service, corrected["id"])["status"] == "completed"

    stopped = service.create_task({"name": "baseline stop", "retry_limit": 1, "turns": [{"angle_deg": 8, "wavelength_nm": 290}], "simulator_anomalies": [{"step_index": 0, "kind": "baseline_low", "count": 5}]})
    service.start(stopped["id"])
    safety = _advance(service, stopped["id"])
    assert safety["status"] == "safety_stopped"
    assert safety["failure_code"] == "safety_stop"
    assert safety["frames"] and all(not frame["confirmed"] for frame in safety["frames"])
    assert any(trace["name"] == "safety.stop" for trace in safety["traces"])


@pytest.mark.parametrize("kind", ["baseline_low", "baseline_high", "baseline_shift", "peak_shift", "frame_fault", "turn_timeout"])
def test_s14_each_anomaly_kind_is_detected_and_stopped(tmp_path: Path, kind: str) -> None:
    database = Database(tmp_path / f"{kind}.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({"name": kind, "retry_limit": 0, "turns": [{"angle_deg": 9, "wavelength_nm": 295}], "simulator_anomalies": [{"step_index": 0, "kind": kind, "count": 1}]})
    service.start(task["id"])
    stopped = _advance(service, task["id"])
    assert stopped["status"] == "safety_stopped"
    assert kind in stopped["decisions"][-1]["anomaly_kind"]
    frames = stopped["frames"]
    assert frames and all(not frame["confirmed"] for frame in frames)
    assert all(bool(frame["damaged"]) == (kind in {"frame_fault", "turn_timeout"}) for frame in frames)


def test_s14_task_control_lock_rejects_overlapping_operation(tmp_path: Path) -> None:
    database = Database(tmp_path / "mutex.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({"name": "mutex", "turns": [{"angle_deg": 6, "wavelength_nm": 285}]})
    with service._control_scope(task["id"]):
        with pytest.raises(HardwareError) as busy:
            service.start(task["id"])
    assert busy.value.code == "hardware_task_busy"
    assert service.start(task["id"])["status"] == "pre_excitation"


def test_s14_manual_takeover_and_immutable_hardware_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "manual.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({"name": "manual review", "anomaly_policy": "manual", "retry_limit": 0, "turns": [{"angle_deg": 12, "wavelength_nm": 300}], "simulator_anomalies": [{"step_index": 0, "kind": "baseline_shift", "count": 1}]})
    service.start(task["id"])
    manual = _advance(service, task["id"])
    assert manual["status"] == "manual_intervention"
    accepted = service.intervene(task["id"], "accept", "operator checked baseline")
    assert accepted["status"] == "completed"
    assert accepted["completed_steps"] == 1

    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE hardware_frames SET points_sha256='tampered' WHERE task_id=?", (task["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE hardware_traces SET payload_json='{}' WHERE task_id=?", (task["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("DELETE FROM hardware_frames WHERE task_id=?", (task["id"],))


def test_s14_serial_protocol_gate_is_deferred_without_command_bytes(tmp_path: Path) -> None:
    database = Database(tmp_path / "serial.sqlite3")
    database.initialize()
    with database.write() as db:
        db.execute("UPDATE device_profiles SET transport='serial', name='Serial external' WHERE id=1")
    service = HardwareAcquisitionService(database)
    task = service.create_task({"name": "serial gate", "device_profile_id": 1, "turns": [{"angle_deg": 1, "wavelength_nm": 260}]})
    deferred = service.start(task["id"])
    assert deferred["status"] == "deferred_external"
    assert deferred["failure_code"] == "hardware_protocol_unavailable"
    assert all(trace["kind"] != "command" for trace in deferred["traces"])
    assert "no command bytes" in deferred["messages"][-1]["message"]


def test_s14_api_permissions_and_simulator_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    main_module._device_service_instance = None
    main_module._hardware_acquisition_service_instance = None
    with TestClient(main_module.app) as client:
        assert client.get("/api/v1/hardware-acquisitions/tasks").status_code == 401
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/hardware-acquisitions/options", headers=headers).status_code == 200
        payload = {"name": "API hardware", "turns": [{"angle_deg": 1, "wavelength_nm": 260}]}
        created = client.post("/api/v1/hardware-acquisitions/tasks", headers=headers, json=payload)
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert client.post(f"/api/v1/hardware-acquisitions/tasks/{task_id}/start", headers=headers).json()["status"] == "pre_excitation"
        assert client.post(f"/api/v1/hardware-acquisitions/tasks/{task_id}/step", headers=headers).json()["status"] == "turning"
        capability = next(item for item in client.get("/api/v1/capabilities").json()["capabilities"] if item["key"] == "hardware-acquisition")
        assert {"hardware-acquisition.read", "hardware-acquisition.write", "hardware-acquisition.execute"}.issubset(capability["permissions"])
