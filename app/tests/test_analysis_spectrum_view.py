"""Analysis desk coordinates and PDF must use the same immutable spectrum."""
import base64
import hashlib
import struct

from tests.test_methods import method_client
from tests.test_s16_analysis import _seed


def test_save_calibration_keeps_restored_lines_at_the_stored_position(method_client, monkeypatch):
    from backend.modules.analysis.service import AnalysisService

    client, runtime, headers = method_client
    version, ids = _seed(runtime.database, complete_conditions=True)
    run = client.post('/api/v1/analyses/runs', headers=headers, json={
        'acquisition_sample_ids': ids, 'method_version_id': version}).json()
    url = f"/api/v1/analyses/runs/{run['id']}/spectra/0/calibration"
    captured = []
    def preview(*_):
        return {'source_key': 'test', 'positions': [
            {'line_id': 'ref', 'line_type': 'baseline', 'stored_wavelength_nm': 250.1, 'measured_wavelength_nm': 250.2, 'found': True},
            {'line_id': 'line', 'line_type': 'analysis', 'stored_wavelength_nm': 251.1, 'measured_wavelength_nm': 251.2, 'found': False},
        ]}

    def save(_, positions, __):
        captured.append(positions)
        return {'latest_version': 2}

    from backend.modules.methods.service import MethodService
    monkeypatch.setattr(AnalysisService, 'calibration_preview', preview)
    monkeypatch.setattr(MethodService, 'save_calibrated_positions', save)
    assert client.post(url, headers=headers, json={'measured_line_ids': ['unknown']}).status_code >= 400
    assert client.post(url, headers=headers, json={}).status_code >= 400
    saved = client.post(url, headers=headers, json={'measured_line_ids': ['ref']})
    assert saved.is_success, saved.text
    assert [line['measured_wavelength_nm'] for line in captured[0]['positions']] == [250.2, 251.1]


def test_analysis_desk_coordinates_print_and_integrity(method_client, monkeypatch):
    client, runtime, headers = method_client
    version, samples = _seed(runtime.database, complete_conditions=True)
    created = client.post('/api/v1/analyses/runs', headers=headers, json={
        'name': 'analysis desk', 'acquisition_sample_ids': samples, 'method_version_id': version,
        'calculation_profile': 'modern_v1', 'slow_mode': False})
    assert created.status_code == 201, created.text
    run = created.json()
    url = f"/api/v1/analyses/runs/{run['id']}/spectra/0"
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    spectrum = response.json()
    band = spectrum['bands'][0]
    points, waves = band['mean_points'], band['wavelengths_nm']
    assert len(points) == len(waves) == 2048
    assert all(left < right for left, right in zip(waves, waves[1:]))
    blob = struct.pack(f'<{len(points)}f', *points)
    assert hashlib.sha256(blob).hexdigest() == band['mean_sha256']
    # A method line and the coordinate conversion agree at the identical fractional point.
    line = spectrum['lines'][0]
    with runtime.database.read() as db:
        _, payload, _ = runtime.analysis_service().repository._context(db, run['id'])
        geometry = runtime.analysis_service().methods.bind_geometry(db, payload['conditions'])
        assert waves[0] == geometry.wavelength_at(band['ccd_index'], 0)
        assert waves[-1] == geometry.wavelength_at(band['ccd_index'], 2047)
        assert abs(geometry.wavelength_at(line['ccd_index'], line['point']) - line['wavelength_nm']) < 1e-6
    from backend.modules import spectrum_pdf
    render = spectrum_pdf.render_spectrum_pdf
    printed = []
    def record(curves, *args, **kwargs):
        printed.extend(curves)
        return render(curves, *args, **kwargs)
    monkeypatch.setattr(spectrum_pdf, 'render_spectrum_pdf', record)
    view = {'ccd': band['ccd_index'], 'x_min': 1, 'x_max': len(points), 'y_min': 0, 'y_max': max(points)}
    pdf = client.post(url + '/print', headers=headers, json=view)
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b'%PDF-')
    assert printed[0]['points'] == list(enumerate(points, start=1))
    assert client.post(url + '/print', headers=headers, json={**view, 'x_min': 2048, 'x_max': 1}).status_code == 422
    invalid_ccd = client.post(url + '/print', headers=headers, json={**view, 'ccd': 255})
    assert invalid_ccd.status_code == 409
    assert invalid_ccd.json()['detail']['code'] == 'analysis_ccd_invalid'
    # Corruption cannot be hidden by drawing or by exporting the source record directly.
    from backend.modules.acquisition import AcquisitionService
    snapshot = AcquisitionService.spectrum_snapshot
    def corrupt(service, *args, **kwargs):
        value = snapshot(service, *args, **kwargs)
        value['bands'][0]['mean_points'][0] += 1
        return value
    monkeypatch.setattr(AcquisitionService, 'spectrum_snapshot', corrupt)
    for response in (client.get(url, headers=headers), client.post(url + '/print', headers=headers, json=view)):
        assert response.status_code >= 400
        assert response.json()['detail']['code'] == 'analysis_band_integrity_failed'


