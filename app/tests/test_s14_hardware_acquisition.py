from __future__ import annotations

import sqlite3
import json
import struct
import runpy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.db import Database
from backend.modules.hardware_acquisition import HardwareAcquisitionService, HardwareError


def _manual_method(database, *, multiple=False, sampling_period=1):
    from backend.db import utc_now
    seed = runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))
    version_id, _ = seed['_seed'](database, complete_conditions=True)
    with database.write() as db:
        source = db.execute('SELECT * FROM method_versions WHERE id=?', (version_id,)).fetchone()
        payload = json.loads(source['payload_json'])
        payload['conditions']['sampling_period_seconds'] = sampling_period
        payload['conditions']['angle_exposures'] = [
            {'angle_deg': 10, 'storage_mode': 'averaged', 'start_frame': 2, 'end_frame': 3}]
        if multiple:
            payload['conditions']['selected_ccds'] = [0, 2, 4]
            payload['conditions']['angle_exposures'] += [
                {'angle_deg': 20, 'storage_mode': 'full_interval', 'start_frame': 1, 'end_frame': 2},
                {'angle_deg': 30, 'storage_mode': 'averaged', 'start_frame': 3, 'end_frame': 4}]
        db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) "
                   "VALUES (?,2,'published',?,'[]',?)", (source['method_id'], json.dumps(payload), utc_now()))
        db.execute('UPDATE methods SET current_version=2 WHERE id=?', (source['method_id'],))
    return source['method_id']


def test_manual_method_turns_match_by_angle_after_reorder_and_repetition(tmp_path):
    database = Database(tmp_path/'manual-method-map.sqlite3')
    method_id = _manual_method(database, multiple=True)
    service = HardwareAcquisitionService(database, run_manual=False)
    automatic = service.create_task({'method_id': method_id, 'method_version': 2})
    payload = {'method_id': method_id, 'method_version': 2, 'execution_mode': 'manual',
               'manual_turns': [{'angle_deg': angle, 'duration_seconds': 5} for angle in [30, 10, 30]]}
    manual = service.create_task(payload)
    assert [item['angle_deg'] for item in manual['plan']] == [30, 10, 30]
    assert [item['method_turn_index'] for item in manual['plan']] == [2, 0, 2]
    assert manual['ccd_indices'] == [0, 4]
    keys = ['angle_deg', 'wavelength_nm', 'ccd_indices', 'storage_mode', 'start_frame', 'end_frame',
            'expected_baseline_position', 'expected_peak_position', 'baseline_ccd_index', 'peak_ccd_index',
            'method_content_sha256']
    for item in manual['plan']:
        match = next(row for row in automatic['plan'] if row['angle_deg'] == item['angle_deg'])
        assert {key: item[key] for key in keys} == {key: match[key] for key in keys}
    for extra, code in [
        ({'manual_turns': [{'angle_deg': 11, 'duration_seconds': 5}]}, 'hardware_manual_angle_mismatch'),
        ({'manual_turns': [{'angle_deg': 10, 'duration_seconds': 1}]}, 'hardware_manual_duration_too_short'),
        ({'turn_angles': [99]}, 'hardware_manual_config_invalid'),
    ]:
        before = len(service.list_tasks())
        with pytest.raises(HardwareError) as error:
            service.create_task({**payload, **extra})
        assert error.value.code == code and len(service.list_tasks()) == before


