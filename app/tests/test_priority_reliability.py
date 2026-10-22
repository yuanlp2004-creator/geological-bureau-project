"""Regression cases from the 2026-09-20 reliability review."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
import sys
import tempfile

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api.acquisition import create_acquisition_task, rename_acquisition_sample, step_acquisition_task
from backend.db import Database
from backend.modules.acquisition import AcquisitionError, AcquisitionService
from backend.modules.sample_queues import SampleQueueError
from backend.modules.reports import ReportError, ReportService
from backend.modules.postprocessing.exporting import ExportService
from backend.modules.postprocessing.errors import PostProcessingError
from backend.schemas.acquisition import AcquisitionTaskCreate, AcquisitionRename


@pytest.mark.parametrize('endpoint', ['create', 'rename', 'step'])
def test_queue_errors_keep_api_status_and_details(endpoint):
    def fail(*args):
        raise SampleQueueError('queue_item_not_found', 'missing', status_code=404, details={'id': 7})
    service = SimpleNamespace(create_task=fail, rename=fail, step=fail)
    runtime = SimpleNamespace(acquisition_service=lambda: service)
    session = SimpleNamespace(user_id=1)
    with pytest.raises(HTTPException) as caught:
        if endpoint == 'create':
            create_acquisition_task(AcquisitionTaskCreate(task_kind='sample', name='test'), session, runtime=runtime)
        elif endpoint == 'rename':
            rename_acquisition_sample(1, 1, AcquisitionRename(post_name='test'), session, runtime=runtime)
        else:
            step_acquisition_task(1, session, runtime=runtime)
    assert caught.value.status_code == 404
    assert caught.value.detail['code'] == 'queue_item_not_found'
    assert caught.value.detail['details'] == {'id': 7}


@pytest.mark.parametrize('operation', ['start', 'step', 'pause', 'resume', 'stop'])
def test_acquisition_control_is_exclusive_and_releases_after_error(tmp_path, monkeypatch, operation):
    database = Database(tmp_path / 'control.sqlite3')
    database.initialize()
    service = AcquisitionService(database)
    task = service.create_task({'task_kind': 'sample', 'name': 'control', 'burn_frame_count': 3,
                                'dark_frame_count': 0, 'pre_excitation_seconds': 0})
    service.start(task['id'])
    entered, release = Event(), Event()
    original = service.repository._context
    def blocked(task_id, db=None):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
            raise AcquisitionError('injected_failure', 'test failure')
        return original(task_id, db)
    monkeypatch.setattr(service.repository, '_context', blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.step, task['id'])
        assert entered.wait(5)
        try:
            with pytest.raises(AcquisitionError) as caught:
                getattr(service, operation)(task['id'])
            assert caught.value.code == 'acquisition_task_busy'
            assert caught.value.status_code == 409
            # A different task must not share the command lock.
            with pytest.raises(AcquisitionError) as missing:
                service.step(999999)
            assert missing.value.code != 'acquisition_task_busy'
        finally:
            release.set()
        with pytest.raises(AcquisitionError, match='test failure'):
            future.result()
    assert service.step(task['id'])['status'] == 'burn'


@pytest.mark.parametrize('writer', [ReportService._atomic, ExportService._atomic_write])
@pytest.mark.parametrize('strategy', ['suffix', 'error'])
def test_concurrent_exports_do_not_overwrite(tmp_path, monkeypatch, writer, strategy):
    barrier = Barrier(2)
    original = tempfile.mkstemp
    def synchronized(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(tempfile, 'mkstemp', synchronized)
    def save(content):
        try:
            return writer(tmp_path, 'same', content, '.csv', strategy)
        except (ReportError, PostProcessingError) as error:
            assert error.status_code == 409
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [b'first', b'second']))
    saved = [path for path in results if path is not None]
    assert len(set(saved)) == (2 if strategy == 'suffix' else 1)
    assert len(list(tmp_path.iterdir())) == len(saved)
    if strategy == 'suffix':
        assert {path.read_bytes() for path in saved} == {b'first', b'second'}


@pytest.mark.parametrize('directory', [None, '', '   '])
def test_report_directory_is_validated_before_rendering(directory, monkeypatch):
    service = ReportService(None, printers=None, analysis=None)
    monkeypatch.setattr(service, 'get', lambda _: {'status': 'confirmed'})
    with pytest.raises(ReportError) as caught:
        service.export(1, {'format': 'csv', 'output_directory': directory})
    assert caught.value.code == 'report_output_directory_required'
