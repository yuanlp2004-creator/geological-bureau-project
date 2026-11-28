from __future__ import annotations

import hashlib
import struct
import sys
import time
from collections import deque
from importlib.resources import files
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import Database
from backend.config import AppConfig
from backend.modules.devices import DeviceError, DeviceService, SerialAcqAdapter, validate_profile
from backend.modules.devices import serial_acq
from backend.modules.acquisition import AcquisitionService, AcquisitionError
from backend.modules.dispersion import DispersionService, DispersionError
from backend.runtime import Runtime


def transfer(value: int) -> bytes:
    return (b"\x00" + struct.pack("<4096H", *([value] * 4096))) * 3


class Wire:
    """Fragmented byte stream at the Serial boundary, never the simulator."""
    def __init__(self, payloads, *, write_limit=None):
        self.payload = bytearray(b"".join(payloads))
        self.writes = []
        self.resets = []
        self.closed = False
        self.write_limit = write_limit

    def write(self, data):
        self.writes.append(bytes(data))
        return min(len(data), self.write_limit) if self.write_limit is not None else len(data)

    def read(self, count):
        if not self.payload:
            time.sleep(.001)
        count = min(count, 113, len(self.payload))
        data = bytes(self.payload[:count])
        del self.payload[:count]
        return data

    def reset_input_buffer(self):
        self.resets.append("rx")

    def reset_output_buffer(self):
        self.resets.append("tx")

    def close(self):
        self.closed = True


@pytest.fixture
def wire_factory(monkeypatch):
    scripts = deque()
    opened = []
    def open_wire(**settings):
        wire = scripts.popleft()
        wire.settings = settings
        opened.append(wire)
        return wire
    monkeypatch.setattr(serial_acq.serial, "Serial", open_wire)
    # Only scheduling waits are accelerated. Real framing, command encoding,
    # partial reads, database writes, state machines and errors execute normally.
    monkeypatch.setattr(SerialAcqAdapter, "_wait_until", lambda self, deadline: not self._cancel.is_set())
    return scripts, opened


def connected(wire_factory, wire, *, on_notice=None):
    wire_factory[0].append(wire)
    adapter = SerialAcqAdapter(on_notice=on_notice)
    profile = validate_profile({"name": "serial", "transport": "serial"})
    event = adapter.connect(profile, correlation_id="test")
    assert event.details["instrument_verified"] is False
    return adapter


def wait_for(check, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError("serial operation did not settle")


def test_legacy_wire_command_order_fragments_transition_and_original_points(wire_factory):
    original = files("backend.resources.simulator").joinpath("280-288.acq").read_bytes()
    wire = Wire([original, transfer(300), transfer(65000), transfer(20)])
    adapter = connected(wire_factory, wire)
    adapter.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=2, dark_seconds=1,
                            dark_count=1, correlation_id="golden")
    adapter.begin_capture()
    adapter._worker.join(2)
    assert not adapter._worker.is_alive()
    events = [adapter.next_capture_event() for _ in range(3)]
    assert [(e.details["phase"], e.details["phase_index"]) for e in events] == [("burn", 0), ("burn", 1), ("dark", 0)]
    assert events[0].details["sha256"] == hashlib.sha256(original).hexdigest()
    assert events[1].ccds[0]["points"] == [300] * 2048
    assert events[2].ccds[0]["points"] == [20] * 2048
    assert wire.writes == [bytes.fromhex("f0000404f0"), b"\x04", b"\x00"]
    assert wire.settings["stopbits"] == 2 and wire.settings["bytesize"] == 8
    assert wire.settings["parity"] == "N" and wire.settings["baudrate"] == 460800
    assert wire.settings["write_timeout"] == .1
    assert not any(wire.settings[key] for key in ("xonxoff", "rtscts", "dsrdtr"))
    assert adapter.diagnostics()["stop_confirmed"]
    adapter.disconnect(correlation_id="done")
    assert wire.closed and len(wire.writes) == 3


