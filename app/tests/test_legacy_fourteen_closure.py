"""Source-backed F01–F14 closure: numerical/file/output contracts; gestures use browser QA."""
import base64
import hashlib
import io
import json
import re
import shutil
import struct
import zlib
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from backend.db import Database,utc_now
from backend.runtime import Runtime
from backend.config import AppConfig
from backend.main import create_app
from backend.services import AppService
from backend.schemas.system import SettingsPatch
from backend.modules.dispersion import DispersionService,DispersionError
from backend.modules.sample_queues import SampleQueueService,_parse_lines,SampleQueueError
from backend.modules.legacy_migration import LegacyMigrationService,LegacyMigrationError
from backend.modules.reports.rendering import _table,_pdf,_page_tables
from backend.modules.analysis.printing import CurvePrintingService
from tests.test_spec_gap_closure import _sample_chain
from tests.test_s19_reports import _seed
from tests.test_s09_result_migration import source_file


def fresh(tmp_path):
    db=Database(tmp_path/'fourteen.sqlite3');db.initialize();return db


def add_frame(db,task,phase,index,values):
    raw=struct.pack('<'+'H'*len(values),*values);digest=hashlib.sha256(raw).hexdigest()
    with db.write() as connection:
        connection.execute("""INSERT INTO dispersion_task_frames(task_id,phase,frame_index,ccd_index,points_blob,points_count,
            compression,points_sha256,raw_transfer_sha256,raw_byte_length,headers_json,virtual_time_ms,captured_at)
            VALUES (?,?,?,0,?,?,'zlib',?,?,?,'{}',0,?)""",(task,phase,index,zlib.compress(raw),len(values),digest,digest,len(raw),utc_now()))


def test_dispersion_uses_all_period_normalized_burn_and_dark_frames(tmp_path):
    db=fresh(tmp_path);service=DispersionService(db)
    task=service.create_task({'ccd_layout_id':'default','frame_count':2,'dark_frame_count':1})
    line=service.add_line(task['id'],{'element':'Fe','wavelength_nm':250.1,'ccd_index':0})
    a,b=107,117
    for phase,index,left,right in [('burn',0,1000,1),('burn',1,1,900),('dark',0,10,800)]:
        values=[1]*task['layout']['points_per_ccd'];values[a]=left;values[b]=right;add_frame(db,task['id'],phase,index,values)
    assert service.locate_line(task['id'],line['id'])['located_position']==107
    # With unequal periods, a separate immutable source can reverse the selected peak.
    second=service.create_task({'ccd_layout_id':'default','frame_count':2,'dark_frame_count':1})
    second_line=service.add_line(second['id'],{'element':'Fe','wavelength_nm':250.1,'ccd_index':0})
    for index,left,right in [(0,1000,1),(1,1,900)]:
        values=[1]*second['layout']['points_per_ccd'];values[a]=left;values[b]=right;add_frame(db,second['id'],'burn',index,values)
    with db.write() as connection:
        connection.execute('UPDATE dispersion_tasks SET condition_json=? WHERE id=?',(json.dumps({'ignition':{'burn_cyc':1,'dark_cyc':100}}),second['id']))
    dark=[1]*task['layout']['points_per_ccd'];dark[a]=10000;dark[b]=1;add_frame(db,second['id'],'dark',0,dark)
    assert service.locate_line(second['id'],second_line['id'])['located_position']==117
    # A malformed source frame is rejected without weakening frame immutability.
    bad=service.create_task({'ccd_layout_id':'default'})
    bad_line=service.add_line(bad['id'],{'element':'Fe','wavelength_nm':250.1,'ccd_index':0})
    add_frame(db,bad['id'],'burn',0,[1]*8)
    with pytest.raises(DispersionError):service.locate_line(bad['id'],bad_line['id'])