def test_temporary_exposure_uses_saved_frame_and_does_not_change_run(method_client, monkeypatch):
    from backend.db import utc_now
    from backend.modules import spectrum_pdf
    from backend.modules.acquisition_import import AcquisitionRecordImporter, ImportedAcquisition, ImportedBand

    client, runtime, headers = method_client
    version, averaged = _seed(runtime.database, complete_conditions=True)
    with runtime.database.write() as db:
        method = db.execute('SELECT method_id FROM method_versions WHERE id=?', (version,)).fetchone()[0]
        layout = db.execute("SELECT id FROM ccd_layouts WHERE name='default'").fetchone()[0]
        _, full = AcquisitionRecordImporter().bind(db).import_record(ImportedAcquisition(
            name='观察批次', layout_id=layout, method_version_id=version, method_id=method, method_version=1,
            sample_name='全时', original_sample_name='全时', source_record_id='test', source_sha256='test',
            measure_time=None, interval_start=1, frame_count=2, actor_user_id=None, created_at=utc_now(),
            burn_cycle_seconds=2, dark_cycle_seconds=4,
            bands=[ImportedBand(0, 2048, [[100] * 2048, [200] * 2048], [[20] * 2048])],
        ))
    created = client.post('/api/v1/analyses/runs', headers=headers, json={
        'acquisition_sample_ids': [full, averaged[0]], 'method_version_id': version})
    assert created.is_success, created.text
    run = created.json()
    base = f"/api/v1/analyses/runs/{run['id']}"
    url = base + '/spectra/0'
    original = client.get(url, headers=headers).json()
    assert original['bands'][0]['observation_frame_count'] == 2
    assert original['bands'][0]['mean_points'][0] == 70
    selection = {'band_position': 0, 'exposure_start': 2, 'exposure_end': 2}
    temporary = client.get(url, headers=headers, params=selection)
    assert temporary.is_success, temporary.text
    assert temporary.json()['bands'][0]['mean_points'] == [95] * 2048
    assert temporary.json()['bands'][0]['source_mean_sha256'] == original['bands'][0]['mean_sha256']
    assert client.get(url, headers=headers, params={**selection, 'exposure_end': 3}).status_code == 422
    assert client.get(base + '/spectra/1', headers=headers, params=selection).status_code == 422
    printed = []
    render = spectrum_pdf.render_spectrum_pdf

    def record(curves, *args, **kwargs):
        printed.extend(curves)
        return render(curves, *args, **kwargs)

    monkeypatch.setattr(spectrum_pdf, 'render_spectrum_pdf', record)
    response = client.post(url + '/print', headers=headers, json={
        **selection, 'ccd': 0, 'x_min': 1, 'x_max': 50, 'y_min': 0, 'y_max': 100})
    assert response.is_success and response.content.startswith(b'%PDF-')
    assert printed[0]['points'][0] == (1, 95)
    assert client.get(url, headers=headers).json() == original
    assert client.get(base, headers=headers).json() == run


def test_analysis_sample_number_copy_clear_and_history(method_client):
    client, runtime, headers = method_client
    version, samples = _seed(runtime.database, complete_conditions=True)
    payload = {'name': '编号副本', 'acquisition_sample_ids': samples, 'method_version_id': version,
               'calculation_profile': 'modern_v1', 'slow_mode': False}
    original = client.post('/api/v1/analyses/runs', headers=headers, json=payload).json()
    renamed_response = client.post('/api/v1/analyses/runs', headers=headers, json={**payload, 'sample_names': ['编号甲', '编号乙']})
    assert renamed_response.status_code == 201, renamed_response.text
    renamed = renamed_response.json()
    assert [sample['sample_name'] for sample in renamed['samples']] == ['编号甲', '编号乙']
    assert renamed['input_sha256'] != original['input_sha256']
    assert client.get(f"/api/v1/analyses/runs/{original['id']}", headers=headers).json() == original
    acquisition = runtime.acquisition_service()
    assert acquisition.spectrum_snapshot(samples[0])['sample']['sample_name'] == 'S16-A'
    assert acquisition.spectrum_snapshot(samples[1])['sample']['sample_name'] == 'S16-B'
    assert client.post(f"/api/v1/analyses/runs/{renamed['id']}/start", headers=headers).status_code == 200
    for _ in range(30):
        done = client.post(f"/api/v1/analyses/runs/{renamed['id']}/step", headers=headers).json()
        if done['status'] == 'completed':
            break
    assert done['status'] == 'completed'
    cleared = client.post('/api/v1/analyses/runs', headers=headers, json={**payload, 'sample_names': ['', '']}).json()
    assert all(not sample['sample_name'] for sample in cleared['samples'])
    started = client.post(f"/api/v1/analyses/runs/{cleared['id']}/start", headers=headers)
    assert started.status_code == 422
    assert started.json()['detail']['code'] == 'analysis_sample_names_required'
    assert client.get(f"/api/v1/analyses/runs/{renamed['id']}", headers=headers).json() == done
    for names in [['仅一条'], ['a' * 21, '有效编号']]:
        invalid = client.post('/api/v1/analyses/runs', headers=headers, json={**payload, 'sample_names': names})
        assert invalid.status_code == 422