@pytest.mark.parametrize("burns,darks,expected", [
    (1, 0, ["f0000402f0", "00"]),
    (3, 0, ["f0000404f0", "00"]),
    (1, 2, ["f0000404f0", "04", "00"]),
])
def test_legacy_single_last_burn_and_last_dark_end_commands(wire_factory, burns, darks, expected):
    wire = Wire([transfer(100)] * (burns + darks + bool(darks)))
    adapter = connected(wire_factory, wire)
    adapter.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=burns, dark_seconds=1,
                            dark_count=darks, correlation_id="edges")
    adapter.begin_capture()
    adapter._worker.join(2)
    assert adapter._error is None and adapter._stop_error is None
    assert [data.hex() for data in wire.writes] == expected
    assert adapter._frames.qsize() == burns + darks
    adapter.disconnect(correlation_id="done")


@pytest.mark.parametrize("changes", [
    {"pre_seconds": .1}, {"pre_seconds": 64}, {"burn_seconds": .5},
    {"burn_seconds": 1.01}, {"dark_seconds": 1.1}, {"burn_count": 255},
    {"pre_seconds": 10.25}, {"burn_seconds": 2.25}, {"dark_seconds": 2.25},
])
def test_invalid_physical_conditions_send_no_commands(wire_factory, changes):
    wire = Wire([])
    adapter = connected(wire_factory, wire)
    settings = dict(pre_seconds=0, burn_seconds=1, burn_count=2, dark_seconds=1, dark_count=1, correlation_id="invalid")
    with pytest.raises(DeviceError):
        adapter.prepare_capture(**(settings | changes))
    adapter.disconnect(correlation_id="done")
    assert wire.writes == [] and wire.closed


def test_truncated_frame_failure_sends_end_and_never_fills_missing_points(wire_factory):
    wire = Wire([transfer(100)[:123]])
    notices = []
    adapter = connected(wire_factory, wire, on_notice=lambda kind, message, severity, details: notices.append(kind))
    adapter.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=2, dark_seconds=1,
                            dark_count=0, correlation_id="truncated")
    adapter.begin_capture()
    adapter._worker.join(4)
    with pytest.raises(DeviceError) as error:
        adapter.next_capture_event()
    assert error.value.code == "serial_frame_incomplete"
    assert error.value.details["actual"] == 123
    with pytest.raises(DeviceError, match="结束指令"):
        adapter.disconnect(correlation_id="done")
    assert wire.closed and wire.writes[-1] == b"\x00"
    assert adapter.diagnostics()["stop_confirmed"] is False
    assert notices == ["command_sent", "communication_fault", "stop_waiting", "command_sent", "stop_unconfirmed"]
    # Releasing a failed port is idempotent; an old missing stop response
    # must not keep reporting that a closed port cannot be disconnected.
    assert adapter.disconnect(correlation_id="already-closed").state.value == "idle"
    assert adapter.session_id is None


def test_cancel_before_countdown_has_no_excitation_command(wire_factory, monkeypatch):
    wire = Wire([])
    adapter = connected(wire_factory, wire)
    monkeypatch.setattr(adapter, "_wait_until", lambda deadline: not adapter._cancel.wait(2))
    adapter.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=2, dark_seconds=1,
                            dark_count=0, countdown_seconds=10, correlation_id="cancel")
    adapter.begin_capture()
    adapter.disconnect(correlation_id="done")
    assert wire.writes == [] and wire.closed


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "serial.sqlite3")
    db.initialize()
    return db


def serial_profile(database):
    return DeviceService(database).create_profile({"name": "真实CCD", "transport": "serial", "port": 12})


def transfer_logs(runtime):
    return [
        row for row in reversed(runtime.service.list_events(category="acquisition"))
        if (row["details"] or {}).get("event_type") == "ccd_transfer"
    ]


def stage_logs(runtime):
    return [row for row in reversed(runtime.service.list_events(category="acquisition"))
            if (row["details"] or {}).get("tick_ns") is not None]


