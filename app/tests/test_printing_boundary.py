"""The shared print adapter must stay independent of business and storage modules."""

import ast
from pathlib import Path


def test_printing_adapter_has_only_technical_dependencies():
    backend = Path(__file__).resolve().parents[1] / "backend"
    forbidden = {"api", "backend", "db", "fastapi", "modules", "sqlite3"}
    for path in (backend / "printing").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert not forbidden.intersection(alias.name.split(".")[0] for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert node.level <= 1, path
                assert (node.module or "").split(".")[0] not in forbidden, path

    reports = backend / "modules/reports/service.py"
    for node in ast.walk(ast.parse(reports.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            assert all("method_printing" not in name.split(".") for name in names), reports
