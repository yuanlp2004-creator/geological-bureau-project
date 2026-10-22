from pathlib import Path
import json, hashlib, struct, zlib, tempfile, sys, shutil
import fitz

WORK=Path(__file__).resolve().parent
ROOT=next(p for p in WORK.parents if (p/'PLAN.md').is_file() and (p/'app').is_dir())
sys.path.insert(0,str(ROOT/'app'))
from backend.db import Database, utc_now
from backend.config import AppConfig
from backend.runtime import Runtime
from backend.modules.dispersion import DispersionService
from backend.modules.sample_queues import _parse_lines, SampleQueueService
from backend.modules.reports.rendering import _pdf, _table
from backend.modules.legacy_migration import LegacyMigrationService
from backend.services import AppService
from backend.schemas.system import SettingsPatch

facts={}
with tempfile.TemporaryDirectory(prefix='geospectrum-full-audit-') as folder:
    temporary=Path(folder)
    database=Database(temporary/'audit.sqlite3'); database.initialize()
    service=DispersionService(database)
    with database.read() as db:
        layout=db.execute('SELECT * FROM ccd_layouts ORDER BY id LIMIT 1').fetchone()
        coefficients=service.repository._default_coefficients(db,layout['id'])
        indices=json.loads(layout['ccd_indices_json']); ccd=indices[0]
        left,point_count=service.repository._geometry(layout,ccd)
        wave=next(w for w in [160+i*.1 for i in range(6401)]
            if 100 < coefficients[0]*w*w+coefficients[1]*w+coefficients[2]-left < point_count-100)
    task=service.create_task({'ccd_layout_id':layout['id'],'frame_count':2,'dark_frame_count':0,
        'pre_excitation_seconds':0,'sampling_period_seconds':1})
    line=service.add_line(task['id'],{'element':'Fe','wavelength_nm':wave,'ccd_index':ccd})
    center=round(line['expected_position']); first_peak,second_peak=center-5,center+5
    frames=[]
    for frame_index in range(2):
        values=[1]*point_count
        if frame_index==0: values[first_peak]=1000
        else: values[second_peak]=900
        frames.append(values)
        raw=struct.pack('<'+'H'*point_count,*values)
        with database.write() as db:
            db.execute('''INSERT INTO dispersion_task_frames(task_id,phase,frame_index,ccd_index,
                points_blob,points_count,compression,points_sha256,raw_transfer_sha256,
                raw_byte_length,headers_json,virtual_time_ms,captured_at)
                VALUES (?,'burn',?,?,?,?,'zlib',?,?,?,'{}',0,?)''',
                (task['id'],frame_index,ccd,zlib.compress(raw),point_count,
                    hashlib.sha256(raw).hexdigest(),hashlib.sha256(raw).hexdigest(),len(raw),utc_now()))
    located=service.locate_line(task['id'],line['id'])
    mean=[sum(row[index] for row in frames)/2 for index in range(point_count)]
    old_mean_peak=max(range(point_count),key=lambda index:mean[index])
    facts['dispersion_last_frame_vs_mean']={'wavelength_nm':wave,'expected_position':line['expected_position'],
        'source_frames':[{first_peak:row[first_peak],second_peak:row[second_peak]} for row in frames],
        'legacy_mean_peak_index':old_mean_peak,'current_located_position':located['located_position'],
        'different':old_mean_peak!=located['located_position'],
        'oracle':'old source loads normalized CcdAvgs; equal periods and zero dark make peak equal to arithmetic-mean peak'}
    assert facts['dispersion_last_frame_vs_mean']['different']

    for index in range(3):
        item=service.add_line(task['id'],{'element':'Cu','wavelength_nm':300+10*index,
            'ccd_index':ccd,'actual_position':100+100*index})
        if index==1: middle=item
    baseline=service.fit_calibration(task['id'],{'name':'audit-saved-position','degree':2})
    service.set_line_position(task['id'],middle['id'],250)
    moved=service.get_task(task['id'])
    fitted=service.fit_calibration(task['id'],{'name':'audit-saved-position','degree':2})
    residual=next(x for x in fitted['residuals'] if x['line_id']==middle['id'])
    facts['dispersion_move_requires_save']={'stored_position':middle['saved_position'],
        'new_located_position':next(x for x in moved['lines'] if x['id']==middle['id'])['located_position'],
        'fit_used_position':residual['measured_position']-left,
        'coefficients_unchanged':baseline['coefficients']==fitted['coefficients']}

    raw='样1\t1\r\n'.encode('gb18030'); (WORK/'sam-gb18030.sam').write_bytes(raw)
    facts['sam_encoding']={'original_name':'样1','raw_hex':raw.hex(),'original_sha256':hashlib.sha256(raw).hexdigest(),
        'backend_original_bytes_name':_parse_lines(raw)[0]['name'],
        'browser_file_text_name':raw.decode('utf-8',errors='replace').split('\t')[0],
        'ambiguous_gb18030_name':'铅1',
        'ambiguous_backend_name':_parse_lines('铅1\t1\r\n'.encode('gb18030'))[0]['name']}

    model={'columns':['sample_name','element','calculated_value'],'rows':[
        {'sample_name':f'N{i+1}','element':'Cu','calculated_value':i/10} for i in range(25)],
        'arrangement':'standard'}
    report={'report_number':'AUDIT','version':1,'arrangement':'standard','model_sha256':'a'*64,
        'template_name':'audit','model':model}
    a,pages_a=_pdf(report); (WORK/'report-before.pdf').write_bytes(a)
    AppService(database).update_settings(SettingsPatch.model_validate({'printing':{
        'paper':'A3','orientation':'portrait','font_size_pt':12}}),None)
    b,pages_b=_pdf(report); (WORK/'report-after.pdf').write_bytes(b)
    document=fitz.open(stream=b,filetype='pdf')
    facts['report_settings']={'requested_paper':'A3 portrait','requested_font':12,'rows':25,
        'pages_before':pages_a,'pages_after':pages_b,'bytes_identical':a==b,
        'actual_page_mm':[round(value*25.4/72,3) for value in document[0].rect[2:]],
        'actual_text_font_sizes':sorted({span['size'] for block in document[0].get_text('dict')['blocks']
            if 'lines' in block for line in block['lines'] for span in line['spans']})}
    assert a==b and pages_b==2
    matrix_model={'columns':['sample_name','element','calculated_value'],'rows':[
        {'sample_name':f'N{i+1}','element':element,'calculated_value':i+offset/10}
        for i in range(3) for offset,element in enumerate(['Cu','Fe'])], 'arrangement':'standard'}
    standard_table=_table(matrix_model)
    exchanged={**matrix_model,'arrangement':'exchange','columns':['element','sample_name','calculated_value']}
    exchanged_table=_table(exchanged)
    facts['report_exchange_not_matrix_transpose']={'standard_dimensions':[len(standard_table),len(standard_table[0])],
        'exchange_dimensions':[len(exchanged_table),len(exchanged_table[0])],
        'exchange_header':exchanged_table[0], 'sample_count':3,'element_count':2,
        'legacy_standard_matrix_dimensions':[4,3], 'legacy_exchange_matrix_dimensions':[3,4],
        'legacy_exchange_header':['样品号','N1','N2','N3']}

    # Import only fresh copies. Test a distinctive CFG value rather than trusting an archived profile flag.
    source=ROOT/'app/tests/fixtures/legacy_runtime'; target=temporary/'sources'; target.mkdir()
    for name in ['DIRECT.MTD','DIRECT.CFG','DIRECT.OPT']: shutil.copy2(source/name,target/name)
    (target/'DIRECT.CFG').write_text('[ANALYZE]\nRoundDarkTime=12\nLookBand=1\nWaitTime=1234\nLogAna=1\n',encoding='ascii')
    migration=LegacyMigrationService(database)
    staged=migration.stage(str(target/'DIRECT.MTD'),str(target/'DIRECT.CFG'),str(target/'DIRECT.OPT'),None)
    committed=migration.commit(staged['id'],None)
    assert committed['status']=='committed'
    with database.read() as db:
        profile=dict(db.execute('SELECT id,active,cfg_json FROM legacy_configuration_profiles ORDER BY id DESC LIMIT 1').fetchone())
    facts['imported_cfg_runtime']={'source_dark_seconds':12,'source_wait_ms':1234,
        'configuration_profile_id':profile['id'],'profile_active':profile['active'],
        'archived_cfg':json.loads(profile['cfg_json'])['normalized']['analyze'],
        'runtime_dark_seconds':AppService(database).get_settings()['analysis']['dark_round_time_seconds']}

(WORK/'probe-results.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(facts,ensure_ascii=False,indent=2))
