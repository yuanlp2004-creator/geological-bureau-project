import math

import pytest

from backend.db import Database
from backend.modules.dispersion import DispersionService, DispersionError
from .test_s12_dispersion import dispersion_client


def old_fit(waves, steps):
    """Independent transcription of FmWstc.CalWstc's scalar equations."""
    count = len(waves)
    x = [sum(w**power for w in waves) for power in range(1,5)]
    y0 = sum(steps)/count
    y1 = sum(w*s for w,s in zip(waves,steps))-x[0]*y0
    y2 = sum(w*w*s for w,s in zip(waves,steps))-x[1]*y0
    d,e = x[0]/count,x[1]/count
    xx,xy,yy = x[1]-x[0]*d,x[2]-x[0]*e,x[3]-x[1]*e
    determinant=xx*yy-xy*xy
    a=(xx*y2-xy*y1)/determinant;b=(yy*y1-xy*y2)/determinant
    return [a,b,y0-b*d-a*e]


def prepare(database):
    database.initialize();service=DispersionService(database)
    task=service.create_task({'name':'旧版色散对齐','ccd_indices':[0,1]})
    service.update_gap(task['id'],0,9800,legacy_limits=True)
    for i,(wave,ccd,point) in enumerate([(250,0,100),(255,0,601),(278,1,152),(280,1,352)]):
        service.add_line(task['id'],{'element':str(i),'wavelength_nm':wave,'ccd_index':ccd,'actual_position':point})
    return service,service.get_task(task['id'])


def test_six_columns_and_six_results_match_old_scalar_algorithm(tmp_path):
    service,task=prepare(Database(tmp_path/'old.sqlite3'))
    fit=service.fit_calibration(task['id'],{'degree':2,'use_legacy_limit':True})
    task=service.get_task(task['id']);view=task['calibrations'][0]['legacy_results']
    measured=[100,601,2900,3100];waves=[250,255,278,280]
    assert [line['measured_step'] for line in task['legacy_lines']]==measured
    coefficients=old_fit(waves,measured)
    assert fit['coefficients']==pytest.approx(coefficients,abs=1e-6)
    assert view['intercept']==pytest.approx(coefficients[2],abs=1e-6)
    assert view['linear_coefficient']==pytest.approx(coefficients[1],abs=1e-7)
    assert view['quadratic_coefficient']==pytest.approx(coefficients[0],abs=1e-9)
    expected_predictions=[sum(c*w**(2-i) for i,c in enumerate(coefficients)) for w in waves]
    assert [row['predicted_position'] for row in view['rows']]==pytest.approx(expected_predictions,abs=1e-6)
    assert [row['step_error'] for row in view['rows']]==pytest.approx([s-p for s,p in zip(measured,expected_predictions)],abs=1e-6)
    assert view['wave_per_step']==pytest.approx(sum((w-waves[0])/(s-measured[0]) for w,s in zip(waves[1:],measured[1:]))/3)
    assert view['wavelength_range']==[250,280]
    assert view['step_range']==pytest.approx([min(measured[0],expected_predictions[0]),max(measured[-1],expected_predictions[-1])],abs=1e-6)
    service.publish_calibration(fit['id'],name='旧版保存')
    snapshot=service.calibration(fit['id'])
    changed=service.update_gap(task['id'],0,9801,legacy_limits=True)
    assert changed['legacy_lines'][2]['measured_step']==pytest.approx(2900+1/14)
    assert not changed['calibrations'][0]['inputs_current']
    assert service.calibration(fit['id'])==snapshot
    with pytest.raises(DispersionError):service.update_gap(task['id'],0,9500,legacy_limits=True)


def test_save_name_and_all_positions_are_guarded_and_preserve_versions(dispersion_client):
    client,runtime,headers=dispersion_client
    service,task=prepare(runtime.database)
    fit=service.fit_calibration(task['id'],{'degree':2,'use_legacy_limit':True})
    url=f"/api/v1/dispersion/calibrations/{fit['id']}/save?name=LegacySaved"
    assert client.post(url).status_code==401
    role=client.post('/api/v1/roles',headers=headers,json={'name':'色散只读验证','permission_keys':['dispersion.read']})
    assert role.status_code==201,role.text
    user=client.post('/api/v1/users',headers=headers,json={'username':'legacy_curve_reader','password':'Readonly-curve-2026!','role_ids':[role.json()['id']]})
    assert user.status_code==201,user.text
    reader=client.post('/api/v1/auth/login',json={'username':'legacy_curve_reader','password':'Readonly-curve-2026!'}).json()['access_token']
    read_headers={'Authorization':f'Bearer {reader}'}
    assert client.get(f"/api/v1/dispersion/tasks/{task['id']}",headers=read_headers).status_code==200
    assert client.post(url,headers=read_headers).status_code==403
    assert client.post(f"/api/v1/dispersion/tasks/{task['id']}/positions/save",headers=read_headers).status_code==403
    saved=client.post(url,headers=headers);assert saved.status_code==200,saved.text
    assert saved.json()['state']=='published' and saved.json()['name']=='LegacySaved'
    assert client.post(url,headers=headers).json()==saved.json()
    original=service.calibration(fit['id'])
    positions=f"/api/v1/dispersion/tasks/{task['id']}/positions"
    assert client.post(positions+'/save',headers=headers).status_code==200
    identifier=task['lines'][0]['id'];service.move_line(task['id'],identifier,'long',1)
    restored=client.post(positions+'/restore',headers=headers)
    assert restored.status_code==200
    assert restored.json()['lines'][0]['located_position']==task['lines'][0]['located_position']
    second=service.fit_calibration(task['id'],{'name':'LegacySaved','degree':2,'use_legacy_limit':True})
    next_saved=service.publish_calibration(second['id'])
    assert next_saved['version']>original['version']
    assert service.calibration(fit['id'])==original
    service.move_line(task['id'],identifier,'long',1)
    stale=service.fit_calibration(task['id'],{'use_legacy_limit':True})
    service.move_line(task['id'],identifier,'long',1)
    response=client.post(f"/api/v1/dispersion/calibrations/{stale['id']}/save?name=Stale",headers=headers)
    assert response.status_code==409
    assert service.calibration(stale['id'])['state']=='draft'


