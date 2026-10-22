"""Use the common Windows output contract for legacy PDT tables."""
import base64
from ...db import utc_now
from ...services import AppService
from ...table_output import table_excel, table_pdf, dispatch_table
from ..result_migration import ResultMigrationService, ResultMigrationError
from .errors import PostProcessingError
from .serialization import _json


def legacy_output(service, identifiers, fmt, printer, actor):
    with service.database.read() as db:
        try:
            tables = ResultMigrationService.intensity_tables(db, identifiers)
        except ResultMigrationError as exc:
            raise PostProcessingError(exc.code, exc.message) from exc
    table = []
    for item in tables:
        if table and table[0] != item['table'][0]:
            raise PostProcessingError('intensity_columns_mismatch', '请选择相同谱线布局的 PDT，或分别打开输出')
        table = item['table'] if not table else table + item['table'][1:]
    files, job = [], None
    if fmt is not None:
        printing = AppService(service.database).get_settings()['printing']
        content = table_excel(table, 'Intensity') if fmt == 'excel' else table_pdf(table, '旧 PDT 强度表', printing)
        files.append(dict(filename='legacy-intensity.' + ('xls' if fmt == 'excel' else 'pdf'),
                          media_type='application/vnd.ms-excel' if fmt == 'excel' else 'application/pdf',
                          content_base64=base64.b64encode(content).decode()))
        if fmt == 'print':
            job = dispatch_table(content, service.database.path.parent, printer or printing['default_printer'])
        with service.database.write() as db:
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,details_json,created_at) "
                       "VALUES (?,'postprocessing.export','legacy_intensity',?,?)",
                       (actor, _json({'record_ids': identifiers, 'format': fmt, 'print_job': job}), utc_now()))
    return dict(table=table, files=files, print_job=job)
