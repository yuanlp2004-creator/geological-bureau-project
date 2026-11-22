"""Bluetooth SPP reuses the actual serial adapter; no physical port is opened."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.modules.devices import DeviceError, DeviceService
from backend.modules.devices import ports, serial_acq
from tests.test_s11_devices import device_client
from tests.test_legacy_serial_acquisition import database, wire_factory, Wire, transfer, wait_for


def info(device, description='', hwid='', manufacturer=None):
    return SimpleNamespace(device=device, description=description, hwid=hwid, manufacturer=manufacturer)


def test_port_discovery_is_read_only_numerically_sorted_and_identifies_bluetooth(monkeypatch):
    monkeypatch.setattr(ports.list_ports, 'comports', lambda: [
        info('COM12', 'Standard Serial', 'BTHENUM\\device'), info('COM2', 'USB serial'),
        info('com3', '蓝牙串口'), info('COM257'), info('COM0'), info('loop://'), info('COM2', 'USB serial')])
    monkeypatch.setattr(serial_acq.serial, 'Serial', lambda **kw: pytest.fail('Enumeration must never open a port'))
    result = ports.available_serial_ports()
    assert [item['device'] for item in result] == ['COM2', 'COM3', 'COM12']
    assert [item['is_bluetooth'] for item in result] == [False, True, True]
    monkeypatch.setattr(ports.list_ports, 'comports', lambda: [])
    assert ports.available_serial_ports() == []


def test_ports_api_authentication_empty_and_enumeration_failure(device_client, monkeypatch):
    client, runtime, headers = device_client
    assert client.get('/api/v1/devices/ports').status_code == 401
    monkeypatch.setattr(ports.list_ports, 'comports', lambda: [])
    assert client.get('/api/v1/devices/ports', headers=headers).json() == []
    def fail(): raise OSError('enumeration unavailable')
    monkeypatch.setattr(ports.list_ports, 'comports', fail)
    response = client.get('/api/v1/devices/ports', headers=headers)
    assert response.status_code == 503 and response.json()['detail']['code'] == 'serial_ports_unavailable'
    assert runtime.devices_service().adapter.diagnostics()['connected'] is False


def test_connect_and_disconnect_send_no_acquisition_commands_and_protect_active_profile(device_client, wire_factory):
    client, runtime, headers = device_client
    service = runtime.devices_service()
    profile = service.create_profile({'name': 'Bluetooth SPP', 'transport': 'serial', 'port': 12})
    original = service.profiles()[0]
    wire = Wire([]); wire_factory[0].append(wire)
    response = client.post('/api/v1/devices/connect', headers=headers, json={'profile_id': profile['id']})
    assert response.status_code == 200
    diagnostics = client.get('/api/v1/devices/diagnostics', headers=headers).json()
    assert diagnostics['adapter']['profile_id'] == profile['id']
    assert diagnostics['adapter']['port'] == 'COM12'
    assert diagnostics['adapter']['instrument_responded'] is False
    assert wire.writes == []
    assert client.patch(f"/api/v1/devices/profiles/{profile['id']}", headers=headers, json={'port': 13}).status_code == 409
    assert client.put('/api/v1/devices/current', headers=headers, json={'profile_id': original['id']}).status_code == 409
    assert client.post('/api/v1/devices/connect', headers=headers, json={'profile_id': original['id']}).status_code == 409
    assert client.post('/api/v1/devices/disconnect', headers=headers).status_code == 200
    assert client.post('/api/v1/devices/disconnect', headers=headers).status_code == 200
    assert wire.closed and wire.writes == []
    assert service.profile(profile['id'])['port'] == 12


def test_failed_open_remains_disconnected_and_can_retry(device_client, wire_factory, monkeypatch):
    client, runtime, headers = device_client
    service = runtime.devices_service()
    profile = service.create_profile({'name': 'occupied', 'transport': 'serial'})
    factory = serial_acq.serial.Serial
    def occupied(**settings): raise serial_acq.serial.SerialException('Access denied')
    monkeypatch.setattr(serial_acq.serial, 'Serial', occupied)
    response = client.post('/api/v1/devices/connect', headers=headers, json={'profile_id': profile['id']})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'serial_open_failed'
    assert not service.adapter.diagnostics()['connected']
    assert service.profile(profile['id']) == profile
    monkeypatch.setattr(serial_acq.serial, 'Serial', factory)
    wire_factory[0].append(Wire([]))
    assert client.post('/api/v1/devices/connect', headers=headers, json={'profile_id': profile['id']}).status_code == 200
    service.disconnect()


@pytest.mark.parametrize('kind', ['sample', 'evaporation', 'dispersion'])
def test_idle_connection_hands_off_to_ccd_gate_and_capture(device_client, wire_factory, kind):
    client, runtime, headers = device_client
    devices = runtime.devices_service()
    profile = devices.create_profile({'name': 'Bluetooth capture', 'transport': 'serial', 'port': 12})
    idle, probe, capture = Wire([]), Wire([transfer(700)]), Wire([transfer(800)])
    wire_factory[0].extend([idle, probe, capture])
    devices.connect(profile['id'])
    purpose = 'dispersion' if kind == 'dispersion' else 'acquisition'
    response = client.post(f"/api/v1/devices/profiles/{profile['id']}/connection-test?purpose={purpose}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['instrument_responded'] and idle.closed and probe.closed
    assert not devices.adapter.diagnostics()['connected']
    if kind == 'dispersion':
        service = runtime.dispersion_service()
        task = service.create_task({'name': 'SPP dispersion', 'device_profile_id': profile['id'],
            'ccd_layout_id': 1, 'ccd_indices': [0], 'frame_count': 1, 'dark_frame_count': 0,
            'pre_excitation_seconds': 0, 'sampling_period_seconds': 1})
        service.start_task(task['id'])
    else:
        service = runtime.acquisition_service()
        task = service.create_task({'name': 'SPP '+kind, 'task_kind': kind, 'device_profile_id': profile['id'],
            'ccd_indices': [0], 'burn_frame_count': 1, 'dark_frame_count': 0,
            'pre_excitation_seconds': 0, 'sampling_period_seconds': 1, 'burn_cycle_seconds': 1})
        service.start(task['id'])
    wait_for(lambda: service.get_task(task['id'])['status'] in {'completed', 'failed'})
    assert service.get_task(task['id'])['status'] == 'completed'
    assert capture.closed and runtime.active_serial_captures() == []
    assert all(wire.settings['port'] == 'COM12' for wire in (idle, probe, capture))


def test_handoff_never_interrupts_other_profile_or_running_debug(database, wire_factory):
    service = DeviceService(database)
    original = service.profiles()[0]
    target = service.create_profile({'name': 'other', 'transport': 'serial'})
    service.connect(original['id'])
    with pytest.raises(DeviceError, match='请先停止'):
        service.test_connection(target['id'], handoff=True)
    service.start_debug({})
    with pytest.raises(DeviceError, match='请先停止'):
        service.test_connection(original['id'], handoff=True)
    assert service.adapter.diagnostics()['state'] == 'debugging'
    assert not wire_factory[1]
    service.disconnect()


def test_direct_com_selection_preserves_existing_profiles_and_reuses_saved_port(device_client, monkeypatch):
    client, runtime, headers = device_client
    service = runtime.devices_service()
    original = service.profiles()
    monkeypatch.setattr(serial_acq.serial, 'Serial', lambda **kw: pytest.fail('Selecting a port must not open it'))
    assert client.put('/api/v1/devices/port', json={'transport': 'serial', 'port': 12}).status_code == 401
    response = client.put('/api/v1/devices/port', headers=headers, json={'transport': 'serial', 'port': 12})
    assert response.status_code == 200, response.text
    selected = response.json()
    assert selected['transport'] == 'serial' and selected['port'] == 12
    assert service.current_profile()['id'] == selected['id']
    assert service.profiles()[:len(original)] == original
    assert client.put('/api/v1/devices/port', headers=headers,
                      json={'transport': 'serial', 'port': 12}).json()['id'] == selected['id']
    assert len(service.profiles()) == len(original) + 1
    other = client.put('/api/v1/devices/port', headers=headers,
                       json={'transport': 'serial', 'port': 7}).json()
    assert other['id'] != selected['id'] and service.profile(selected['id']) == selected
    simulator = client.put('/api/v1/devices/port', headers=headers, json={'transport': 'simulator'}).json()
    assert simulator['id'] == original[0]['id'] and simulator['transport'] == 'simulator'
    assert client.put('/api/v1/devices/port', headers=headers,
                      json={'transport': 'serial', 'port': 12}).json()['id'] == selected['id']


def test_direct_com_selection_rejects_invalid_and_connected_changes_without_creating_records(device_client):
    client, runtime, headers = device_client
    service = runtime.devices_service()
    original = service.profiles()
    for payload in ({'transport': 'serial'}, {'transport': 'serial', 'port': 0},
                    {'transport': 'serial', 'port': 257}, {'transport': 'unknown'}):
        assert client.put('/api/v1/devices/port', headers=headers, json=payload).status_code == 422
    client.put('/api/v1/devices/port', headers=headers, json={'transport': 'simulator'})
    service.connect(original[0]['id'])
    response = client.put('/api/v1/devices/port', headers=headers, json={'transport': 'serial', 'port': 12})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'device_busy'
    assert service.profiles() == original
    assert service.current_profile()['id'] == original[0]['id']
    service.disconnect()
