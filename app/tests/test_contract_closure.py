"""合同四处软件缺口：真实点值、区间执行、管理样适配和输入追溯。"""

import copy
import hashlib
import json
import sqlite3
import struct
import pytest
from backend.db import Database
from backend.modules.acquisition import AcquisitionService
from backend.modules.analysis import AnalysisService, AnalysisError, fit_curve, evaluate_curve
from backend.modules.analysis.control_adaptation import adapt_control, signal_for_value
from backend.modules.hardware_acquisition import HardwareAcquisitionService, HardwareError
from backend.modules.hardware_acquisition.rules import _metrics, _thresholds
from backend.modules.methods import MethodService
from tests.test_methods import method_client, _create, _publish
from tests.test_contract_additions import complete
from tests.test_s14_hardware_acquisition import _advance
from tests.test_s16_analysis import _seed
from tests.test_s17_quality_curves import _seed_completed_run
from tests.contract_sync_support import checkpoint


# 基线和定位峰必须来自各自窗口，远处大峰和理想位置不能替代实测值。
def test_metrics_use_actual_windows_without_script():
    points = [0] * 2048
    points[256] = 800
    points[1060] = 3000
    points[1800] = 65000
    plan = {'order_index': 0, 'expected_peak_position': 1024, 'expected_baseline_position': 256}
    task = {'plan_json': json.dumps([plan]), 'thresholds_json': json.dumps(_thresholds({}))}
    _, observed, abnormal = _metrics(task, plan, {'points': points}, [])
    assert abnormal and observed['detected'] == ['peak_shift']
    assert observed['baseline_intensity'] == 800 and observed['baseline_position'] == 256
    assert observed['peak_position'] == 1060 and observed['raw_peak_value'] == 3000
    # 故障诊断字段不得伪造或改写点值观测。
    assert _metrics(task, plan, {'points': points}, ['baseline_high'])[1]['baseline_intensity'] == 800
    plan |= {'baseline_ccd_index': 0, 'peak_ccd_index': 1}
    task['plan_json'] = json.dumps([plan])
    _, observed, abnormal = _metrics(task, plan, {'ccd_index': 0, 'points': points}, [])
    assert not abnormal and not observed['peak_monitored']


# 区间外帧不能污染平均，保存模式只影响正式逐帧结果，不丢失原始证据。
@pytest.mark.parametrize('mode', ['averaged', 'full_interval'])
def test_turn_interval_uses_only_selected_frames(tmp_path, mode):
    database = Database(tmp_path / 'turn.sqlite3')
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({'ccd_indices': [0], 'turns': [{'angle_deg': 10, 'wavelength_nm': 280,
        'start_frame': 2, 'end_frame': 3, 'storage_mode': mode}]})
    service.start(task['id'])
    service.step(task['id'])
    service.step(task['id'])
    adapter = service._adapters[task['id']]
    counter = 0
    # 提供真实 uint16 窗口峰，首帧干扰和后两帧不同，验证边界及小数均值。
    def capture(**kwargs):
        nonlocal counter
        counter += 1
        points = [0] * 2048
        points[256], points[1024] = 1000, [8000, 3000, 3001][counter - 1]
        return {'event_type': 'frame', 'ccds': [{'ccd_index': 0, 'points': points}], 'details': {}}
    adapter.capture = capture
    service.step(task['id'])
    paused = service.pause(task['id'])
    assert paused['status'] == 'paused'
    service.resume(task['id'])
    assert service.step(task['id'])['status'] == 'collecting'
    assert service.step(task['id'])['status'] == 'completed'
    result = service.get_task(task['id'], include_points=True)['exposures'][0]
    assert result['confirmed'] and result['mean_points'][1024] == 3000.5
    assert result['start_frame'] == 2 and result['end_frame'] == 3
    assert len(result['frames']) == (2 if mode == 'full_interval' else 0)
    with database.read() as db:
        assert db.execute('SELECT COUNT(*) FROM hardware_exposure_frames').fetchone()[0] == 3
    with database.write() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute('DELETE FROM hardware_exposure_results')