@pytest.mark.parametrize("kind", ["sample", "evaporation"])
def test_real_sample_and_evaporation_save_without_ui_polling_and_without_seed_changes(database, wire_factory, kind):
    profile = serial_profile(database)
    wire = Wire([transfer(100), transfer(300), transfer(65000), transfer(20)])
    wire_factory[0].append(wire)
    runtime = Runtime(AppConfig(data_dir=database.path.parent), database=database)
    service = runtime.acquisition_service()
    task = service.create_task(dict(name="serial", task_kind=kind, device_profile_id=profile["id"],
        ccd_indices=[0], burn_frame_count=2, dark_frame_count=1, pre_excitation_seconds=0, seed=123,
        sampling_period_seconds=1, burn_cycle_seconds=1, dark_cycle_seconds=1))
    service.start(task["id"])
    wait_for(lambda: service.get_task(task["id"])["status"] in {"completed", "failed"})
    result = service.get_task(task["id"])
    assert result["status"] == "completed", result
    frames = service.frames(task["id"], include_points=True)
    assert len(frames) == 3
    assert [frame["points"][0] for frame in frames] == [100, 300, 20]
    assert "simulation_model" not in result["last_event"]["details"]
    band = service.band(result["samples"][0]["id"], include_points=True)[0]
    assert band["mean_points"] == [180.0] * 2048
    wait_for(lambda: wire.closed)
    runtime.messages.close()
    rows = transfer_logs(runtime)
    assert [(row["details"]["phase"], row["details"]["frame_index"]) for row in rows] == [
        ("burn", 0), ("burn", 1), ("dark", 0),
    ]
    for row in rows:
        details = row["details"]
        assert row["severity"] == "info" and details["channel"] == "communication"
        assert details["task_id"] == task["id"] and details["transport"] == "serial"
        assert details["byte_length"] == 24579
        assert details["receive_start_ms"] <= details["receive_end_ms"] <= details["stored_ms"]
        assert "ccds" not in details and "points" not in details
    assert "信号收到" in rows[1]["message"] and "第 2 次" in rows[1]["message"]
    assert "接收空白" in rows[2]["message"] and "空白收到" in rows[2]["message"]
    assert all(row["message"].count("Freq:") == 3 and "转存完成" in row["message"] for row in rows)
    runtime.messages.task(service.get_task(task["id"]), source="acquisition")
    assert transfer_logs(runtime) == rows
    stages = stage_logs(runtime)
    assert [row["details"]["event_type"] for row in stages] == [
        "command_sent", "command_sent", "dark_transition", "command_sent", "measurement_ended",
    ]
    assert [row["details"]["command_hex"] for row in stages if "command_hex" in row["details"]] == [
        payload.hex() for payload in wire.writes
    ]
    assert all(row["details"]["task_id"] == task["id"] and row["details"]["port"] == 12 for row in stages)
    assert "切换至空白采集" in stages[2]["message"]


def test_desktop_exit_endpoint_requires_process_key_and_blocks_new_serial_connections(tmp_path, wire_factory):
    from fastapi.testclient import TestClient
    from backend.config import AppConfig
    from backend.runtime import Runtime
    from backend.main import create_app
    runtime = Runtime(AppConfig(data_dir=tmp_path), process_key="paired-desktop-key")
    with TestClient(create_app(runtime=runtime)) as client:
        assert client.post('/api/v1/devices/prepare-exit').status_code == 403
        profile = serial_profile(runtime.database)
        result = client.post('/api/v1/devices/prepare-exit', headers={'X-GeoSpectrum-Process-Key': 'paired-desktop-key'})
        assert result.status_code == 200 and result.json()['safe_to_exit'] is True
        with pytest.raises(DeviceError) as error:
            runtime.devices_service().connect(profile['id'])
        assert error.value.code == 'device_exit_in_progress'
        assert not wire_factory[1]


