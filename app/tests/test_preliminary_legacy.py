"""Legacy EDT/WDT fields, authoritative context and confirmation-only defaults."""
import pytest
import json
from tests.test_sample_current_context import client_state, select_context
from backend.modules.devices import DeviceError


def endpoint(kind):
    return '/dispersion/capture-sessions' if kind == 'dispersion' else '/acquisitions/evaporation-sessions'


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_preliminary_angle_pages_capture_separately_and_lock_real_turns(client_state, monkeypatch, kind):
    from backend.modules.hardware_acquisition import SimulatorTurnAdapter
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
    original = SimulatorTurnAdapter.turn
    def position(self, **kwargs):
        positions.append(kwargs['angle_deg'])
        return original(self, **kwargs)
    monkeypatch.setattr(SimulatorTurnAdapter, 'turn', position)
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