def test_manual_method_calculation_interval_snapshot_and_analysis_sample(tmp_path, monkeypatch):
    import math
    from backend.modules.hardware_acquisition.adapters import SimulatorTurnAdapter
    from backend.modules.methods import MethodService
    from backend.modules.analysis import AnalysisService
    database = Database(tmp_path/'manual-method-analysis.sqlite3')
    method_id = _manual_method(database, sampling_period=.1)
    original_capture = SimulatorTurnAdapter.capture
    frame_number = [0]
    def capture(adapter, **kwargs):
        event = original_capture(adapter, **kwargs)
        frame_number[0] += 1
        # Independent, non-flat analysis peaks; changing amplitudes reveal an incorrect averaging interval.
        for ccd in event.get('ccds', []):
            ccd['points'] = [value + round(sum(200 * frame_number[0] * math.exp(-((i-center)/3)**2)
                                                for center in (700, 900, 1100, 1300)))
                             for i,value in enumerate(ccd['points'])]
        return event
    monkeypatch.setattr(SimulatorTurnAdapter, 'capture', capture)
    service = HardwareAcquisitionService(database, run_manual=False)
    now = [0.0]; service._clock = lambda: now[0]
    with database.read() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM method_versions')]
    task = service.create_task({'method_id': method_id, 'method_version': 2, 'execution_mode': 'manual',
                               'sampling_period_seconds': .02,
                               'manual_turns': [{'angle_deg': 10, 'duration_seconds': .5}]})
    assert task['sampling_period_seconds'] == .1
    service.start(task['id'])
    for _ in range(20):
        now[0] += .1
        task = service.step(task['id'])
        if task['status'] == 'completed': break
    assert task['status'] == 'completed', task['last_message']
    assert any(row['baseline_monitored'] and row['peak_monitored'] for row in task['decisions'][-1]['observed'])
    exposure = task['exposures'][0]
    assert (exposure['start_frame'], exposure['end_frame']) == (2, 3)
    with database.read() as db:
        rows = db.execute('SELECT frame_index,points_blob FROM hardware_exposure_frames WHERE task_id=? ORDER BY frame_index', (task['id'],)).fetchall()
        assert len(rows) == 5  # Extra dwell frames are retained, but do not change the method interval.
        vectors = [struct.unpack('<2048H', row['points_blob']) for row in rows if row['frame_index'] in (2, 3)]
        expected = struct.pack('<2048f', *((a+b)/2 for a,b in zip(*vectors)))
        assert bytes(db.execute('SELECT mean_blob FROM hardware_exposure_results WHERE task_id=?', (task['id'],)).fetchone()[0]) == expected
    saved = service.save_analysis_sample(task['id'], {'sample_name': '手动方法样', 'sample_kind': 'test', 'name_length': 12})
    with database.read() as db:
        assert bytes(db.execute('SELECT mean_blob FROM acquisition_sample_bands WHERE sample_id=?', (saved['acquisition_sample_id'],)).fetchone()[0]) == expected
        assert [tuple(row) for row in db.execute('SELECT * FROM method_versions')] == before
    analysis = AnalysisService(database, methods=MethodService(database))
    run = analysis.create_run({'acquisition_sample_ids': [saved['acquisition_sample_id']]})
    assert run['method_id'] == method_id and run['method_version'] == 2
    assert run['calculation_profile'] == 'modern_v1'
    finished = runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))['_finish'](analysis, run)
    assert finished['status'] == 'completed'
    assert {row['line_id'] for row in finished['line_results']} >= {'A-none', 'A-background', 'A-gaussian'}


def test_manual_background_collection_and_shutdown_without_ui_steps(tmp_path):
    import time
    database=Database(tmp_path/'background.sqlite3');database.initialize()
    service=HardwareAcquisitionService(database)
    task=service.create_task({'execution_mode':'manual','sampling_period_seconds':.1,
        'manual_turns':[{'angle_deg':-5,'duration_seconds':.3}]})
    service.start(task['id'])
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        task=service.get_task(task['id'])
        if task['status']=='completed': break
        time.sleep(.05)
    assert task['status']=='completed' and min(row['end_frame'] for row in task['exposures'])>=3
    task=service.create_task({'execution_mode':'manual','manual_turns':[{'angle_deg':10,'duration_seconds':4}]})
    service.start(task['id']);service.shutdown()
    assert service.get_task(task['id'])['status']=='stopped'
    assert not service._adapters and not service._capture_clocks


