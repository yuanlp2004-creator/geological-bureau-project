"""Operator workflows restored together; immutable acquisition/curve inputs remain intact."""
import hashlib
import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import AppConfig
from backend.main import create_app
from backend.runtime import Runtime
from backend.services import AppService
from backend.schemas.system import PreliminaryConditions, SettingsPatch
from backend.schemas.spectrum_viewer import SpectrumPrintRequest
from backend.modules.analysis import AnalysisError
from backend.modules.acquisition import AcquisitionService
from backend.modules.spectrum_viewer import SpectrumViewerError, SpectrumViewerService
from tests.test_spec_gap_closure import _sample_chain
from tests.test_s10_spectrum_viewer import seed_database


def test_selected_line_exposure_view_preserves_original_bands(tmp_path, monkeypatch):
    db, runtime, method, line_id, _, sample_id, run = _sample_chain(tmp_path)
    analysis, acquisition = runtime.analysis_service(), runtime.acquisition_service()
    before = acquisition.spectrum_snapshot(sample_id)
    original = analysis.spectrum(run['id'], 0, acquisition)
    selected = analysis.spectrum(run['id'], 0, acquisition, line_id)
    assert selected['exposure_interval'] == (1, 2)
    assert selected['bands'][0]['mean_points'][902] == 490
    assert original['bands'][0]['mean_points'][902] == pytest.approx(2323.333251953125)
    assert selected['bands'][0]['source_mean_sha256'] == before['bands'][0]['mean_sha256']
    assert acquisition.spectrum_snapshot(sample_id) == before
    assert runtime.methods_service().get(method['id'])['published_version']['content_sha256'] == method['published_version']['content_sha256']
    with pytest.raises(AnalysisError, match='不存在'):
        analysis.spectrum(run['id'], 0, acquisition, 'foreign-line')
    original_snapshot = acquisition.spectrum_snapshot
    def corrupt_snapshot(*args, **kwargs):
        result = original_snapshot(*args, **kwargs)
        result['bands'][0]['mean_points'][902] += 1
        return result
    monkeypatch.setattr(acquisition, 'spectrum_snapshot', corrupt_snapshot)
    with pytest.raises(AnalysisError, match='哈希不符'):
        analysis.spectrum(run['id'], 0, acquisition, line_id)


def test_arbitrary_point_keeps_burn_and_dark_raw_values(tmp_path, monkeypatch):
    db, runtime, _, _, _, sample_id, _ = _sample_chain(tmp_path)
    viewer = runtime.spectrum_viewer_service()
    details = viewer.point_details(f'sample:{sample_id}', ccd=0, point=902)
    assert [row['value'] for row in details['rows']] == [900, 600, 9000, 20]
    assert [row['phase'] for row in details['rows']] == ['burn', 'burn', 'burn', 'dark']
    assert details['pre_excitation_seconds'] == 2
    assert details['burn_cycle_seconds'] == 1.5 and details['dark_cycle_seconds'] == 2
    with pytest.raises(SpectrumViewerError):
        viewer.point_details(f'sample:{sample_id}', ccd=0, point=2048)
    original_snapshot = AcquisitionService.spectrum_snapshot
    def damaged_snapshot(self, *args, **kwargs):
        result = original_snapshot(self, *args, **kwargs)
        for frame in result['frames']:
            if frame['phase'] == 'dark': frame['damaged'] = 1
        return result
    monkeypatch.setattr(AcquisitionService, 'spectrum_snapshot', damaged_snapshot)
    with pytest.raises(SpectrumViewerError, match='损坏'):
        viewer.point_details(f'sample:{sample_id}', ccd=0, point=902)


def test_legacy_point_details_and_truncated_raw_rejected(tmp_path):
    database = seed_database(tmp_path / 'legacy.sqlite3')
    viewer = SpectrumViewerService(database)
    details = viewer.point_details('raw:1', ccd=1, point=2)
    assert [row['value'] for row in details['rows']] == [110, 126, 210]
    with database.write() as db:
        db.execute("UPDATE spectrum_bands SET mean_blob=NULL WHERE id=1")
    assert [row['value'] for row in viewer.point_details('raw:1', ccd=1, point=2)['rows']] == [110, 126, 210]
    with database.write() as db:
        db.execute("UPDATE spectrum_bands SET dark_adcs_blob=x'00' WHERE id=1")
    with pytest.raises(SpectrumViewerError, match='完整'):
        viewer.point_details('raw:1', ccd=1, point=2)


