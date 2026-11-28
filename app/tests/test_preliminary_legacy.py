"""Legacy EDT/WDT fields, authoritative context and confirmation-only defaults."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading

import pytest
import json
from tests.test_sample_current_context import client_state, select_context
from tests.test_legacy_serial_acquisition import Wire, transfer, wait_for, wire_factory
from backend.modules.devices import DeviceError
from backend.modules.devices import serial_acq
from backend.schemas.system import PreliminaryConditions, SettingsPreliminary


def endpoint(kind):
    return '/dispersion/capture-sessions' if kind == 'dispersion' else '/acquisitions/evaporation-sessions'


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_preliminary_angle_pages_capture_separately_and_lock_real_turns(client_state, monkeypatch, kind):
    from backend.modules.devices import AcqSimulatorAdapter
    from backend.db import utc_now

    client, runtime, headers, call, old_method = client_state
    select_context(call)
    # Model a published legacy method which has angles but has not yet calibrated them.
    with runtime.database.write() as db:
        row = db.execute("SELECT * FROM method_versions WHERE method_id=? AND state='published'", (old_method['id'],)).fetchone()
        payload = json.loads(row['payload_json'])
        payload['conditions']['angle_exposures'] = [
            dict(angle_deg=angle, storage_mode='averaged', start_frame=1, end_frame=2, ccd_indices=[0]) for angle in (17, 4)]
        version = row['version'] + 1
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,?,'published',?,'[]',?)",
                   (old_method['id'], version, json.dumps(payload), utc_now()))
        db.execute('UPDATE methods SET current_version=? WHERE id=?', (version, old_method['id']))
    call('/methods/current', {'method_id': old_method['id']})
    body = dict(name='同名不同角', pre_excitation_seconds=1, sampling_period_seconds=1,
                frame_count=2, dark_frame_count=1, save_conditions=False)
    result = call(endpoint(kind), body)
    assert [item['angle_deg'] for item in result['capture_turns']] == [17, 4]
    first, second = [item['id'] for item in result['capture_turns']]
    assert result['id'] == first and result['ccd_indices'] == [0]
    base = '/dispersion/tasks' if kind == 'dispersion' else '/acquisitions/tasks'
    other = next(item for item in call('/methods') if item['id'] != old_method['id'])
    call('/methods/current', {'method_id': other['id']})
    assert call(f'{base}/{second}')['method_version'] == version
    positions = []
    original = AcqSimulatorAdapter.position_angle
    def position(self, angle, correlation_id):
        positions.append(angle)
        return original(self, angle, correlation_id)
    monkeypatch.setattr(AcqSimulatorAdapter, 'position_angle', position)
    warmup = call(f'{base}/{second}/preheat', {})
    assert warmup['capture_turn']['angle_deg'] == 4
    assert client.post(f'/api/v1{base}/{first}/start', headers=headers).status_code == 409
    call(f"{base}/{warmup['id']}/stop", {})
    frame_sets = []
    for task_id in (second, first):
        current = call(f'{base}/{task_id}/start', {})
        for _ in range(10):
            if current['status'] == 'completed':
                break
            current = call(f'{base}/{task_id}/step', {})
        assert current['status'] == 'completed'
        frames = call(f'{base}/{task_id}/frames?ccd_index=0')
        assert len(frames) == 3
        assert {frame['task_id'] for frame in frames} == {task_id}
        frame_sets.append({frame['id'] for frame in frames})
    assert positions == [4, 4, 17] and frame_sets[0].isdisjoint(frame_sets[1])

    call('/methods/current', {'method_id': old_method['id']})
    serial = call('/devices/profiles', {'name': '真实角度门禁', 'transport': 'serial', 'port': 4})
    call('/devices/current', {'profile_id': serial['id']}, 'PUT')
    monkeypatch.setattr(runtime.devices_service(), 'test_connection', lambda *a, **kw: pytest.fail('不能向真实设备发命令'))
    blocked = client.post('/api/v1' + endpoint(kind), headers=headers, json=body)
    assert blocked.status_code == 409 and blocked.json()['detail']['code'] == 'hardware_protocol_unavailable'


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_preliminary_sources_and_independent_saved_conditions(client_state, kind):
    client, runtime, headers, call, method = client_state
    profile, _ = select_context(call)
    original = call('/settings')['preliminary']
    body = dict(name='本次曲线_20261105', pre_excitation_seconds=1, sampling_period_seconds=1.5,
                frame_count=2, dark_frame_count=0, save_conditions=False)
    task = call(endpoint(kind), body)
    assert task['name'] == body['name'] and task['device_profile_id'] == profile['id']
    assert task['method_id'] == method['id']
    assert [(angle['id'], angle['angle_deg']) for angle in task['capture_turns']] == [(task['id'], 0)]
    if kind == 'dispersion':
        assert task['frame_count'] == 2
        assert task['ccd_indices'] == profile['ccd_indices']
    else:
        assert task['method_id'] == method['id'] and task['burn_frame_count'] == 2
        assert task['storage_mode'] == 'full_interval' and task['repeat_count'] == 1
        assert task['ccd_indices'] == [0] and task['sample_name'] == body['name']
    assert task['dark_frame_count'] == 0 and task['sampling_period_seconds'] == 1.5
    task_path = f"/dispersion/tasks/{task['id']}" if kind == 'dispersion' else f"/acquisitions/tasks/{task['id']}"
    call(task_path + '/start', {})
    call(task_path + '/stop', {})
    assert call('/settings')['preliminary'] == original
    body.update(name='保存条件的曲线', pre_excitation_seconds=2, sampling_period_seconds=1.25,
                frame_count=4, dark_frame_count=2, save_conditions=True)
    call(endpoint(kind), body)
    saved = call('/settings')['preliminary']
    assert saved[kind] == {key:value for key,value in body.items() if key not in {'name','save_conditions'}}
    other = 'evaporation' if kind == 'dispersion' else 'dispersion'
    assert saved[other] == original[other]
    runtime.database.initialize()
    assert call('/settings')['preliminary'] == saved
    assert client.post('/api/v1' + endpoint(kind), json=body).status_code == 401
    assert client.post('/api/v1' + endpoint(kind), headers=headers, json={**body, 'device_profile_id': 1}).status_code == 422


def test_save_preliminary_conditions_reuses_transaction_with_invalid_settings(client_state, monkeypatch):
    _, runtime, _, call, _ = client_state
    actor_id = call('/auth/me')['id']
    previous = PreliminaryConditions(frame_count=7, dark_frame_count=2).model_dump()
    replacement = PreliminaryConditions(frame_count=12, dark_frame_count=4)
    evaporation_default = SettingsPreliminary().evaporation.model_dump()
    insert_setting = "INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, '2026-01-01')"
    with runtime.database.write() as connection:
        connection.execute(insert_setting, ('preliminary.evaporation', '{"frame_count": 0}'))

    def reject_new_connection():
        pytest.fail('saving conditions must reuse the active database connection')

    with runtime.database.write() as connection:
        connection.execute(insert_setting, ('preliminary.dispersion', json.dumps(previous)))
        with monkeypatch.context() as patch:
            patch.setattr(runtime.database, 'connect', reject_new_connection)
            patch.setattr(runtime.database, 'write', reject_new_connection)
            saved = runtime.service.save_preliminary_conditions(
                'dispersion', replacement, actor_id, connection=connection
            )
        assert saved == replacement.model_dump()
        audit = connection.execute(
            "SELECT actor_user_id, details_json FROM audit_events WHERE action='settings.update' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert audit['actor_user_id'] == actor_id
        assert json.loads(audit['details_json']) == {
            'changed_groups': ['preliminary'],
            'before': {'preliminary': {'dispersion': previous, 'evaporation': evaporation_default}},
            'after': {'preliminary': {'dispersion': saved, 'evaporation': evaporation_default}},
        }
    assert runtime.service.get_settings()['preliminary'] == {'dispersion': saved, 'evaporation': evaporation_default}


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_save_failure_rolls_back_task_and_defaults(client_state, monkeypatch, kind):
    _, runtime, _, call, _ = client_state
    select_context(call)
    tasks_url = '/dispersion/tasks' if kind == 'dispersion' else '/acquisitions/tasks'
    before, defaults = len(call(tasks_url)), call('/settings')['preliminary']
    def unavailable(*args, **kwargs):
        raise OSError('save failed')
    monkeypatch.setattr(runtime.service, 'save_preliminary_conditions', unavailable)
    with pytest.raises(OSError, match='save failed'):
        call(endpoint(kind), dict(name='不得留下半成品', pre_excitation_seconds=1,
             sampling_period_seconds=1, frame_count=2, dark_frame_count=0, save_conditions=True))
    assert len(call(tasks_url)) == before
    assert call('/settings')['preliminary'] == defaults


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_legacy_limits_and_missing_device_reject_without_writes(client_state, kind):
    client, _, headers, call, _ = client_state
    body = dict(name='合法曲线名', pre_excitation_seconds=1, sampling_period_seconds=1,
                frame_count=2, dark_frame_count=0, save_conditions=True)
    missing = client.post('/api/v1' + endpoint(kind), headers=headers, json=body)
    assert missing.status_code == 422 and missing.json()['detail']['code'] == 'current_device_required'
    select_context(call)
    original = call('/settings')['preliminary']
    for field, value in [('name',' '), ('name','bad/name'), ('pre_excitation_seconds',0),
                         ('pre_excitation_seconds',11), ('sampling_period_seconds',.5),
                         ('sampling_period_seconds',2.1), ('frame_count',0), ('dark_frame_count',21)]:
        response = client.post('/api/v1' + endpoint(kind), headers=headers, json={**body,field:value})
        assert response.status_code == 422, response.text
    assert call('/settings')['preliminary'] == original


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_selected_serial_connection_failure_creates_no_task_or_defaults(client_state, monkeypatch, kind):
    client, runtime, headers, call, _ = client_state
    profile = call('/devices/profiles', {'name': '当前真实设备', 'transport': 'serial', 'port': 4})
    call('/devices/current', {'profile_id': profile['id']}, 'PUT')
    attempted = []
    def unavailable(profile_id, **kwargs):
        attempted.append(profile_id)
        raise DeviceError('qa_connection_failed', '模拟当前仪器未连通')
    monkeypatch.setattr(runtime.devices_service(), 'test_connection', unavailable)
    tasks_url = '/dispersion/tasks' if kind == 'dispersion' else '/acquisitions/tasks'
    count, defaults = len(call(tasks_url)), call('/settings')['preliminary']
    response = client.post('/api/v1' + endpoint(kind), headers=headers, json=dict(name='不可建立',
        pre_excitation_seconds=1, sampling_period_seconds=1, frame_count=2, dark_frame_count=0, save_conditions=True))
    assert response.status_code >= 400 and attempted == [profile['id']]
    assert len(call(tasks_url)) == count and call('/settings')['preliminary'] == defaults


@pytest.mark.parametrize('kind', ['sample', 'evaporation', 'dispersion'])
def test_serial_session_hands_off_idle_alignment_and_checks_one_frame(client_state, wire_factory, kind):
    client, runtime, headers, call, _ = client_state
    select_context(call)
    profile = call('/devices/profiles', {'name': 'serial handoff', 'transport': 'serial', 'port': 12})
    call('/devices/current', {'profile_id': profile['id']}, 'PUT')
    idle, check = Wire([]), Wire([transfer(100)])
    wire_factory[0].extend((idle, check))
    call('/devices/connect', {'profile_id': profile['id']})
    assert call('/devices/diagnostics')['ownership']['owner'] == 'alignment'
    route = '/acquisitions/sample-sessions' if kind == 'sample' else endpoint(kind)
    body = {'name': 'serial handoff'}
    permission = 'dispersion.execute' if kind == 'dispersion' else 'acquisition.execute'
    token = headers['Authorization'].split()[-1]
    original = runtime.auth_service.sessions[token]
    runtime.auth_service.sessions[token] = replace(original, permissions=original.permissions - {permission})
    assert client.post('/api/v1' + route, headers=headers, json=body).status_code == 403
    assert not idle.closed and wire_factory[1] == [idle]
    runtime.auth_service.sessions[token] = original

    task = call(route, body)
    assert task['device_profile_id'] == profile['id'] and task['status'] == 'draft'
    assert wire_factory[1] == [idle, check] and idle.closed and check.closed
    assert idle.writes == [] and check.writes == [bytes([0xF0, 0, 4, 2, 0xF0]), b'\x00']
    assert call('/devices/diagnostics')['ownership'] is None


@pytest.mark.parametrize('winner', ['alignment', 'sample-acquisition'])
def test_serial_requests_reserve_before_contended_port_open(client_state, wire_factory, monkeypatch, winner):
    client, runtime, headers, call, _ = client_state
    profile = call('/devices/profiles', {'name': 'serial race', 'transport': 'serial', 'port': 12})
    sample = runtime.acquisition_service().create_task(dict(name='sample race', device_profile_id=profile['id'],
        ccd_indices=[0], burn_frame_count=1, dark_frame_count=0, pre_excitation_seconds=0))
    dispersion = runtime.dispersion_service().create_task(dict(name='dispersion race', device_profile_id=profile['id'],
        ccd_indices=[0], frame_count=1, dark_frame_count=0, pre_excitation_seconds=0))
    routes = {
        'alignment': f"/devices/profiles/{profile['id']}/connection-test",
        'sample-acquisition': f"/acquisitions/tasks/{sample['id']}/start",
        'dispersion': f"/dispersion/tasks/{dispersion['id']}/start",
    }
    challenger = 'sample-acquisition' if winner == 'alignment' else 'dispersion'
    opening, proceed = threading.Event(), threading.Event()
    open_wire = serial_acq.serial.Serial
    wire = Wire([transfer(100)])
    wire_factory[0].append(wire)

    def blocked_open(**settings):
        assert not opening.is_set(), 'the second request reached the serial boundary'
        opening.set()
        assert proceed.wait(10)
        return open_wire(**settings)

    def post(owner):
        return client.post('/api/v1' + routes[owner], headers=headers)

    monkeypatch.setattr(serial_acq.serial, 'Serial', blocked_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, winner)
        try:
            assert opening.wait(5)
            second = pool.submit(post, challenger).result(timeout=5)
            assert second.status_code == 409 and second.json()['detail']['code'] == 'device_busy'
            diagnostics = call('/devices/diagnostics')
            assert diagnostics['ownership']['owner'] == winner
            assert diagnostics['ownership']['task_id'] == (sample['id'] if winner == 'sample-acquisition' else None)
            if winner == 'sample-acquisition':
                assert diagnostics['active_captures'][0]['owner'] == winner
        finally:
            proceed.set()
        assert first.result(timeout=8).status_code == 200
    wait_for(lambda: wire.closed and runtime.device_ownership.snapshot() is None)
    loser = runtime.acquisition_service().get_task(sample['id']) if challenger == 'sample-acquisition' else runtime.dispersion_service().get_task(dispersion['id'])
    assert loser['status'] == 'draft' and wire_factory[1] == [wire]


def test_disconnect_interrupts_an_active_serial_capture(client_state, wire_factory, monkeypatch):
    _, runtime, _, call, _ = client_state
    profile = call('/devices/profiles', {'name': 'serial emergency stop', 'transport': 'serial', 'port': 12})
    task = runtime.acquisition_service().create_task(dict(name='countdown', device_profile_id=profile['id'],
        countdown_seconds=10))
    waiting = threading.Event()

    def countdown(adapter, _):
        waiting.set()
        assert adapter._cancel.wait(6)
        return False

    monkeypatch.setattr(serial_acq.SerialAcqAdapter, '_wait_until', countdown)
    wire = Wire([])
    wire_factory[0].append(wire)
    call(f"/acquisitions/tasks/{task['id']}/start", {})
    assert waiting.wait(5)
    assert call('/devices/diagnostics')['ownership']['owner'] == 'sample-acquisition'
    assert call('/devices/disconnect', {})['diagnostics']['connected'] is False
    assert wire.closed and not wire.writes
    assert runtime.acquisition_service().get_task(task['id'])['status'] == 'stopped'
    assert call('/devices/diagnostics')['ownership'] is None
