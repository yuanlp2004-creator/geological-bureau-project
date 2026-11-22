from pathlib import Path

import pytest

from backend.db import Database
from backend.modules.dispersion import DispersionError, DispersionService
from .test_s12_dispersion import dispersion_client
from .test_legacy_fourteen_closure import add_frame


def test_locate_has_stable_anchor_and_manual_relocation_resets_it(tmp_path):
    database = Database(tmp_path / 'stable.sqlite3'); database.initialize()
    service = DispersionService(database)
    task = service.create_task({'name': 'stable peak', 'ccd_indices': [0], 'dark_frame_count': 0})
    line = service.add_point(task['id'], 0, 100)
    points = [10] * task['layout']['points_per_ccd']
    points[120] = 500; points[140] = 1000
    add_frame(database, task['id'], 'burn', 0, points)
    first = service.locate_line(task['id'], line['id'])
    assert first['located_position'] == 120
    assert first['locate_anchor_position'] == 100
    for _ in range(3):
        assert service.locate_line(task['id'], line['id']) == first
    with database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='dispersion.line.locate'").fetchone()[0] == 1
    # Assigning a known wavelength and saving keep the search origin.
    service.update_line_wavelength(task['id'], line['id'], 250)
    service.save_line_position(task['id'], line['id'])
    assert service.locate_line(task['id'], line['id'])['located_position'] == 120
    service.set_line_position(task['id'], line['id'], 140)
    assert service.locate_line(task['id'], line['id'])['located_position'] == 140
    service.restore_line_position(task['id'], line['id'])
    assert service.get_task(task['id'])['lines'][0]['locate_anchor_position'] == 120
    service.move_line(task['id'], line['id'], 'long', 20)
    assert service.locate_line(task['id'], line['id'])['located_position'] == 140


@pytest.mark.parametrize('signal', ['flat', 'cancelled', 'slope', 'tied', 'plateau'])
def test_locate_rejects_missing_or_ambiguous_peak_without_changing_line(tmp_path, signal):
    database = Database(tmp_path / f'{signal}.sqlite3'); database.initialize()
    service = DispersionService(database)
    task = service.create_task({'name': signal, 'ccd_indices': [0], 'dark_frame_count': 1})
    line = service.add_point(task['id'], 0, 100)
    points = [10] * task['layout']['points_per_ccd']
    if signal == 'slope': points = list(range(len(points)))
    if signal == 'tied': points[90] = points[110] = 100
    if signal in {'cancelled', 'plateau'}: points[100:103] = [100, 100, 100]
    add_frame(database, task['id'], 'burn', 0, points)
    if signal == 'cancelled': add_frame(database, task['id'], 'dark', 0, points)
    if signal == 'plateau':
        located = service.locate_line(task['id'], line['id'])
        assert located['located_position'] == 101
        assert service.locate_line(task['id'], line['id']) == located
    else:
        for _ in range(3):
            result = service.locate_all(task['id'])
            assert not result['all_succeeded'] and result['located'] == []
            assert result['errors'][0]['code'] == 'dispersion_peak_not_found'
            assert service.get_task(task['id'])['lines'][0] == line


