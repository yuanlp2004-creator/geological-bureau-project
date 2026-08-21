from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path

from backend.app.modules.legacy_migration import LegacyMigrationService
from tools.runtime_resources import REPO_ROOT, RESOURCE_ROOT, load_runtime_resources


def test_runtime_resource_manifest_matches_packaged_files_and_read_only_sources() -> None:
    manifest = load_runtime_resources()
    assert {item["key"] for item in manifest["resources"]} == {
        "simulator.280-288",
        "simulator.291-299",
        "simulator.303-310",
        "legacy-reader.powershell",
    }
    for item in manifest["resources"]:
        packaged = RESOURCE_ROOT / item["path"]
        source = REPO_ROOT / item["source"]
        assert packaged.read_bytes() == source.read_bytes()
        assert hashlib.sha256(packaged.read_bytes()).hexdigest().upper() == item["sha256"]


def test_runtime_modules_resolve_only_app_owned_resources() -> None:
    sample = files("backend.app.resources.simulator").joinpath("280-288.acq")
    reader = files("backend.app.resources.legacy_reader").joinpath("read_access.ps1")
    assert sample.is_file() and reader.is_file()

    devices_source = (RESOURCE_ROOT.parent / "modules" / "devices.py").read_text(encoding="utf-8")
    assert "Spec Source" not in devices_source
    candidates = dict(LegacyMigrationService._reader_candidates())
    if "windows-powershell-x86" in candidates:
        command = candidates["windows-powershell-x86"]
        script = Path(command[command.index("-File") + 1])
        assert script.is_file()
        assert script.resolve() == Path(str(reader)).resolve()