def test_manual_turn_duration_order_pause_and_live_spectrum(tmp_path):
    from backend.schemas.hardware_acquisition import HardwareTaskCreate
    database = Database(tmp_path/'manual.sqlite3'); database.initialize()
    service = HardwareAcquisitionService(database, run_manual=False)
    now = [100.0]; service._clock = lambda: now[0]
    payload = HardwareTaskCreate(execution_mode='manual', sampling_period_seconds=.2,
        manual_turns=[{'angle_deg': angle, 'duration_seconds': duration} for angle, duration in [(20,.5),(-5,.3),(20,.1)]]).model_dump()
    task = service.create_task(payload)
    assert task['execution_mode'] == 'manual'
    assert [step['angle_deg'] for step in task['steps']] == [20,-5,20]
    assert all(step['wavelength_nm'] is None for step in task['steps'])
    service.start(task['id']); service.step(task['id']); task = service.step(task['id'])
    assert task['status'] == 'collecting'
    assert not service.step(task['id'])['frames']
    now[0] += .2; task = service.step(task['id'])
    assert task['status'] == 'collecting' and task['completed_steps'] == 0
    assert task['steps'][0]['captured_seconds'] == pytest.approx(.2)
    assert task['frames'] and not any(frame['confirmed'] for frame in task['frames'])
    assert service.frames(task['id'],include_points=True)[0]['points']
    service.pause(task['id']); now[0] += 30
    assert service.get_task(task['id'])['status'] == 'paused'
    service.resume(task['id']); task = service.step(task['id'])
    assert task['steps'][0]['captured_seconds'] == pytest.approx(.2)
    now[0] += .2; task = service.step(task['id'])
    assert task['completed_steps'] == 0
    now[0] += .1; task = service.step(task['id'])
    assert task['completed_steps'] == 1
    for duration in [.3,.1]:
        task = service.step(task['id'])
        remaining = duration
        while remaining > 1e-9:
            delta=min(.2,remaining); now[0] += delta; remaining -= delta
            task=service.step(task['id'])
    assert task['status'] == 'completed' and task['result_sha256']
    assert [row['payload']['angle_deg'] for row in task['traces'] if row['name']=='turn.request'] == [20,-5,20]
    assert all(row['confirmed'] for row in task['frames'])
    assert [step['captured_seconds'] for step in task['steps']] == [.5,.3,.1]
    assert sorted(set(row['end_frame'] for row in task['exposures'])) == [1,2,3]
    with database.read() as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT COUNT(*) FROM hardware_exposure_frames WHERE task_id=?',(task['id'],)).fetchone()[0] == 6*len(task['ccd_indices'])


def test_manual_stop_fault_and_incomplete_interval_cannot_be_accepted(tmp_path):
    database = Database(tmp_path/'manual-failure.sqlite3'); database.initialize()
    service = HardwareAcquisitionService(database, run_manual=False)
    now=[0.0]; service._clock=lambda:now[0]
    payload={'execution_mode':'manual','manual_turns':[{'angle_deg':30,'duration_seconds':3}]}
    task=service.create_task(payload); service.start(task['id']); service.step(task['id']); service.step(task['id'])
    now[0]=1; service.step(task['id']); stopped=service.stop(task['id'])
    assert stopped['status']=='stopped' and not any(row['confirmed'] for row in stopped['frames'])
    assert not stopped['exposures'] and task['id'] not in service._capture_clocks
    task=service.create_task({**payload,'retry_limit':0,'anomaly_policy':'manual',
        'simulator_anomalies':[{'step_index':0,'kind':'frame_fault','count':1}]})
    service.start(task['id']);service.step(task['id']);service.step(task['id']);now[0]+=1
    fault=service.step(task['id']); assert fault['status']=='manual_intervention'
    with pytest.raises(HardwareError,match='曝光区间未完成'):
        service.intervene(task['id'],'accept')
    service.intervene(task['id'],'retry'); service.step(task['id'])
    now[0]+=1; task=service.step(task['id'])
    assert task['status']=='collecting' and not task['completed_steps']
    service.stop(task['id'])


