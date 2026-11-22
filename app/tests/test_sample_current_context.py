"""Number-only acquisition must use the explicit current selections, never list order."""
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import AppConfig
from backend.main import create_app
from backend.modules.devices import DeviceError
from backend.modules.devices.service import DeviceService
from backend.modules.sample_queues import SampleQueueService


@pytest.fixture
def client_state(tmp_path):
    app = create_app(AppConfig(data_dir=tmp_path))
    with TestClient(app) as client:
        client.post('/api/v1/auth/bootstrap', json={'username': 'context-admin', 'password': 'context-password-2026'})
        token = client.post('/api/v1/auth/login', json={'username': 'context-admin', 'password': 'context-password-2026'}).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        def call(url, body=None, verb=None):
            response = client.request(verb or ('GET' if body is None else 'POST'), '/api/v1' + url, headers=headers, json=body)
            assert response.status_code < 300, response.text
            return response.json()
        for name in ('other-method', 'current-method'):
            method = call('/methods', {'name': name, 'conditions': {'frame_count': 2, 'dark_frame_count': 0,
                'pre_excitation_seconds': 1, 'sampling_period_seconds': 1, 'selected_ccds': [0],
                'exposure_mode': 'simple_mean', 'angle_exposures': [{'angle_deg': 0, 'storage_mode': 'averaged', 'start_frame': 1, 'end_frame': 2}]}})
            call(f"/methods/{method['id']}/lines", json.loads(Path(__file__).with_name('fixtures').joinpath('station17-line.json').read_text('utf-8')))
            call(f"/methods/{method['id']}/publish", {})
        call('/methods/current', {'method_id': method['id']})
        yield client, app.state.runtime, headers, call, method


def select_context(call):
    profile = call('/devices/profiles', {'name': 'chosen-second-device'})
    call('/devices/current', {'profile_id': profile['id']}, 'PUT')
    call('/sample-queues', {'name': 'other-list', 'items': [{'pre_name': 'OTHER', 'repeats': 1}]})
    queue = call('/sample-queues', {'name': 'chosen-list', 'name_length': 20,
        'items': [{'pre_name': 'A1234567890123456789', 'repeats': 3}, {'pre_name': 'S1', 'repeats': 2}]})
    call('/sample-queues/current', {'queue_id': queue['id']}, 'PUT')
    return profile, queue


def test_number_only_uses_current_sources_and_keeps_task_snapshot(client_state):
    client, runtime, headers, call, method = client_state
    profile, queue = select_context(call)
    name = '本次摄谱数据编号_20261105_1630'
    task = call('/acquisitions/sample-sessions', {'name': name})
    assert task['name'] == name and task['sample_name'] == queue['items'][0]['pre_name']
    assert task['method_id'] == method['id'] and task['device_profile_id'] == profile['id']
    assert task['queue_id'] == queue['id'] and task['repeat_count'] == 3 and task['name_length'] == 20
    assert task['burn_frame_count'] == 2 and task['dark_frame_count'] == 0
    other = next(item for item in call('/methods') if item['id'] != method['id'])
    call('/methods/current', {'method_id': other['id']})
    assert call(f"/acquisitions/tasks/{task['id']}")['method_id'] == method['id']
    assert DeviceService(runtime.database).current_profile()['id'] == profile['id']
    assert SampleQueueService(runtime.database).current_queue()['id'] == queue['id']
    assert client.post('/api/v1/acquisitions/sample-sessions', headers=headers,
                       json={'name': 'override', 'method_id': other['id']}).status_code == 422


def test_missing_context_does_not_select_first_or_create_task(client_state):
    client, _, headers, call, _ = client_state
    before = len(call('/acquisitions/tasks'))
    response = client.post('/api/v1/acquisitions/sample-sessions', headers=headers, json={'name': 'number'})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'current_device_required'
    profile = call('/devices/profiles')[0]
    call('/devices/current', {'profile_id': profile['id']}, 'PUT')
    response = client.post('/api/v1/acquisitions/sample-sessions', headers=headers, json={'name': 'number'})
    assert response.status_code == 422 and response.json()['detail']['code'] == 'current_sample_queue_required'
    assert len(call('/acquisitions/tasks')) == before
    assert client.post('/api/v1/acquisitions/sample-sessions', headers=headers, json={'name': '   '}).status_code == 422
    assert client.post('/api/v1/acquisitions/sample-sessions', headers=headers, json={'name': 'bad/name'}).status_code == 422


def test_failed_selected_serial_connection_creates_no_draft(client_state, monkeypatch):
    client, runtime, headers, call, _ = client_state
    _, queue = select_context(call)
    profile = call('/devices/profiles', {'name': 'selected-real', 'transport': 'serial', 'port': 4})
    call('/devices/current', {'profile_id': profile['id']}, 'PUT')
    attempted = []
    def unavailable(profile_id, **kwargs):
        attempted.append(profile_id)
        raise DeviceError('test_unavailable', '模拟真实设备连接失败')
    monkeypatch.setattr(runtime.devices_service(), 'test_connection', unavailable)
    before = len(call('/acquisitions/tasks'))
    response = client.post('/api/v1/acquisitions/sample-sessions', headers=headers, json={'name': 'serial-check'})
    assert response.status_code >= 400 and attempted == [profile['id']]
    assert len(call('/acquisitions/tasks')) == before
    assert call('/sample-queues/current')['id'] == queue['id']


def test_current_selection_and_creation_require_write_permission(client_state):
    client, _, _, call, _ = client_state
    profile, queue = select_context(call)
    roles = call('/roles')
    call('/users', {'username': 'context-viewer', 'password': 'context-viewer-password',
        'role_ids': [next(role['id'] for role in roles if role['name'] == 'read_only_auditor')]})
    token = client.post('/api/v1/auth/login', json={'username': 'context-viewer', 'password': 'context-viewer-password'}).json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    for url, body, verb in [('/devices/current', {'profile_id': profile['id']}, 'PUT'),
                            ('/sample-queues/current', {'queue_id': queue['id']}, 'PUT'),
                            ('/acquisitions/sample-sessions', {'name': 'viewer'}, 'POST')]:
        assert client.request(verb, '/api/v1' + url, headers=headers, json=body).status_code == 403


def test_saved_default_device_parameters_survive_restart(client_state):
    _, runtime, _, call, _ = client_state
    profile = next(item for item in call('/devices/profiles') if item['name'] == 'S11 模拟器')
    call('/devices/current', {'profile_id': profile['id']}, 'PUT')
    saved = call(f"/devices/profiles/{profile['id']}", {'port': 8, 'baud_rate': 921600, 'mirror': True}, 'PATCH')
    runtime.database.initialize()
    current = call('/devices/current')
    assert current == saved
