"""The live editor must retain the selected line's physical turn association."""
import json

import pytest

from tests.test_methods import method_client
from tests.test_s16_analysis import _seed
from backend.db import utc_now


def bind_angles(runtime):
    method_id, _ = _seed(runtime.database, complete_conditions=True)
    with runtime.database.write() as db:
        payload = json.loads(db.execute('SELECT payload_json FROM method_versions WHERE method_id=? ORDER BY version LIMIT 1', (method_id,)).fetchone()[0])
        conditions = payload['conditions']
        groups = [['AL'], [line['id'] for line in payload['lines'] if line['id'] != 'AL']]
        conditions['angle_exposures'] = [dict(angle_deg=angle, ccd_indices=[0],
            dispersion_calibration_id=conditions['dispersion_calibration_id'], line_ids=names,
            storage_mode='averaged', start_frame=1, end_frame=conditions['frame_count'])
            for angle, names in zip([17, 4], groups)]
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,2,'published',?,'[]',?)",
            (method_id, json.dumps(payload), utc_now()))
        db.execute('UPDATE methods SET current_version=2 WHERE id=?', (method_id,))
    line = next(line for line in payload['lines'] if line['id'] == 'AL')
    return method_id, payload, dict(wavelength_nm=line['wavelength_nm'], actual_wavelength_nm=line['actual_wavelength_nm'], scan_width_points=line['scan_width_points'])


def test_editor_detect_endpoint_retains_saved_association_without_writes(method_client):
    client, runtime, headers = method_client
    method, _, request = bind_angles(runtime)
    url = f'/api/v1/methods/{method}/lines/detect'
    with runtime.database.read() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM method_versions ORDER BY id')]
    unbound = client.post(url, headers=headers, json=request)
    assert unbound.status_code == 200
    assert unbound.json()['reason_code'] == 'sample_line_turn_ambiguous'
    bound = client.post(url, headers=headers, json={**request, 'line_id': 'AL'})
    assert bound.status_code == 200, bound.text
    assert bound.json()['detectable'] and bound.json()['angle_deg'] == 17
    assert bound.json()['ccd_index'] == 0 and bound.json()['point_index'] == pytest.approx(600)
    # The same draft wavelength on a different existing line must retain that line's own association.
    other = client.post(url, headers=headers, json={**request, 'line_id': 'IS'})
    assert other.status_code == 200 and other.json()['angle_deg'] == 4
    assert client.post(url, headers=headers, json={**request, 'line_id': 'not-in-this-method'}).status_code == 404
    assert client.post(url, headers=headers, json={**request, 'line_id': ''}).status_code == 422
    assert client.post(url, json={**request, 'line_id': 'AL'}).status_code == 401
    with runtime.database.read() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM method_versions ORDER BY id')] == before


@pytest.mark.parametrize('problem,code', [('ambiguous', 'sample_line_turn_ambiguous'), ('missing', 'sample_line_turn_missing')])
def test_line_identity_never_bypasses_invalid_associations(method_client, problem, code):
    client, runtime, headers = method_client
    method, payload, request = bind_angles(runtime)
    if problem == 'ambiguous':
        payload['conditions']['angle_exposures'][1]['line_ids'].append('AL')
    else:
        payload['conditions']['angle_exposures'][0]['line_ids'] = ['IS']
    with runtime.database.write() as db:
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) VALUES (?,3,'published',?,'[]',?)",
            (method, json.dumps(payload), utc_now()))
    response = client.post(f'/api/v1/methods/{method}/lines/detect', headers=headers, json={**request, 'line_id': 'AL'})
    assert response.status_code == 200
    assert not response.json()['detectable'] and response.json()['reason_code'] == code