def test_desktop_exit_failure_is_reported_and_browser_cannot_invoke_exit(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.config import AppConfig
    from backend.runtime import Runtime
    from backend.main import create_app
    runtime = Runtime(AppConfig(data_dir=tmp_path/'desktop'), process_key="paired-desktop-key")
    with TestClient(create_app(runtime=runtime)) as client:
        device = runtime.devices_service()
        monkeypatch.setattr(device, 'shutdown', lambda: [{'code': 'serial_stop_unconfirmed', 'message': 'no stop response'}])
        result = client.post('/api/v1/devices/prepare-exit', headers={'X-GeoSpectrum-Process-Key': 'paired-desktop-key'})
        assert result.json()['safe_to_exit'] is False
        assert result.json()['errors'][0]['code'] == 'serial_stop_unconfirmed'
        assert not runtime.device_exit_gate.is_set()
    with TestClient(create_app(AppConfig(data_dir=tmp_path/'browser'))) as client:
        assert client.post('/api/v1/devices/prepare-exit').status_code == 403


def test_real_dispersion_transition_is_not_saved_as_dark(database, wire_factory):
    profile = serial_profile(database)
    wire = Wire([transfer(700), transfer(65000), transfer(40)])
    wire_factory[0].append(wire)
    runtime = Runtime(AppConfig(data_dir=database.path.parent), database=database)
    service = runtime.dispersion_service()
    task = service.create_task(dict(name="serial dispersion", device_profile_id=profile["id"], ccd_indices=[0],
        frame_count=1, dark_frame_count=1, pre_excitation_seconds=0, sampling_period_seconds=1))
    service.start_task(task["id"])
    wait_for(lambda: service.get_task(task["id"])["status"] in {"completed", "failed"})
    assert service.get_task(task["id"])["status"] == "completed"
    frames = service.frames(task["id"])
    assert [(frame["phase"], frame["points"][0]) for frame in frames] == [("burn", 700), ("dark", 40)]
    wait_for(lambda: wire.closed)
    runtime.messages.close()
    assert [(row["details"]["phase"], row["details"]["frame_index"]) for row in transfer_logs(runtime)] == [
        ("burn", 0), ("dark", 0),
    ]


def test_real_repeat_waits_for_manual_start_and_preheat_creates_no_band(database, wire_factory):
    profile = serial_profile(database)
    wires = [Wire([transfer(500)]), Wire([transfer(600)]), Wire([transfer(700)])]
    wire_factory[0].extend(wires)
    service = AcquisitionService(database)
    task = service.create_task(dict(name="repeats", device_profile_id=profile["id"], ccd_indices=[0],
        repeat_count=2, burn_frame_count=1, dark_frame_count=0, pre_excitation_seconds=0))
    warm = service.preheat(task["id"])
    wait_for(lambda: service.get_task(warm["id"])["status"] == "completed")
    assert not service.get_task(warm["id"])["samples"][0]["bands"]
    service.start(task["id"])
    wait_for(lambda: service.get_task(task["id"])["status"] == "between_repeats")
    time.sleep(.1)
    assert len(wire_factory[1]) == 2
    service.start(task["id"])
    wait_for(lambda: service.get_task(task["id"])["status"] == "completed")
    assert len(service.get_task(task["id"])["samples"]) == 2
    assert all(wire.closed for wire in wires)


def test_open_failure_cannot_fall_back_to_simulation(database, monkeypatch):
    profile = serial_profile(database)
    def unavailable(**settings):
        raise serial_acq.serial.SerialException("port is occupied")
    monkeypatch.setattr(serial_acq.serial, "Serial", unavailable)
    service = AcquisitionService(database)
    task = service.create_task({"name": "no hardware", "device_profile_id": profile["id"]})
    with pytest.raises(AcquisitionError):
        service.start(task["id"])
    result = service.get_task(task["id"])
    assert result["status"] == "failed" and result["samples"] == []
    assert not service.frames(task["id"])


def test_real_pause_rejected_and_shutdown_cancels_before_excitation(database, wire_factory, monkeypatch):
    profile = serial_profile(database)
    wire = Wire([])
    wire_factory[0].append(wire)
    monkeypatch.setattr(SerialAcqAdapter, "_wait_until", lambda self, deadline: not self._cancel.wait(2))
    service = AcquisitionService(database)
    task = service.create_task({"name": "shutdown", "device_profile_id": profile["id"], "countdown_seconds": 10})
    service.start(task["id"])
    with pytest.raises(AcquisitionError) as error:
        service.pause(task["id"])
    assert error.value.code == "serial_pause_unsupported"
    service.shutdown()
    assert service.get_task(task["id"])["status"] == "stopped"
    assert wire.closed and not wire.writes


def test_corrupt_transfer_preserves_previously_received_frames(database, wire_factory):
    profile = serial_profile(database)
    broken = bytearray(transfer(100))
    broken[8193] = 5
    wire = Wire([transfer(120), bytes(broken), transfer(0)])
    wire_factory[0].append(wire)
    runtime = Runtime(AppConfig(data_dir=database.path.parent), database=database)
    service = runtime.acquisition_service()
    task = service.create_task(dict(name="corrupt", device_profile_id=profile["id"], ccd_indices=[0],
        burn_frame_count=3, dark_frame_count=0, pre_excitation_seconds=0))
    service.start(task["id"])
    wait_for(lambda: service.get_task(task["id"])["status"] == "failed")
    assert len(service.frames(task["id"])) == 1
    assert not service.get_task(task["id"])["samples"][0]["bands"]
    wait_for(lambda: wire.closed)
    runtime.messages.close()
    assert wire.writes[-1] == b"\x00"
    assert [row["details"]["frame_index"] for row in transfer_logs(runtime)] == [0]
    stages = {row["details"]["event_type"]: row for row in stage_logs(runtime)}
    assert stages["communication_fault"]["severity"] == "error"
    assert "等待中止" in stages["stop_waiting"]["message"]
    assert "中止成功" in stages["stop_confirmed"]["message"]
    assert "measurement_ended" not in stages


def test_serial_session_loss_cannot_replay_or_seed_the_last_real_frame(database, wire_factory):
    profile = serial_profile(database)
    wire_factory[0].append(Wire([transfer(120)]))
    service = AcquisitionService(database)
    task = service.create_task(dict(name="lost", device_profile_id=profile["id"], burn_frame_count=2, dark_frame_count=0))
    with database.write() as db:
        db.execute("UPDATE acquisition_tasks SET status='burn',last_event_json=? WHERE id=?",
                   ('{"event_type":"frame","state":"debugging","ccds":[]}', task["id"]))
    with pytest.raises(AcquisitionError) as error:
        service.step(task["id"])
    assert error.value.code == "acquisition_session_lost"
    assert service.get_task(task["id"])["status"] == "failed"
    assert service.frames(task["id"]) == [] and not wire_factory[1]


def test_serial_single_burn_uses_real_minimum_preheat_clock(wire_factory, monkeypatch):
    wire = Wire([transfer(1234)])
    adapter = connected(wire_factory, wire)
    monkeypatch.setattr(adapter, "_wait_until", lambda deadline: not adapter._cancel.wait(max(0, deadline - time.monotonic())))
    adapter.prepare_capture(pre_seconds=0, burn_seconds=1, burn_count=1, dark_seconds=1,
                            dark_count=0, countdown_seconds=.2, correlation_id="clock")
    started = time.monotonic()
    adapter.begin_capture()
    time.sleep(.05)
    assert wire.writes == []
    time.sleep(.25)
    assert wire.writes == [bytes.fromhex("f0000402f0")]
    assert adapter.next_capture_event() is None
    adapter._worker.join(5)
    event = adapter.next_capture_event()
    assert event is not None and event.ccds[0]["points"][0] == 1234
    assert time.monotonic() - started >= 3.4
    adapter.disconnect(correlation_id="done")


def test_debug_service_serial_is_separate_from_simulator_and_still_creates_no_samples(database, wire_factory):
    device = DeviceService(database)
    original_profiles = device.profiles()
    profile = serial_profile(database)
    wire = Wire([transfer(1500)] * 50)
    wire_factory[0].append(wire)
    device.connect(profile["id"])
    device.start_debug({})
    frame = wait_for(lambda: (event if (event := device.step_debug()["event"])["ccds"] else None))
    assert frame["details"]["transport"] == "serial"
    assert frame["ccds"][0]["points"][0] == 1500
    # The continuously filled stream can be stopped even when the last UI frame
    # has not been fetched. A full transfer acknowledges the end command.
    device.stop_debug()
    device.disconnect()
    assert wire.closed and b"\x00" in wire.writes
    assert device.profiles()[0] == original_profiles[0]
    with database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM acquisition_samples").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM spectrum_bands").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["sample", "dispersion"])
