from dataclasses import replace
import json
import sqlite3
import struct

import pytest

from backend.db import Database, utc_now
from backend.modules.acquisition import AcquisitionError, AcquisitionService
from backend.modules.acquisition import service as acquisition_service
from backend.modules.acquisition.monitoring import evaluate_event_monitoring, format_anomaly_summary, normalize_thresholds
from backend.modules.devices import AcqSimulatorAdapter
from tests.test_legacy_serial_acquisition import Wire, serial_profile, transfer, wait_for, wire_factory
from tests.test_continuous_capture_motor import CheckedWire, bind, motor_server
from tests.test_methods import method_client
from tests.test_sample_turn_integration import seed


SPEC = {
    'monitored': True,
    'baseline': {'ccd_index': 0, 'point_index': 100, 'search_radius_points': 40},
    'positioning': {'ccd_index': 1, 'point_index': 300, 'search_radius_points': 40},
}


def spectrum(ccd, *peaks, background=1):
    points = [background] * 2048
    for pixel, intensity in peaks:
        points[pixel] = intensity
    return {'ccd_index': ccd, 'points': points}


def test_windows_ignore_large_peaks_on_other_pixels_and_ccds():
    result = evaluate_event_monitoring([
        spectrum(0, (100, 1200), (900, 65000)),
        spectrum(1, (300, 800), (100, 65000)),
        spectrum(2, (100, 65000), (300, 65000)),
    ], SPEC, normalize_thresholds(None))
    assert result['monitored'] and not result['abnormal']
    baseline, positioning, unrelated = result['observations']
    assert (baseline['baseline_position'], baseline['baseline_intensity']) == (100, 1200)
    assert (positioning['peak_position'], positioning['raw_peak_value']) == (300, 800)
    assert not unrelated['baseline_monitored'] and not unrelated['peak_monitored']


@pytest.mark.parametrize('case, expected, label', [
    ('low', ['baseline_low'], '基线强度过低'),
    ('high', ['baseline_high'], '基线强度过高'),
    ('both', ['baseline_high', 'baseline_shift', 'peak_shift'], '基线位置漂移'),
    ('fault', ['frame_fault'], 'CCD 帧损坏'),
    ('timeout', ['turn_timeout'], '转角定位超时'),
])
def test_anomalies_report_values_and_chinese_message(case, expected, label):
    baseline_pixel = 131 if case == 'both' else 100
    baseline = {'low': 4, 'high': 61000, 'both': 62000}.get(case, 1200)
    positioning_pixel = 269 if case == 'both' else 300
    result = evaluate_event_monitoring([
        spectrum(0, (baseline_pixel, baseline)), spectrum(1, (positioning_pixel, 1200)),
    ], SPEC, normalize_thresholds(None), damaged=case in {'fault', 'timeout'},
        fault_kind='turn_timeout' if case == 'timeout' else None)
    assert result['detected'] == expected
    message = format_anomaly_summary(result['detected'], result['observations'])
    assert label in message
    if case == 'both':
        assert '定位峰位偏移' in message and '62000' in message and '269' in message
        assert result['correction_offset'] == 31


def test_unmonitored_snapshot_ignores_old_placeholder_pixels(tmp_path):
    result = evaluate_event_monitoring([spectrum(0, (256, 65000), (1024, 65000))],
        {**SPEC, 'monitored': False}, normalize_thresholds(None))
    assert not result['monitored'] and not result['detected']
    database = Database(tmp_path / 'historical.sqlite3')
    database.initialize()
    service = AcquisitionService(database)
    task = service.create_task({'ccd_indices': [0], 'burn_frame_count': 1, 'dark_frame_count': 0,
                                'pre_excitation_seconds': 0})
    # Emulate a task created before v33 with no stored monitoring binding.
    with database.write() as db:
        db.execute("UPDATE acquisition_tasks SET excitation_condition_json='{}' WHERE id=?", (task['id'],))
    finished = advance(service, service.start(task['id']))
    assert finished['status'] == 'completed'
    assert finished['monitoring']['monitored'] is False
    assert finished['monitoring']['state']['status'] == 'unmonitored'
    assert finished['monitoring']['decisions'] == []


