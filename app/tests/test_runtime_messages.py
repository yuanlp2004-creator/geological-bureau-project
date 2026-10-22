"""Operator logs follow actual public events without changing command outcomes."""
from __future__ import annotations

from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import AppConfig
from backend.main import create_app
from backend.runtime_messages import RuntimeMessages


@pytest.fixture
def device_client(tmp_path):
    application = create_app(AppConfig(data_dir=tmp_path))
    with TestClient(application) as client:
        account = {'username': 'operator', 'password': 'correct-horse'}
        assert client.post('/api/v1/auth/bootstrap', json=account).status_code == 201
        token = client.post('/api/v1/auth/login', json=account).json()['access_token']
        yield client, application.state.runtime, {'Authorization': f'Bearer {token}'}


def test_device_logs_are_real_events_not_http_requests(device_client):
    client, runtime, headers = device_client
    profile = client.get('/api/v1/devices/profiles', headers=headers).json()[0]
    assert client.post('/api/v1/devices/connect', headers=headers, json={'profile_id': profile['id']}).status_code == 200
    start = client.post('/api/v1/devices/debug/start', headers=headers, json={'sample': '280-288.acq', 'seed': 19})
    assert start.status_code == 200
    assert client.post('/api/v1/devices/debug/step', headers=headers).status_code == 200
    assert client.post('/api/v1/devices/debug/stop', headers=headers).status_code == 200
    events = client.get('/api/v1/logs?limit=500', headers=headers).json()
    communications = [e for e in events if (e['details'] or {}).get('channel') == 'communication']
    assert len(communications) == 4
    assert any(e['severity'] == 'debug' for e in communications)
    assert all('ccds' not in e['details'] and 'points' not in e['details'] for e in communications)
    count = len(events)
    assert client.get('/api/v1/devices/diagnostics', headers=headers).status_code == 200
    assert client.get('/api/v1/logs', headers=headers).status_code == 200
    assert client.post('/api/v1/devices/debug/step').status_code == 401
    assert len(client.get('/api/v1/logs?limit=500', headers=headers).json()) == count
    with runtime.database.read() as db:
        assert db.execute('SELECT COUNT(*) FROM spectrum_bands').fetchone()[0] == 0


def test_public_task_messages_are_deduplicated_across_refresh_and_restart(device_client):
    _, runtime, _ = device_client
    response = {'id': 91, 'messages': [
        {'id': 711, 'level': 'info', 'code': 'started', 'message': '分析开始'},
        {'id': 712, 'level': 'success', 'code': 'completed', 'message': '分析完成'},
    ]}
    assert runtime.messages.task(response, source='analysis', category='analysis') is response
    runtime.messages.task(response, source='analysis', category='analysis')
    RuntimeMessages(runtime.service).task(response, source='analysis', category='analysis')
    rows = runtime.service.list_events(category='analysis', limit=500)
    assert [row['message'] for row in rows] == ['分析完成', '分析开始']
    assert all(row['details']['channel'] == 'general' for row in rows)


def test_logging_failure_does_not_fail_or_repeat_a_device_command(device_client, monkeypatch):
    client, runtime, headers = device_client
    profile = client.get('/api/v1/devices/profiles', headers=headers).json()[0]
    def unavailable(*args, **kwargs):
        raise OSError('simulated log storage failure')
    with monkeypatch.context() as patch:
        patch.setattr(runtime.service, 'append_event', unavailable)
        connected = client.post('/api/v1/devices/connect', headers=headers, json={'profile_id': profile['id']})
        assert connected.status_code == 200
        assert connected.json()['diagnostics']['connected'] is True
