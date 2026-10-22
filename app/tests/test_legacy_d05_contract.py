"""D05 source rules and confirmed turn → spectrum → curve → report integration."""
import json
from pathlib import Path

import pytest

from backend.db import Database
from backend.modules.dispersion import DispersionService, DispersionError
from tests.test_methods import method_client, _create, _publish


def test_current_measured_positions_legacy_limit_and_stale_publish(tmp_path):
    database=Database(tmp_path/'d05.sqlite3');database.initialize()
    service=DispersionService(database)
    task=service.create_task({'lines':[{'element':str(i),'wavelength_nm':250+i*10,'ccd_index':0,'actual_position':p}
                                      for i,p in enumerate([100,200,300,420])]})
    assert task['residual_limit_points']==pytest.approx(150/14)
    line=task['lines'][0]
    service.save_line_position(task['id'],line['id'])
    original=service.fit_calibration(task['id'],{'degree':2})
    assert 2 < original['residual_max'] < task['residual_limit_points']
    service.move_line(task['id'],line['id'],'long',10)
    with pytest.raises(DispersionError) as stale:service.publish_calibration(original['id'])
    assert stale.value.code=='calibration_inputs_changed'
    moved=service.fit_calibration(task['id'],{'degree':2})
    assert moved['coefficients']!=original['coefficients']
    assert next(r for r in moved['residuals'] if r['line_id']==line['id'])['measured_position']==110
    assert service.get_task(task['id'])['lines'][0]['saved_position']==100
    published=service.publish_calibration(moved['id'])
    frozen=published['coefficients']
    service.restore_line_position(task['id'],line['id'])
    assert service.calibration(published['id'])['coefficients']==frozen
    assert service.get_task(task['id'])['calibrations'][-1]['inputs_current']
    boundary=service.fit_calibration(task['id'],{'degree':2,'residual_limit_points':original['residual_max']})
    assert not boundary['publishable']
    with pytest.raises(DispersionError) as exceeded:service.publish_calibration(boundary['id'])
    assert exceeded.value.code=='calibration_residual_exceeded'
    legacy_task=service.create_task({'residual_limit_points':2,'lines':[
        {'element':str(i),'wavelength_nm':250+i*10,'ccd_index':0,'actual_position':p}
        for i,p in enumerate([100,200,300,420])]})
    assert not service.fit_calibration(legacy_task['id'],{'degree':2})['publishable']
    restored=service.fit_calibration(legacy_task['id'],{'degree':2,'use_legacy_limit':True})
    assert restored['publishable'] and restored['residual_limit_points']==pytest.approx(150/14)


def _method(client,headers,runtime):
    method=_create(client,headers,'转角结果全链验证')
    line=json.loads((Path(__file__).parent/'fixtures/station17-line.json').read_text(encoding='utf-8'))
    with runtime.database.read() as db:
        geometry=runtime.methods_service().bind_geometry(db,{'ccd_layout_id':'default','dispersion_calibration_id':'default'})
        line['wavelength_nm']=line['actual_wavelength_nm']=geometry.wavelength_at(0,1024)
    assert client.post(f"/api/v1/methods/{method['id']}/lines",headers=headers,json=line).status_code==201
    assert client.patch(f"/api/v1/methods/{method['id']}",headers=headers,json={'conditions':{
        'frame_count':3,'dark_frame_count':0,'angle_exposures':[
            {'angle_deg':10,'start_frame':2,'end_frame':3,'storage_mode':'full_interval'},
            {'angle_deg':20,'start_frame':2,'end_frame':3,'storage_mode':'averaged'},
            {'angle_deg':30,'start_frame':2,'end_frame':3,'storage_mode':'full_interval'}]}}).status_code==200
    return _publish(client,headers,method['id'])


def _capture(runtime,method,name='T1',factor=1):
    hardware=runtime.hardware_acquisition_service()
    task=hardware.create_task({'method_id':method['id'],'method_version':method['current_version'],'sample_name':name})
    task=hardware.start(task['id'])
    adapter=hardware._adapters[task['id']]
    original=adapter.capture
    # Golden ADC inputs enter before capture/confirmation, never during adaptation.
    def capture(**kwargs):
        event=original(**kwargs)
        for ccd in event.get('ccds',[]):ccd['points']=[round(v*factor) for v in ccd['points']]
        event['details']={'source':'golden-turn-frame-fixture'}
        return event
    adapter.capture=capture
    for _ in range(100):
        if task['status']=='completed':break
        task=hardware.step(task['id'])
    assert task['status']=='completed',task
    return task