# 从方法生成完整有序转角计划，样品正式谱带也执行同一分角度区间。
def test_method_intervals_feed_turn_and_sample_chains(method_client):
    client, runtime, headers = method_client
    method = _create(client, headers)
    conditions = {'frame_count': 4, 'dark_frame_count': 0, 'angle_exposures': [
        {'angle_deg': 10, 'start_frame': 2, 'end_frame': 3, 'storage_mode': 'averaged'},
        {'angle_deg': 20, 'start_frame': 3, 'end_frame': 4, 'storage_mode': 'full_interval'},
        {'angle_deg': 30, 'start_frame': 1, 'end_frame': 2, 'storage_mode': 'averaged'}]}
    assert client.patch(f"/api/v1/methods/{method['id']}", headers=headers,
                        json={'conditions': conditions}).status_code == 200
    method = _publish(client, headers, method['id'])
    hardware = runtime.hardware_acquisition_service()
    turns = hardware.create_task({'method_id': method['id'], 'method_version': method['current_version']})
    assert [(item['start_frame'], item['end_frame']) for item in turns['steps']] == [(2, 3), (3, 4), (1, 2)]
    hardware.start(turns['id'])
    assert _advance(hardware, turns['id'])['status'] == 'completed'
    assert {item['method_id'] for item in hardware.options()['methods']} == {method['id']}
    acquisition = runtime.acquisition_service()
    task = complete(acquisition, acquisition.create_task({'method_id': method['id'], 'use_method_intervals': True,
        'management_sample': True, 'sample_kind': 'test', 'sample_name': 'M1'}))
    sample = task['samples'][0]
    bands = acquisition.band(sample['id'], include_points=True)
    assert {item['ccd_index']: item['storage_mode'] for item in bands} == {0:'averaged', 1:'averaged', 2:'full_interval', 4:'averaged', 5:'averaged'}
    assert all(item['burn_frame_count'] == 2 for item in bands)
    frames = acquisition.frames(task['id'], include_points=True)
    for band in bands:
        exposure = conditions['angle_exposures'][band['ccd_index'] // 2]
        selected = [row for row in frames if row['ccd_index'] == band['ccd_index'] and row['phase'] == 'burn'
                    and exposure['start_frame'] - 1 <= row['frame_index'] < exposure['end_frame']]
        expected = sum(row['points'][100] for row in selected) / 2
        assert band['mean_points'][100] == expected
    with runtime.database.read() as db:
        assert task['id'] in acquisition.management_task_ids(db)


# 普通、对数和四种拟合的管理样倍率都应回算给定含量并保留原强度。
@pytest.mark.parametrize('mode', ['linear', 'quadratic', 'cubic', 'spline'])
@pytest.mark.parametrize('coordinate', ['normal', 'logarithmic'])
def test_management_adaptation_math(mode, coordinate):
    workspace = {'fit_mode': mode, 'coordinate_type': coordinate, 'points': [
        {'active': True, 'original_intensity': x, 'adjusted_intensity': x, 'standard_value': 2 * x}
        for x in (1., 2., 3., 4.)]}
    original = copy.deepcopy(workspace)
    group = {'acquisition_task_id': 1, 'sample_name': 'M1', 'statistics': {'mean': 5., 'effective_count': 2},
             'warnings': [], 'members': []}
    evidence = adapt_control(workspace, group, 5.)
    assert evidence['factor'] == pytest.approx(2., abs=1e-6)
    assert [point['original_intensity'] for point in workspace['points']] == [point['original_intensity'] for point in original['points']]
    fit = fit_curve([p['adjusted_intensity'] for p in workspace['points']], [p['standard_value'] for p in workspace['points']], mode, coordinate)
    assert evaluate_curve(fit, 5., coordinate) == pytest.approx(5., abs=1e-5)


# 非单调曲线、越界含量和未处理管理样质控不得自动适配。
def test_management_adaptation_refuses_ambiguous_or_unresolved():
    fit = {'kind': 'polynomial', 'coefficients': [0, 1, -1, 0], 'x': [0, .3, .7, 1]}
    with pytest.raises(AnalysisError, match='不单调'): signal_for_value(fit, .1, 'normal')
    fit = fit_curve([1,2,3,4], [2,4,6,8], 'linear')
    with pytest.raises(AnalysisError, match='超出'): signal_for_value(fit, 9, 'normal')
    with pytest.raises(AnalysisError, match='预警'):
        adapt_control({}, {'statistics': {'mean': 2, 'effective_count': 1}, 'warnings': [{}]}, 4)


# 通过实际工作区事务保存整组强度及不可变管理样证据，旧曲线仍可追溯。
def test_management_adaptation_service_persists_new_version(tmp_path):
    database = Database(tmp_path / 'management.sqlite3')
    run_id, _ = _seed_completed_run(database)
    with database.write() as db:
        task_id = db.execute("SELECT id FROM acquisition_tasks WHERE sample_name='N1'").fetchone()[0]
        db.execute('INSERT INTO acquisition_management_tasks VALUES (?,?)', (task_id, 'test'))
    service = AnalysisService(database, methods=MethodService(database))
    run = service.build_quality(run_id)
    for group in run['quality']['latest_snapshot']['groups']:
        if group['warnings']:
            service.decide_quality(run_id, {'acquisition_task_id': group['acquisition_task_id'], 'line_id': 'L1', 'action': 'accept', 'reason': '复核'})
    before = service.fit_standard_curve(run_id, 'L1', {})
    fingerprint = before['curves']['lines'][0]['snapshots'][0]['result_sha256']
    after = service.curve_action(run_id, 'L1', {'action': 'adapt_control', 'control_task_id': task_id,
                                               'control_value': 11., 'reason': '管理样给定值'})
    line = after['curves']['lines'][0]
    assert line['snapshots'][0]['result_sha256'] == fingerprint
    assert line['workspace']['points'][2]['adjusted_intensity'] == pytest.approx(2.5)
    assert line['control_adaptations'][0]['snapshot']['target_value'] == 11.
    fitted = service.fit_standard_curve(run_id, 'L1', {})
    latest = fitted['curves']['lines'][0]['snapshots'][-1]
    assert evaluate_curve(latest['fit'], 2.5) == pytest.approx(11., abs=1e-5)
    with database.write() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute('UPDATE analysis_control_adaptations SET snapshot_json=\'{}\'')


# 分析页读取完整点值，越界样品或被篡改固化谱带不能返回成功。
def test_analysis_full_spectrum_integrity_and_membership(tmp_path):
    database = Database(tmp_path / 'spectrum.sqlite3')
    version, samples = _seed(database)
    service = AnalysisService(database, methods=MethodService(database))
    run = service.create_run({'acquisition_sample_ids': samples, 'method_version_id': version})
    acquisition = AcquisitionService(database)
    spectrum = service.spectrum(run['id'], 0, acquisition)
    assert len(spectrum['bands'][0]['mean_points']) == 2048
    assert spectrum['bands'][0]['mean_points'][900] > 0
    with pytest.raises(AnalysisError): service.spectrum(run['id'], 999, acquisition)
    original = acquisition.spectrum_snapshot
    # 在公开读取边界模拟损坏点值，保留数据库及其触发器。
    def corrupted(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        snapshot['bands'][0]['mean_points'][100] += 1
        return snapshot
    acquisition.spectrum_snapshot = corrupted
    with pytest.raises(AnalysisError, match='哈希'): service.spectrum(run['id'], 0, acquisition)


# v14 升级的任意 SQL 失败必须原子回滚，成功后保留旧数据及全部历史迁移。
def test_v23_upgrade_failure_rolls_back(tmp_path, monkeypatch):
    import backend.migrations.v23_contract_closure as db_module
    database = Database(tmp_path / 'upgrade.sqlite3')
    checkpoint(database.path, 22)
    with database.read() as db:
        before = list(db.iterdump())
    sql = db_module.SQL
    monkeypatch.setattr(db_module, 'SQL', sql + '\nINVALID SQL;')
    with pytest.raises(sqlite3.OperationalError): database.initialize()
    with database.read() as db:
        assert list(db.iterdump()) == before
    monkeypatch.setattr(db_module, 'SQL', sql)
    database.initialize()
    with database.read() as db:
        assert int(db.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0]) == 23
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


# 区间中真实异常应立即重试，失败尝试的前缀不得混入新尝试均值。
def test_exposure_retry_restarts_interval_and_preserves_rejected_prefix(tmp_path):
    database = Database(tmp_path / 'retry.sqlite3')
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({'ccd_indices': [0], 'retry_limit': 1, 'turns': [
        {'angle_deg': 10, 'wavelength_nm': 280, 'start_frame': 2, 'end_frame': 3}]})
    service.start(task['id'])
    service.step(task['id'])
    service.step(task['id'])
    counter = 0
    # 首次给出真实偏移，后续完整重采，检测过程没有脚本指标注入。
    def capture(**kwargs):
        nonlocal counter
        counter += 1
        points = [0] * 2048
        points[256] = 1000
        points[1060 if counter == 1 else 1024] = 3000
        return {'event_type': 'frame', 'ccds': [{'ccd_index': 0, 'points': points}]}
    service._adapters[task['id']].capture = capture
    retry = service.step(task['id'])
    assert retry['status'] == 'turning' and retry['steps'][0]['correction_offset'] == -36
    done = _advance(service, task['id'])
    assert done['status'] == 'completed'
    with database.read() as db:
        assert [(row[0], row[1]) for row in db.execute('SELECT attempt,COUNT(*) FROM hardware_exposure_frames GROUP BY attempt')] == [(0,1),(1,3)]
    assert len(done['exposures']) == 1 and done['exposures'][0]['attempt'] == 1


# 真实缺失或长度错误的帧必须保持损坏状态，人工接受也不能绕过完整区间。
def test_invalid_frame_and_partial_exposure_cannot_be_manually_accepted(tmp_path):
    database = Database(tmp_path / 'missing.sqlite3')
    database.initialize()
    service = HardwareAcquisitionService(database)
    task = service.create_task({'ccd_indices': [0], 'anomaly_policy': 'manual', 'retry_limit': 0, 'turns': [
        {'angle_deg': 10, 'wavelength_nm': 280, 'start_frame': 2, 'end_frame': 3}]})
    service.start(task['id'])
    service.step(task['id'])
    service.step(task['id'])
    # 在适配器边界提供错误长度，保持服务正常执行失败路径。
    def capture(**kwargs):
        return {'event_type': 'frame', 'ccds': [{'ccd_index': 0, 'points': [1,2,3]}]}
    service._adapters[task['id']].capture = capture
    failed = service.step(task['id'])
    assert failed['status'] == 'manual_intervention'
    assert all(frame['damaged'] for frame in failed['frames'])
    with pytest.raises(HardwareError): service.intervene(task['id'], 'accept', '人工不能放行损坏帧')
    assert service.stop(task['id'])['status'] == 'stopped'


# 完整谱图接口遵守读取权限，管理样标记拒绝标准样而非静默改类。
def test_new_spectrum_route_and_management_validation(method_client):
    client, runtime, headers = method_client
    version, ids = _seed(runtime.database)
    run = runtime.analysis_service().create_run({'acquisition_sample_ids': ids, 'method_version_id': version})
    url = f"/api/v1/analyses/runs/{run['id']}/spectra/0"
    assert client.get(url).status_code == 401
    response = client.get(url, headers=headers)
    assert response.status_code == 200 and len(response.json()['bands'][0]['mean_points']) == 2048
    assert client.get(url.rsplit('/',1)[0] + '/99', headers=headers).status_code == 404
    response = client.post('/api/v1/acquisitions/tasks', headers=headers,
                           json={'sample_kind': 'standard', 'management_sample': True})
    assert response.status_code == 422
