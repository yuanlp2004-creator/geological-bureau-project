import ast
from pathlib import Path

import pytest

from backend.db import Database
from backend.modules.methods import MethodService
from backend.modules.analysis import AnalysisService, AnalysisError
from tests.test_s16_analysis import _seed


# 定位结果与原几何入口一致，读取复用当前连接且不提交；快照可脱离连接使用。
def test_geometry_snapshot_preserves_positions_and_transaction(tmp_path, monkeypatch):
    database = Database(tmp_path / 'geometry.sqlite3')
    database.initialize()
    methods = MethodService(database)
    with database.read() as db:
        layout = methods._layout(db, 'default')
        dispersion = methods._dispersion(db, 'default')
        references = [{}, {'ccd_layout_id': layout['id'], 'dispersion_calibration_id': dispersion['id']}]
        statements = []
        def reject_connection():
            raise AssertionError('geometry opened a new connection')
        monkeypatch.setattr(database, 'connect', reject_connection)
        db.set_trace_callback(statements.append)
        for conditions in references:
            statements.clear()
            locator = methods.bind_geometry(db, conditions)
            assert len(statements) == 2
            assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
            for wave in (200.0, 253.65, 300.0, -1000000.0, 1000000.0):
                assert locator.locate(wave) == methods._reference_position(wave, layout, dispersion)
    assert locator.locate(253.65) == methods._reference_position(253.65, layout, dispersion)


@pytest.mark.parametrize('conditions,code', [
    ({'ccd_layout_id': 999999}, 'analysis_geometry_missing'),
    ({'dispersion_calibration_id': 999999}, 'analysis_geometry_missing'),
    ({}, 'analysis_line_outside_ccd'),
])
# 收拢边界后保留分析侧的缺失、越界错误码及字段。
def test_analysis_geometry_error_contract(tmp_path, conditions, code):
    database = Database(tmp_path / 'analysis.sqlite3')
    version_id, sample_ids = _seed(database)
    service = AnalysisService(database, methods=MethodService(database))
    run = service.create_run({'acquisition_sample_ids': sample_ids, 'method_version_id': version_id})
    line = {'id': 'probe', 'wavelength_nm': -1000000.0}
    with database.read() as db, pytest.raises(AnalysisError) as caught:
        service.inputs.candidate(db, run, {'conditions': conditions}, [line], 0, 0)
    assert caught.value.code == code
    assert caught.value.status_code == 409
    assert caught.value.details['line_id'] == 'probe'


# 防止分析服务重新依赖方法模块私有的存储或几何入口。
def test_analysis_uses_public_geometry_boundary():
    source = Path(__file__).resolve().parents[1] / 'backend/modules/analysis/service.py'
    attributes = [node.attr for node in ast.walk(ast.parse(source.read_text(encoding='utf-8-sig')))
                  if isinstance(node, ast.Attribute)]
    assert not {'_layout', '_dispersion', '_reference_position'}.intersection(attributes)