@pytest.mark.parametrize('extra',[
    {'manual_turns':[]}, {'manual_turns':[{'angle_deg':0,'duration_seconds':0}]},
    {'manual_turns':[{'angle_deg':361,'duration_seconds':2}]},
    {'manual_turns':[{'angle_deg':0,'duration_seconds':float('nan')}]},
    {'method_id':1}, {'turn_angles':[2]},
])
def test_manual_invalid_config_is_atomic(tmp_path,extra):
    database=Database(tmp_path/'manual-invalid.sqlite3');database.initialize()
    service=HardwareAcquisitionService(database)
    with pytest.raises(HardwareError):
        service.create_task({'execution_mode':'manual','manual_turns':[{'angle_deg':0,'duration_seconds':2}],**extra})
    assert not service.list_tasks()


def _advance(service: HardwareAcquisitionService, task_id: int, limit: int = 100) -> dict:
    task = service.get_task(task_id)
    for _ in range(limit):
        if task["status"] in {
            "completed",
            "failed",
            "stopped",
            "safety_stopped",
            "deferred_external",
            "manual_intervention",
        }:
            return task
        task = service.step(task_id)
    raise AssertionError(f"task did not settle: {task['status']}")


def test_s14_plan_ordering_duplicate_guard_and_simulator_completion(tmp_path: Path) -> None:
    database = Database(tmp_path / "hardware.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)

    task = service.create_task(
        {
            "name": "key-band order",
            "strategy": "key_first",
            "turns": [
                {"angle_deg": 30, "wavelength_nm": 310, "priority": 2, "key_band": False, 'storage_mode':'full_interval','end_frame':2},
                {"angle_deg": 10, "wavelength_nm": 250, "priority": 0, "key_band": True},
                {"angle_deg": 20, "wavelength_nm": 280, "priority": 8, "key_band": True},
            ],
        }
    )
    assert [(step["key_band"], step["priority"]) for step in task["steps"]] == [(True, 8), (True, 0), (False, 2)]

    with pytest.raises(HardwareError) as duplicate:
        service.create_task(
            {"turns": [{"angle_deg": 1, "wavelength_nm": 270}, {"angle_deg": 2, "wavelength_nm": 270.005}]}
        )
    assert duplicate.value.code == "turn_duplicate_wavelength"

    started = service.start(task["id"])
    assert started["status"] == "pre_excitation"
    completed = _advance(service, task["id"])
    assert completed["status"] == "completed"
    assert completed["completed_steps"] == 3
    assert completed["result_sha256"]
    assert len(completed["frames"]) == 15
    full = service.get_task(task['id'],include_points=True)['exposures']
    assert all(len(row['frames']) == 2 for row in full if row['storage_mode']=='full_interval')
    assert any(trace["name"] == "turn.request" for trace in completed["traces"])
    assert any(decision["decision"] == "accept" for decision in completed["decisions"])


def test_task_angles_override_method_positions_and_preserve_method_and_sample_saving(tmp_path):
    database = Database(tmp_path/'method-angles.sqlite3')
    method_id, _ = runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))['_seed'](database, complete_conditions=True)
    service = HardwareAcquisitionService(database)
    method = next(item for item in service.options()['methods'] if item['method_id']==method_id)
    with database.read() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM method_versions WHERE method_id=? ORDER BY id', (method_id,))]
    task = service.create_task({'method_id':method_id, 'method_version':method['version'], 'turn_angles':[42.5]})
    assert task['steps'][0]['angle_deg']==42.5
    assert task['plan'][0]['original_angle_deg']==method['turn_angles'][0]
    assert task['plan'][0]['ccd_indices']==task['ccd_indices']
    service.start(task['id']); done = _advance(service,task['id'])
    assert done['status']=='completed'
    requests = [row for row in done['traces'] if row['name']=='turn.request']
    assert requests[0]['payload']['angle_deg']==42.5
    saved = service.save_analysis_sample(task['id'],{'sample_name':'手改角度','sample_kind':'test','name_length':12})
    assert saved['acquisition_sample_id']>0
    with database.read() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM method_versions WHERE method_id=? ORDER BY id', (method_id,))]==before


