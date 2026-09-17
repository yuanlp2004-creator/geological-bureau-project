import ast
from dataclasses import replace
from pathlib import Path

import pytest

from backend.modules.method_printing.document import MethodDocument
from backend.modules.method_printing.settings import PrintSettings
from backend.modules.methods.errors import MethodDomainError
from backend.modules.postprocessing.errors import PostProcessingError
from backend.modules.postprocessing.legacy_calculation import LegacyIntensity, legacy_net, recalculate_legacy


@pytest.mark.parametrize("pair,back,ratio,expected", [
    ((10, 1), 1, False, 9.0), ((10, 1), 0, False, 10.0),
    ((10, 2), 1, True, 5.0), ((1, 5), 1, False, 1e-5),
])
def test_net_intensity_runs_on_values_without_storage(pair, back, ratio, expected):
    assert legacy_net(pair, {"back": back}, background_ratio=ratio) == expected


def test_pure_legacy_curve_calculation_keeps_internal_standard_and_diagnostics():
    source = LegacyIntensity("source", [{"element": "Cu", "wavelength_nm": 324.754, "back": 1},
                                       {"element": "Fe", "wavelength_nm": 250.0, "back": 1}],
                             [], [[(10, 1), (20, 2)], [(5, 2), (10, 4)]], 2)
    lines = [{"id": "L1", "line_type": "analysis", "element": "Cu", "wavelength_nm": 324.754,
              "internal_standard_mode": "line", "internal_standard_line_id": "IS"},
             {"id": "IS", "line_type": "internal_standard", "element": "Fe", "wavelength_nm": 250.0}]
    evaluators = {"L1": {"fit": {"kind": "polynomial", "coefficients": [0, 2, 0, 0]},
                          "coordinate_type": "normal", "curve_snapshot_id": 7}}
    result = recalculate_legacy(source, lines, evaluators, "legacy_2_0_2")
    assert [line["quantitative_signal"] for line in result["lines"]] == [3, 3]
    assert [line["calculated_value"] for line in result["lines"]] == [6, 6]
    assert [line["sample_name"] for line in result["lines"]] == ["#1", "#2"]
    with pytest.raises(PostProcessingError) as missing:
        recalculate_legacy(source, lines, {}, "legacy_2_0_2")
    assert missing.value.code == "postprocessing_recalculation_no_lines"
    assert missing.value.details == {"diagnostics": [{"line_id": "L1", "code": "curve_snapshot_missing"}]}
    with pytest.raises(PostProcessingError) as background:
        legacy_net((10, 0), {"back": 1}, background_ratio=True)
    assert background.value.code == "postprocessing_background_invalid"


def test_document_geometry_and_pagination_accept_internal_settings():
    settings = PrintSettings("geospectrum-pdf", "A4", "portrait", 12, 12, 12, 12,
                             "standard", 9, 1, "none", False, True)
    document = MethodDocument()
    rows = [{"kind": "item", "label": str(index), "value": "x"} for index in range(100)]
    result = document._paginate(rows, settings)
    assert result["field_count"] == 100
    assert sum(len(page) for page in result["pages"]) == 100
    assert result["page_count"] > 1
    assert document._paper(replace(settings, paper="A3", orientation="landscape")) == (420, 297)
    with pytest.raises(MethodDomainError) as margins:
        document._validate_geometry(replace(settings, margin_left_mm=100, margin_right_mm=100))
    assert margins.value.code == "print_margin_width_invalid"


def test_calculation_modules_do_not_import_storage_requests_or_renderers():
    root = Path(__file__).resolve().parents[1] / "backend/modules"
    for relative in ("postprocessing/legacy_calculation.py", "method_printing/document.py", "method_printing/settings.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert all(not any(part in name.split(".") for part in ("sqlite3", "db", "schemas", "fastapi", "reportlab", "subprocess", "pathlib")) for name in modules), relative
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "Database"}, relative
