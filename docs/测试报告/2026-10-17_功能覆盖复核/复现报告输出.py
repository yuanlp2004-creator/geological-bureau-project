"""Resolve outdated assertions using real renderers and a captured print boundary."""
import base64
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
APP=HERE.parents[2]/"app"
sys.path.insert(0,str(APP))
SCRATCH=APP/".local/test-runs/coverage-audit-20261017/repro"
SCRATCH.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=SCRATCH,prefix='geospectrum-output-audit-') as directory:
    os.environ['SPECTRUM_DATA_DIR']=directory
    import fitz
    from tests.test_s19_reports import _seed
    from tests.test_spec_gap_closure import _sample_chain
    from backend.config import AppConfig
    from backend.runtime import Runtime
    from backend.services import AppService
    from backend.schemas.system import SettingsPatch
    from backend.printing import SystemPrinters

    path=Path(directory)/'report';path.mkdir()
    db,run=_seed(path,result_count=25)
    runtime=Runtime(AppConfig(data_dir=path),database=db)
    service=runtime.reports_service()
    report=service.create({'analysis_run_ids':[run]});service.confirm(report['id'])
    before=service.get(report['id'])['model_sha256']
    AppService(db).update_settings(SettingsPatch.model_validate({'printing':{'paper':'A3','orientation':'portrait','font_size_pt':13,'elements_per_line':1,'samples_per_page':3,'time_mode':'system'}}))
    exported=service.export(report['id'],{'format':'pdf','output_directory':str(path/'exports')})
    pdf=fitz.open(exported['path'])
    dimensions=[v*25.4/72 for v in pdf[0].rect[2:]]
    fonts=sorted({span['size'] for block in pdf[0].get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for span in line['spans']})
    css=re.search(r'@page\{([^}]+)\}',service.preview(report['id'])).group(1)
    assert len(pdf)==9 and all(abs(x-y)<.01 for x,y in zip(dimensions,[297,420]))
    assert 13 in fonts and service.get(report['id'])['model_sha256']==before
    result={'report':{'pages':len(pdf),'paper_mm':dimensions,'font_sizes':fonts,'html_page_css':css,'confirmed_model_preserved':True}}
    pdf.close()

    path=Path(directory)/'intensity';path.mkdir()
    db,runtime,method,line,_,_,run=_sample_chain(path)
    submitted=[]
    def fake_dispatch(self,pdf_path,printer_name,settings=None):
        content=Path(pdf_path).read_bytes()
        assert content.startswith(b'%PDF')
        submitted.append({'printer':printer_name,'pdf_bytes':len(content)})
        return 'audit-captured'
    with patch.object(SystemPrinters,'dispatch_pdf',fake_dispatch):
        output=runtime.analysis_service().intensity_output(run['id'],{'save_intensity':True,'print_to_text':True,'print_intensity':True,'save_positions':False},1)
    files={item['filename'].rsplit('.',1)[-1]:base64.b64decode(item['content_base64']) for item in output['files']}
    assert set(files)=={'json','txt','pdf'}
    assert json.loads(files['json'])['table']==output['table']
    assert output['print_job']['status']=='queued' and len(submitted)==1
    result['intensity']={'file_formats':sorted(files),'captured_submissions':submitted,'status_after_submission':output['print_job']['status'],'physical_printer_used':False}
    (HERE/'output-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