def advance(service, result):
    for _ in range(30):
        if result['status'] in {'paused', 'stopped', 'failed', 'completed', 'between_repeats'}:
            return result
        result = service.step(result['id'], single_repeat=True)
    pytest.fail('采集未完成')


def deterministic_capture(monkeypatch, *, persistent=False, incomplete=False):
    def signals(event, *, phase, **_):
        if event.event_type == 'fault':
            return event
        seed_no = event.details.get('seed', 0)
        burn = 3 if persistent or seed_no < 65537 else 180
        curves = [spectrum(ccd['ccd_index'], background=burn if phase == 'burn' else 20)
                  for ccd in event.ccds]
        if incomplete:
            curves = [ccd for ccd in curves if ccd['ccd_index'] != 0]
        return replace(event, ccds=curves)
    monkeypatch.setattr(acquisition_service, '_seeded_acquisition_event', signals)


def task_for(service, method, **options):
    return service.create_task({'method_id': method, 'method_version': 2, 'repeat_count': 1, **options})


@pytest.mark.parametrize('multiple', [False, True], ids=['fixed', 'multiple'])
def test_retry_keeps_rejected_evidence_out_of_results(tmp_path, monkeypatch, multiple):
    database, method = seed(tmp_path, multiple=multiple)
    with database.write() as db:
        row = db.execute('SELECT * FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()
        payload = json.loads(row['payload_json'])
        for turn in payload['conditions']['angle_exposures']:
            turn['storage_mode'] = 'full_interval'
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at)"
                   " VALUES (?,3,'published',?,'[]',?)", (method, json.dumps(payload), utc_now()))
    deterministic_capture(monkeypatch)
    service = AcquisitionService(database)
    task = task_for(service, method, method_version=3, anomaly_policy='stop', retry_limit=1)
    state = service.start(task['id'])
    captures = {0: 3, 1: 180}
    for _ in range(30):
        state = service.step(task['id'], single_repeat=True)
        monitoring = state['monitoring']['state']
        attempt = monitoring['attempt']
        if state['burn_frames_captured'] != 1 or attempt not in captures:
            continue
        turn = state['turns']['turn_index']
        if not state['turns']['plan'][turn]['monitoring']['baseline']:
            continue
        with database.read() as db:
            observed, provisional = service.measurement_frames(db, task['id'], 0, turn, phase='burn', include_points=True)
        assert provisional and observed
        assert {frame['attempt'] for frame in observed} == {attempt}
        assert {frame['points'][0] for frame in observed} == {captures.pop(attempt)}
        assert service.frames(task['id'], turn_index=turn) == []
        if not captures:
            break
    assert not captures
    result = advance(service, state)
    assert result['status'] == 'completed', result['monitoring']
    plan = result['turns']['plan']
    turn = next(item for item in plan if item['monitoring']['baseline'])
    binding = turn['monitoring']['baseline']
    line = next(line for line in turn['lines'] if line['id'] == binding['line_id'])
    assert binding['line_type'] == 'baseline'
    assert binding['pixel_index'] == line['point_index'] and binding['search_window_source']
    turn_index, ccd = turn['turn_index'], binding['ccd_index']
    frames = service.frames(task['id'], turn_index=turn_index, ccd_index=ccd, evidence=True, include_points=True)
    assert {(frame['attempt'], frame['accepted']) for frame in frames} == {(0, 0), (1, 1)}
    assert {frame['points'][0] for frame in frames if not frame['accepted'] and frame['phase'] == 'burn'} == {3}
    winners = service.frames(task['id'], turn_index=turn_index, ccd_index=ccd, phase='burn', include_points=True)
    assert len(winners) == 2 and all(frame['points'][0] == 180 for frame in winners)
    sample_id = result['samples'][0]['id']
    snapshot = service.measurement_snapshot(task['id'])
    band = next(item for item in snapshot['samples'][0]['bands'] if item.get('turn_index', 0) == turn_index)
    assert band['points'] == [16000] * 2048
    with database.read() as db:
        analysis_band = service.interval_band(db, sample_id, ccd, (1, 2), turn_index=turn_index)
        assert analysis_band['points'] == [16000] * 2048
        table = 'acquisition_turn_bands' if multiple else 'acquisition_sample_bands'
        scope = ' AND turn_index=?' if multiple else ''
        row = db.execute(f'SELECT * FROM {table} WHERE sample_id=? AND ccd_index=?{scope}',
                         (sample_id, ccd, turn_index) if multiple else (sample_id, ccd)).fetchone()
        assert struct.unpack('<4096H', row['burn_frames_blob']) == (180,) * 4096
        assert struct.unpack('<2048H', row['dark_frames_blob']) == (20,) * 2048
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert any(item['decision'] == 'retry' and item['anomaly_kinds'] == ['baseline_low']
               for item in result['monitoring']['decisions'])