def test_gap_correction_clones_geometry_and_wavelength_edits_keep_positions(tmp_path):
    db=fresh(tmp_path);service=DispersionService(db)
    task=service.create_task({'ccd_layout_id':'default','lines':[
        {'element':'A','wavelength_nm':250,'ccd_index':0,'actual_position':100},
        {'element':'B','wavelength_nm':260,'ccd_index':1,'actual_position':200},
        {'element':'C','wavelength_nm':270,'ccd_index':2,'actual_position':300}]})
    old=service.fit_calibration(task['id'],{'name':'before','degree':2})
    with db.read() as connection:original=dict(connection.execute('SELECT * FROM ccd_layouts WHERE id=?',(task['ccd_layout_id'],)).fetchone())
    gap=task['layout']['gap_points'][0]+1
    updated=service.update_gap(task['id'],0,gap*task['layout']['point_width_um'])
    fitted=service.fit_calibration(task['id'],{'name':'after','degree':2})
    assert updated['ccd_layout_id']!=task['ccd_layout_id']
    assert [new['measured_position']-prior['measured_position'] for new,prior in zip(fitted['residuals'],old['residuals'])]==pytest.approx([0,1,1])
    with db.read() as connection:assert dict(connection.execute('SELECT * FROM ccd_layouts WHERE id=?',(task['ccd_layout_id'],)).fetchone())==original
    assert service.calibration(old['id'])['coefficients']==old['coefficients']
    first=updated['lines'][0];changed=service.update_line_wavelength(task['id'],first['id'],251)
    assert changed['id']==first['id'] and changed['saved_position']==first['saved_position']
    assert changed['wavelength_nm']==251
    before=json.dumps(service.get_task(task['id']),sort_keys=True)
    with pytest.raises(DispersionError):service.update_gap(task['id'],0,-1)
    with pytest.raises(DispersionError):service.update_line_wavelength(task['id'],first['id'],9999)
    assert json.dumps(service.get_task(task['id']),sort_keys=True)==before
    # D05 now follows the old RealStep: current position is used, saved position remains a restore point.
    service.set_line_position(task['id'],first['id'],150)
    saved=service.fit_calibration(task['id'],{'name':'current-position-wins','degree':2})
    assert saved['residuals'][0]['measured_position']==150
    assert service.get_task(task['id'])['lines'][0]['saved_position']==100


def test_curve_output_uses_content_x_intensity_y_and_log_both_axes(tmp_path):
    points=[{'point_index':i,'name':str(i),'adjusted_intensity':v,'standard_value':c} for i,(v,c) in enumerate([(100,1),(200,10),(400,100)])]
    curve={'id':1,'line_id':'Fe','fit_mode':'linear','coordinate_type':'logarithmic','result_sha256':'a'*64,
           'diagnostics':{'points':points,'rmse':0,'correlation':1},'chart':[{'intensity':p['adjusted_intensity'],'value':p['standard_value']} for p in points]}
    html=CurvePrintingService._curve_preview_html(curve,'image')
    xy=[(float(x),float(y)) for x,y in re.findall(r"<circle cx='([^']+)' cy='([^']+)'",html)]
    assert xy==pytest.approx([(40,300),(450,170),(860,40)])
    curve['coordinate_type']='normal'
    html=CurvePrintingService._curve_preview_html(curve,'image')
    xy=[(float(x),float(y)) for x,y in re.findall(r"<circle cx='([^']+)' cy='([^']+)'",html)]
    assert xy[1][0]==pytest.approx(40+820*9/99,abs=.01)
    assert xy[1][1]==pytest.approx(300-260*100/300,abs=.01)


def test_report_settings_are_consumed_and_confirmed_model_stays_immutable(tmp_path):
    db,run=_seed(tmp_path,result_count=25);runtime=Runtime(AppConfig(data_dir=tmp_path),database=db)
    service=runtime.reports_service();report=service.create({'analysis_run_ids':[run]});service.confirm(report['id'])
    before=service.get(report['id'])['model_sha256']
    AppService(db).update_settings(SettingsPatch.model_validate({'printing':{'paper':'A3','orientation':'portrait','font_size_pt':13,'elements_per_line':1,'samples_per_page':3,'time_mode':'system'}}))
    exported=service.export(report['id'],{'format':'pdf','output_directory':str(tmp_path/'exports')})
    document=fitz.open(exported['path'])
    assert len(document)==9
    assert [v*25.4/72 for v in document[0].rect[2:]]==pytest.approx([297,420],abs=.01)
    assert 13 in {span['size'] for block in document[0].get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for span in line['spans']}
    assert '系统时间' in document[0].get_text()
    assert service.get(report['id'])['model_sha256']==before
    assert 'size:297mm 420mm' in service.preview(report['id'])


def test_standard_and_exchange_are_real_matrices_without_losing_detail_format():
    model={'table_layout':'legacy_matrix','arrangement':'standard','rows':[
        {'sample_name':name,'element':element,'calculated_value':value}
        for name,values in [('N1',[1,2]),('N2',[3,4]),('N3',[5,6])] for element,value in zip(['Cu','Fe'],values)]}
    assert _table(model)==[['样品号','Cu','Fe'],['N1',1,2],['N2',3,4],['N3',5,6]]
    assert _table({**model,'arrangement':'exchange'})==[['样品号','N1','N2','N3'],['Cu',1,3,5],['Fe',2,4,6]]
    detail={**model,'table_layout':'detail','columns':['sample_name','element','calculated_value']}
    assert len(_table(detail))==7