def test_angle_options_preserve_legacy_methods_without_exposure_config(tmp_path):
    database=Database(tmp_path/'legacy-options.sqlite3')
    method_id,_=runpy.run_path(str(Path(__file__).with_name('test_s16_analysis.py')))['_seed'](database)
    method=next(row for row in HardwareAcquisitionService(database).options()['methods'] if row['method_id']==method_id)
    assert method['turn_angles']==[]


def test_task_angle_overrides_follow_source_slots_after_key_band_sort(tmp_path):
    database=Database(tmp_path/'sorted-angles.sqlite3');database.initialize();service=HardwareAcquisitionService(database)
    task=service.create_task({'strategy':'key_first','turns':[
        {'angle_deg':10,'wavelength_nm':250}, {'angle_deg':20,'wavelength_nm':280}, {'angle_deg':30,'wavelength_nm':310,'key_band':True}],
        'turn_angles':[11.25,-22.5,33.75]})
    assert [(row['source_index'],row['angle_deg']) for row in task['steps']]==[(2,33.75),(0,11.25),(1,-22.5)]
    assert [(row['source_index'],row['original_angle_deg']) for row in task['plan']]==[(2,30),(0,10),(1,20)]
    service.start(task['id']);done=_advance(service,task['id'])
    assert [row['payload']['angle_deg'] for row in done['traces'] if row['name']=='turn.request']==[33.75,11.25,-22.5]


@pytest.mark.parametrize('angles', [[],[1],[1,1,3],[0,float('nan'),3],[0,float('inf'),3],[0,361,3]])
def test_invalid_task_angle_override_is_rejected_before_task_creation(tmp_path,angles):
    database=Database(tmp_path/'invalid-angles.sqlite3');database.initialize();service=HardwareAcquisitionService(database)
    with pytest.raises(HardwareError):
        service.create_task({'turns':[{'angle_deg':10,'wavelength_nm':250},{'angle_deg':20,'wavelength_nm':280},{'angle_deg':30,'wavelength_nm':310}], 'turn_angles':angles})
    assert service.list_tasks()==[]


