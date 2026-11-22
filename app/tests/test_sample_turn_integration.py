"""Physical sample plans, per-repeat completion and immutable angle-specific data."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import Database, utc_now
from backend.modules.acquisition import AcquisitionService, AcquisitionError
from backend.modules.analysis import AnalysisService
from backend.modules.methods import MethodService
from backend.modules.hardware_acquisition.adapters import SimulatorTurnAdapter


def seed(tmp_path, *, multiple=True, mapping=True):
    database = Database(tmp_path / 'sample-turns.sqlite3')
    method_id, _ = runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))['_seed'](database, complete_conditions=True)
    with database.write() as db:
        version = db.execute('SELECT * FROM method_versions WHERE method_id=?', (method_id,)).fetchone()
        payload = json.loads(version['payload_json'])
        conditions = payload['conditions']
        conditions.update(pre_excitation_seconds=0, frame_count=2, dark_frame_count=1, exposure_mode='simple_mean',
                          sampling_period_seconds=.01, sample_repeats=2)
        # All lines share CCD0 at two different physical grating positions.
        lines = payload['lines']
        ids = [str(line['id']) for line in lines if line.get('line_type') != 'baseline']
        assert len(ids) >= 2
        turns = [dict(angle_deg=17, storage_mode='full_interval', start_frame=1, end_frame=2),
                 dict(angle_deg=4, storage_mode='averaged', start_frame=1, end_frame=2)] if multiple else [
                 dict(angle_deg=17, storage_mode='averaged', start_frame=1, end_frame=2)]
        if multiple and mapping:
            for turn, names in zip(turns, [ids[:1], ['reference-baseline', *ids[1:]]]):
                turn.update(ccd_indices=[0], dispersion_calibration_id=conditions['dispersion_calibration_id'], line_ids=names)
        conditions['angle_exposures'] = turns
        for line in lines:
            line['peak_mode'] = 'max_single_point'
            line['peak_width_points'] = 1
            line['critical_band'] = str(line['id']) == ids[0]
            line['priority'] = 7 if line['critical_band'] else 100
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,2,'published',?,'[]',?)",
                   (method_id, json.dumps(payload), utc_now()))
        db.execute('UPDATE methods SET current_version=2 WHERE id=?', (method_id,))
    return database, method_id


def finish_repeat(service, task_id):
    current = service.start(task_id)
    for _ in range(40):
        if current['status'] in {'between_repeats', 'completed', 'failed', 'stopped'}:
            return current
        current = service.step(task_id, single_repeat=True)
    raise AssertionError('repeat did not finish')


def test_sample_angle_controls_keep_a_partial_repeat_unpublished(tmp_path):
    database, method = seed(tmp_path)
    service = AcquisitionService(database)
    queue = service.sample_queues.create('manual-turns', [{'pre_name': 'A002', 'repeats': 1}], None)
    task = service.create_task(dict(method_id=method, method_version=2, queue_id=queue['id'], queue_item_id=queue['items'][0]['id']))
    task_id = task['id']
    with pytest.raises(AcquisitionError, match='当前待采'):
        service.start(task_id, turn_index=1, single_turn=True)
    warmup = service.preheat(task_id, turn_index=1)
    assert warmup['capture_turn']['angle_deg'] == 4
    service.stop(warmup['id'])
    assert service.get_task(task_id)['status'] == 'draft'
    assert service.get_task(task_id)['samples'] == []

    current = service.start(task_id, turn_index=0, single_turn=True)
    for _ in range(8):
        if current['status'] == 'paused':
            break
        current = service.step(task_id, single_repeat=True)
    assert current['turns']['awaiting_turn'] and current['turns']['turn_index'] == 1
    assert current['progress'] == 50 and current['samples'][0]['bands'] == []
    assert not service.sample_queues.get(queue['id'])['items'][0]['spectrum_hash']
    assert task_id not in service._adapters
    assert len(service.frames(task_id, turn_index=0, phase='burn')) == 2
    assert service.frames(task_id, turn_index=1) == []
    with pytest.raises(AcquisitionError, match='下一转角'):
        service.resume(task_id)
    service = AcquisitionService(database)
    current = service.start(task_id, turn_index=1, single_turn=True)
    for _ in range(8):
        if current['status'] == 'completed':
            break
        current = service.step(task_id, single_repeat=True)
    assert current['status'] == 'completed' and current['completed_repeats'] == 1
    assert [band['angle_deg'] for band in current['samples'][0]['bands']] == [17, 4]
    assert service.sample_queues.get(queue['id'])['items'][0]['spectrum_hash'] == current['result_sha256']


def test_sample_turns_complete_whole_plan_then_wait_for_next_repeat(tmp_path, monkeypatch):
    database, method = seed(tmp_path)
    service = AcquisitionService(database)
    queue = service.sample_queues.create('turns', [{'pre_name': 'A001', 'repeats': 2}], None)
    task = service.create_task(dict(method_id=method, method_version=2, queue_id=queue['id'], queue_item_id=queue['items'][0]['id']))
    plan = task['turns']['plan']
    assert plan[0]['angle_deg'] == 17 and plan[0]['key_band'] and plan[0]['priority'] == 7
    assert plan[1]['angle_deg'] == 4 and not plan[1]['key_band']
    positions = []
    original = SimulatorTurnAdapter.turn
    def turn(self, **kwargs):
        positions.append(kwargs['angle_deg'])
        return original(self, **kwargs)
    monkeypatch.setattr(SimulatorTurnAdapter, 'turn', turn)
    warmup = service.preheat(task['id'])
    service.stop(warmup['id'])
    assert not positions and not warmup.get('turns')
    first = finish_repeat(service, task['id'])
    assert first['status'] == 'between_repeats' and first['completed_repeats'] == 1 and first['progress'] == 50
    assert positions == [17, 4] and len(first['samples']) == 1
    assert not service.sample_queues.get(queue['id'])['items'][0]['spectrum_hash']
    assert service.step(task['id'], single_repeat=True)['status'] == 'between_repeats'
    second = finish_repeat(service, task['id'])
    assert second['status'] == 'completed' and second['completed_repeats'] == 2 and second['progress'] == 100
    assert positions == [17, 4, 17, 4] and len(second['samples']) == 2
    assert service.sample_queues.get(queue['id'])['items'][0]['spectrum_hash'] == second['result_sha256']
    sample = second['samples'][0]
    bands = service.band(sample['id'], include_points=True)
    assert [(b['angle_deg'], b['ccd_index']) for b in bands] == [(17, 0), (4, 0)]
    assert len({b['mean_sha256'] for b in bands}) == 2
    with database.read() as db:
        assert len(db.execute('SELECT * FROM acquisition_turn_frames WHERE accepted=1').fetchall()) == 12
        assert not db.execute('SELECT * FROM acquisition_sample_bands WHERE sample_id=?', (sample['id'],)).fetchall()
        with pytest.raises(AcquisitionError, match='明确'):
            service.interval_band(db, sample['id'], 0)
        for turn in plan:
            location = service.line_location(db, sample['id'], turn['lines'][0]['id'])
            assert location['angle_deg'] == turn['angle_deg']
            assert service.interval_band(db, sample['id'], 0, turn_index=location['turn_index'])['points'] == bands[turn['turn_index']]['mean_points']
    analysis = AnalysisService(database, methods=MethodService(database))
    run = analysis.create_run({'acquisition_sample_ids': [s['id'] for s in second['samples']]})
    result = analysis.start(run['id'])
    for _ in range(40):
        if result['status'] == 'completed': break
        result = analysis.step(run['id'])
    assert result['status'] == 'completed'
    assert {r['intermediates']['angle_deg'] for r in result['line_results']} == {4, 17}
    spectrum = analysis.spectrum(run['id'], 0, service)
    assert [(band['turn_index'], band['ccd_index']) for band in spectrum['bands']] == [(0, 0), (1, 0)]
    from backend.modules.spectrum_viewer import SpectrumViewerService
    viewer = SpectrumViewerService(database)
    views = [viewer.get(f"sample:{sample['id']}", ccd=index, detail='frame', phase='burn', frame=0) for index in (0, 1)]
    assert [view['angle_deg'] for view in views] == [17, 4]
    assert len({view['frame_detail']['ccd']['points'][0]['value'] for view in views}) > 1
    assert all(len(viewer.point_details(f"sample:{sample['id']}", ccd=index, point=500)['rows']) == 3 for index in (0, 1))
    assert {position['angle_deg'] for position in analysis.calibration_preview(run['id'], 0)['positions']} == {4, 17}


def test_missing_mapping_blocks_without_creating_task_and_fixed_angle_has_no_motor(tmp_path, monkeypatch):
    database, method = seed(tmp_path, mapping=False)
    service = AcquisitionService(database)
    before = service.list_tasks()
    with pytest.raises(AcquisitionError) as error:
        service.create_task(dict(method_id=method))
    assert error.value.code == 'sample_turn_mapping_missing'
    assert service.list_tasks() == before


def test_fixed_angle_and_failed_turn_never_fabricate_or_confirm_data(tmp_path, monkeypatch):
    database, method = seed(tmp_path, multiple=False)
    service = AcquisitionService(database)
    monkeypatch.setattr(SimulatorTurnAdapter, 'turn', lambda *a, **k: pytest.fail('fixed angle must not move'))
    task = service.create_task(dict(method_id=method, repeat_count=1))
    done = finish_repeat(service, task['id'])
    assert done['status'] == 'completed'
    assert {b['angle_deg'] for b in service.band(done['samples'][0]['id'])} == {17}


def test_stop_and_restart_during_partial_plan_keeps_evidence(tmp_path, monkeypatch):
    database, method = seed(tmp_path)
    service = AcquisitionService(database)
    task = service.create_task(dict(method_id=method, repeat_count=1))
    service.start(task['id'])
    service.step(task['id'], single_repeat=True)
    service.pause(task['id'])
    before = service.frames(task['id'], include_points=True)
    assert before
    service.resume(task['id'])
    stopped = service.stop(task['id'])
    assert stopped['status'] == 'stopped' and stopped['completed_repeats'] == 0
    assert not stopped['samples'][0]['finalized'] and not stopped['samples'][0]['bands']
    assert service.frames(task['id'], include_points=True) == before
    assert not service._adapters


def test_failed_position_closes_adapter_and_keeps_unconfirmed_repeat(tmp_path, monkeypatch):
    database, method = seed(tmp_path)
    service = AcquisitionService(database)
    task = service.create_task(dict(method_id=method, repeat_count=1))
    service.start(task['id'])
    monkeypatch.setattr(SimulatorTurnAdapter, 'turn', lambda *a, **k: {'event_type': 'timeout'})
    with pytest.raises(AcquisitionError): service.step(task['id'], single_repeat=True)
    failed = service.get_task(task['id'])
    assert failed['status'] == 'failed' and not failed['samples'][0]['finalized'] and not service._adapters


def test_multiple_critical_priorities_tie_by_shortest_required_line_then_remaining_wavelength(tmp_path):
    database, method = seed(tmp_path)
    with database.write() as db:
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()[0])
        groups = [['reference-baseline', 'AL'], ['IS'], ['A-none'], ['A-background'], ['A-gaussian']]
        priorities = {'IS': 5, 'A-none': 9, 'A-background': 5}
        for line in payload['lines']:
            line['critical_band'] = line['id'] in priorities
            line['priority'] = priorities.get(line['id'], 100)
        payload['conditions']['angle_exposures'] = [dict(angle_deg=angle, storage_mode='averaged', start_frame=1, end_frame=2,
            ccd_indices=[0], dispersion_calibration_id=payload['conditions']['dispersion_calibration_id'], line_ids=names)
            for angle, names in zip([55, 10, 40, 20, 5], groups)]
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,3,'published',?,'[]',?)",
                   (method, json.dumps(payload), utc_now()))
    service = AcquisitionService(database)
    task = service.create_task(dict(method_id=method, method_version=3, repeat_count=1))
    assert [turn['angle_deg'] for turn in task['turns']['plan']] == [40, 10, 20, 55, 5]
    assert len(task['turns']['plan'][3]['lines']) == 2
    assert task['turns']['plan'][3]['wavelength_nm'] == min(line['wavelength_nm'] for line in payload['lines'] if line['id'] in groups[0])
    before = copy.deepcopy(task['turns']['plan'])
    with database.write() as db:
        payload['conditions']['angle_exposures'].reverse()
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,4,'published',?,'[]',?)",
                   (method, json.dumps(payload), utc_now()))
    assert service.get_task(task['id'])['turns']['plan'] == before


@pytest.mark.parametrize('failure', ['ambiguous', 'calibration', 'serial'])
def test_invalid_association_and_serial_turn_gate_create_no_task(tmp_path, failure):
    database, method = seed(tmp_path)
    service = AcquisitionService(database)
    with database.write() as db:
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()[0])
        if failure == 'ambiguous':
            for angle in payload['conditions']['angle_exposures']: angle.pop('line_ids')
        elif failure == 'calibration':
            payload['conditions']['angle_exposures'][0]['dispersion_calibration_id'] = 'missing'
        else:
            db.execute("UPDATE device_profiles SET transport='serial',port=8 WHERE id=1")
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,3,'published',?,'[]',?)",
                   (method, json.dumps(payload), utc_now()))
    before = len(service.list_tasks())
    with pytest.raises(AcquisitionError) as error: service.create_task(dict(method_id=method, method_version=3))
    assert error.value.code == {'ambiguous': 'sample_line_turn_ambiguous', 'calibration': 'method_geometry_missing', 'serial': 'hardware_protocol_unavailable'}[failure]
    assert len(service.list_tasks()) == before and not service._adapters


def test_single_physical_angle_spans_transport_groups_and_viewer_retains_angles(tmp_path):
    database, method = seed(tmp_path, multiple=False)
    with database.write() as db:
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()[0])
        payload['conditions']['selected_ccds'] = [0, 4]
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,3,'published',?,'[]',?)",
                   (method, json.dumps(payload), utc_now()))
    service = AcquisitionService(database)
    task = service.create_task(dict(method_id=method, method_version=3, repeat_count=1))
    done = finish_repeat(service, task['id'])
    assert done['status'] == 'completed' and len(done['samples'][0]['bands']) == 2
    assert {band['angle_deg'] for band in service.band(done['samples'][0]['id'])} == {17}
    from backend.modules.spectrum_viewer import SpectrumViewerService
    viewer = SpectrumViewerService(database)
    record = viewer.get(f"sample:{done['samples'][0]['id']}", ccd=1)
    assert record['angle_deg'] == 17 and record['ccd']['index'] == 4
    assert record['layout']['band_labels'] == ['17° · CCD 1', '17° · CCD 5']


def test_restart_loses_active_session_without_confirming_partial_turn(tmp_path):
    database, method = seed(tmp_path)
    service = AcquisitionService(database)
    task = service.create_task(dict(method_id=method, repeat_count=1))
    service.start(task['id']); service.step(task['id'], single_repeat=True)
    before = service.frames(task['id'], include_points=True)
    restarted = AcquisitionService(database)
    with pytest.raises(AcquisitionError): restarted.step(task['id'], single_repeat=True)
    assert restarted.get_task(task['id'])['status'] == 'failed'
    assert restarted.frames(task['id'], include_points=True) == before
    service._close_adapter(task['id'])


def test_schema30_addition_preserves_legacy_data_and_rolls_back_on_failure(tmp_path, monkeypatch):
    from backend import db as db_module
    from backend.migrations import MIGRATIONS
    database = Database(tmp_path / 'v29.sqlite3')
    with monkeypatch.context() as patch:
        patch.setattr(db_module, 'MIGRATIONS', tuple(step for step in MIGRATIONS if step[0] < 30))
        patch.setattr(db_module, 'SCHEMA_VERSION', 29)
        runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))['_seed'](database, complete_conditions=True)
    with database.read() as db:
        before = list(db.iterdump())
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if row[0].startswith(('acquisition_', 'hardware_', 'method', 'sample_', 'dispersion_'))]
        data = {table: [tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')] for table in tables}
    actual = next(step for step in MIGRATIONS if step[0] == 30)
    def fail(connection):
        actual[2](connection)
        raise sqlite3.OperationalError('injected migration failure')
    with monkeypatch.context() as patch:
        patch.setattr(db_module, 'MIGRATIONS', tuple((30, 'acquisition', fail) if step[0] == 30 else step for step in MIGRATIONS))
        with pytest.raises(sqlite3.OperationalError, match='injected'): database.initialize()
    with database.read() as db: assert list(db.iterdump()) == before
    database.initialize()
    with database.read() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for table in tables: assert [tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')] == data[table]


def test_each_angle_uses_its_own_calibration_and_line_positions(tmp_path):
    database, method = seed(tmp_path)
    with database.write() as db:
        original = db.execute("SELECT * FROM dispersion_calibrations WHERE name='default'").fetchone()
        coefficients = json.loads(original['coefficients_json'])
        coefficients[2] -= 100  # The same known wavelength falls 100 pixels earlier at this angle.
        calibration = db.execute('INSERT INTO dispersion_calibrations(name,ccd_layout_id,wavelength_min,wavelength_max,coefficients_json,created_at) VALUES (?,?,?,?,?,?)',
            ('shifted-angle', original['ccd_layout_id'], original['wavelength_min'], original['wavelength_max'], json.dumps(coefficients), utc_now())).lastrowid
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()[0])
        payload['conditions']['angle_exposures'][0]['dispersion_calibration_id'] = calibration
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,3,'published',?,'[]',?)",
                   (method, json.dumps(payload), utc_now()))
    acquisition = AcquisitionService(database)
    task = acquisition.create_task(dict(method_id=method, method_version=3, repeat_count=1))
    first = task['turns']['plan'][0]
    assert first['angle_deg'] == 17 and first['lines'][0]['id'] == 'AL'
    assert first['lines'][0]['point_index'] == pytest.approx(500)
    done = finish_repeat(acquisition, task['id'])
    analysis = AnalysisService(database, methods=MethodService(database))
    run = analysis.create_run({'acquisition_sample_ids': [done['samples'][0]['id']]})
    spectrum = analysis.spectrum(run['id'], 0, acquisition)
    al = next(line for line in spectrum['lines'] if line['id'] == 'AL')
    assert al['point'] == pytest.approx(500)
    assert spectrum['bands'][0]['wavelengths_nm'][500] == pytest.approx(al['wavelength_nm'])
    assert spectrum['bands'][0]['wavelengths_nm'] != spectrum['bands'][1]['wavelengths_nm']