def test_wide_exchange_pdf_paginates_all_sample_columns_without_tiny_cells():
    model={'table_layout':'legacy_matrix','arrangement':'exchange','rows':[
        {'sample_name':f'N{index}','element':element,'calculated_value':index*2+offset}
        for index in range(50) for offset,element in enumerate(['Cu','Fe'])]}
    report={'report_number':'wide','version':1,'arrangement':'exchange','model':model,'model_sha256':'a'*64}
    pages=_page_tables(report)
    assert len(pages)>1 and max(len(table[0]) for table in pages)<=13
    assert sorted(value for table in pages for row in table[1:] for value in row[1:])==list(range(100))
    content,count=_pdf(report)
    assert content.startswith(b'%PDF') and count>=len(pages)
    from backend.table_output import table_pdf
    content=table_pdf([['样号',*[f'E{index}' for index in range(50)]],['N1',*range(50)]],
                      '宽强度表',{'paper':'A4','orientation':'portrait','font_size_pt':13,'elements_per_line':50})
    doc=fitz.open(stream=content,filetype='pdf')
    assert len(doc)>1 and 'E49' in ''.join(page.get_text() for page in doc)


def test_intensity_wide_outputs_native_snapshot_text_pdf_and_method_text(tmp_path, monkeypatch):
    db,runtime,method,line_id,_,_,run=_sample_chain(tmp_path)
    service=runtime.analysis_service();before=runtime.methods_service().get(method['id'])['published_version']['content_sha256']
    from backend.printing import SystemPrinters
    submitted=[]
    monkeypatch.setattr(SystemPrinters,'dispatch_pdf',lambda self,path,*args: submitted.append(Path(path).read_bytes()))
    result=service.intensity_output(run['id'],{'save_intensity':True,'print_to_text':True,'print_intensity':True,'save_positions':False},1)
    files={item['filename'].split('.')[-1]:base64.b64decode(item['content_base64']) for item in result['files']}
    assert {'json','txt','pdf'}==set(files) and files['pdf'].startswith(b'%PDF')
    assert json.loads(files['json'])['table']==result['table']
    assert len(result['table'])==len(run['samples'])+1 and len(result['table'][0])>=2
    assert result['print_job']['status']=='queued'
    assert submitted==[files['pdf']]
    assert '峰值' in files['txt'].decode('utf-8-sig')
    text=runtime.method_print_service().text(method['id'],None,1).decode('utf-8-sig')
    assert '方法条件' in text and '谱线' in text and '标准' in text and method['name'] in text
    assert runtime.methods_service().get(method['id'])['published_version']['content_sha256']==before
    positioned=service.intensity_output(run['id'],{'save_intensity':False,'print_to_text':False,'print_intensity':False,'save_positions':True},1)
    assert positioned['method_draft']['latest_version']>method['published_version']['version']
    assert runtime.methods_service().get(method['id'])['published_version']['content_sha256']==before


def test_old_pdt_wide_table_exact_peak_background_and_integrity_rejection(tmp_path):
    db=fresh(tmp_path);runtime=Runtime(AppConfig(data_dir=tmp_path),database=db)
    source=source_file('pdt');copy=tmp_path/'input.pdt';shutil.copy2(source,copy);digest=hashlib.sha256(source.read_bytes()).hexdigest()
    migration=runtime.result_migration_service();staged=migration.stage(str(copy),None);committed=migration.commit(staged['id'],None)
    with db.read() as connection:
        row=connection.execute('SELECT * FROM result_matrices ORDER BY id LIMIT 1').fetchone();identifier=row['id']
        tables=migration.intensity_tables(connection,[identifier]);payload=json.loads(row['payload_json'])
        first=struct.unpack_from('<ff',bytes(row['matrix_blob']),0)
    assert tables[0]['table'][1][1]==first[0]
    assert tables[0]['table'][1][0].endswith('[1]')
    if payload['lines'][0]['back']:assert tables[0]['table'][1][2]==first[1]
    content,media=runtime.postprocessing_service().intensity_table([identifier],'pdf')
    assert content.startswith(b'%PDF') and media=='application/pdf'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    with db.write() as connection:connection.execute("UPDATE result_matrices SET matrix_blob=x'00' WHERE id=?",(identifier,))
    from backend.modules.postprocessing import PostProcessingError
    with pytest.raises(PostProcessingError):runtime.postprocessing_service().intensity_table([identifier],'txt')