def test_preliminary_defaults_are_independent_persistent_and_patch_preserving(tmp_path):
    db, runtime, method, _, _, _, _ = _sample_chain(tmp_path)
    service = AppService(db)
    original = service.get_settings()
    old_hash = method['published_version']['content_sha256']
    saved = PreliminaryConditions(pre_excitation_seconds=4.5, sampling_period_seconds=1.25, frame_count=11, dark_frame_count=7)
    service.save_preliminary_conditions('evaporation', saved, 1)
    fresh = AppService(db).get_settings()
    assert fresh['preliminary']['evaporation'] == saved.model_dump()
    assert fresh['preliminary']['dispersion'] == original['preliminary']['dispersion']
    service.update_settings(SettingsPatch.model_validate({'analysis': {'dark_round_time_seconds': 9}}), 1)
    assert AppService(db).get_settings()['analysis']['dark_round_time_seconds'] == 9
    assert AppService(db).get_settings()['preliminary']['evaporation'] == saved.model_dump()
    assert runtime.methods_service().get(method['id'])['published_version']['content_sha256'] == old_hash
    with pytest.raises(ValueError):
        PreliminaryConditions(frame_count=0)
    assert fresh['directories'] == original['directories']


@pytest.mark.parametrize('layers', [['curve'], ['grayscale'], ['curve', 'grayscale']])
def test_ccd_print_layers_scope_and_physical_size(tmp_path, layers):
    _, runtime, _, _, _, sample_id, _ = _sample_chain(tmp_path)
    viewer = runtime.spectrum_viewer_service()
    args = dict(selected_record_ids=[f'sample:{sample_id}'], ccd=0, line=0, mode='mean', reference_shift=0,
                visible_x_min=880, visible_x_max=930, visible_y_min=0, visible_y_max=10000,
                print_layers=layers)
    pdf, metadata = viewer.render_visible_pdf(f'sample:{sample_id}', **args, print_scale='ccd_10x')
    assert pdf.startswith(b'%PDF')
    # FmPrintCcd.CalGraphicWidth: (right-left+1) * point_width_um * 10 / 1000.
    assert metadata['physical_width_mm'] == pytest.approx(7.14)
    assert metadata['print_layers'] == layers
    assert metadata['grayscale_max'] == (5000 if 'grayscale' in layers else None)
    with pytest.raises(SpectrumViewerError, match='超过'):
        viewer.render_visible_pdf(f'sample:{sample_id}', **args, print_scale='ccd_10x', print_scope='ccd')
    pdf, metadata = viewer.render_visible_pdf(f'sample:{sample_id}', **args, print_scale='ccd_10x', print_scope='ccd', paper='A3')
    assert metadata['physical_width_mm'] == pytest.approx(286.72)
    assert metadata['visible_point_count'] == 2048 and pdf.startswith(b'%PDF')
    assert SpectrumPrintRequest(**{key: value for key, value in args.items() if key not in {'print_layers'}}, print_layers=['curve']).print_scope == 'visible'
    with pytest.raises(ValueError):
        SpectrumPrintRequest(**{key: value for key, value in args.items() if key != 'print_layers'}, print_layers=[])


def test_standard_relative_error_outputs_keep_snapshot_bytes(tmp_path):
    db, runtime, _, line_id, _, _, run = _sample_chain(tmp_path)
    analysis = runtime.analysis_service()
    run = analysis.build_quality(run['id'])
    run = analysis.curve_action(run['id'], line_id, {'action': 'adjust', 'point_index': 1, 'adjusted_intensity': 210, 'reason': 'operator'})
    run = analysis.fit_standard_curve(run['id'], line_id, {})
    snapshot = run['curves']['lines'][0]['snapshots'][-1]
    before = json.dumps(snapshot, sort_keys=True)
    assert any(abs(row['relative_error_percent']) > 0 for row in snapshot['diagnostics']['points'])
    html = analysis.curve_preview(run['id'], snapshot['id'], 'text', 1)
    assert '相对误差 %' in html and '计算值' in html
    pdf, _ = analysis.print_curve(run['id'], snapshot['id'], 'text', 1)
    assert pdf.startswith(b'%PDF')
    after = analysis.run(run['id'])['curves']['lines'][0]['snapshots'][-1]
    assert json.dumps(after, sort_keys=True) == before


