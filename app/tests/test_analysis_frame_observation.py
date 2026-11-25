from dataclasses import replace
import hashlib
import struct

import pytest

from .test_s12_dispersion import dispersion_client
from .test_s16_analysis import _seed


def test_committed_burn_frames_stay_observable_until_full_exposure_and_dark_are_ready(dispersion_client, monkeypatch):
    client, runtime, headers = dispersion_client
    standards = [{'name': f'S{index}', 'value': intensity / 10, 'adjusted_intensity': intensity,
                  'intensity_valid': True, 'active': True}
                 for index, intensity in enumerate((100, 300, 600, 900), start=1)]
    version_id, _ = _seed(runtime.database, copper_standards=standards)
    with runtime.database.read() as db:
        method_id = runtime.methods_service().bind_snapshots(db).by_id(version_id).method.id

    def known_frame(event, *, phase, frame_index, **_kwargs):
        points = [20 if phase == 'burn' else 2] * 2048
        if phase == 'burn':
            for point, peak in [(500, 1400), (600, 900), (700, 1300), (900, (600, 1000)[frame_index])]:
                points[point] = peak
        else:
            points[900] = 10
        return replace(event, ccds=[{**event.ccds[0], 'ccd_index': 0, 'points': points}])

    monkeypatch.setattr('backend.modules.acquisition.service._seeded_acquisition_event', known_frame)
    response = client.post('/api/v1/acquisitions/tasks', headers=headers, json={
        'name': '模拟双帧测量', 'method_id': method_id, 'method_version': 1, 'sample_name': 'QA-FRAME',
        'burn_frame_count': 2, 'dark_frame_count': 1, 'burn_cycle_seconds': 2, 'dark_cycle_seconds': 0.5,
        'storage_mode': 'full_interval', 'pre_excitation_seconds': 0,
    })
    assert response.is_success, response.text
    task_id = response.json()['id']
    base = f'/api/v1/acquisitions/tasks/{task_id}'

    def frame(index, *, authorized=True):
        return client.get(base + '/measurement-frame', headers=headers if authorized else {},
                          params={'repeat_index': 0, 'turn_index': 0, 'frame_index': index, 'ccd': 0})

    def copper(response):
        assert response.is_success, response.text
        return next(row for row in response.json()['rows'] if row['element'] == 'Cu')

    def step_to(burns, darks):
        for _ in range(6):
            state = client.post(base + '/step', headers=headers)
            assert state.is_success, state.text
            saved = state.json()
            if saved['burn_frames_captured'] == burns and saved['dark_frames_captured'] == darks:
                return saved
        raise AssertionError('模拟摄谱未达到指定帧数')

    assert frame(0, authorized=False).status_code == 401
    assert frame(0).status_code == 404
    started = client.post(base + '/start', headers=headers)
    assert started.is_success, started.text
    step_to(1, 0)
    first = frame(0)
    row = copper(first)
    assert row['raw_intensity'] == 600 and row['peak_found']
    assert row['concentration'] is None and row['code'] == 'analysis_frame_exposure_incomplete'
    assert first.json()['frame_sha256'] == hashlib.sha256(struct.pack('<2048H', *first.json()['points'])).hexdigest()
    assert frame(1).status_code == 404

    step_to(2, 0)
    second = frame(1)
    row = copper(second)
    assert row['raw_intensity'] == 1000 and row['code'] == 'analysis_frame_dark_pending'
    assert row['concentration'] is None
    assert any(row['diagnostic_code'] == 'analysis_frame_peak_missing' for row in second.json()['rows'])
    assert frame(0).json()['points'] == first.json()['points']

    final = step_to(2, 1)
    assert final['status'] == 'completed'
    row = copper(frame(1))
    assert row['raw_intensity'] == 1000 and row['code'] is None
    assert row['reference_interval'] == [1, 2]
    assert row['quantitative_signal'] == pytest.approx((800 / 2 - 10 / 0.5) - (20 / 2 - 2 / 0.5))
    assert row['concentration'] == pytest.approx(37.4)
    assert copper(frame(0))['code'] == 'analysis_frame_exposure_incomplete'
    with runtime.database.read() as db:
        assert not db.execute('SELECT 1 FROM analysis_runs').fetchone()
        assert not db.execute('SELECT 1 FROM analysis_curve_snapshots').fetchone()