@pytest.mark.parametrize('name',['样1','铅1'])
def test_sam_original_bytes_and_ambiguous_gb_encoding_are_preserved(tmp_path,name):
    db=fresh(tmp_path);service=SampleQueueService(db);raw=(name+'\t1\r\n').encode('gb18030')
    result=service.import_bytes(raw,None,'legacy','legacy.sam')
    assert result['items'][0]['pre_name']==name and result['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert _parse_lines((name+'\t1\r\n').encode('utf-8'),'utf-8-sig')[0]['name']==name
    before=service.get(result['id'])
    with pytest.raises(SampleQueueError):service.import_bytes(b'no-tab',None,'legacy','broken.sam')
    assert service.get(result['id'])==before


def test_configuration_preview_apply_consumers_and_atomic_rollback(tmp_path,monkeypatch):
    db=fresh(tmp_path);migration=LegacyMigrationService(db);source=Path(__file__).parent/'fixtures/legacy_runtime';target=tmp_path/'original';target.mkdir()
    for name in ['DIRECT.MTD','DIRECT.CFG','DIRECT.OPT']:shutil.copy2(source/name,target/name)
    cfg='[ANALYZE]\nRoundDarkTime=12\nLookBand=1\nWaitTime=1234\nLogAna=0\n[IgnitWst]\nPreBurn=5\nBurnCyc=1.25\nBurnCount=9\nBackCount=2\n[METHOD]\nSavePdt=1\nPrintPdt=0\nPrintToTxt=1\nSaveWave=0\n'
    (target/'DIRECT.CFG').write_text(cfg,encoding='ascii')
    original={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}
    staged=migration.stage(*(str(target/name) for name in ['DIRECT.MTD','DIRECT.CFG','DIRECT.OPT']),None);migration.commit(staged['id'],None)
    before=AppService(db).get_settings();preview=migration.configuration_preferences(staged['id'])
    assert not preview['applied'] and AppService(db).get_settings()==before
    with monkeypatch.context() as patch:
        patch.setattr(migration,'_audit_preferences',lambda *a: (_ for _ in ()).throw(RuntimeError('audit failed')))
        with pytest.raises(RuntimeError):migration.configuration_preferences(staged['id'],None,apply=True)
    assert AppService(db).get_settings()==before
    migration.configuration_preferences(staged['id'],None,apply=True)
    actual=AppService(db).get_settings()
    assert actual['analysis']['dark_round_time_seconds']==12 and actual['analysis']['wait_time_ms']==1234
    assert actual['analysis']['log_analysis'] is False
    assert actual['preliminary']['dispersion']['frame_count']==9
    assert actual['intensity_output']==dict(save_intensity=True,print_intensity=False,print_to_text=True,save_positions=False)
    assert actual['directories']==before['directories'] and actual['display']['theme']==before['display']['theme']
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}==original
    with db.read() as connection:assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_new_output_configuration_and_edit_api_permission_boundaries(tmp_path):
    db,runtime,method,_,_,_,run=_sample_chain(tmp_path)
    app=create_app(runtime=runtime)
    with TestClient(app) as client:
        login=client.post('/api/v1/auth/login',json={'username':'spec-gap-operator','password':'correct-horse'}).json()
        headers={'Authorization':'Bearer '+login['access_token']}
        role=client.post('/api/v1/roles',headers=headers,json={'name':'fourteen-reader','permission_keys':['analysis.read','spectra.read','methods.read','migration.read']}).json()
        assert client.post('/api/v1/users',headers=headers,json={'username':'fourteen-reader','password':'Reader-fourteen-2026!','role_ids':[role['id']]}).status_code==201
        reader=client.post('/api/v1/auth/login',json={'username':'fourteen-reader','password':'Reader-fourteen-2026!'}).json()
        read={'Authorization':'Bearer '+reader['access_token']}
        profiles=client.get('/api/v1/spectra/display-profiles',headers=read)
        assert profiles.status_code==200 and profiles.json()[0]['screen_width_mm']==409.2
        text=client.post(f"/api/v1/methods/{method['id']}/text",headers=read,json={})
        assert text.status_code==200 and '方法条件' in text.text
        options=dict(save_intensity=True,print_intensity=False,print_to_text=False,save_positions=False)
        assert client.post(f"/api/v1/analyses/runs/{run['id']}/intensity-output",headers=read,json=options).status_code==200
        for change in [{'print_intensity':True},{'save_positions':True}]:
            assert client.post(f"/api/v1/analyses/runs/{run['id']}/intensity-output",headers=read,json={**options,**change}).status_code==403
        before=AppService(db).get_settings()
        assert client.post('/api/v1/legacy-migration/runs/missing/preferences',headers=read).status_code==403
        task=runtime.dispersion_service().create_task({'ccd_layout_id':'default'})
        line=runtime.dispersion_service().add_line(task['id'],{'element':'Fe','wavelength_nm':250,'ccd_index':0})
        assert client.patch(f"/api/v1/dispersion/tasks/{task['id']}/lines/{line['id']}/wavelength?wavelength_nm=251",headers=read).status_code==403
        assert client.patch(f"/api/v1/dispersion/tasks/{task['id']}/gaps/0?gap_um=-1",headers=headers).status_code==422
        assert AppService(db).get_settings()==before