def test_s14_peak_correction_retry_and_retry_exhausted_safety_stop(tmp_path: Path) -> None:
    database = Database(tmp_path / "anomalies.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)

    corrected = service.create_task(
        {
            "name": "peak correction",
            "retry_limit": 1,
            "turns": [{"angle_deg": 5, "wavelength_nm": 280}],
            "simulator_anomalies": [{"step_index": 0, "kind": "peak_shift", "count": 1}],
        }
    )
    service.start(corrected["id"])
    first = service.step(corrected["id"])
    assert first["status"] == "turning"
    collecting = service.step(corrected["id"])
    assert collecting["status"] == "collecting"
    retried = service.step(corrected["id"])
    assert retried["status"] == "turning"
    assert retried["steps"][0]["correction_offset"] < 0
    assert retried["latest_decision"]["decision"] == "correct"
    assert _advance(service, corrected["id"])["status"] == "completed"

    stopped = service.create_task(
        {
            "name": "baseline stop",
            "retry_limit": 1,
            "turns": [{"angle_deg": 8, "wavelength_nm": 290}],
            "simulator_anomalies": [{"step_index": 0, "kind": "baseline_low", "count": 5}],
        }
    )
    service.start(stopped["id"])
    safety = _advance(service, stopped["id"])
    assert safety["status"] == "safety_stopped"
    assert safety["failure_code"] == "safety_stop"
    assert safety["frames"] and all(not frame["confirmed"] for frame in safety["frames"])
    assert any(trace["name"] == "safety.stop" for trace in safety["traces"])


@pytest.mark.parametrize(
    "kind", ["baseline_low", "baseline_high", "baseline_shift", "peak_shift", "frame_fault", "turn_timeout"]
)
def test_s14_each_anomaly_kind_is_detected_and_stopped(tmp_path: Path, kind: str) -> None:
    database = Database(tmp_path / f"{kind}.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task(
        {
            "name": kind,
            "retry_limit": 0,
            "turns": [{"angle_deg": 9, "wavelength_nm": 295}],
            "simulator_anomalies": [{"step_index": 0, "kind": kind, "count": 1}],
        }
    )
    service.start(task["id"])
    stopped = _advance(service, task["id"])
    assert stopped["status"] == "safety_stopped"
    assert kind in stopped["decisions"][-1]["anomaly_kind"]
    frames = stopped["frames"]
    assert frames and all(not frame["confirmed"] for frame in frames)
    assert all(bool(frame["damaged"]) == (kind in {"frame_fault", "turn_timeout"}) for frame in frames)


def test_s14_task_control_lock_rejects_overlapping_operation(tmp_path: Path) -> None:
    database = Database(tmp_path / "mutex.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({"name": "mutex", "turns": [{"angle_deg": 6, "wavelength_nm": 285}]})
    with service._control_scope(task["id"]):
        with pytest.raises(HardwareError) as busy:
            service.start(task["id"])
    assert busy.value.code == "hardware_task_busy"
    assert service.start(task["id"])["status"] == "pre_excitation"


def test_s14_manual_takeover_and_immutable_hardware_evidence(tmp_path: Path) -> None:
    database = Database(tmp_path / "manual.sqlite3")
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task(
        {
            "name": "manual review",
            "anomaly_policy": "manual",
            "retry_limit": 0,
            "turns": [{"angle_deg": 12, "wavelength_nm": 300}],
            "simulator_anomalies": [{"step_index": 0, "kind": "baseline_shift", "count": 1}],
        }
    )
    service.start(task["id"])
    manual = _advance(service, task["id"])
    assert manual["status"] == "manual_intervention"
    accepted = service.intervene(task["id"], "accept", "operator checked baseline")
    assert accepted["status"] == "completed"
    assert accepted["completed_steps"] == 1

    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE hardware_frames SET points_sha256='tampered' WHERE task_id=?", (task["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE hardware_traces SET payload_json='{}' WHERE task_id=?", (task["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("DELETE FROM hardware_frames WHERE task_id=?", (task["id"],))


def test_s14_serial_protocol_gate_is_deferred_without_command_bytes(tmp_path: Path) -> None:
    database = Database(tmp_path / "serial.sqlite3")
    database.initialize()
    with database.write() as db:
        db.execute("UPDATE device_profiles SET transport='serial', name='Serial external' WHERE id=1")
    service = HardwareAcquisitionService(database)
    task = service.create_task(
        {"name": "serial gate", "device_profile_id": 1, "turns": [{"angle_deg": 1, "wavelength_nm": 260}]}
    )
    deferred = service.start(task["id"])
    assert deferred["status"] == "deferred_external"
    assert deferred["failure_code"] == "hardware_protocol_unavailable"
    assert all(trace["kind"] != "command" for trace in deferred["traces"])
    assert "no command bytes" in deferred["messages"][-1]["message"]


def test_s14_api_permissions_and_simulator_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.config as config_module
    import backend.main as main_module

    test_config = config_module.AppConfig(data_dir=tmp_path)
    application = main_module.create_app(test_config)
    runtime = application.state.runtime
    with TestClient(application) as client:
        assert client.get("/api/v1/hardware-acquisitions/tasks").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}
            ).status_code
            == 201
        )
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()[
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/hardware-acquisitions/options", headers=headers).status_code == 200
        payload = {"name": "API hardware", "turns": [{"angle_deg": 1, "wavelength_nm": 260}]}
        created = client.post("/api/v1/hardware-acquisitions/tasks", headers=headers, json=payload)
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert (
            client.post(f"/api/v1/hardware-acquisitions/tasks/{task_id}/start", headers=headers).json()["status"]
            == "pre_excitation"
        )
        assert (
            client.post(f"/api/v1/hardware-acquisitions/tasks/{task_id}/step", headers=headers).json()["status"]
            == "turning"
        )
        capability = next(
            item
            for item in client.get("/api/v1/capabilities").json()["capabilities"]
            if item["key"] == "hardware-acquisition"
        )
        assert {"hardware-acquisition.read", "hardware-acquisition.write", "hardware-acquisition.execute"}.issubset(
            capability["permissions"]
        )
