from __future__ import annotations

import hashlib
import gc
import struct
import sys
import tracemalloc
import uuid
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.devices import AcqSimulatorAdapter, DeviceError, parse_acq_frame, screen_conversion, validate_profile


SAMPLES = {
    "280-288.acq": "ef130de0bde91cdb084333002207493380ad4b776fc2ce1c6960d19e0e164c0c",
    "291-299.acq": "9ccf429c0b89e873711a400fba9267711f0287279c39593988a2ed4cb01294e2",
    "303-310.acq": "b031f17cbc3c207a1213cba0abf351f3ccb011adcde8542e4ae9c85d322fd297",
}
SAMPLE_ROOT = files("backend.app.resources.simulator")


def test_s11_packaged_acq_samples_match_frame_contract_and_ccd_order() -> None:
    for name, expected_hash in SAMPLES.items():
        payload = SAMPLE_ROOT.joinpath(name).read_bytes()
        parsed = parse_acq_frame(payload)
        assert len(payload) == 24579
        assert hashlib.sha256(payload).hexdigest() == expected_hash
        assert parsed["frame_size"] == 8193
        assert parsed["headers"] == [0, 0, 0]
        assert len(parsed["ccds"]) == 6
        # The non-mirrored mapping follows the Delphi Acq2Ccd order: CCD1 is
        # the second slot of the last frame and CCD6 the first slot of frame 1.
        raw = parsed["raw_frames"]
        assert parsed["ccds"][0]["points"][0] == raw[2][1]
        assert parsed["ccds"][5]["points"][0] == raw[0][0]


def test_s11_rejects_incomplete_and_fault_headers_with_offsets() -> None:
    payload = SAMPLE_ROOT.joinpath("280-288.acq").read_bytes()
    with pytest.raises(DeviceError) as incomplete:
        parse_acq_frame(payload[:-1])
    assert incomplete.value.code == "acq_frame_incomplete"
    assert incomplete.value.details["offset"] == 24578
    broken = bytearray(payload)
    broken[8193] = 9
    with pytest.raises(DeviceError) as header:
        parse_acq_frame(bytes(broken))
    assert header.value.code == "acq_frame_header_invalid"
    assert header.value.details == {"offset": 8193, "frame_index": 1, "raw_header": 9}


def test_s11_profile_boundaries_and_screen_conversion() -> None:
    profile = validate_profile({"name": "test", "ccd_indices": [0, 1, 2, 4, 5]})
    conversion = screen_conversion(profile)
    assert conversion["pixels_per_mm"] == pytest.approx(1920 / 40.92)
    assert conversion["point_width_px"] == pytest.approx(14 / 1000 * 1920 / 40.92)
    with pytest.raises(DeviceError, match="unsupported baud"):
        validate_profile({"name": "bad", "baud_rate": 12345})
    with pytest.raises(DeviceError, match="duplicate"):
        validate_profile({"name": "bad", "ccd_indices": [0, 0]})


def test_s11_ten_thousand_frames_cover_thirty_virtual_minutes_with_bounded_memory() -> None:
    adapter = AcqSimulatorAdapter()
    profile = validate_profile({"name": "endurance", "ccd_indices": [0, 1, 2, 4, 5]})
    adapter.connect(profile, correlation_id=str(uuid.uuid4()))
    adapter.start_debug(sample="280-288.acq", seed=11, fault_frame=None, correlation_id=str(uuid.uuid4()))
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    event = None
    for frame_index in range(1, 10_001):
        event = adapter.step_debug(correlation_id=str(uuid.uuid4()))
        assert event.frame_index == frame_index
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert event is not None
    assert event.details["virtual_time_ms"] == 10_000_000
    assert event.details["virtual_time_ms"] >= 30 * 60 * 1000
    assert current - baseline < 256 * 1024
    assert peak - baseline < 1024 * 1024
    stopped = adapter.stop_debug(correlation_id=str(uuid.uuid4()))
    assert stopped.frame_index == 10_000
    assert adapter.diagnostics()["connected"] is True


@pytest.fixture()
def device_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    main_module._device_service_instance = None
    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        yield client, main_module, {"Authorization": f"Bearer {token}"}


def test_s11_api_debug_is_audited_and_does_not_create_records(device_client) -> None:
    client, main_module, headers = device_client
    assert client.get("/api/v1/devices/profiles").status_code == 401
    profiles = client.get("/api/v1/devices/profiles", headers=headers)
    assert profiles.status_code == 200
    profile = profiles.json()[0]
    connected = client.post("/api/v1/devices/connect", headers=headers, json={"profile_id": profile["id"]})
    assert connected.status_code == 200, connected.text
    assert connected.json()["diagnostics"]["connected"] is True
    started = client.post("/api/v1/devices/debug/start", headers=headers, json={"sample": "280-288.acq", "seed": 19})
    assert started.status_code == 200, started.text
    assert len(started.json()["event"]["ccds"]) == 5
    stepped = client.post("/api/v1/devices/debug/step", headers=headers)
    assert stepped.status_code == 200
    stopped = client.post("/api/v1/devices/debug/stop", headers=headers)
    assert stopped.status_code == 200
    with main_module.database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM sample_queues").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM spectrum_bands").fetchone()[0] == 0
        actions = {row[0] for row in db.execute("SELECT action FROM audit_events WHERE target_type='device'")}
    assert {"device.connect", "device.debug.start", "device.debug.step", "device.debug.stop"}.issubset(actions)
    assert stopped.json()["sample_records_created"] == 0
    assert stopped.json()["spectrum_records_created"] == 0