def test_v26_backfills_only_search_origin_and_rolls_back_on_failure(tmp_path, monkeypatch):
    from backend import db as database_module
    from backend.migrations import MIGRATIONS
    path = tmp_path / 'v25.sqlite3'
    with monkeypatch.context() as patch:
        patch.setattr(database_module, 'MIGRATIONS', tuple(step for step in MIGRATIONS if step[0] <= 25))
        patch.setattr(database_module, 'SCHEMA_VERSION', 25)
        Database(path).initialize()
    with Database(path).write() as db:
        db.execute("INSERT INTO dispersion_tasks(id,name,device_profile_id,ccd_layout_id,frame_count,ccd_indices_json,created_at,updated_at) VALUES(1,'old',1,1,1,'[0]','then','then')")
        db.execute("INSERT INTO dispersion_task_lines(task_id,element,wavelength_nm,ccd_index,expected_position,located_position,saved_position,created_at,updated_at) VALUES(1,'Fe',250,0,100,110,105,'then','then')")
        before = dict(db.execute('SELECT * FROM dispersion_task_lines').fetchone())
        dump = list(db.iterdump())
    def fail(db):
        MIGRATIONS[-1][2](db)
        raise RuntimeError('injected anchor failure')
    with monkeypatch.context() as patch:
        patch.setattr(database_module, 'MIGRATIONS', (*MIGRATIONS[:-1], (26, 'dispersion', fail)))
        with pytest.raises(RuntimeError, match='injected anchor failure'): Database(path).initialize()
    with Database(path).read() as db: assert list(db.iterdump()) == dump
    Database(path).initialize(); Database(path).initialize()
    with Database(path).read() as db:
        after = dict(db.execute('SELECT * FROM dispersion_task_lines').fetchone())
        assert after.pop('locate_anchor_position') == 110
        assert after == before
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_point_first_lines_preserve_positions_and_require_known_wavelengths(tmp_path: Path):
    database = Database(tmp_path / 'points.sqlite3')
    database.initialize()
    service = DispersionService(database)
    task = service.create_task({'name': 'point-buttons', 'ccd_indices': [0]})
    identifier = task['id']
    lines = [service.add_point(identifier, 0, point) for point in (100, 200, 300, 400)]
    assert [line['located_position'] for line in lines] == [100, 200, 300, 400]
    assert all(line['wavelength_nm'] == 0 and line['saved_position'] is None for line in lines)
    with pytest.raises(DispersionError, match='已有谱线'):
        service.add_point(identifier, 0, 100)
    for ccd, point in ((1, 100), (0, 2048), (0, -1)):
        with pytest.raises(DispersionError):
            service.add_point(identifier, ccd, point)
    with pytest.raises(DispersionError) as missing:
        service.fit_calibration(identifier, {'use_legacy_limit': True})
    assert missing.value.code == 'calibration_wavelength_missing'
    for line, wavelength in zip(lines, (250, 260, 270, 280)):
        updated = service.update_line_wavelength(identifier, line['id'], wavelength)
        assert updated['located_position'] == line['located_position']
    fit = service.fit_calibration(identifier, {'use_legacy_limit': True, 'degree': 2})
    assert fit['publishable'] and fit['point_count'] == 4
    line = lines[0]
    service.save_line_position(identifier, line['id'])
    assert service.move_line(identifier, line['id'], 'short', 1)['located_position'] == 99
    assert not service.get_task(identifier)['calibrations'][0]['publishable']
    assert service.restore_line_position(identifier, line['id'])['located_position'] == 100
    service.delete_line(identifier, line['id'])
    with pytest.raises(DispersionError) as insufficient:
        service.fit_calibration(identifier, {'use_legacy_limit': True})
    assert insufficient.value.code == 'calibration_points_insufficient'
    assert len(service.get_task(identifier)['lines']) == 3
    with database.read() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='dispersion.line.create'").fetchone()[0] == 4


def test_point_creation_rejects_active_and_preheat_tasks(tmp_path: Path):
    database = Database(tmp_path / 'busy.sqlite3')
    database.initialize()
    service = DispersionService(database)
    task = service.create_task({'name': 'busy'})
    with database.write() as db:
        db.execute("UPDATE dispersion_tasks SET status='burn' WHERE id=?", (task['id'],))
    with pytest.raises(DispersionError) as busy:
        service.add_point(task['id'], 0, 100)
    assert busy.value.code == 'dispersion_task_busy'
    with database.write() as db:
        db.execute("UPDATE dispersion_tasks SET status='completed',condition_json=? WHERE id=?", ('{"preheat":true}', task['id']))
    with pytest.raises(DispersionError) as preheat:
        service.add_point(task['id'], 0, 100)
    assert preheat.value.code == 'preheat_not_calibration_source'


def test_point_api_authentication_integer_contract_and_coordinate(dispersion_client):
    client, runtime, headers = dispersion_client
    task = runtime.dispersion_service().create_task({'name': 'API points', 'ccd_indices': [0]})
    url = f"/api/v1/dispersion/tasks/{task['id']}/line-points"
    assert client.post(url, json={'ccd_index': 0, 'point_index': 100}).status_code == 401
    assert client.post(url, headers=headers, json={'ccd_index': 0, 'point_index': 100.5}).status_code == 422
    response = client.post(url, headers=headers, json={'ccd_index': 0, 'point_index': 100})
    assert response.status_code == 201
    assert response.json()['located_position'] == 100
    assert response.json()['wavelength_nm'] == 0
    assert client.post(url, headers=headers, json={'ccd_index': 0, 'point_index': 100}).status_code == 409
    assert client.post(url, headers=headers, json={'ccd_index': 1, 'point_index': 100}).status_code == 422
    coordinate = client.get(f"/api/v1/dispersion/tasks/{task['id']}/coordinate?wavelength_nm=253.65", headers=headers)
    assert coordinate.status_code == 200
    assert coordinate.json()['ccd_index'] == 0
    assert isinstance(coordinate.json()['point_index'], int)
