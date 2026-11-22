"""EDT preparation: numerical evidence, target decisions, identity and rollback."""
import json
import sqlite3
import struct
import uuid

import pytest

from tests.test_s18_postprocessing import _fixture, _seed_method_curve
from backend.modules.methods import MethodService
from backend.modules.postprocessing import PostProcessingError
from backend.modules.spectrum_viewer import SpectrumViewerService
from tests.test_sample_current_context import client_state
from backend.schemas.methods import MethodCondition


def seed_prepared(database):
    method, version, _ = _seed_method_curve(database)
    with database.write() as db:
        db.execute("UPDATE ccd_layouts SET ccds_per_frame=2,gap_points_json='[0]' WHERE id=2")
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE id=?', (version,)).fetchone()[0])
        payload['conditions'] = MethodCondition(ccd_layout_id=2, dispersion_calibration_id='default', frame_count=2,
            reference_wavelength_nm=200, selected_ccds=[0, 1],
            angle_exposures=[{'angle_deg': 0, 'storage_mode': 'averaged', 'start_frame': 1, 'end_frame': 2}]).model_dump()
        payload['legacy_migration'] = {'legacy_method_id': 88}
        version = db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (?,2,'published',?,'2026-11-05T00:00:00+00:00')",
                             (method, json.dumps(payload))).lastrowid
        db.execute('UPDATE methods SET current_version=2 WHERE id=?', (method,))
        layout = MethodService(database).bind_geometry(db, payload['conditions']).prepared_layout()
        layout['legacy_method_id'] = 77
        layout['ws_cof'] = [0.001, 1.0, 3.0]
        db.execute('UPDATE spectrum_bands SET layout_json=?,ignition_json=?,dark_adcs_blob=?',
                   (json.dumps(layout), json.dumps({'burn_count': 3, 'dark_count': 1, 'burn_cyc': 2, 'dark_cyc': 1}), struct.pack('<6H', *([1]*6))))
    MethodService(database).open(method, None)
    return version


@pytest.fixture
def prepared(tmp_path):
    database, service = _fixture(tmp_path)
    version = seed_prepared(database)
    return database, service.prepared, version


def input_for(version, **changes):
    return dict(request_id=uuid.uuid4().hex, source_sha256='source-sha', record_ids=['raw:1'], target_name='输出样品',
                storage_mode='averaged', start_frame=2, end_frame=3, use_method_id=True,
                same_name_strategy='error', expected_method_version_id=version) | changes


def test_mean_frames_and_viewer_share_target_identity(prepared):
    database, service, version = prepared
    result = service.import_records(input_for(version), None)
    target = result['target']
    assert target['method_version_id'] == version and target['legacy_method_id'] == 88
    sample = target['records'][0]['id']
    assert target['records'][0]['name'] == 'band'
    with database.read() as db:
        band = db.execute('SELECT * FROM acquisition_sample_bands WHERE sample_id=? AND ccd_index=0', (sample,)).fetchone()
        # Mean of frames 2,3 / 2 seconds, minus one-second dark=1.
        assert struct.unpack('<3f', band['mean_blob']) == (0.25, 0.75, 1.25)
        assert band['burn_frames_blob'] is None and band['dark_frames_blob'] is None
    viewer = SpectrumViewerService(database)
    group = 'prepared:' + target['id']
    assert viewer.files(kind='sample')[0]['key'] == group
    assert len(viewer.list(kind='sample', group=group)) == 1
    detail = viewer.get(f'sample:{sample}')
    assert detail['sample_name'] == 'band'
    assert detail['measure_time'] == '2026-08-14T08:00:00+08:00'
    assert detail['ccd']['points'][0]['wavelength_nm'] is not None


def test_full_time_preserves_selected_burn_and_all_dark(prepared):
    database, service, version = prepared
    result = service.import_records(input_for(version, storage_mode='full_interval'), None)
    with database.read() as db:
        band = db.execute('SELECT * FROM acquisition_sample_bands WHERE sample_id=? AND ccd_index=1', (result['target']['records'][0]['id'],)).fetchone()
        assert bytes(band['burn_frames_blob']) == struct.pack('<6H', 5, 6, 7, 6, 7, 8)
        assert bytes(band['dark_frames_blob']) == struct.pack('<3H', 1, 1, 1)
    with pytest.raises(PostProcessingError, match='小于当前方法'):
        service.import_records(input_for(version, storage_mode='full_interval', start_frame=3), None)


def test_append_keeps_target_method_and_replace_preserves_history(prepared):
    database, service, version = prepared
    first = service.import_records(input_for(version, use_method_id=False), None)['target']
    assert first['method_version_id'] is None and first['legacy_method_id'] == 77
    with pytest.raises(PostProcessingError, match='已存在'):
        service.import_records(input_for(version), None)
    second = service.import_records(input_for(version, same_name_strategy='append', expected_target_revision=first['revision']), None)['target']
    assert len(second['records']) == 2 and second['method_version_id'] is None
    third = service.import_records(input_for(version, same_name_strategy='replace', expected_target_revision=second['revision']), None)['target']
    assert len(third['records']) == 1 and third['method_version_id'] == version
    with database.read() as db:
        assert db.execute('SELECT COUNT(*) FROM acquisition_samples').fetchone()[0] == 3
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_retries_are_idempotent_and_stale_target_is_rejected(prepared):
    database, service, version = prepared
    payload = input_for(version)
    first = service.import_records(payload, None)
    assert service.import_records(payload, None)['reused']
    with pytest.raises(PostProcessingError, match='不能更改参数'):
        service.import_records(payload | {'end_frame': 2}, None)
    with pytest.raises(PostProcessingError, match='已更新'):
        service.import_records(input_for(version, same_name_strategy='append', expected_target_revision=9), None)
    with database.read() as db:
        assert db.execute('SELECT COUNT(*) FROM acquisition_samples').fetchone()[0] == 1