def test_stop_preserves_complete_frames_waiting_for_database_save(database, wire_factory, monkeypatch, kind):
    import backend.modules.acquisition.service as acquisition_module
    import backend.modules.dispersion.service as dispersion_module
    monkeypatch.setattr(acquisition_module, "monitor_capture", lambda *args: None)
    monkeypatch.setattr(dispersion_module, "monitor_capture", lambda *args: None)
    profile = serial_profile(database)
    wire = Wire([transfer(100), transfer(200)])
    wire_factory[0].append(wire)
    if kind == "sample":
        service = AcquisitionService(database)
        task = service.create_task(dict(name="stop queue", device_profile_id=profile["id"], ccd_indices=[0],
            burn_frame_count=2, dark_frame_count=0, pre_excitation_seconds=0))
        service.start(task["id"])
    else:
        service = DispersionService(database)
        task = service.create_task(dict(name="stop queue", device_profile_id=profile["id"], ccd_indices=[0],
            frame_count=2, dark_frame_count=0, pre_excitation_seconds=0, sampling_period_seconds=1))
        service.start_task(task["id"])
    adapter = service._adapters[task["id"]]
    adapter._worker.join(2)
    assert adapter.pending_frames
    assert service.frames(task["id"]) == []
    result = service.stop(task["id"]) if kind == "sample" else service.stop_task(task["id"])
    assert result["status"] == "completed"
    assert len(service.frames(task["id"])) == 2
    assert wire.closed


