"""Workbook bytes and field semantics through the real sample queue API."""

import base64
import hashlib
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook

from backend.modules.sample_queues import SampleQueueError
from backend.modules.sample_workbook import read_sample_workbook
from tests.test_sample_current_context import client_state


def workbook_with(*rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def upload(content, name='样号往返.xlsx'):
    return {'filename': name, 'last_modified_ms': 1764000000000,
            'content_base64': base64.b64encode(content).decode('ascii')}


def test_queue_xlsx_roundtrip_preserves_text_positions_and_existing_queue(client_state, tmp_path):
    client, runtime, headers, call, _ = client_state
    entries = [('0007', 2), ('A-0008', 3), ('', 0), ('=A+1', 1), ('+B_µ9', 2),
               ('长样号-A1234567890123', 4), ('', 0)]
    existing = call('/sample-queues', {'name': '同名样号表', 'name_length': 20, 'items': [
        {'pre_name': name, 'repeats': repeats} for name, repeats in entries]})
    route = '/api/v1/sample-queues'
    exported = client.get(f"{route}/{existing['id']}/export?format=xlsx", headers=headers)
    assert exported.status_code == 200
    assert exported.content.startswith(b'PK')
    assert exported.headers['content-type'].endswith('spreadsheetml.sheet')
    digest = hashlib.sha256(exported.content).hexdigest()
    assert exported.headers['x-source-sha256'] == digest
    (tmp_path / 'sample-roundtrip.xlsx').write_bytes(exported.content)
    with BytesIO(exported.content) as stream:
        book = load_workbook(stream, data_only=False)
        assert book['样号']['A2'].value == '0007'
        assert book['样号']['A5'].value == '=A+1' and book['样号']['A5'].data_type == 's'
        assert book['样号']['A6'].value == '+B_µ9' and book['样号']['A6'].data_type == 's'
        assert book['样号设置'].sheet_state == 'hidden'
        book.close()

    imported = call('/sample-queues/import', upload(exported.content, '同名样号表.xlsx'))
    assert imported['id'] != existing['id']
    assert imported['source_sha256'] == digest and imported['name_length'] == 20
    assert [(row['pre_name'], row['repeats']) for row in imported['items']] == entries
    assert [row['position'] for row in imported['items']] == list(range(len(entries)))
    assert call('/sample-queues/import', upload(exported.content))['id'] == imported['id']
    assert call(f"/sample-queues/{existing['id']}") == existing
    with runtime.database.read() as db:
        actions = db.execute("SELECT action FROM audit_events WHERE action LIKE 'sample_queue.xlsx_%' ORDER BY id")
        assert [row[0] for row in actions] == ['sample_queue.xlsx_export', 'sample_queue.xlsx_import']
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


@pytest.mark.parametrize('rows,cell', [
    ([('A001', 1), ('=A1&1', 1)], 'A2'),
    ([('A001', 1), ('bad/name', 1)], 'A2'),
    ([('A001', 1), ('A\t2', 1)], 'A2'),
    ([('A001', 1), ('A003', 1.5)], 'B2'),
])
def test_invalid_workbook_rejects_entire_import(client_state, tmp_path, rows, cell):
    client, _, headers, call, _ = client_state
    before = call('/sample-queues')
    content = workbook_with(*rows)
    if rows[-1][0].startswith('='):
        (tmp_path / 'sample-invalid-formula.xlsx').write_bytes(content)
    result = client.post('/api/v1/sample-queues/import', json=upload(content), headers=headers)
    assert result.status_code == 422
    assert result.json()['detail']['code'] == 'sample_workbook_invalid'
    assert result.json()['detail']['details']['cell'] == cell
    assert call('/sample-queues') == before


def test_xlsx_numeric_padding_and_structural_failures():
    book = Workbook()
    book.active['A1'] = 7
    book.active['A1'].number_format = '0000'
    book.active['A3'] = 'A-0009'
    stream = BytesIO()
    book.save(stream)
    entries, width = read_sample_workbook(stream.getvalue())
    assert width == 12
    assert entries == [{'name': '0007', 'repeats': 1}, {'name': '', 'repeats': 0},
                       {'name': 'A-0009', 'repeats': 1}]
    with pytest.raises(SampleQueueError, match=r'有效的 .xlsx'):
        read_sample_workbook(b'invalid')
    with pytest.raises(SampleQueueError, match=r'最多支持 2 条'):
        read_sample_workbook(stream.getvalue(), limit=2)