def test_confirmed_turn_samples_reach_analysis_curves_and_report(method_client):
    client,runtime,headers=method_client;method=_method(client,headers,runtime)
    method_hash=runtime.methods_service().get(method['id'])['published_version']['content_sha256']
    samples=[]
    for index in range(5):
        name=f'S{index+1}' if index<4 else 'T1'
        task=_capture(runtime,method,name,(index+1)/4 if index<4 else .625)
        url=f"/api/v1/hardware-acquisitions/tasks/{task['id']}/analysis-sample"
        payload={'sample_name':name,'sample_kind':'standard' if index<4 else 'test','name_length':12}
        saved=client.post(url,headers=headers,json=payload)
        assert saved.status_code==200,saved.text
        record=saved.json();samples.append(record['acquisition_sample_id'])
        again=client.post(url,headers=headers,json=payload).json()
        assert again['already_saved'] and again['acquisition_sample_id']==samples[-1]
        with runtime.database.read() as db:
            hardware=db.execute('SELECT ccd_index,mean_blob,mean_sha256 FROM hardware_exposure_results WHERE task_id=? ORDER BY ccd_index',(task['id'],)).fetchall()
            formal=db.execute('SELECT ccd_index,mean_blob,mean_sha256,burn_frame_count FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index',(samples[-1],)).fetchall()
            assert [(r['ccd_index'],bytes(r['mean_blob']),r['mean_sha256']) for r in hardware]==[(r['ccd_index'],bytes(r['mean_blob']),r['mean_sha256']) for r in formal]
            assert all(r['burn_frame_count']==2 for r in formal)
            stored=db.execute('SELECT simulator_json FROM acquisition_tasks WHERE id=?',(record['acquisition_task_id'],)).fetchone()[0]
            metadata=json.loads(stored)
            assert metadata['method_content_sha256']==method_hash and metadata['confirmed_exposures']
    assert len(runtime.analysis_service().options()['samples'])==5
    assert len(runtime.spectrum_viewer_service().list())==5
    service=runtime.analysis_service();run=service.create_run({'acquisition_sample_ids':samples});run=service.start(run['id'])
    for _ in range(100):
        if run['status']!='running':break
        run=service.step(run['id'])
    assert run['status']=='completed',run
    run=service.build_quality(run['id'])
    for group in run['quality']['latest_snapshot']['groups']:
        if group['warnings']:run=service.decide_quality(run['id'],{'acquisition_task_id':group['acquisition_task_id'],'line_id':group['line_id'],'action':'accept','reason':'核对单次黄金帧'})
    line=run['curves']['lines'][0]['line_id']
    run=service.fit_standard_curve(run['id'],line,{})
    curve=run['curves']['lines'][0]['snapshots'][-1]
    run=service.publish_standard_curve(run['id'],line,curve['id'],'转角样品黄金结果验证')
    assert next(r for r in run['curves']['results'] if r['sample_name']=='T1')['calculated_value']==pytest.approx(2.5,abs=.01)
    run=service.merge_results(run['id'],'保存转角样品分析结果')
    reports=runtime.reports_service();report=reports.create({'analysis_run_ids':[run['id']]});reports.confirm(report['id'])
    assert 'T1' in reports.preview(report['id'])
    assert runtime.methods_service().get(method['id'])['published_version']['content_sha256']==method_hash


def test_turn_adaptation_incomplete_permission_and_audit_rollback(method_client,monkeypatch):
    client,runtime,headers=method_client;method=_method(client,headers,runtime)
    hardware=runtime.hardware_acquisition_service()
    draft=hardware.create_task({'method_id':method['id']})
    url=f"/api/v1/hardware-acquisitions/tasks/{draft['id']}/analysis-sample"
    assert client.post(url,json={'sample_name':'T1'}).status_code==401
    assert client.post(url,headers=headers,json={'sample_name':'T1'}).status_code==409
    task=_capture(runtime,method)
    from backend.schemas.auth import RoleCreate,UserCreate
    role=runtime.auth_service.create_role(RoleCreate(name='仅转角执行',permission_keys=['hardware-acquisition.execute']),1)
    runtime.auth_service.create_user(UserCreate(username='turn-only',password='turn-only-password',role_ids=[role['id']]),1)
    limited_token,_=runtime.auth_service.login('turn-only','turn-only-password')
    response=client.post(f"/api/v1/hardware-acquisitions/tasks/{task['id']}/analysis-sample",
                         headers={'Authorization':'Bearer '+limited_token},json={'sample_name':'T1'})
    assert response.status_code==403
    assert runtime.analysis_service().options()['samples']==[]
    def fail(*args,**kwargs):raise RuntimeError('audit failed')
    with monkeypatch.context() as patch:
        patch.setattr(hardware.repository,'_audit',fail)
        with pytest.raises(RuntimeError,match='audit failed'):
            hardware.save_analysis_sample(task['id'],{'sample_name':'T1'},1)
    assert runtime.analysis_service().options()['samples']==[]
    result=hardware.save_analysis_sample(task['id'],{'sample_name':'T1'},1)
    assert result['acquisition_sample_id'] and not result['already_saved']
    with runtime.database.read() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
