from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.mercury_calibration import MercuryCalibrationService, MercuryError


def _create(service: MercuryCalibrationService, **overrides) -> dict:
    line_ids = [line["id"] for line in service.options()["reference_lines"][:4]]
    return service.create_session({"line_ids": line_ids, "stabilization_frames": 2, "simulator_offset_points": 6.0} | overrides)


def _ready(service: MercuryCalibrationService, session_id: int) -> dict:
    session = service.start(session_id)
    for _ in range(20):
        if session["status"] not in {"stabilizing", "acquiring"}:
            return session
        session = service.step(session_id)
    raise AssertionError(f"session did not settle: {session['status']}")


def test_s15_nist_lines_peak_gold_apply_and_rollback(tmp_path: Path) -> None:
    database = Database(tmp_path / "mercury.sqlite3")
    database.initialize()
    service = MercuryCalibrationService(database)
    options = service.options()
    assert [line["wavelength_nm"] for line in options["reference_lines"]] == [253.6517, 296.7280, 302.1498, 312.5668, 313.1548]
    assert all(line["source_name"] == "NIST Strong Lines of Mercury" for line in options["reference_lines"])

    before_counts: tuple[int, int]
    with database.read() as db:
        before_counts = (db.execute("SELECT COUNT(*) FROM dispersion_calibration_versions").fetchone()[0], db.execute("SELECT COUNT(*) FROM method_versions").fetchone()[0])
    created = _create(service)
    assert created["before_version"]["version"] == 1
    ready = _ready(service, created["id"])
    assert ready["status"] == "ready"
    assert ready["analysis"]["within_tolerance"] is True
    offsets = [line["offset_points"] for line in ready["lines"]]
    ordered = sorted(offsets)
    median = (ordered[1] + ordered[2]) / 2
    assert ready["analysis"]["suggestion_points"] == pytest.approx(-median)
    assert ready["analysis"]["after_rms"] < ready["analysis"]["before_rms"]
    assert max(abs(line["after_offset_points"]) for line in ready["lines"]) <= ready["tolerance_points"]
    assert len(ready["frames"]) == 15
    assert all(trace["kind"] != "command" for trace in ready["traces"])

    applied = service.apply(created["id"])
    assert applied["status"] == "applied" and applied["safe_off"] is True
    assert applied["active_version"]["id"] == applied["candidate_version"]["id"]
    rolled_back = service.rollback(created["id"])
    assert rolled_back["active_version"]["id"] == rolled_back["before_version"]["id"]
    with database.read() as db:
        after_counts = (db.execute("SELECT COUNT(*) FROM dispersion_calibration_versions").fetchone()[0], db.execute("SELECT COUNT(*) FROM method_versions").fetchone()[0])
    assert after_counts == before_counts


@pytest.mark.parametrize("fault", ["switch_failure", "stability_failure", "capture_failure"])
def test_s15_failures_safe_off_without_applying_calibration(tmp_path: Path, fault: str) -> None:
    database = Database(tmp_path / f"{fault}.sqlite3")
    database.initialize()
    service = MercuryCalibrationService(database)
    session = _create(service, simulator_fault=fault)
    result = _ready(service, session["id"])
    assert result["status"] == "safe_off"
    assert result["safe_off"] is True
    assert result["candidate_version"] is None
    assert result["active_version"]["id"] == result["before_version"]["id"]
    assert any(trace["name"] == "safe_off" for trace in result["traces"])


def test_s15_serial_protocol_gate_sends_no_commands(tmp_path: Path) -> None:
    database = Database(tmp_path / "serial.sqlite3")
    database.initialize()
    with database.write() as db:
        db.execute("UPDATE device_profiles SET transport='serial', name='Mercury serial external' WHERE id=1")
    service = MercuryCalibrationService(database)
    session = _create(service)
    deferred = service.start(session["id"])
    assert deferred["status"] == "deferred_external"
    assert deferred["safe_off"] is True
    assert deferred["failure_code"] == "mercury_protocol_unavailable"
    assert all(trace["kind"] != "command" for trace in deferred["traces"])
    assert deferred["traces"][-1]["payload"]["commands_sent"] is False


def test_s15_immutable_frames_versions_and_control_lock(tmp_path: Path) -> None:
    database = Database(tmp_path / "integrity.sqlite3")
    database.initialize()
    service = MercuryCalibrationService(database)
    session = _create(service)
    with service._control_scope(session["id"]):
        with pytest.raises(MercuryError) as busy:
            service.start(session["id"])
    assert busy.value.code == "mercury_session_busy"
    ready = _ready(service, session["id"])
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE mercury_frames SET points_sha256='tampered' WHERE session_id=?", (session["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE mercury_alignment_versions SET offset_points=999 WHERE id=?", (ready["candidate_version"]["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("DELETE FROM mercury_traces WHERE session_id=?", (session["id"],))


def test_s15_api_permissions_and_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    main_module._mercury_calibration_service_instance = None
    with TestClient(main_module.app) as client:
        assert client.get("/api/v1/mercury-calibrations/options").status_code == 401
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        options = client.get("/api/v1/mercury-calibrations/options", headers=headers).json()
        created = client.post("/api/v1/mercury-calibrations/sessions", headers=headers, json={"line_ids": [line["id"] for line in options["reference_lines"][:2]], "stabilization_frames": 1})
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert client.post(f"/api/v1/mercury-calibrations/sessions/{session_id}/start", headers=headers).json()["status"] == "stabilizing"
        capability = next(item for item in client.get("/api/v1/capabilities").json()["capabilities"] if item["key"] == "mercury-calibration")
        assert {"mercury-calibration.read", "mercury-calibration.write", "mercury-calibration.execute"}.issubset(capability["permissions"])
