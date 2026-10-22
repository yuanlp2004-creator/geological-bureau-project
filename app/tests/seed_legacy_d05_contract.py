"""Independent golden turn frames and dispersion points for browser/QA desktop."""
import json
import os
from pathlib import Path
import sys

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
directory=Path(sys.argv[1]).resolve();directory.mkdir(parents=True,exist_ok=True)
assert not (directory/'geospectrum.sqlite3').exists(), 'fresh data directory required'
os.environ['SPECTRUM_DATA_DIR']=str(directory)
from backend.config import AppConfig
from backend.main import create_app
from fastapi.testclient import TestClient
from tests.test_legacy_d05_contract import _method,_capture

application=create_app(AppConfig(data_dir=directory))
runtime=application.state.runtime
with TestClient(application) as client:
    assert client.post('/api/v1/auth/bootstrap',json={'username':'qa_admin','password':'QaTest-2026!'}).status_code==201
    token=client.post('/api/v1/auth/login',json={'username':'qa_admin','password':'QaTest-2026!'}).json()['access_token']
    headers={'Authorization':'Bearer '+token}
    method=_method(client,headers,runtime)
    runtime.methods_service().open(method['id'],1)
    standards=[]
    for index in range(4):
        task=_capture(runtime,method,f'S{index+1}',(index+1)/4)
        saved=runtime.hardware_acquisition_service().save_analysis_sample(task['id'],{'sample_name':f'S{index+1}','sample_kind':'standard'},1)
        standards.append(saved['acquisition_sample_id'])
    unknown=_capture(runtime,method,'T1',.625)
    dispersion=runtime.dispersion_service().create_task({'name':'旧版位置参与拟合验证','residual_limit_points':2,'lines':[
        {'element':str(i),'wavelength_nm':250+i*10,'ccd_index':0,'actual_position':value} for i,value in enumerate([100,200,300,420])]})
    first=dispersion['lines'][0]
    runtime.dispersion_service().save_line_position(dispersion['id'],first['id'],1)
    runtime.dispersion_service().fit_calibration(dispersion['id'],{'degree':2,'name':'旧版拟合闭环'},1)
    fixture={'method_id':method['id'],'method_version':method['current_version'],'hardware_task_id':unknown['id'],
             'standard_sample_ids':standards,'dispersion_task_id':dispersion['id'],'dispersion_line_id':first['id']}
    (directory/'d05-contract-fixture.json').write_text(json.dumps(fixture),encoding='utf-8')
    print(json.dumps(fixture))
