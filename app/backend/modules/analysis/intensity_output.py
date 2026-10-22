"""Legacy peak/background wide tables with native snapshots and explicit output choices."""
from __future__ import annotations
import base64,csv,hashlib,io,json
from ...db import utc_now
from ...services import AppService
from ...table_output import table_pdf,dispatch_table,table_excel
from .errors import AnalysisError


def intensity_output(service,run_id: int,options: dict,actor: int) -> dict:
    with service.database.read() as db:
        run,payload,lines=service.repository._context(db,run_id)
        if run['status']!='completed':raise AnalysisError('analysis_intensity_incomplete','分析完成后才能输出强度表',status_code=409)
        samples=[dict(row) for row in db.execute('SELECT * FROM analysis_run_samples WHERE run_id=? ORDER BY position',(run_id,))]
        results=[dict(row) for row in db.execute('SELECT * FROM analysis_line_results WHERE run_id=? ORDER BY sample_position,line_position',(run_id,))]
    columns=[line for line in lines if line['line_type']!='baseline']
    if not samples or not columns or any(not any(row['sample_position']==sample['position'] and str(row['line_id'])==str(line['id']) for row in results) for sample in samples for line in columns):
        raise AnalysisError('analysis_intensity_missing','强度矩阵不完整，禁止输出')
    header=['强度编号'];table=[header]
    for line in columns:
        header.append(f"{line['element']} {line['wavelength_nm']:g} 峰值")
        if line.get('background_offset_points',0):header.append(f"{line['element']} 背景")
    for sample in samples:
        from ..acquisition import AcquisitionService
        identity=AcquisitionService(service.database).sample_identity(sample['acquisition_sample_id'])
        row=[f"{sample['sample_name']} [{int(identity['repeat_index'])+1}]"]
        for line in columns:
            item=next(item for item in results if item['sample_position']==sample['position'] and str(item['line_id'])==str(line['id']))
            row.append(item['peak_height'])
            if line.get('background_offset_points',0):row.append(item['background'])
        table.append(row)
    preview=None
    if options.get('save_positions'):
        preview=service.calibration_preview(run_id,samples[-1]['position'])
        if not preview['save_allowed']:raise AnalysisError('analysis_calibration_peak_missing','存在无效定位，不能保存校正波长')
    snapshot={'format':'geospectrum-intensity-v1','run_id':run_id,'method_version_id':run['method_version_id'],
              'calculation_profile':run['calculation_profile'],'table':table,'line_results':results,'method':payload,'input_snapshot_sha256':run['input_sha256']}
    content=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')
    digest=hashlib.sha256(content).hexdigest(); files=[]
    fmt = options.get('export_format')
    if fmt not in {None, 'excel', 'pdf'}:
        raise AnalysisError('analysis_intensity_format_invalid', '强度导出格式无效')
    if fmt == 'excel':
        data = table_excel(table, 'Intensity')
        files.append({'filename':f'analysis-{run_id}-intensity.xls','content_base64':base64.b64encode(data).decode(),'media_type':'application/vnd.ms-excel'})
    if fmt == 'pdf':
        printing=AppService(service.database).get_settings()['printing']
        data=table_pdf(table,'分析强度表',printing,f"{run['calculation_profile']} · SHA-256 {digest}")
        files.append({'filename':f'analysis-{run_id}-intensity.pdf','content_base64':base64.b64encode(data).decode(),'media_type':'application/pdf'})
    if options.get('save_intensity'):files.append({'filename':f'analysis-{run_id}-intensity.json','content_base64':base64.b64encode(content).decode(),'media_type':'application/json'})
    if options.get('print_to_text'):
        stream=io.StringIO(newline='');csv.writer(stream,delimiter='\t',lineterminator='\r\n').writerows(table)
        files.append({'filename':f'analysis-{run_id}-intensity.txt','content_base64':base64.b64encode(('\ufeff'+stream.getvalue()).encode('utf-8')).decode(),'media_type':'text/plain'})
    job=None
    if options.get('print_intensity'):
        printing=AppService(service.database).get_settings()['printing']
        pdf=table_pdf(table,'分析强度表',printing,f"{run['calculation_profile']} · SHA-256 {digest}")
        job=dispatch_table(pdf,service.database.path.parent,options.get('printer_name') or printing['default_printer'])
        files.append({'filename':f'analysis-{run_id}-intensity.pdf','content_base64':base64.b64encode(pdf).decode(),'media_type':'application/pdf'})
    method=None
    if preview is not None:method=service.save_calibration(run_id,samples[-1]['position'],actor,mode='measured',scope='all')
    with service.database.write() as db:
        service.repository._audit(db,actor,'analysis.intensity.output',run_id,{'options':options,'snapshot_sha256':digest,'print_job':job,'method_draft_version':method.get('latest_version') if method else None})
    return {'table':table,'files':files,'snapshot_sha256':digest,'print_job':job,'method_draft':method}
