"""Direct workspace opening preserves originals and reuses validated snapshots."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.config import AppConfig
from backend.main import create_app
from backend.modules.spectrum_migration.reader import SpectrumAccessReader
from tests.test_s08_spectrum_migration import payload
from tests.test_s09_result_migration import source_file
from tests.test_legacy_migration import _facts, SOURCE_ROOT


@pytest.fixture
def workspace(tmp_path):
    application = create_app(AppConfig(data_dir=tmp_path / 'app'))
    with TestClient(application) as client:
        client.post('/api/v1/auth/bootstrap', json={'username': 'operator', 'password': 'correct-horse'})
        auth = client.post('/api/v1/auth/login', json={'username': 'operator', 'password': 'correct-horse'}).json()
        client.headers['Authorization'] = 'Bearer ' + auth['access_token']
        yield client, application.state.runtime


@pytest.mark.parametrize(('fmt', 'purpose'), [('cdt', 'spectra'), ('cmt', 'analysis'),
                                              ('wdt', 'dispersion'), ('edt', 'evaporation')])
def test_direct_spectra_open_reuses_source_and_enters_consumer(workspace, tmp_path, monkeypatch, fmt, purpose):
    client, runtime = workspace
    path = tmp_path / ('source.' + fmt)
    path.write_bytes(('old-' + fmt).encode())
    before = _facts(path)
    monkeypatch.setattr(SpectrumAccessReader, 'read', lambda *args: (payload(fmt), {}))
    first = client.post('/api/v1/legacy-migration/open-file', json={'path': str(path), 'purpose': purpose})
    assert first.status_code == 200, first.text
    opened = first.json()
    again = client.post('/api/v1/legacy-migration/open-file', json={'path': str(path), 'purpose': purpose}).json()
    assert again['record_ids'] == opened['record_ids'] and again['reused']
    assert _facts(path) == before and not list(tmp_path.glob('*.ldb'))
    identifier = opened['record_ids'][0]
    if fmt == 'wdt':
        assert again['task_ids'] == opened['task_ids']
        task = runtime.dispersion_service().get_task(opened['task_ids'][0])
        assert task['status'] == 'completed' and task['ccd_indices'] == [1, 3]
        assert task['last_event']['ccds'][0]['points'] == [106, 107, 108]
    if fmt == 'edt':
        response = client.get(f'/api/v1/spectrum-migration/evaporation-records/{identifier}/curve')
        assert response.status_code == 200, response.text
        rows = response.json()['frames']
        assert [(row['peak_value'], row['integral_value'], row['virtual_time_ms']) for row in rows] == [
            (102, 303, 1000), (105, 312, 1000), (108, 321, 2000), (111, 330, 2000)]
    with runtime.database.read() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT count(*) FROM spectrum_bands').fetchone()[0] == 1


def test_real_method_and_result_files_open_without_manual_stage(workspace, tmp_path):
    client, runtime = workspace
    original = tmp_path / 'originals'
    original.mkdir()
    for source in SOURCE_ROOT.iterdir():
        if source.suffix.lower() in {'.mtd', '.cfg', '.opt'}:
            shutil.copy2(source, original / source.name)
    method = original / 'DIRECT.MTD'
    before = {p.name: _facts(p) for p in original.iterdir()}
    result = client.post('/api/v1/legacy-migration/open-file', json={'path': str(method), 'purpose': 'methods'})
    assert result.status_code == 200, result.text
    assert len(result.json()['method_ids']) == 3
    repeated = client.post('/api/v1/legacy-migration/open-file', json={'path': str(method), 'purpose': 'methods'})
    assert repeated.status_code == 200 and repeated.json()['reused']
    for fmt, purpose in [('pdt', 'recalculate'), ('dat', 'reports')]:
        path = Path(shutil.copy2(source_file(fmt), original / ('old.' + fmt)))
        before[path.name] = _facts(path)
        opened = client.post('/api/v1/legacy-migration/open-file', json={'path': str(path), 'purpose': purpose})
        assert opened.status_code == 200, opened.text
        if fmt == 'pdt':
            ids = opened.json()['record_ids']
            preview = client.post('/api/v1/postprocessing/legacy-intensity-output', json={'record_ids': ids})
            assert preview.status_code == 200 and len(preview.json()['table']) > 1
            exported = client.post('/api/v1/postprocessing/legacy-intensity-output', json={'record_ids': ids, 'format': 'excel'})
            assert exported.status_code == 200 and exported.json()['table'] == preview.json()['table']
            assert exported.json()['print_job'] is None
        else:
            assert client.get('/api/v1/reports/legacy-sources').json()[0]['id'] == opened.json()['record_ids'][0]
    assert {p.name: _facts(p) for p in original.iterdir()} == before
    assert not list(original.glob('*.ldb'))


def test_invalid_file_or_missing_permissions_never_creates_formal_data(workspace, tmp_path):
    client, runtime = workspace
    path = tmp_path / 'bad.pdt'
    path.write_bytes(b'not a legacy matrix')
    for purpose, status in [('recalculate', 400), ('reports', 422)]:
        response = client.post('/api/v1/legacy-migration/open-file', json={'path': str(path), 'purpose': purpose})
        assert response.status_code == status
    with runtime.database.read() as db:
        assert db.execute('SELECT count(*) FROM result_matrices').fetchone()[0] == 0
    role = client.post('/api/v1/roles', json={'name': 'view-only-open-test', 'description': 'read only',
                                           'permission_keys': ['spectra.read']}).json()
    client.post('/api/v1/users', json={'username': 'reader', 'password': 'correct-horse', 'role_ids': [role['id']]})
    auth = client.post('/api/v1/auth/login', json={'username': 'reader', 'password': 'correct-horse'}).json()
    client.headers['Authorization'] = 'Bearer ' + auth['access_token']
    assert client.get('/api/v1/legacy-migration/open-options').json() == {}
    assert client.post('/api/v1/legacy-migration/open-file', json={'path': str(path), 'purpose': 'recalculate'}).status_code == 403