def test_analysis_numbering_assigns_consecutive_bands_and_round_trips_sam(method_client):
    client, runtime, headers = method_client
    version, samples = _seed(runtime.database, complete_conditions=True)
    url = '/api/v1/analyses/runs'
    payload = {'name': '谱带编号', 'acquisition_sample_ids': samples, 'method_version_id': version,
               'calculation_profile': 'modern_v1', 'slow_mode': False}
    overflow = client.post(url, headers=headers, json={**payload, 'sample_numbering': [{'name': '甲', 'repeats': 3}]})
    assert overflow.status_code == 422
    assert overflow.json()['detail']['code'] == 'analysis_sample_numbering_capacity'
    entries = [{'name': '001', 'repeats': 2}]
    files = '/api/v1/analyses/sample-numbers'
    exported = client.post(files + '/write', headers=headers, json={'entries': entries})
    assert exported.status_code == 200, exported.text
    opened = client.post(files + '/read', headers=headers,
                         json={'content_base64': base64.b64encode(exported.content).decode('ascii')})
    assert opened.status_code == 200, opened.text
    assert opened.json()['entries'] == entries
    response = client.post(url, headers=headers, json={**payload, 'sample_numbering': entries})
    assert response.status_code == 201, response.text
    run = response.json()
    assert [item['sample_name'] for item in run['samples']] == ['001', '001']
    assert [item['acquisition_sample_id'] for item in run['samples']] == samples
    run_url = f"{url}/{run['id']}"
    assert client.post(run_url + '/start', headers=headers).status_code == 200
    for _ in range(30):
        if client.post(run_url + '/step', headers=headers).json()['status'] == 'completed':
            break
    quality = client.post(run_url + '/quality/recalculate', headers=headers)
    assert quality.status_code == 200, quality.text
    groups = quality.json()['quality']['latest_snapshot']['groups']
    assert groups and all(group['sample_group_position'] == 0 and len(group['members']) == 2 for group in groups)

    skip = [{'name': '', 'repeats': 0}, {'name': '乙', 'repeats': 1}]
    result = client.post(url, headers=headers, json={**payload, 'sample_numbering': skip})
    assert result.status_code == 201, result.text
    assert [item['acquisition_sample_id'] for item in result.json()['samples']] == samples[1:]
    assert result.json()['input_snapshot']['sample_numbering']['source_sample_ids'] == samples


def test_analysis_numbering_workbook_round_trips_with_prerecord_queue(method_client):
    client, runtime, headers = method_client
    queues = '/api/v1/sample-queues'
    files = '/api/v1/analyses/sample-numbers'
    entries = [{'name': '0007', 'repeats': 2}, {'name': '', 'repeats': 0}, {'name': '=A+1', 'repeats': 1}]
    queue = client.post(queues, headers=headers, json={'name': '互读样号', 'name_length': 20, 'items': [
        {'pre_name': item['name'], 'repeats': item['repeats']} for item in entries
    ]})
    assert queue.status_code == 201, queue.text
    queue_id = queue.json()['id']
    prerecord = client.get(f'{queues}/{queue_id}/export?format=xlsx', headers=headers)
    assert prerecord.is_success, prerecord.text

    def read_workbook(content):
        return client.post(files + '/read', headers=headers, json={
            'format': 'xlsx', 'content_base64': base64.b64encode(content).decode('ascii'),
        })

    opened = read_workbook(prerecord.content)
    assert opened.status_code == 200, opened.text
    assert opened.json()['entries'] == entries
    exported = client.post(files + '/write', headers=headers, json={'format': 'xlsx', 'entries': entries})
    assert exported.is_success, exported.text
    assert exported.headers['content-type'].endswith('spreadsheetml.sheet')
    assert read_workbook(exported.content).json()['entries'] == entries
    from_queue = client.post(queues + '/import', headers=headers, json={
        'filename': '分析名单.xlsx', 'content_base64': base64.b64encode(exported.content).decode('ascii'),
    })
    assert from_queue.status_code == 201, from_queue.text
    assert [(row['pre_name'], row['repeats']) for row in from_queue.json()['items']] == [
        (item['name'], item['repeats']) for item in entries
    ]

    from backend.modules.sample_workbook import write_sample_workbook
    bad = read_workbook(write_sample_workbook([{'name': '有效样号', 'repeats': 0}]))
    assert bad.status_code == 422
    assert bad.json()['detail']['code'] == 'analysis_sample_numbering_invalid'
    assert bad.json()['detail']['details']['position'] == 1
    named_standard = [{'name': 'SA', 'repeats': 1}]
    exported_exact = client.post(files + '/write', headers=headers, json={'format': 'xlsx', 'entries': named_standard})
    assert read_workbook(exported_exact.content).json()['entries'] == named_standard
    with runtime.database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='analysis.sample_numbers.xlsx_export'").fetchone()[0] == 2