def test_connection_test_requires_a_valid_ccd_frame_and_closes_every_attempt(database, wire_factory):
    device = DeviceService(database)
    profile = serial_profile(database)
    silent = Wire([])
    wire_factory[0].append(silent)
    with pytest.raises(DeviceError) as rejected:
        device.test_connection(profile['id'])
    assert rejected.value.code == 'device_connection_test_failed'
    assert silent.closed and rejected.value.details['connected'] is False
    assert rejected.value.details['reason'] == 'serial_stop_unconfirmed'
    with pytest.raises(DeviceError) as blocked:
        device.test_connection(profile['id'])
    assert blocked.value.code == 'device_busy'
    assert device.shutdown()[0]['code'] == 'serial_stop_unconfirmed'
    valid = Wire([transfer(1500)])
    wire_factory[0].append(valid)
    result = DeviceService(database).test_connection(profile['id'])
    assert result['passed'] and result['instrument_responded']
    assert result['connected'] is False and valid.closed
    assert valid.writes == [bytes([0xF0, 0, 4, 2, 0xF0]), b'\x00']
    with database.read() as db:
        assert db.execute('SELECT COUNT(*) FROM acquisition_samples').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM spectrum_bands').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='device.connection_test'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='device.connection_test.failed'").fetchone()[0] == 1


def test_connection_test_refuses_to_interrupt_active_debug(database, wire_factory):
    device = DeviceService(database)
    original = device.profiles()[0]
    device.connect(original['id'])
    device.start_debug({})
    with pytest.raises(DeviceError) as error:
        device.test_connection(serial_profile(database)['id'])
    assert error.value.code == 'device_busy'
    assert device.adapter.diagnostics()['state'] == 'debugging'
    assert not wire_factory[1]
    device.disconnect()
