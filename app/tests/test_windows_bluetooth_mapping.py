"""Device/COM mapping comes from Windows, not names or saved app profiles."""
import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.modules.devices import ports, bluetooth, DeviceError
from tests.test_s11_devices import device_client


@pytest.fixture
def windows_mapping(monkeypatch):
    devices = [dict(address='112233445566', name='Test SPP', connected=False, paired=True),
               dict(address='AABBCCDDEEFF', name='Test keyboard', connected=True, paired=True)]
    monkeypatch.setattr(bluetooth, 'windows_bluetooth_devices', lambda: devices)
    monkeypatch.setattr(ports.list_ports, 'comports', lambda: [
        SimpleNamespace(device='COM7', description='Bluetooth serial', manufacturer=None,
                        hwid=r'BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}\7&0&112233445566_C00000000'),
        SimpleNamespace(device='COM8', description='Bluetooth serial', manufacturer=None,
                        hwid=r'BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}\7&0&000000000000_00000004'),
        SimpleNamespace(device='COM12', description='USB serial', manufacturer=None, hwid='USB\\serial')])
    return devices


def test_read_devices_and_only_their_outgoing_ports_without_opening_hardware(device_client, windows_mapping, monkeypatch):
    client, runtime, headers = device_client
    import serial
    monkeypatch.setattr(serial, 'Serial', lambda **kw: pytest.fail('Device enumeration must not open hardware'))
    assert client.get('/api/v1/devices/bluetooth').status_code == 401
    result = client.get('/api/v1/devices/bluetooth', headers=headers)
    assert result.status_code == 200
    devices = result.json()['devices']
    assert [item['name'] for item in devices] == ['Test SPP', 'Test keyboard']
    assert devices[0]['connected'] is False and devices[1]['connected'] is True
    assert [item['device'] for item in devices[0]['ports']] == ['COM7']
    assert devices[1]['ports'] == []
    raw = ports.available_serial_ports()
    assert raw[1]['direction'] == 'incoming' and raw[1]['bluetooth_address'] is None
    assert not runtime.devices_service().adapter.diagnostics()['connected']


def test_binding_rechecks_windows_mapping_before_persisting(device_client, windows_mapping):
    client, runtime, headers = device_client
    service = runtime.devices_service()
    before = service.profiles()
    for address, port in [('112233445566', 8), ('AABBCCDDEEFF', 7), ('112233445566', 12), ('000000000001', 7)]:
        response = client.put('/api/v1/devices/port', headers=headers,
                              json={'transport': 'serial', 'port': port, 'bluetooth_address': address})
        assert response.status_code == 409 and response.json()['detail']['code'] == 'bluetooth_port_mismatch'
        assert service.profiles() == before and service.current_profile() is None
    response = client.put('/api/v1/devices/port', headers=headers,
                          json={'transport': 'serial', 'port': 7, 'bluetooth_address': '112233445566'})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['port'] == 7 and saved['transport'] == 'serial'
    assert service.current_profile()['id'] == saved['id']
    assert service.profiles()[:len(before)] == before
    windows_mapping.clear()
    assert client.put('/api/v1/devices/port', headers=headers,
                      json={'transport': 'serial', 'port': 7, 'bluetooth_address': '112233445566'}).status_code == 409
    assert service.current_profile() == saved


def test_simulator_checkbox_selection_restores_real_port_and_parameters(device_client):
    client, runtime, headers = device_client
    service = runtime.devices_service()
    serial = service.create_profile({'name': 'Preserve settings', 'transport': 'serial', 'port': 9,
                                     'baud_rate': 921600, 'ccd_indices': [0, 2, 5], 'mirror': True})
    service.select_profile(serial['id'], 1)
    simulated = client.put('/api/v1/devices/port', headers=headers, json={'transport': 'simulator'})
    assert simulated.status_code == 200 and simulated.json()['transport'] == 'simulator'
    assert service.profile(serial['id']) == serial
    restored = client.put('/api/v1/devices/port', headers=headers, json={'transport': 'serial', 'port': 9})
    assert restored.status_code == 200 and restored.json() == serial
    assert not service.adapter.diagnostics()['connected']


def test_read_only_role_can_read_devices_but_cannot_change_binding(device_client, windows_mapping):
    client, runtime, headers = device_client
    role = client.post('/api/v1/roles', headers=headers, json={'name':'bt observer','permission_keys':['devices.read']}).json()
    created = client.post('/api/v1/users', headers=headers,
                          json={'username':'bt_observer','password':'Bluetooth-Test-2026!','role_ids':[role['id']]})
    assert created.status_code == 201
    token = client.post('/api/v1/auth/login', json={'username':'bt_observer','password':'Bluetooth-Test-2026!'}).json()['access_token']
    readonly = {'Authorization': f'Bearer {token}'}
    assert client.get('/api/v1/devices/bluetooth', headers=readonly).status_code == 200
    assert client.put('/api/v1/devices/port', headers=readonly,
                      json={'transport':'serial','port':7,'bluetooth_address':'112233445566'}).status_code == 403


def test_windows_enumeration_closes_handle_and_never_issues_inquiry(monkeypatch):
    class Function:
        def __init__(self, callback): self.callback = callback
        def __call__(self, *args): return self.callback(*args)
    closed = []
    def first(params, info):
        assert params._obj.inquiry == 0 and params._obj.unknown == 0
        assert params._obj.connected and params._obj.authenticated and params._obj.remembered
        info._obj.name = 'paired device'; info._obj.address = 0x112233445566
        info._obj.authenticated = True
        return 123
    api = SimpleNamespace(BluetoothFindFirstDevice=Function(first),
        BluetoothFindNextDevice=Function(lambda *args: False), BluetoothFindDeviceClose=Function(lambda handle: closed.append(handle)))
    monkeypatch.setattr(bluetooth.ctypes, 'WinDLL', lambda *args, **kwargs: api)
    monkeypatch.setattr(bluetooth.ctypes, 'get_last_error', lambda: 259)
    result = bluetooth.windows_bluetooth_devices()
    assert result == [{'name':'paired device','address':'112233445566','paired':True,'connected':False}]
    assert closed == [123]
    def failing(*args): raise OSError('adapter error')
    api.BluetoothFindNextDevice = Function(failing)
    with pytest.raises(DeviceError, match='无法读取'):
        bluetooth.windows_bluetooth_devices()
    assert closed == [123, 123]