def test_old_wavelength_bounds_search_width_and_nominal_gap(dispersion_client):
    from .test_legacy_fourteen_closure import add_frame
    from backend.modules.legacy_migration.configuration import _typed_opt
    assert _typed_opt({'CCD':{'CcdGap':'9820'}})['ccd']['nominal_gap_um']==9820
    client,runtime,headers=dispersion_client
    service=runtime.dispersion_service()
    task=service.create_task({'name':'旧版边界','ccd_indices':[0],'dark_frame_count':0})
    line=service.add_point(task['id'],0,100)
    base=f"/api/v1/dispersion/tasks/{task['id']}"
    wavelength=f"{base}/lines/{line['id']}/wavelength?legacy_input=true&wavelength_nm="
    for value in [160,350,800]:assert client.patch(wavelength+str(value),headers=headers).status_code==200
    for value in [159,801]:assert client.patch(wavelength+str(value),headers=headers).status_code==422
    values=[10]*task['layout']['points_per_ccd'];values[102]=100;values[120]=1000
    add_frame(runtime.database,task['id'],'burn',0,values)
    located=client.post(f"{base}/lines/{line['id']}/locate?legacy_window=true",headers=headers)
    assert located.status_code==200,located.text
    assert located.json()['located_position']==102
    for _ in range(3):assert client.post(f"{base}/lines/{line['id']}/locate?legacy_window=true",headers=headers).json()==located.json()
    assert client.patch('/api/v1/settings',headers=headers,json={'analysis':{'dispersion_nominal_gap_um':9800,'dispersion_allow_gap_error_um':100}}).status_code==200
    assert client.get('/api/v1/dispersion/options',headers=headers).json()['gap_limits_um']==[9700,9900]


def test_point_details_outputs_use_the_same_verified_rows(dispersion_client):
    from base64 import b64decode
    from struct import unpack_from
    from .test_legacy_fourteen_closure import add_frame

    client, runtime, headers = dispersion_client
    task = runtime.dispersion_service().create_task({'name': '分时明细', 'ccd_indices': [0],
        'frame_count': 2, 'dark_frame_count': 1, 'sampling_period_seconds': 2})
    url = f"/api/v1/dispersion/tasks/{task['id']}/point-details"
    params = {'ccd': 0, 'point': 11}
    assert client.get(url, params=params, headers=headers).status_code == 409
    count = task['layout']['points_per_ccd']
    for phase, index, value in [('burn', 0, 321), ('burn', 1, 654), ('dark', 0, 87)]:
        points = [0] * count
        points[11] = value
        add_frame(runtime.database, task['id'], phase, index, points)
    response = client.get(url, params=params, headers=headers)
    assert response.is_success, response.text
    details = response.json()
    assert details['rows'] == [
        {'phase': 'burn', 'integration': 1, 'value': 321},
        {'phase': 'burn', 'integration': 2, 'value': 654},
        {'phase': 'dark', 'integration': 1, 'value': 87},
    ]
    assert details['burn_cycle_seconds'] == 2
    frames = client.get(url, params={**params, 'all_points': True}, headers=headers).json()
    raw = b64decode(frames['frames_base64'])
    assert frames['point_count'] == count
    assert [unpack_from('<H', raw, 2 * (i * count + 11))[0] for i in range(3)] == [321, 654, 87]
    for orientation in ['horizontal', 'vertical']:
        copied = client.post(url + '/copy', params={**params, 'orientation': orientation}, headers=headers)
        assert copied.is_success, copied.text
        assert copied.json()['sha256'] == details['sha256']
        assert '\t654' in copied.json()['text']
    printed = client.post(url + '/print', params=params, headers=headers)
    assert printed.is_success and printed.content.startswith(b'%PDF-')
    assert client.get(url, params={**params, 'point': count}, headers=headers).status_code == 422
    assert client.get(url, params=params, headers=headers).json() == details
