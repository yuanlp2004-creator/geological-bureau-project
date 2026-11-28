"""Continuous captures use real orchestration and isolated instrument boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

_serial_tests = runpy.run_path(str(Path(__file__).with_name('test_legacy_serial_acquisition.py')))
Wire, serial_profile, transfer, wait_for, wire_factory = (_serial_tests[key] for key in
    ('Wire', 'serial_profile', 'transfer', 'wait_for', 'wire_factory'))
seed = runpy.run_path(str(Path(__file__).with_name('test_sample_turn_integration.py')))['seed']
from backend.db import utc_now
from backend.config import AppConfig
from backend.runtime import Runtime
from backend.modules.acquisition import AcquisitionError, AcquisitionService
from backend.modules.devices import DeviceError
from backend.modules.devices import motor_turn
from backend.modules.devices.service import DeviceService
from backend.modules.devices.values import AcquisitionState, DeviceEvent
from backend.modules.dispersion import DispersionService


def add_operator(database):
    with database.write() as db:
        db.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES(1,'capture-test','fixture',?,?)",
                   (utc_now(), utc_now()))


def preliminary(database, kind, profile_id=1, *, group=None, angles=(17, 4), service=None):
    if service is None:
        service = DispersionService(database) if kind == 'dispersion' else AcquisitionService(database)
    group = group or uuid.uuid4().hex
    tasks = []
    for index, angle in enumerate(angles):
        turn = {'group': group, 'turn_index': index, 'angle_deg': angle, 'multiple': len(angles) > 1,
                'reference_coefficients': [1, 2, 3]}
        common = dict(name=f'{kind}-{group}', device_profile_id=profile_id, pre_excitation_seconds=0,
                      ccd_indices=[0], sampling_period_seconds=1, dark_frame_count=1)
        if kind == 'dispersion':
            tasks.append(service.create_task({**common, 'frame_count': 2}, capture_turn=turn))
        else:
            tasks.append(service.create_task({**common, 'sample_name': 'A01', 'task_kind': kind,
                                               'burn_frame_count': 2, 'storage_mode': 'full_interval'}, capture_turn=turn))
    return service, [task['id'] for task in tasks]


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_preliminary_whole_group_keeps_each_angles_frames(tmp_path, kind):
    database, _ = seed(tmp_path)
    add_operator(database)
    service, ids = preliminary(database, kind)
    # Starting from the second page still visits all pending angles in plan order.
    first = service.start_sequence(ids[1], 1)
    assert first['id'] == ids[0]
    wait_for(lambda: service.get_task(ids[1])['status'] == 'completed')
    assert [service.get_task(task)['status'] for task in ids] == ['completed', 'completed']
    assert all(len(service.frames(task)) == 3 for task in ids)

    service, ids = preliminary(database, kind)
    start = service.start_task if kind == 'dispersion' else service.start
    step = service.step_task if kind == 'dispersion' else service.step
    start(ids[1])
    for _ in range(8):
        if service.get_task(ids[1])['status'] == 'completed':
            break
        step(ids[1])
    assert [service.get_task(task)['status'] for task in ids] == ['draft', 'completed']


class FakeMotor:
    key = 'test-only-' + 'k' * 28

    def __init__(self):
        self.allow_arrival = threading.Event()
        self.arrived = threading.Event()
        self.moves = []
        self.operation = None
        self.stops = 0
        self.refreshes = 0
        self.drop_on_refresh = None
        self.stop_confirmed = True

    def reply(self, path, data):
        if path == 'status':
            return self.status()
        if path == 'move':
            self.arrived.clear()
            self.refreshes = 0
            self.moves.append(data['angle_deg'])
            self.operation = {'id': uuid.uuid4().hex, 'status': 'turning', 'correlation_id': data['correlation_id'],
                              'requested_angle_deg': data['angle_deg'], 'target_mms': str(int(data['angle_deg'] * 100))}
            return {'operation': self.operation}
        if path == 'operations/' + (self.operation or {}).get('id', ''):
            if self.allow_arrival.is_set():
                self.operation['status'] = 'completed'
            return {'operation': self.operation, 'worker_active': self.operation['status'] != 'completed'}
        if path == 'refresh':
            self.refreshes += 1
            if self.drop_on_refresh == self.refreshes:
                raise ConnectionError()
            self.arrived.set()
            return self.status()
        if path == 'stop':
            self.stops += 1
            return {'stop_confirmed': self.stop_confirmed}
        raise AssertionError(path)

    def status(self):
        position = (self.operation or {}).get('target_mms', '0')
        return {'profile': {'transport': 'serial', 'port': 'COM22', 'motion_verified': True, 'calibration_id': 'site-cal',
                            'min_angle_deg': -100, 'max_angle_deg': 100, 'move_timeout_s': 5},
                'state': 'idle', 'worker_active': False, 'simulated': False, 'reference_valid': True,
                'snapshot': {'position': position, 'position_set': position, 'velocity': 0, 'error_code': 0}}


@pytest.fixture
def motor_server(monkeypatch):
    motor = FakeMotor()

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            assert self.headers['Authorization'] == 'Bearer ' + motor.key
            assert self.path.startswith('/api/v1/motors/')
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            try:
                result = motor.reply(self.path.removeprefix('/api/v1/motors/'), json.loads(data) if data else None)
            except ConnectionError:
                self.close_connection = True
                return
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = handle_request

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(motor_turn, 'validate_bluetooth_binding',
                        lambda address, port: None if (address, port) == ('0123456789AB', 22) else pytest.fail('wrong SPP binding'))
    yield motor, server.server_port
    server.shutdown()
    server.server_close()
    thread.join()


def bind(database, profile, motor_server):
    motor, api_port = motor_server
    add_operator(database)
    (database.path.parent / 'motor-api.key').write_text(motor.key, encoding='utf-8')
    binding = motor_turn.MotorBinding(bluetooth_address='0123456789AB', motor_port=22, api_port=api_port,
                                      calibration_id='site-cal', angles=[
        {'method_angle_deg': 17, 'motor_angle_deg': 21},
        {'method_angle_deg': 4, 'motor_angle_deg': -11},
    ])
    motor_turn.save_motor_binding(database, profile, binding, 1)
    return motor


def test_dual_port_binding_is_profile_scoped_and_keeps_mercury_evidence(tmp_path, motor_server):
    database, _ = seed(tmp_path)
    profile = serial_profile(database)
    bind(database, profile, motor_server)
    binding = motor_turn.motor_binding(database, profile['id'])
    assert motor_turn.motor_binding(database, 1) is None
    evidence = motor_turn.MotorPositionEvidence(reference_source='现场记录', reference_file='reference.csv',
        observed_file='observation.csv', ccd_index=0, reference_angle_deg=16.8, reference_peak=201,
        observed_peak=203, target_angle_deg=17)
    angles = [binding.angles[0].model_copy(update={'evidence': evidence}), binding.angles[1]]
    with pytest.raises(DeviceError, match='两个不同'):
        motor_turn.save_motor_binding(database, profile, binding.model_copy(update={'motor_port': profile['port']}), 1)
    motor_turn.save_motor_binding(database, profile, binding.model_copy(update={'angles': angles}), 1)
    assert motor_turn.motor_binding(database, profile['id']).angles[0].evidence == evidence
    assert motor_turn.motor_binding(database, 1) is None
    with database.read() as db:
        row = db.execute("SELECT details_json FROM audit_events WHERE action='device.profile.update' ORDER BY id DESC LIMIT 1").fetchone()
    entry = json.loads(row['details_json'])['motor_binding']['angles'][0]['evidence']
    assert (entry['reference_peak'], entry['observed_peak']) == (201, 203)


def capture_payloads():
    return [transfer(100), transfer(300), transfer(65000), transfer(20)]


def test_debug_turn_confirms_motor_and_stop_interrupts_movement(tmp_path, motor_server, wire_factory):
    database, _ = seed(tmp_path)
    profile = serial_profile(database)
    motor = bind(database, profile, motor_server)
    wire = Wire([])
    wire_factory[0].append(wire)
    devices = DeviceService(database)
    devices.connect(profile['id'], 1)
    # Alignment before a working method is open uses the commissioned positions.
    assert devices.turn_state([])['angles'] == [17, 4]
    motor.allow_arrival.set()
    assert devices.switch_debug_angle(profile['id'], 17, [], 1)['current_angle_deg'] == 17
    assert motor.moves == [21] and motor.refreshes == 1 and not wire.writes
    # A completed CCD transfer can still belong to an exposure started in motion.
    def observe(started_at):
        frame = DeviceEvent("frame", AcquisitionState.DEBUGGING, ccds=[{"points": [22]}],
                            details={"exposure_started_at": started_at})
        devices.adapter._frames.put_nowait(frame)
        return devices.step_debug(1)["event"]
    stale = observe(0)
    assert stale["event_type"] == "waiting" and stale["ccds"] == []
    fresh = observe(time.monotonic())
    assert fresh["ccds"] == [{"points": [22]}] and fresh["details"]["angle_deg"] == 17
    with pytest.raises(DeviceError, match='未标定'):
        devices.switch_debug_angle(profile['id'], 9, [9], 1)
    assert devices.turn_state([])['current_angle_deg'] == 17

    motor.allow_arrival.clear()
    motor.stop_confirmed = False
    with ThreadPoolExecutor() as pool:
        move = pool.submit(devices.switch_debug_angle, profile['id'], 4, [], 1)
        wait_for(lambda: motor.moves == [21, -11])
        assert devices.turn_state([])['moving'] and devices.turn_state([])['current_angle_deg'] is None
        with pytest.raises(DeviceError, match='正在切换'):
            devices.release_for_capture(profile['id'], 1)
        with pytest.raises(DeviceError, match='未能确认电机停止'):
            devices.disconnect(1)
        with pytest.raises(DeviceError, match='未能确认电机停止'):
            move.result()
    with pytest.raises(DeviceError, match='请先停止设备'):
        devices.switch_debug_angle(profile['id'], 17, [], 1)
    motor.stop_confirmed = True
    assert devices.disconnect(1)['diagnostics']['connected'] is False
    assert wire.closed and not wire.writes


class CheckedWire(Wire):
    def __init__(self, motor, payloads):
        self.motor = motor
        super().__init__(payloads)

    def write(self, data):
        if bytes(data)[0] == 0xF0:
            assert self.motor.arrived.is_set(), "CCD activated before motor confirmation"
        return super().write(data)


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation'])
def test_single_angle_with_a_commissioned_motor_still_confirms_position(tmp_path, motor_server, wire_factory, kind):
    database, _ = seed(tmp_path)
    profile = serial_profile(database)
    motor = bind(database, profile, motor_server)
    motor.allow_arrival.set()
    service, [task] = preliminary(database, kind, profile['id'], angles=(17,))
    wire = CheckedWire(motor, capture_payloads())
    wire_factory[0].append(wire)
    start = service.start_task if kind == 'dispersion' else service.start
    assert service.get_task(task)['position_controlled'] is True
    start(task, 1)
    wait_for(lambda: service.get_task(task)['status'] in {'completed', 'failed'})
    assert service.get_task(task)['status'] == 'completed'
    assert motor.moves == [21]


@pytest.mark.parametrize('kind', ['dispersion', 'evaporation', 'sample'])
def test_real_workflows_capture_only_after_each_arrival(tmp_path, motor_server, wire_factory, kind):
    database, method = seed(tmp_path)
    profile = serial_profile(database)
    motor = bind(database, profile, motor_server)
    if kind == 'sample':
        with database.write() as db:
            row = db.execute('SELECT payload_json FROM method_versions WHERE method_id=? AND version=2', (method,)).fetchone()
            data = json.loads(row['payload_json'])
            data['conditions'].update(sampling_period_seconds=1, burn_cycle_seconds=1, dark_cycle_seconds=1)
            db.execute("INSERT INTO method_versions(method_id,version,state,payload_json,validation_errors_json,created_at) "
                       "VALUES (?,3,'published',?,'[]',?)", (method, json.dumps(data), utc_now()))
            db.execute('UPDATE methods SET current_version=3 WHERE id=?', (method,))
        service = AcquisitionService(database)
        task = service.create_task(dict(name='real sample', method_id=method, method_version=3, device_profile_id=profile['id']))
        ids = [task['id']]
        wires = [CheckedWire(motor, capture_payloads() * 2)]
        terminal = 'between_repeats'
    else:
        service, ids = preliminary(database, kind, profile['id'])
        wires = [CheckedWire(motor, capture_payloads()) for _ in range(2)]
        terminal = 'completed'
    wire_factory[0].extend(wires)
    service.start_sequence(ids[0], 1)
    wait_for(lambda: motor.moves == [21])
    assert not wires[0].writes
    motor.allow_arrival.set()
    wait_for(lambda: service.get_task(ids[-1])['status'] in {terminal, 'failed'})
    result = service.get_task(ids[-1])
    assert result['status'] == terminal, result.get('failure_message')
    assert motor.moves == [21, -11]
    assert all(wire.settings['port'] == f"COM{profile['port']}" for wire in wires)
    assert sum(command[0] == 0xF0 for wire in wires for command in wire.writes) == 2
    if kind == 'sample':
        assert result['completed_repeats'] == 1
        assert {item['turn_index'] for item in result['samples'][0]['bands']} == {0, 1}


@pytest.mark.parametrize('fault', ['stop', 'stop_unconfirmed', 'disconnect'])
def test_stop_or_disconnect_never_starts_next_angle(tmp_path, motor_server, wire_factory, fault):
    database, _ = seed(tmp_path)
    profile = serial_profile(database)
    motor = bind(database, profile, motor_server)
    service, ids = preliminary(database, 'evaporation', profile['id'])
    wire = CheckedWire(motor, capture_payloads())
    wire_factory[0].append(wire)
    if fault == 'disconnect':
        motor.drop_on_refresh = 2
        motor.allow_arrival.set()
    motor.stop_confirmed = fault != 'stop_unconfirmed'
    service.start_sequence(ids[0], 1)
    wait_for(lambda: motor.moves == [21])
    if fault.startswith('stop'):
        service.stop(ids[0], 1)
    wait_for(lambda: service.get_task(ids[0])['status'] in {'stopped', 'failed'})
    first = service.get_task(ids[0])
    assert first['status'] == ('stopped' if fault == 'stop' else 'failed')
    assert service.get_task(ids[1])['status'] == 'draft'
    assert motor.stops == 1
    assert not first['result_sha256']
    if fault == 'stop_unconfirmed':
        assert first['failure_code'] == 'motor_stop_unconfirmed'
        wait_for(lambda: service._sequence.current() is None)
        with pytest.raises(AcquisitionError) as blocked:
            service.start(ids[1], 1)
        assert blocked.value.code == 'device_busy'
        assert service._hardware.current().task_id == ids[0]
        motor.stop_confirmed = True
        assert service.stop(ids[0], 1)['stop_confirmed'] is True
        assert service._hardware.current() is None
    assert wire.writes == [] if fault.startswith('stop') else wire.writes[0][0] == 0xF0


def test_continuous_capture_waits_for_previous_port_close_and_keeps_ownership(tmp_path, motor_server, wire_factory):
    database, _ = seed(tmp_path)
    profile = serial_profile(database)
    motor = bind(database, profile, motor_server)
    runtime = Runtime(AppConfig(data_dir=tmp_path), database=database)
    service, ids = preliminary(database, 'dispersion', profile['id'], service=runtime.dispersion_service())
    closing, proceed = threading.Event(), threading.Event()

    class ClosingWire(CheckedWire):
        def close(self):
            closing.set()
            assert proceed.wait(8)
            super().close()

    first = ClosingWire(motor, capture_payloads())
    second = CheckedWire(motor, capture_payloads())
    wire_factory[0].extend((first, second))
    motor.allow_arrival.set()
    service.start_sequence(ids[0], 1)
    try:
        assert closing.wait(6)
        assert service.get_task(ids[0])['status'] == 'completed'
        assert service.get_task(ids[1])['status'] == 'draft'
        assert runtime.active_serial_captures()[0]['task_id'] == ids[0]
        with pytest.raises(DeviceError) as rejected:
            runtime.devices_service().connect(profile['id'])
        assert rejected.value.status_code == 409 and rejected.value.code == 'device_busy'
        assert wire_factory[1] == [first]
    finally:
        proceed.set()
        try:
            wait_for(lambda: second.closed and runtime.device_ownership.snapshot() is None)
        finally:
            runtime.shutdown()
    assert service.get_task(ids[1])['status'] == 'completed'
