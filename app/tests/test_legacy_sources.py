from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.modules import legacy_sources
from backend.modules.legacy_migration import LegacyMigrationError


def test_default_roots_find_checkout_sources_from_unrelated_cwd(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    module = checkout / "app" / "backend" / "modules" / "legacy_sources.py"
    module.parent.mkdir(parents=True)
    legacy = checkout / "Spec2.02"
    legacy.mkdir()
    monkeypatch.setattr(legacy_sources, "__file__", str(module))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.chdir(tmp_path)
    assert legacy.resolve() in legacy_sources.default_roots()


def test_discovery_pairs_only_same_directory_and_preserves_sources(tmp_path):
    for folder, names in (("旧版", ["direct.MTD", "DIRECT.cfg", "Direct.OPT", "光谱.CDT", "结果.pdt"]),
                          ("缺配置", ["DIRECT.MTD", "other.CFG"]), (".local", ["hidden.cdt"])):
        directory = tmp_path / folder
        directory.mkdir()
        for name in names:
            (directory / name).write_bytes(b"discovery does not parse or modify")
    def facts():
        return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in tmp_path.rglob('*') if p.is_file()}
    before = facts()
    methods = legacy_sources.discover_sources("methods", str(tmp_path))["candidates"]
    complete = next(item for item in methods if not item["missing"])
    assert Path(complete["paths"]["cfg_path"]).parent == tmp_path / "旧版"
    assert next(item for item in methods if item["missing"])["missing"] == ["DIRECT.CFG", "DIRECT.OPT"]
    assert [x["name"] for x in legacy_sources.discover_sources("spectra", str(tmp_path))["candidates"]] == ["光谱.CDT"]
    assert [x["name"] for x in legacy_sources.discover_sources("results", str(tmp_path))["candidates"]] == ["结果.pdt"]
    assert facts() == before


def test_invalid_directory_and_scan_limit(tmp_path, monkeypatch):
    with pytest.raises(LegacyMigrationError, match="不存在"):
        legacy_sources.discover_sources("methods", str(tmp_path / "missing"))
    for index in range(5):
        (tmp_path / f'{index}.cdt').write_bytes(b'')
    monkeypatch.setattr(legacy_sources, "MAX_CANDIDATES", 2)
    scan = legacy_sources.discover_sources("spectra", str(tmp_path))
    assert scan["truncated"] and len(scan["candidates"]) == 2 and scan["warnings"]


def test_frozen_discovery_uses_executable_location(tmp_path, monkeypatch):
    root = tmp_path / "安装" / "Spec2.02"
    root.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(root.parent / "geospectrum-backend.exe"))
    monkeypatch.chdir(tmp_path)
    assert root in legacy_sources.default_roots()


def test_discovery_api_permissions_and_no_database_import(tmp_path, monkeypatch):
    import backend.main as main
    from backend.config import AppConfig
    from dataclasses import replace
    config = AppConfig(data_dir=tmp_path / "runtime")
    application = main.create_app(config)
    runtime = application.state.runtime
    database = runtime.database
    with TestClient(application) as client:
        for kind in ("legacy-migration", "spectrum-migration", "result-migration"):
            assert client.get(f"/api/v1/{kind}/sources").status_code == 401
        client.post('/api/v1/auth/bootstrap', json={"username": "tester", "password": "test-password-123"})
        token = client.post('/api/v1/auth/login', json={"username": "tester", "password": "test-password-123"}).json()['access_token']
        headers = {"Authorization": f"Bearer {token}"}
        for kind in ("legacy-migration", "spectrum-migration", "result-migration"):
            response = client.get(f"/api/v1/{kind}/sources", params={"root": str(tmp_path)}, headers=headers)
            assert response.status_code == 200
            assert response.json()['candidates'] == []
        assert client.get('/api/v1/legacy-migration/sources', params={"root": str(tmp_path / 'missing')}, headers=headers).status_code == 422
        original_session = runtime.auth_service.sessions[token]
        runtime.auth_service.sessions[token] = replace(original_session, permissions=frozenset({'migration.read'}))
        assert client.get('/api/v1/legacy-migration/sources', headers=headers).status_code == 200
        for kind in ('spectrum-migration', 'result-migration'):
            assert client.get(f'/api/v1/{kind}/sources', headers=headers).status_code == 403
        runtime.auth_service.sessions[token] = original_session
        with database.read() as connection:
            assert connection.execute('SELECT COUNT(*) FROM methods').fetchone()[0] == 0
            assert connection.execute('SELECT COUNT(*) FROM spectrum_bands').fetchone()[0] == 0
