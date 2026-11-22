"""Golden peak locations and per-frame output through both spectrum sources."""
import hashlib
from io import BytesIO
import json
import struct

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.config import AppConfig
from backend.db import utc_now
from backend.main import create_app
from backend.modules.acquisition_import import AcquisitionRecordImporter, ImportedAcquisition, ImportedBand
from tests.test_s10_spectrum_viewer import seed_database
from tests.test_s16_analysis import _seed


def test_calibration_and_full_time_export_keep_fixed_points_and_validate_source(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    database = seed_database(config.database_path)
    version_id, _ = _seed(database, complete_conditions=True)
    source = 'a' * 64
    count = 2048
    darks, first, second = [20] * count, [40] * count, [45] * count
    # The frame-2 maximum is at an adjacent point. The full interval selects the same point in both frames.
    for point in (502, 602, 702, 902, 1102):
        first[point], second[point], second[point + 1] = 1200, 440, 880
    # Ni remains flat, so it must retain its configured viewer position and export blank intensity cells.
    pack = lambda frame: struct.pack(f'<{count}H', *frame)
    burn, dark = pack(first) + pack(second), pack(darks)
    sha = lambda value: hashlib.sha256(value).hexdigest()
    with database.write() as db:
        version = db.execute('SELECT * FROM method_versions WHERE id=?', (version_id,)).fetchone()
        conditions = json.loads(version['payload_json'])['conditions']
        layout = {'ccd_indices': [0], 'gap_points': json.loads(db.execute(
            'SELECT gap_points_json FROM ccd_layouts WHERE id=?', (conditions['ccd_layout_id'],)
        ).fetchone()[0]), 'ws_cof': json.loads(db.execute(
            'SELECT coefficients_json FROM dispersion_calibrations WHERE id=?', (conditions['dispersion_calibration_id'],)
        ).fetchone()[0])}
        db.execute("UPDATE spectrum_bands SET source_sha256=?, format='cmt', sample_name='=sample', "
                   "ccd_count=1, ccd_indices_json='[0]', points_per_ccd=?, layout_json=?, ignition_json=?, "
                   "mean_blob=NULL, burn_adcs_blob=?, dark_adcs_blob=?, burn_sha256=?, dark_sha256=? WHERE id=1",
                   (source, count, json.dumps(layout), json.dumps({'burn_count': 2, 'dark_count': 1, 'burn_cyc': 2, 'dark_cyc': 4}),
                    burn, dark, sha(burn), sha(dark)))
        row = dict(db.execute('SELECT * FROM spectrum_bands WHERE id=1').fetchone())
        row.pop('id')
        row.update(record_index=1, band_id=8, sample_name='第二条')
        db.execute(f"INSERT INTO spectrum_bands({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        task_id, sample_id = AcquisitionRecordImporter().bind(db).import_record(ImportedAcquisition(
            name='全时样品', layout_id=conditions['ccd_layout_id'], method_version_id=version_id,
            method_id=version['method_id'], method_version=1, sample_name='新版样品', original_sample_name='新版样品',
            source_record_id='raw:1', source_sha256=source, measure_time=None,
            interval_start=1, frame_count=2, bands=[ImportedBand(0, count, [first, second], [darks])],
            actor_user_id=None, created_at=utc_now(), burn_cycle_seconds=2, dark_cycle_seconds=4,
        ))
    with TestClient(create_app(config)) as client:
        root = '/api/v1/postprocessing/full-time'
        assert client.get(root).status_code == 401
        assert client.post(root + '/export', json={'source_id': f'raw:{source}', 'start_frame': 1, 'end_frame': 2}).status_code == 401
        client.post('/api/v1/auth/bootstrap', json={'username': 'operator', 'password': 'batch-test-password'})
        token = client.post('/api/v1/auth/login', json={'username': 'operator', 'password': 'batch-test-password'}).json()['access_token']
        client.headers['Authorization'] = f'Bearer {token}'
        assert client.post('/api/v1/methods/current', json={'method_id': version['method_id']}).is_success
        assert client.get('/api/v1/legacy-migration/open-options').json()['full-time']['extensions'] == ['cmt']
        records = {item['id']: item for item in client.get(root).json()['sources']}
        assert records[f'raw:{source}']['record_count'] == 2
        assert records[f'task:{task_id}']['record_count'] == 1

        for identifier in ('raw:1', f'sample:{sample_id}'):
            response = client.get(f'/api/v1/spectra/{identifier}/calibration?scope=reference&exposure_start=1&exposure_end=2')
            assert response.is_success, response.text
            assert [item['point'] for item in response.json()['positions']] == [502]
            response = client.get(f'/api/v1/spectra/{identifier}/calibration?scope=all&exposure_start=1&exposure_end=2')
            assert response.is_success, response.text
            positions = {item['element']: item['point'] for item in response.json()['positions']}
            assert positions['Cu'] == 902
            assert positions['Ni'] is None

        for identifier, expected_count in ((f'raw:{source}', 2), (f'task:{task_id}', 1)):
            payload = {'source_id': identifier, 'method_version_id': version_id, 'start_frame': 1, 'end_frame': 2}
            response = client.post(root + '/export', json=payload)
            assert response.is_success, response.text
            workbook = load_workbook(BytesIO(response.content), read_only=True)
            try:
                frame_rows = list(workbook['逐帧强度'].values)
                assert len(frame_rows) == expected_count * 2 + 1
                assert [row[6] for row in frame_rows[1:3]] == [595, 215]
                assert [row[2:4] for row in frame_rows[1:3]] == [(1, 2), (2, 4)]
                assert all(len(row) < 9 or row[8] is None for row in frame_rows[1:])
                if expected_count == 2:
                    assert next(workbook['逐帧强度'].iter_rows(min_row=2, max_row=2))[1].data_type == 's'
                assert any(row[-1] == '未检出有效峰' and row[2] == 'Ni' for row in list(workbook['谱线峰位'].values)[1:])
            finally:
                workbook.close()
            assert client.post(root + '/export', json=payload | {'end_frame': 3}).status_code == 422
        assert client.post(root + '/export', json={'source_id': f'raw:{source}', 'method_version_id': version_id + 1,
                                                  'start_frame': 1, 'end_frame': 2}).status_code == 409

    with database.read() as db:
        assert tuple(db.execute('SELECT burn_adcs_blob, dark_adcs_blob FROM spectrum_bands WHERE id=1').fetchone()) == (burn, dark)
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='postprocessing.full_time.export'").fetchone()[0] == 2
