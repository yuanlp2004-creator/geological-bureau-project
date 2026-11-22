"""Permanent deletion here is a persisted list exclusion, never Windows unpairing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.modules.devices import DeviceService
from tests.test_s11_devices import device_client
from tests.test_windows_bluetooth_mapping import windows_mapping


def test_delete_persists_across_service_restart_and_device_rename(device_client, windows_mapping):
    client, runtime, headers = device_client
    profiles = runtime.devices_service().profiles()
    address = windows_mapping[1]['address']
    before = client.get('/api/v1/devices/bluetooth', headers=headers).json()['devices']
    response = client.delete(f'/api/v1/devices/bluetooth/{address.lower()}', headers=headers)
    assert response.status_code == 200 and response.json() == {'deleted': True}
    assert client.get('/api/v1/devices/bluetooth', headers=headers).json()['devices'] == [before[0]]
    assert client.delete(f'/api/v1/devices/bluetooth/{address}', headers=headers).status_code == 200
    windows_mapping[1]['name'] = 'renamed keyboard'
    # A new service (and initialized database) must retain the exclusion.
    runtime.database.initialize()
    restarted = DeviceService(runtime.database)
    assert restarted.bluetooth_devices()['devices'] == [before[0]]
    assert restarted.profiles() == profiles
    assert windows_mapping[1]['connected'] is True and windows_mapping[1]['paired'] is True
    with runtime.database.read() as db:
        assert db.execute('SELECT COUNT(*) FROM device_bluetooth_hidden').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='device.bluetooth.hide'").fetchone()[0] == 1


def test_invalid_or_busy_deletion_preserves_list(device_client, windows_mapping):
    client, runtime, headers = device_client
    assert client.delete('/api/v1/devices/bluetooth/invalid', headers=headers).status_code == 422
    assert client.delete('/api/v1/devices/bluetooth/000000000000', headers=headers).status_code == 404
    service = runtime.devices_service()
    service.connect(service.profiles()[0]['id'])
    try:
        assert client.delete('/api/v1/devices/bluetooth/112233445566', headers=headers).status_code == 409
        assert len(client.get('/api/v1/devices/bluetooth', headers=headers).json()['devices']) == 2
    finally:
        service.disconnect()
    with runtime.database.read() as db:
        db.execute('''CREATE TRIGGER reject_hidden_audit BEFORE INSERT ON audit_events
                      WHEN NEW.action='device.bluetooth.hide'
                      BEGIN SELECT RAISE(ABORT,'test audit rejection'); END''')
        db.commit()
    with pytest.raises(Exception, match='test audit rejection'):
        service.hide_bluetooth_device('112233445566', 1)
    assert len(service.bluetooth_devices()['devices']) == 2


def test_delete_requires_device_write_permission(device_client, windows_mapping):
    client, runtime, headers = device_client
    assert client.delete('/api/v1/devices/bluetooth/112233445566').status_code == 401
    role = client.post('/api/v1/roles', headers=headers, json={'name':'readonly bluetooth','permission_keys':['devices.read']}).json()
    assert client.post('/api/v1/users', headers=headers,
                       json={'username':'bt_reader','password':'ReadOnly-2026!','role_ids':[role['id']]}).status_code == 201
    token = client.post('/api/v1/auth/login', json={'username':'bt_reader','password':'ReadOnly-2026!'}).json()['access_token']
    readonly = {'Authorization': f'Bearer {token}'}
    assert client.get('/api/v1/devices/bluetooth', headers=readonly).status_code == 200
    assert client.delete('/api/v1/devices/bluetooth/112233445566', headers=readonly).status_code == 403
