"""The shared print adapter must stay independent of business and storage modules."""

import ast
from pathlib import Path


def test_printing_adapter_has_only_technical_dependencies():
    backend = Path(__file__).resolve().parents[1] / "backend"
    allowed = {"__future__", "json", "os", "subprocess", "pathlib", "typing", "win32print", "win32api"}
    for path in (backend / "printing").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in allowed for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module.split(".")[0] in allowed, path
    report_source = (backend / "modules/reports.py").read_text(encoding="utf-8")
    assert "method_printing" not in report_source
    assert "MethodPrintService" not in report_source