def test_exhausted_retries_publish_zero_even_after_another_turn(tmp_path, monkeypatch):
    database, method = seed(tmp_path)
    deterministic_capture(monkeypatch, persistent=True)
    service = AcquisitionService(database)
    task = task_for(service, method, anomaly_policy='stop', retry_limit=1)
    result = advance(service, service.start(task['id']))
    assert result['status'] == 'stopped' and result['monitoring']['state']['status'] == 'safety_stopped'
    assert '重采次数已耗尽' in result['last_message']
    assert result['burn_frames_captured'] == result['dark_frames_captured'] == result['completed_repeats'] == 0
    assert result['samples'][0]['bands'] == service.measurement_snapshot(task['id'])['samples'][0]['bands'] == []
    frames = service.frames(task['id'], evidence=True)
    assert {frame['attempt'] for frame in frames} == {0, 1}
    assert not any(frame['accepted'] for frame in frames)
    assert task['id'] not in service._adapters


@pytest.mark.parametrize('action', ['accept', 'retry', 'stop'])
def test_manual_takeover_for_complete_anomalous_capture(tmp_path, monkeypatch, action):
    database, method = seed(tmp_path, multiple=False)
    deterministic_capture(monkeypatch)
    service = AcquisitionService(database)
    task = task_for(service, method, anomaly_policy='manual')
    task_id = task['id']
    with pytest.raises(AcquisitionError, match='未等待人工接管'):
        service.intervene(task_id, action, '复核')
    waiting = advance(service, service.start(task_id))
    assert waiting['status'] == 'paused'
    assert waiting['monitoring']['state']['can_accept']
    assert service.frames(task_id) == []
    with database.read() as db:
        assert service.measurement_frames(db, task_id, 0, 0, phase='burn', include_points=True) == ([], False)
    assert task_id not in service._adapters
    with pytest.raises(AcquisitionError, match='人工接管'):
        service.resume(task_id)
    resolved = advance(service, service.intervene(task_id, action, '操作员复核'))
    assert resolved['status'] == ('stopped' if action == 'stop' else 'completed')
    assert any(item['decision'] == action and '操作员复核' in item['reason']
               for item in resolved['monitoring']['decisions'])
    if action == 'retry':
        assert {frame['attempt'] for frame in service.frames(task_id, evidence=True) if frame['accepted']} == {1}


@pytest.mark.parametrize('failure', ['frame_fault', 'turn_timeout', 'missing_ccd'])
def test_damaged_or_incomplete_attempt_cannot_be_accepted(tmp_path, monkeypatch, failure):
    database, method = seed(tmp_path, multiple=failure == 'turn_timeout')
    deterministic_capture(monkeypatch, incomplete=failure == 'missing_ccd')
    if failure == 'turn_timeout':
        monkeypatch.setattr(AcqSimulatorAdapter, 'position_angle', lambda *args: {'event_type': 'timeout'})
    service = AcquisitionService(database)
    task = task_for(service, method, anomaly_policy='manual', **({'fault_frame': 0} if failure == 'frame_fault' else {}))
    waiting = advance(service, service.start(task['id']))
    state = waiting['monitoring']['state']
    assert waiting['status'] == 'paused' and state['awaiting_intervention'] and not state['can_accept']
    assert ('turn_timeout' if failure == 'turn_timeout' else 'frame_fault') in state['last_anomalies']
    with pytest.raises(AcquisitionError, match='不能接受') as error:
        service.intervene(task['id'], 'accept', '人工接受')
    assert error.value.status_code == 409
    with pytest.raises(AcquisitionError, match='人工接管'):
        service.resume(task['id'])
    assert service.intervene(task['id'], 'stop', '停止检查')['status'] == 'stopped'