@pytest.mark.parametrize('change,match', [({'end_frame': 4}, '区间'), ({'source_sha256': 'other'}, '当前蒸发文件'),
                                        ({'expected_method_version_id': 999}, '当前方法已改变')])
def test_invalid_imports_do_not_write(prepared, change, match):
    database, service, version = prepared
    with database.read() as db: before = list(db.iterdump())
    with pytest.raises(PostProcessingError, match=match): service.import_records(input_for(version, **change), None)
    with database.read() as db: assert list(db.iterdump()) == before


def test_failed_final_audit_rolls_back_conversion_and_target(prepared):
    database, service, version = prepared
    with database.write() as db:
        db.execute("CREATE TRIGGER reject_prepared BEFORE INSERT ON audit_events WHEN NEW.action='postprocessing.prepared.import' "
                   "BEGIN SELECT RAISE(ABORT,'injected final failure'); END")
    with database.read() as db: before = list(db.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match='injected final failure'):
        service.import_records(input_for(version), None)
    with database.read() as db: assert list(db.iterdump()) == before


def test_dispersion_uses_current_method_without_rewriting_source(prepared):
    database, service, version = prepared
    with database.read() as db: before = tuple(db.execute('SELECT * FROM spectrum_bands').fetchone())
    original = SpectrumViewerService(database).get('raw:1', detail='frame')['frame_detail']['ccd']['points'][0]['wavelength_nm']
    service.save_dispersion('source-sha', version, None)
    changed = SpectrumViewerService(database).get('raw:1', detail='frame')['frame_detail']['ccd']['points'][0]['wavelength_nm']
    assert changed != original
    with database.read() as db:
        assert tuple(db.execute('SELECT * FROM spectrum_bands').fetchone()) == before
        assert db.execute('SELECT method_version_id FROM postprocessing_prepared_dispersion').fetchone()[0] == version


def test_layout_and_append_ignition_mismatch_reject(prepared):
    database, service, version = prepared
    first = service.import_records(input_for(version, storage_mode='full_interval'), None)['target']
    with database.write() as db:
        ignition = json.loads(db.execute('SELECT ignition_json FROM spectrum_bands').fetchone()[0])
        ignition['burn_cyc'] = 1
        db.execute('UPDATE spectrum_bands SET ignition_json=?', (json.dumps(ignition),))
    with pytest.raises(PostProcessingError, match='激发条件不一致'):
        service.import_records(input_for(version, storage_mode='full_interval', same_name_strategy='append', expected_target_revision=first['revision']), None)
    with database.write() as db:
        layout = json.loads(db.execute('SELECT layout_json FROM spectrum_bands').fetchone()[0]); layout['ccd_indices'] = [1, 0]
        db.execute('UPDATE spectrum_bands SET layout_json=?', (json.dumps(layout),))
    with pytest.raises(PostProcessingError, match='谱板参数'):
        service.import_records(input_for(version, target_name='不兼容'), None)


def test_v28_upgrade_preserves_existing_records(prepared):
    database, _, _ = prepared
    with database.write() as db:
        db.execute('DROP TABLE postprocessing_prepared_dispersion')
        db.execute('DROP TABLE postprocessing_prepared_targets')
        db.execute('DELETE FROM schema_migrations WHERE version=28')
    with database.read() as db: before = tuple(db.execute('SELECT * FROM spectrum_bands').fetchone())
    database.initialize()
    with database.read() as db:
        assert tuple(db.execute('SELECT * FROM spectrum_bands').fetchone()) == before
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_prepared_http_permissions_and_current_method(client_state):
    client, runtime, headers, call, _ = client_state
    options = call('/postprocessing/prepared-import')
    assert options['method']['title'] == 'current-method'
    body = input_for(options['method']['version_id'], record_ids=['raw:999'])
    assert client.post('/api/v1/postprocessing/prepared-import', json=body).status_code == 401
    assert client.post('/api/v1/postprocessing/prepared-import', headers=headers, json=body).status_code == 404
    roles = call('/roles')
    role = next(role for role in roles if role['name'] == 'read_only_auditor')
    call('/users', {'username': 'prepared-auditor', 'password': 'prepared-auditor-2026', 'role_ids': [role['id']]})
    token = client.post('/api/v1/auth/login', json={'username': 'prepared-auditor', 'password': 'prepared-auditor-2026'}).json()['access_token']
    readonly = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/postprocessing/prepared-import', headers=readonly).status_code == 200
    assert client.post('/api/v1/postprocessing/prepared-import', headers=readonly, json=body).status_code == 403
    assert client.post('/api/v1/postprocessing/prepared-dispersion', headers=readonly,
                       json={'source_sha256': 'source-sha', 'expected_method_version_id': options['method']['version_id']}).status_code == 403

