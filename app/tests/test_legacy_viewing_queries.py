"""Read-side file grouping preserves full legacy record sets and immutable source identity."""
from pathlib import Path
import csv
import hashlib
import io
import json
import runpy
import pytest
from fastapi.testclient import TestClient
from backend.config import AppConfig
from backend.main import create_app
from backend.modules.spectrum_viewer import SpectrumViewerService, SpectrumViewerError


def test_file_directory_and_scope_filter_precede_pagination(tmp_path):
    seed = runpy.run_path(str(Path(__file__).with_name('test_s10_spectrum_viewer.py')))['seed_database']
    database = seed(tmp_path / 'grouping.sqlite3')
    with database.write() as connection:
        connection.execute("UPDATE spectrum_bands SET format='edt' WHERE id=1")
        original = dict(connection.execute('SELECT * FROM spectrum_bands WHERE id=1').fetchone())
        original.pop('id')
        columns = ','.join(original)
        marks = ','.join('?' for _ in original)
        for index in range(130):
            value = original | {'source_sha256':'another-file', 'format':'cmt', 'record_index':index, 'band_id':index+10}
            connection.execute(f'INSERT INTO spectrum_bands({columns}) VALUES ({marks})',tuple(value.values()))
    viewer = SpectrumViewerService(database)
    files = {item['key']:item for item in viewer.files()}
    assert files['raw:another-file']['record_count'] == 130
    assert not any('points' in item or 'ccd' in item for item in files.values())
    first = viewer.list(group='raw:another-file',limit=100)
    second = viewer.list(group='raw:another-file',offset=100,limit=100)
    assert len(first)==100 and len(second)==30
    assert len({item['id'] for item in first+second})==130
    evaporation = viewer.list(scope='evaporation',limit=1)
    assert len(evaporation)==1 and evaporation[0]['id']=='raw:1'
    assert evaporation[0]['band_id']==7 and evaporation[0]['burn_count']==2
    assert viewer.get('raw:1')['band_id']==7
    with pytest.raises(SpectrumViewerError):
        viewer.files(scope='unknown')


def test_file_directory_keeps_the_spectrum_read_permission(tmp_path):
    with TestClient(create_app(AppConfig(data_dir=tmp_path))) as client:
        assert client.get('/api/v1/spectra/files').status_code==401


def test_dispersion_page_offsets_keep_older_records(tmp_path):
    from backend.db import Database
    from backend.modules.dispersion import DispersionService
    database=Database(tmp_path/'dispersion.sqlite3');database.initialize()
    service=DispersionService(database)
    tasks=[service.create_task({'name':f'band-{index}'}) for index in range(4)]
    assert [item['id'] for item in service.list_tasks(2,0)]==[tasks[3]['id'],tasks[2]['id']]
    assert [item['id'] for item in service.list_tasks(2,2)]==[tasks[1]['id'],tasks[0]['id']]


def test_legacy_display_normalizes_cycles_subtracts_dark_and_preserves_sources(tmp_path):
    seed = runpy.run_path(str(Path(__file__).with_name('test_s10_spectrum_viewer.py')))['seed_database']
    database = seed(tmp_path / 'legacy-display.sqlite3')
    with database.write() as connection:
        ignition = {'burn_count': 2, 'dark_count': 1, 'burn_cyc': 2, 'dark_cyc': 4}
        connection.execute('UPDATE spectrum_bands SET ignition_json=? WHERE id=1', (json.dumps(ignition),))
        before = dict(connection.execute('SELECT * FROM spectrum_bands WHERE id=1').fetchone())
        for phase in ('burn', 'dark'):
            connection.execute(f'UPDATE spectrum_bands SET {phase}_sha256=? WHERE id=1',
                               (hashlib.sha256(before[f'{phase}_adcs_blob']).hexdigest(),))
    viewer = SpectrumViewerService(database)
    assert viewer.get('raw:1')['ccd']['points'][0]['value'] == 0  # Existing stored-mean contract.
    display = viewer.get('raw:1', intensity_mode='legacy_2_0_2')
    assert [p['value'] for p in display['ccd']['points']] == [4 + i / 4 for i in range(8)]
    assert display['exposure_segment'] == {'start': 1, 'end': 2, 'count': 2}
    first = viewer.get('raw:1', intensity_mode='legacy_2_0_2', exposure_start=1, exposure_end=1)
    assert first['ccd']['points'][0]['value'] == pytest.approx(0.1)
    content, _, _ = viewer.export_csv('raw:1', intensity_mode='legacy_2_0_2')
    rows = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    assert float(rows[0]['value']) == 4

    # Old single ErrIndex repair happens on a copy, before averaging.
    with database.write() as connection:
        connection.execute('UPDATE spectrum_bands SET bad_frame_indices_json=? WHERE id=1',
                           (json.dumps([{'phase': 'burn', 'index': 0, 'legacy_value': 1}]),))
    assert viewer.get('raw:1', intensity_mode='legacy_2_0_2')['ccd']['points'][0]['value'] == 8
    with database.read() as connection:
        after = connection.execute('SELECT * FROM spectrum_bands WHERE id=1').fetchone()
        for column in ('mean_blob', 'burn_adcs_blob', 'dark_adcs_blob'):
            assert after[column] == before[column]

    ignition['burn_cyc'] = 0
    with database.write() as connection:
        connection.execute('UPDATE spectrum_bands SET ignition_json=? WHERE id=1', (json.dumps(ignition),))
    with pytest.raises(SpectrumViewerError) as invalid:
        viewer.get('raw:1', intensity_mode='legacy_2_0_2')
    assert invalid.value.code == 'spectrum_legacy_view_invalid'
    assert invalid.value.status_code == 422
    assert viewer.get('raw:1')['ccd']['points'][0]['value'] == 0