def test_intervene_route_rejects_a_damaged_frame(method_client):
    client, runtime, headers = method_client
    service = runtime.acquisition_service()
    task = service.create_task({'ccd_indices': [0], 'anomaly_policy': 'manual', 'fault_frame': 0,
                                'burn_frame_count': 2, 'pre_excitation_seconds': 0})
    advance(service, service.start(task['id']))
    url = f"/api/v1/acquisitions/tasks/{task['id']}/intervene"
    payload = {'action': 'accept', 'reason': '复核'}
    assert client.post(url, json=payload).status_code in {401, 403}
    response = client.post(url, json=payload, headers=headers)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'acquisition_intervention_frame_incomplete'
    stopped = client.post(url, json={'action': 'stop', 'reason': '检查仪器'}, headers=headers)
    assert stopped.status_code == 200 and stopped.json()['status'] == 'stopped'


@pytest.mark.parametrize('multiple', [False, True], ids=['fixed', 'multiple'])
def test_serial_retry_closes_first_port_and_only_commits_second_capture(tmp_path, wire_factory, motor_server, multiple):
    database, method = seed(tmp_path, multiple=multiple)
    with database.write() as db:
        row = db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()
        payload = json.loads(row[0])
        payload['conditions']['sampling_period_seconds'] = 1
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at)"
                   " VALUES (?,3,'published',?,'[]',?)", (method, json.dumps(payload), utc_now()))
    profile = serial_profile(database)
    motor = bind(database, profile, motor_server) if multiple else None
    if motor:
        motor.allow_arrival.set()
    service = AcquisitionService(database)
    task = task_for(service, method, method_version=3, device_profile_id=profile['id'], anomaly_policy='stop', retry_limit=1)
    plan = task['turns']['plan']
    target = next(turn['turn_index'] for turn in plan if turn['monitoring']['baseline'])
    bad = [transfer(3), transfer(3), transfer(65000), transfer(20)]
    good = [transfer(180), transfer(180), transfer(65000), transfer(20)]
    wire = (lambda payload: CheckedWire(motor, payload)) if motor else Wire
    first = wire(good * target + bad)
    second = wire(good * (len(plan) - target))
    wire_factory[0].extend((first, second))
    try:
        service.start(task['id'])
        def settled():
            task_state = service.get_task(task['id'])
            return task_state if task_state['status'] in {'stopped', 'completed', 'failed'} else None
        result = wait_for(settled)
        assert result['status'] == 'completed', result['monitoring']
        wait_for(lambda: first.closed and second.closed)
        assert wire_factory[1] == [first, second]
        assert first.writes[-1] == second.writes[-1] == b'\x00'
        frames = service.frames(task['id'], phase='burn', ccd_index=0, turn_index=target, include_points=True, evidence=True)
        assert {(frame['attempt'], frame['accepted'], frame['points'][0]) for frame in frames} == {(0, 0, 3), (1, 1, 180)}
        if motor:
            expected = [{17: 21, 4: -11}[turn['angle_deg']] for turn in plan]
            assert motor.moves == expected[:target] + [expected[target]] + expected[target:]
    finally:
        service.shutdown()


def test_v33_replay_preserves_evidence_and_constraints(tmp_path, monkeypatch):
    database, method = seed(tmp_path, multiple=False)
    deterministic_capture(monkeypatch, persistent=True)
    service = AcquisitionService(database)
    task = task_for(service, method, anomaly_policy='stop')
    result = advance(service, service.start(task['id']))
    assert result['status'] == 'stopped'
    evidence = service.frames(task['id'], evidence=True, include_points=True)
    with database.write() as db:
        db.execute('DELETE FROM schema_migrations WHERE version=33')
    Database(database.path).initialize()
    assert evidence == service.frames(task['id'], evidence=True, include_points=True)
    with database.write() as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT count(*) FROM schema_migrations WHERE version=33').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            db.execute('UPDATE acquisition_monitoring_decisions SET reason=? WHERE task_id=?', ('rewrite', task['id']))
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            db.execute('DELETE FROM acquisition_attempt_frames WHERE task_id=?', (task['id'],))
