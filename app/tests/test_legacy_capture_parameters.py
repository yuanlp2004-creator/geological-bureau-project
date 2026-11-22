"""Legacy sample/method and preliminary-capture parameter ownership."""
import json
from pathlib import Path
import runpy
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import Database, utc_now
from backend.modules.acquisition import AcquisitionError, AcquisitionService
from backend.modules.dispersion import DispersionService
from backend.modules.hardware_acquisition import HardwareAcquisitionService


def seed(tmp_path, mode='simple_mean'):
    database = Database(tmp_path / 'capture.sqlite3')
    method_id, _ = runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))['_seed'](
        database, complete_conditions=True)
    with database.write() as db:
        row = db.execute('SELECT * FROM method_versions WHERE method_id=?', (method_id,)).fetchone()
        payload = json.loads(row['payload_json'])
        conditions = payload['conditions']
        conditions.update(pre_excitation_seconds=0, sampling_period_seconds=1.5, frame_count=2,
                          dark_frame_count=1, sample_repeats=2, standard_repeats=3, control_repeats=4,
                          exposure_mode=mode,
                          angle_exposures=[dict(angle_deg=0, storage_mode='averaged', start_frame=1, end_frame=2)])
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,2,'published',?,'[]',?)",
                   (method_id, json.dumps(payload), utc_now()))
        db.execute('UPDATE methods SET current_version=2 WHERE id=?', (method_id,))
    return database, method_id, conditions


@pytest.mark.parametrize('mode,storage', [('simple_mean', 'averaged'), ('line_interval', 'full_interval')])
def test_sample_cannot_override_method_conditions_and_preheat_keeps_one_repeat(tmp_path, mode, storage):
    database, method_id, conditions = seed(tmp_path, mode)
    service = AcquisitionService(database)
    task = service.create_task(dict(method_id=method_id, method_version=2, ccd_layout_id='invalid',
        ccd_indices=[250], pre_excitation_seconds=42, sampling_period_seconds=.02,
        burn_cycle_seconds=.02, dark_cycle_seconds=.03, burn_frame_count=99, dark_frame_count=0,
        storage_mode='full_interval' if storage == 'averaged' else 'averaged',
        use_method_conditions=False, use_method_intervals=False))
    assert task['ccd_layout_id'] == conditions['ccd_layout_id'] and task['ccd_indices'] == [0]
    assert (task['pre_excitation_seconds'], task['sampling_period_seconds'], task['burn_cycle_seconds'],
            task['dark_cycle_seconds'], task['burn_frame_count'], task['dark_frame_count']) == (0, 1.5, 1.5, 1.5, 2, 1)
    assert task['storage_mode'] == storage and task['repeat_count'] == 2
    warmup = service.preheat(task['id'])
    assert warmup['repeat_count'] == 1 and warmup['ccd_indices'] == task['ccd_indices']
    assert warmup['sampling_period_seconds'] == 1.5 and warmup['burn_frame_count'] == 2
    service.stop(warmup['id'])
    current = service.start(task['id'])
    for _ in range(25):
        if current['status'] == 'completed':
            break
        current = service.step(task['id'])
    assert current['status'] == 'completed' and len(current['samples']) == 2
    assert all(sample['bands'][0]['storage_mode'] == storage for sample in current['samples'])
    # A later method revision does not change the saved capture or its warm-up snapshot.
    with database.write() as db:
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method_id,)).fetchone()[0])
        payload['conditions']['sampling_period_seconds'] = 2
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,3,'published',?,'[]',?)",
                   (method_id, json.dumps(payload), utc_now()))
    warmup = service.preheat(task['id'])
    assert warmup['method_version'] == 2 and warmup['sampling_period_seconds'] == 1.5
    service.stop(warmup['id'])
    with pytest.raises(AcquisitionError, match='已发布'):
        service.create_task(dict(method_id=method_id, method_version=999))


def test_repeats_follow_legacy_defaults_and_explicit_sample_queue(tmp_path):
    database, method_id, _ = seed(tmp_path)
    service = AcquisitionService(database)
    for name, kind, repeats in [('A1', 'normal', 2), ('S1', 'standard', 3), ('D1', 'test', 4)]:
        assert service.create_task(dict(method_id=method_id, sample_name=name, sample_kind=kind))['repeat_count'] == repeats
    standard = service.create_task(dict(method_id=method_id, sample_name='S2'))
    assert standard['sample_kind'] == 'standard' and standard['repeat_count'] == 3
    assert service.create_task(dict(method_id=method_id, repeat_count=5))['repeat_count'] == 5
    queue = service.sample_queues.create('queue', [dict(pre_name='A2', repeats=6)], None)
    task = service.create_task(dict(method_id=method_id, repeat_count=1, queue_id=queue['id'], queue_item_id=queue['items'][0]['id']))
    assert task['repeat_count'] == 6


def test_evaporation_uses_method_layout_but_independent_conditions_and_dispersion_has_no_method(tmp_path):
    database, method_id, _ = seed(tmp_path)
    service = AcquisitionService(database)
    task = service.create_task(dict(task_kind='evaporation', method_id=method_id, ccd_layout_id='invalid', ccd_indices=[250],
        burn_frame_count=4, dark_frame_count=0, pre_excitation_seconds=1, sampling_period_seconds=2,
        burn_cycle_seconds=2, dark_cycle_seconds=2, use_method_conditions=True))
    assert task['ccd_indices'] == [0] and task['storage_mode'] == 'full_interval' and task['repeat_count'] == 1
    assert (task['burn_frame_count'], task['dark_frame_count'], task['pre_excitation_seconds'], task['sampling_period_seconds']) == (4, 0, 1, 2)
    dispersion = DispersionService(database).create_task(dict(frame_count=5, dark_frame_count=0, pre_excitation_seconds=2, sampling_period_seconds=1))
    assert dispersion['method_id'] is None and dispersion['frame_count'] == 5


def test_method_bound_turns_use_method_layout_and_clock(tmp_path):
    database, method_id, conditions = seed(tmp_path)
    service = HardwareAcquisitionService(database)
    task = service.create_task(dict(method_id=method_id, ccd_layout_id='invalid', ccd_indices=[250],
        pre_excitation_seconds=42, sampling_period_seconds=.02))
    assert task['ccd_layout_id'] == conditions['ccd_layout_id'] and task['ccd_indices'] == [0]
    assert task['pre_excitation_seconds'] == 0 and task['sampling_period_seconds'] == 1.5
