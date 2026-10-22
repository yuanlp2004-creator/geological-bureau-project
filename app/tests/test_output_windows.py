"""Native-ready export payloads preserve table values and do not print on export."""
import base64
import io
from xml.etree import ElementTree as ET
import pytest
from pypdf import PdfReader
from tests.test_legacy_fourteen_closure import _sample_chain
from tests.test_s19_reports import _seed
from backend.config import AppConfig
from backend.runtime import Runtime
from backend.printing import SystemPrinters, PrintCancelled


def test_intensity_excel_pdf_are_exports_not_prints(tmp_path, monkeypatch):
    db,runtime,_,_,_,_,run=_sample_chain(tmp_path)
    monkeypatch.setattr(SystemPrinters,'dispatch_pdf',lambda *args: pytest.fail('export must not submit a print job'))
    expected=None
    for fmt in ['excel','pdf']:
        result=runtime.analysis_service().intensity_output(run['id'],dict(save_intensity=False,print_intensity=False,print_to_text=False,save_positions=False,export_format=fmt),1)
        assert len(result['files'])==1 and result['print_job'] is None
        content=base64.b64decode(result['files'][0]['content_base64'])
        if fmt=='excel':
            root=ET.fromstring(content);ns={'s':'urn:schemas-microsoft-com:office:spreadsheet'}
            rows=[[cell.text for cell in row.findall('s:Cell/s:Data',ns)] for row in root.findall('.//s:Row',ns)]
            expected=result['table']
            assert rows==[[str(value) if value is not None else None for value in row] for row in expected]
        else:
            assert result['table']==expected
            assert len(PdfReader(io.BytesIO(content)).pages)>0
    assert not (tmp_path/'print-jobs').exists()


def test_intensity_selected_printer_cancel_is_not_success(tmp_path, monkeypatch):
    _,runtime,_,_,_,_,run=_sample_chain(tmp_path)
    monkeypatch.setattr(SystemPrinters,'printers',lambda self:[{'name':'chosen','default':True}])
    seen=[]
    def cancel(path,name,*args): seen.append(name);raise PrintCancelled('cancel')
    monkeypatch.setattr(SystemPrinters,'dispatch_pdf',staticmethod(cancel))
    result=runtime.analysis_service().intensity_output(run['id'],dict(save_intensity=False,print_intensity=True,print_to_text=False,save_positions=False,printer_name='chosen'),1)
    assert seen==['chosen'] and result['print_job']['status']=='cancelled'


def test_report_download_prepares_bytes_without_writing_or_printing(tmp_path, monkeypatch):
    database,run_id=_seed(tmp_path)
    service=Runtime(AppConfig(data_dir=tmp_path),database=database).reports_service()
    report=service.create({'analysis_run_ids':[run_id]},None)
    from backend.modules.reports import ReportError
    with pytest.raises(ReportError,match='请先预览并确认'):
        service.export(report['id'],dict(format='pdf',download=True),None)
    service.confirm(report['id'])
    monkeypatch.setattr(SystemPrinters,'dispatch_pdf',lambda *args: pytest.fail('export must not print'))
    for fmt,extension in [('excel','.xls'),('pdf','.pdf')]:
        result=service.export(report['id'],dict(format=fmt,download=True),None)
        assert result['status']=='prepared' and result['path'] is None and result['filename'].endswith(extension)
        content=base64.b64decode(result['content_base64'])
        if fmt=='pdf':assert len(PdfReader(io.BytesIO(content)).pages)>0
        else:assert ET.fromstring(content).tag.endswith('Workbook')
    assert service.exports(report['id'])==[]
    with database.read() as db:
        assert db.execute("SELECT count(*) FROM audit_events WHERE action='report.export.prepare'").fetchone()[0]==2