def test_observation_and_defaults_api_permissions_and_failure_zero_mutation(tmp_path):
    database, runtime, _, line_id, _, sample_id, run = _sample_chain(tmp_path)
    application = create_app(runtime=runtime)
    with TestClient(application) as client:
        for endpoint in ('acquisitions', 'dispersion'):
            for origin in ('http://tauri.localhost', 'tauri://localhost'):
                preflight = client.options(f'/api/v1/{endpoint}/defaults', headers={
                    'Origin': origin, 'Access-Control-Request-Method': 'PUT',
                    'Access-Control-Request-Headers': 'content-type,authorization,x-geospectrum-process-key'})
                assert preflight.status_code == 200
                assert preflight.headers['access-control-allow-origin'] == origin
            assert client.options(f'/api/v1/{endpoint}/defaults', headers={
                'Origin': 'https://outside.invalid', 'Access-Control-Request-Method': 'PUT'
            }).status_code == 400
        token = client.post('/api/v1/auth/login', json={'username': 'spec-gap-operator', 'password': 'correct-horse'}).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        options = client.get('/api/v1/methods/options', headers=headers).json()
        assert options['dark_round_time_seconds'] == 8
        new_defaults = {'pre_excitation_seconds': 5, 'sampling_period_seconds': 1.5, 'frame_count': 4, 'dark_frame_count': 2}
        assert client.put('/api/v1/dispersion/defaults', json=new_defaults, headers=headers).status_code == 200
        assert client.get('/api/v1/dispersion/options', headers=headers).json()['preliminary_defaults'] == new_defaults
        assert client.put('/api/v1/dispersion/defaults', json={**new_defaults, 'frame_count': 0}, headers=headers).status_code == 422
        assert client.put('/api/v1/acquisitions/defaults', json=new_defaults).status_code == 401
        spectrum = client.get(f"/api/v1/analyses/runs/{run['id']}/spectra/0?line_id={line_id}", headers=headers)
        assert spectrum.status_code == 200 and spectrum.json()['bands'][0]['mean_points'][902] == 490
        for base in [f'/api/v1/spectra/sample:{sample_id}', f"/api/v1/analyses/runs/{run['id']}/spectra/0"]:
            details = client.get(f'{base}/point-details?ccd=0&point=902', headers=headers)
            assert details.status_code == 200 and len(details.json()['rows']) == 4
            copied = client.post(f'{base}/point-details/copy?ccd=0&point=902&orientation=vertical', headers=headers)
            assert copied.status_code == 200 and '燃烧\t3\t9000' in copied.json()['text']
            pdf = client.post(f'{base}/point-details/print?ccd=0&point=902', headers=headers)
            assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
            assert client.get(f'{base}/point-details?ccd=0&point=-1', headers=headers).status_code == 422
        role = client.post('/api/v1/roles', json={'name': 'operator-observer', 'permission_keys': ['spectra.read', 'analysis.read']}, headers=headers).json()
        assert client.post('/api/v1/users', json={'username': 'operator-observer', 'password': 'Observer-QA-2026!', 'role_ids': [role['id']]}, headers=headers).status_code == 201
        reader = client.post('/api/v1/auth/login', json={'username': 'operator-observer', 'password': 'Observer-QA-2026!'}).json()['access_token']
        read_headers = {'Authorization': f'Bearer {reader}'}
        assert client.get(f'/api/v1/spectra/sample:{sample_id}/point-details?ccd=0&point=902', headers=read_headers).status_code == 200
        assert client.put('/api/v1/dispersion/defaults', json=new_defaults, headers=read_headers).status_code == 403
        assert client.put('/api/v1/acquisitions/defaults', json=new_defaults, headers=read_headers).status_code == 403
        assert client.post(f'/api/v1/spectra/sample:{sample_id}/point-details/print?ccd=0&point=902', headers=read_headers).status_code == 403
        assert client.post(f'/api/v1/spectra/sample:{sample_id}/point-details/copy?ccd=0&point=902&orientation=vertical', headers=read_headers).status_code == 403
        assert client.post(f"/api/v1/analyses/runs/{run['id']}/spectra/0/point-details/copy?ccd=0&point=902&orientation=vertical", headers=read_headers).status_code == 403
        with database.read() as db:
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='analysis.observation.export'").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='spectrum.export' AND details_json LIKE '%clipboard%'").fetchone()[0] == 1
