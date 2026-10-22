from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.config import AppConfig
from backend.main import create_app
from backend.modules.manifest import registered_manifests


@pytest.fixture
def diagnostic_client(tmp_path: Path):
    app = create_app(AppConfig(data_dir=tmp_path))
    with TestClient(app) as client:
        client.post('/api/v1/auth/bootstrap', json={'username': 'module_admin', 'password': 'ModuleTest-2026!'})
        token = client.post('/api/v1/auth/login', json={'username': 'module_admin', 'password': 'ModuleTest-2026!'}).json()['access_token']
        yield app, client, {'Authorization': f'Bearer {token}'}


def read_modules(client, headers):
    response = client.get('/api/v1/diagnostics', headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['checked_at']
    return {module['key']: module for module in payload['modules']}


def test_all_modules_use_actual_readonly_interfaces_without_writes(diagnostic_client, monkeypatch):
    app, client, headers = diagnostic_client
    database = app.state.runtime.database

    def refuse_write():
        raise AssertionError('module detection attempted a database write')

    monkeypatch.setattr(database, 'write', refuse_write)
    modules = read_modules(client, headers)
    assert len(modules) == 18
    assert all(row['status'] == 'active' and row['http_status'] == 200 for row in modules.values()), modules
    assert modules['hardware-acquisition']['note']
    assert modules['mercury-calibration']['note']


@pytest.mark.parametrize('fault', ['missing_route', 'missing_table', 'service_failure', 'bad_response', 'disabled_dependency'])
def test_runtime_failures_cannot_appear_available(diagnostic_client, monkeypatch, fault):
    app, client, headers = diagnostic_client
    runtime = app.state.runtime
    if fault == 'missing_route':
        from backend.api.methods import router as methods_router
        app.router.routes[:] = [route for route in app.router.routes
                               if getattr(route, 'original_router', None) is not methods_router
                               and not (getattr(route, 'path', '') == '/api/v1/methods' and 'GET' in getattr(route, 'methods', set()))]
    elif fault == 'missing_table':
        with runtime.database.write() as connection:
            connection.execute('DROP TABLE method_runtime_state')
    elif fault in {'service_failure', 'bad_response'}:
        class FailedMethods:
            def list(self, *args, **kwargs):
                if fault == 'service_failure':
                    raise HTTPException(status_code=503, detail='isolated service unavailable')
                return {'unexpected': True}
        monkeypatch.setattr(runtime, 'methods_service', lambda: FailedMethods())
    else:
        manifests = tuple(replace(module, enabled=False) if module.key == 'methods' else module
                          for module in registered_manifests())
        monkeypatch.setattr('backend.api.system.registered_manifests', lambda: manifests)
    modules = read_modules(client, headers)
    assert modules['methods']['status'] == ('disabled' if fault == 'disabled_dependency' else 'error'), modules['methods']
    assert modules['analysis']['status'] != 'active'
    assert modules['core']['status'] == 'active'


def test_no_probe_and_permission_failure_are_not_success(diagnostic_client, monkeypatch):
    app, client, headers = diagnostic_client
    manifests = tuple(replace(module, diagnostic_path=None) if module.key == 'reports' else module
                      for module in registered_manifests())
    monkeypatch.setattr('backend.api.system.registered_manifests', lambda: manifests)
    assert read_modules(client, headers)['reports']['status'] == 'unchecked'
    # An administrator with only maintenance permissions must not gain other API rights.
    runtime = app.state.runtime
    token = headers['Authorization'].split()[1]
    session = runtime.auth_service.sessions[token]
    runtime.auth_service.sessions[token] = replace(session, permissions=frozenset({'maintenance.write', 'maintenance.read'}))
    modules = read_modules(client, headers)
    assert modules['methods']['status'] == 'restricted'
    assert modules['about-diagnostics']['status'] == 'restricted'


def test_invalid_manifest_is_reported_instead_of_a_false_pass(diagnostic_client, monkeypatch):
    _, client, headers = diagnostic_client
    manifests = tuple(replace(module, dependencies=('does-not-exist',)) if module.key == 'methods' else module
                      for module in registered_manifests())
    monkeypatch.setattr('backend.api.system.registered_manifests', lambda: manifests)
    response = client.get('/api/v1/diagnostics', headers=headers)
    assert response.status_code == 200
    assert response.json()['manifest_valid'] is False
    assert response.json()['manifest_error']
    assert all(row['status'] == 'error' for row in response.json()['modules'])


def test_internal_probes_preserve_desktop_process_key_boundary(diagnostic_client):
    app, client, headers = diagnostic_client
    app.state.runtime.process_key = 'diagnostic-test-key'
    assert client.get('/api/v1/diagnostics', headers=headers).status_code == 403
    response = client.get('/api/v1/diagnostics', headers=headers | {'X-GeoSpectrum-Process-Key': 'diagnostic-test-key'})
    assert response.status_code == 200
    assert all(module['status'] == 'active' for module in response.json()['modules'])
    assert 'diagnostic-test-key' not in response.text
    app.state.runtime.process_key = ''


def test_query_timeout_is_reported(diagnostic_client, monkeypatch):
    import asyncio
    import httpx
    _, client, headers = diagnostic_client
    original = httpx.AsyncClient.get

    async def delayed(self, url, **kwargs):
        if str(url).startswith('/api/v1/reports?'):
            await asyncio.sleep(5)
        return await original(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, 'get', delayed)
    report = read_modules(client, headers)['reports']
    assert report['status'] == 'error'
    assert report['message'] == '查询接口检测超时'
