"""One manual excitation per repeat, independent warm-up and unchanged result provenance."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import Database
from backend.modules.acquisition import AcquisitionError, AcquisitionService
from backend.modules.dispersion import DispersionError, DispersionService


def finish_once(service, task):
    for _ in range(20):
        if task['status'] in {'between_repeats', 'completed', 'failed', 'stopped'}:
            return task
        task = service.step(task['id'], single_repeat=True)
    raise AssertionError('one excitation did not finish')


def test_manual_repeat_and_preheat_do_not_consume_queue_or_change_saved_repeat(tmp_path):
    db = Database(tmp_path / 'manual.sqlite3'); db.initialize()
    service = AcquisitionService(db)
    queue = service.sample_queues.create('manual', [{'pre_name': 'A001', 'repeats': 2}], None)
    task = service.create_task({'name': 'manual', 'queue_id': queue['id'], 'queue_item_id': queue['items'][0]['id'],
                                'burn_frame_count': 2, 'dark_frame_count': 1, 'pre_excitation_seconds': 0})
    first = finish_once(service, service.start(task['id']))
    assert first['status'] == 'between_repeats' and first['completed_repeats'] == 1
    digest = first['samples'][0]['result_sha256']
    for _ in range(3):
        waiting = service.step(task['id'], single_repeat=True)
        assert waiting['status'] == 'between_repeats' and len(waiting['samples']) == 1
    warmup = finish_once(service, service.preheat(task['id']))
    assert warmup['sample_kind'] == 'preheat' and warmup['repeat_count'] == 1
    assert warmup['queue_item_id'] is None and warmup['samples'][0]['bands'] == []
    assert service.get_task(task['id'])['completed_repeats'] == 1
    assert service.sample_queues.get_item(queue['id'], queue['items'][0]['id'])['spectrum_hash'] is None
    final = finish_once(service, service.start(task['id']))
    assert final['status'] == 'completed' and final['completed_repeats'] == 2
    assert final['samples'][0]['result_sha256'] == digest
    assert service.sample_queues.get_item(queue['id'], queue['items'][0]['id'])['spectrum_hash'] == final['result_sha256']


@pytest.mark.parametrize('kind', ['sample', 'evaporation'])
def test_preheat_and_stop_keep_formal_task_untouched(tmp_path, kind):
    db = Database(tmp_path / 'warmup.sqlite3'); db.initialize()
    service = AcquisitionService(db)
    formal = service.create_task({'name': 'formal', 'task_kind': kind, 'burn_frame_count': 2,
                                  'dark_frame_count': 1, 'pre_excitation_seconds': 0})
    warmup = service.preheat(formal['id'])
    with pytest.raises(AcquisitionError):
        service.preheat(warmup['id'])
    warmup = service.step(warmup['id'], single_repeat=True)
    stopped = service.stop(warmup['id'])
    assert stopped['status'] == 'stopped'
    assert len(service.frames(warmup['id'])) > 0
    assert service.get_task(formal['id']) == formal
    completed = finish_once(service, service.preheat(warmup['id']))
    assert completed['samples'][0]['bands'] == []
    assert completed['excitation_condition']['preheat_source_task_id'] == formal['id']


def test_dispersion_warmup_cannot_be_used_as_formal_calibration(tmp_path):
    db = Database(tmp_path / 'dispersion.sqlite3'); db.initialize()
    service = DispersionService(db)
    formal = service.create_task({'name': 'formal', 'frame_count': 2, 'dark_frame_count': 1,
                                  'pre_excitation_seconds': 0, 'sample': '280-288.acq'})
    warmup = service.preheat_task(formal['id'])
    for _ in range(8):
        if warmup['status'] == 'completed': break
        warmup = service.step_task(warmup['id'])
    assert warmup['status'] == 'completed' and warmup['condition']['preheat'] is True
    assert warmup['calibrations'] == [] and service.frames(warmup['id'])
    assert service.get_task(formal['id']) == formal
    with pytest.raises(DispersionError) as error:
        service.fit_calibration(warmup['id'], {'degree': 2})
    assert error.value.code == 'preheat_not_calibration_source'


def test_preheat_api_refuses_read_only_user_without_creating_records(tmp_path):
    from fastapi.testclient import TestClient
    from backend.config import AppConfig
    from backend.main import create_app
    with TestClient(create_app(AppConfig(data_dir=tmp_path))) as client:
        credentials = {'username': 'capture-admin', 'password': 'capture-password'}
        client.post('/api/v1/auth/bootstrap', json=credentials)
        token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
        admin = {'Authorization': f'Bearer {token}'}
        role = next(role for role in client.get('/api/v1/roles', headers=admin).json() if role['name'] == 'read_only_auditor')
        viewer = {'username': 'capture-viewer', 'password': 'viewer-password'}
        assert client.post('/api/v1/users', headers=admin, json={**viewer, 'role_ids': [role['id']]}).status_code == 201
        token = client.post('/api/v1/auth/login', json=viewer).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        for base in ('/api/v1/acquisitions/tasks', '/api/v1/dispersion/tasks'):
            formal = client.post(base, headers=admin, json={'name': 'formal'}).json()
            before = client.get(base, headers=admin).json()
            assert client.post(f"{base}/{formal['id']}/preheat", headers=headers).status_code == 403
            assert client.get(base, headers=admin).json() == before
