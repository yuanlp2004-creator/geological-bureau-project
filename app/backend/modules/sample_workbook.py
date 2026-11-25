"""Excel exchange for ordered sample numbers and repeat counts."""

from io import BytesIO
import re
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .sample_queues import SampleQueueError, normalize_name


MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MAX_BYTES = 5_000_000
HEADER = ('样号', '重复次数')
SETTINGS_SHEET = '样号设置'
MAX_RECORDS = 1000


def _error(message, **details):
    return SampleQueueError('sample_workbook_invalid', message, details=details)


def _name(cell, line):
    value = cell.value
    if value is None:
        return ''
    if cell.data_type in {'s', 'inlineStr'} and isinstance(value, str):
        return value
    if (cell.data_type == 'n' and type(value) in (float, int)
            and abs(value) < 10**15 and value == int(value)):
        number = str(int(value))
        if re.fullmatch(r'0{1,20}', cell.number_format):
            number = number.zfill(len(cell.number_format))
        return number
    raise _error(f'A{line} 的样号须为文本或最多 15 位的整数，公式请先粘贴为值', cell=f'A{line}')


def _repeats(cell, name, line):
    value = cell.value
    if value is None:
        return 1 if name else 0
    if (cell.data_type == 'n' and type(value) in (int, float) and value in range(11)
            or cell.data_type in {'s', 'inlineStr'} and re.fullmatch(r'0?[0-9]|10', str(value).strip())):
        return int(value)
    raise _error(f'B{line} 的重复次数须为 0 至 10 的整数', cell=f'B{line}')


def read_sample_workbook(content: bytes, *, limit: int = MAX_RECORDS,
                         normalize_standards: bool = True) -> tuple[list[dict], int]:
    if len(content) > MAX_BYTES:
        raise _error('Excel 文件超过 5 MB')
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 512 or sum(item.file_size for item in members) > 25_000_000:
                raise _error('Excel 工作簿解压后超过可读取范围')
        workbook = load_workbook(BytesIO(content), read_only=True, keep_links=False)
        try:
            sheet = workbook['样号'] if '样号' in workbook.sheetnames else workbook.worksheets[0]
            width = None
            if SETTINGS_SHEET in workbook.sheetnames:
                width = workbook[SETTINGS_SHEET]['B1'].value
                if width not in (10, 12, 20):
                    raise _error('样号设置中的长度须为 10、12 或 20')
            records = []
            pending_blanks = []
            header = False
            sheet.reset_dimensions()
            for line, (sample, repeats) in enumerate(sheet.iter_rows(min_row=1, max_col=2), 1):
                if line == 1 and sample.value in (HEADER[0], '样品名', '样品名称') and repeats.value in (HEADER[1], None):
                    header = True
                    continue
                if line - int(header) > limit:
                    raise _error(f'样号表最多支持 {limit} 条记录')
                if sample.value is None and repeats.value is None:
                    pending_blanks.append({'name': '', 'repeats': 0})
                    continue
                raw_name = _name(sample, line)
                try:
                    name, _ = normalize_name(raw_name, width or 20, normalize_standards=normalize_standards)
                except SampleQueueError as exc:
                    raise _error(f'A{line} {exc.message}', cell=f'A{line}', reason=exc.code) from exc
                records.extend(pending_blanks)
                pending_blanks.clear()
                records.append({'name': name, 'repeats': _repeats(repeats, name, line)})
            if not records:
                raise _error('Excel 工作簿中没有可导入的样号记录')
            return records, int(width or (20 if any(len(item['name']) > 12 for item in records) else 12))
        finally:
            workbook.close()
    except (BadZipFile, InvalidFileException, ParseError, OSError, ValueError, RuntimeError, TypeError,
            IndexError, KeyError, AttributeError) as exc:
        if isinstance(exc, SampleQueueError):
            raise
        raise _error('无法读取 Excel 工作簿，请检查文件是否为有效的 .xlsx') from exc


def write_sample_workbook(records: list[dict], name_length: int = 20, *, normalize_standards: bool = True) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '样号'
    sheet.append(HEADER)
    sheet.freeze_panes = 'A2'
    sheet.column_dimensions['A'].width = 24
    sheet.column_dimensions['B'].width = 12
    settings = workbook.create_sheet(SETTINGS_SHEET)
    settings.append(('样号长度', name_length))
    settings.sheet_state = 'hidden'
    for row, item in enumerate(records, 2):
        name, _ = normalize_name(item['name'], name_length, normalize_standards=normalize_standards)
        cell = sheet.cell(row, 1, name)
        cell.data_type = 's'
        cell.number_format = '@'
        sheet.cell(row, 2, item['repeats'])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
