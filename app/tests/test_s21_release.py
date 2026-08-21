from __future__ import annotations

import hashlib
import io
import importlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthService
from backend.app.db import Database, SCHEMA_VERSION
from backend.app.modules.manifest import registered_manifests
from backend.app.upgrade import UpgradeError, prepare_database_upgrade, prepare_legacy_data_directory
from backend.sidecar_entry import _read_process_key
from tools import build_release_manifest


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_upgrade_is_verified_on_copy_and_preserves_data(tmp_path: Path) -> None:
    path = tmp_path / "GeoSpectrum" / "geospectrum.sqlite3"
    database = Database(path)
    database.initialize()
    with database.write() as connection:
        connection.execute("INSERT INTO methods(name, description, work_type, status, created_at, updated_at) VALUES ('upgrade-fixture', '', 'spectral', 'active', 'now', 'now')")
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,))
    result = prepare_database_upgrade(path)
    assert result["status"] == "upgraded"
    assert result["to_schema_version"] == SCHEMA_VERSION
    assert Path(result["backup_path"]).exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM methods WHERE name='upgrade-fixture'").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_corrupt_upgrade_never_replaces_current_database(tmp_path: Path) -> None:
    path = tmp_path / "GeoSpectrum" / "geospectrum.sqlite3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not-a-sqlite-database")
    before = path.read_bytes()
    with pytest.raises(UpgradeError):
        prepare_database_upgrade(path)
    assert path.read_bytes() == before


def test_legacy_install_adjacent_data_is_copied_and_preserved(tmp_path: Path) -> None:
    legacy = tmp_path / "GeoSpectrum"
    target = tmp_path / "cn.geospectrum.desktop"
    database_path = legacy / "geospectrum.sqlite3"
    database = Database(database_path)
    database.initialize()
    with database.write() as connection:
        connection.execute(
            "INSERT INTO methods(name, description, work_type, status, created_at, updated_at) "
            "VALUES ('legacy-user-data', '', 'spectral', 'active', 'now', 'now')"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,))
    (legacy / "geospectrum.exe").write_bytes(b"installer-resource")
    (legacy / "logs").mkdir()
    (legacy / "logs" / "runtime.jsonl").write_text("preserved\n", encoding="utf-8")
    legacy_bytes = database_path.read_bytes()

    result = prepare_legacy_data_directory(legacy, target)
    assert result["status"] == "migrated"
    assert result["legacy_preserved"] is True
    assert database_path.read_bytes() == legacy_bytes
    assert not (target / "geospectrum.exe").exists()
    assert (target / "logs" / "runtime.jsonl").read_text(encoding="utf-8") == "preserved\n"
    assert prepare_database_upgrade(target / "geospectrum.sqlite3")["to_schema_version"] == SCHEMA_VERSION
    with sqlite3.connect(target / "geospectrum.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM methods WHERE name='legacy-user-data'").fetchone()[0] == 1


def test_legacy_migration_reads_live_wal_without_writing_source(tmp_path: Path) -> None:
    legacy = tmp_path / "GeoSpectrum"
    target = tmp_path / "cn.geospectrum.desktop"
    path = legacy / "geospectrum.sqlite3"
    Database(path).initialize()
    keeper = sqlite3.connect(path)
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO methods(name, description, work_type, status, created_at, updated_at) "
            "VALUES ('live-wal-user-data', '', 'spectral', 'active', 'now', 'now')"
        )
        writer.commit()
        source_files = [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]
        before = {source.name: _hash(source) for source in source_files}
        result = prepare_legacy_data_directory(legacy, target)
        after = {source.name: _hash(source) for source in source_files}
        assert result["status"] == "migrated"
        assert after == before
        with sqlite3.connect(target / "geospectrum.sqlite3") as copied:
            assert copied.execute("SELECT COUNT(*) FROM methods WHERE name='live-wal-user-data'").fetchone()[0] == 1
    finally:
        writer.close()
        keeper.close()


def test_manifest_only_test_module_connects_every_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "s21-example-module"
    monkeypatch.setenv("GEOSPECTRUM_TEST_BUILD", "1")
    monkeypatch.setenv("GEOSPECTRUM_TEST_MODULES_DIR", str(fixture_root))
    monkeypatch.delenv("GEOSPECTRUM_PROCESS_KEY", raising=False)
    database = Database(tmp_path / "geospectrum.sqlite3")
    database.initialize()
    manifests = registered_manifests()
    extension = next(item for item in manifests if item.key == "s21-example")
    assert extension.route == "/test-s21-example"
    assert extension.permissions == ("s21-example.execute",)
    assert "event:s21-example.executed.v1" in extension.capabilities
    with database.read() as connection:
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='s21_example_records'").fetchone()

    import backend.app.main as main_module
    main_module = importlib.reload(main_module)
    main_module.database = database
    main_module.service = main_module.AppService(database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = AuthService(database)
    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/auth/bootstrap", json={"username": "admin", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-horse"}).json()["access_token"]
        response = client.post("/api/v1/extensions/s21-example/execute", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["event_type"] == "s21-example.executed.v1"
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM s21_example_records").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='s21_example.execute'").fetchone()[0] == 1

    monkeypatch.delenv("GEOSPECTRUM_TEST_BUILD")
    monkeypatch.delenv("GEOSPECTRUM_TEST_MODULES_DIR")
    formal = json.loads((Path(__file__).parents[1] / "manifest.generated.json").read_text(encoding="utf-8"))
    assert "s21-example" not in {item["key"] for item in formal["modules"]}


def test_process_key_blocks_untrusted_loopback_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.app.main as main_module
    monkeypatch.setattr(main_module, "PROCESS_KEY", "one-time-key")
    main_module.database = Database(tmp_path / "key.sqlite3")
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 403
        assert client.get("/health", headers={"X-GeoSpectrum-Process-Key": "one-time-key"}).status_code == 200


def test_windows_tauri_origin_can_reach_login_preflight_while_unknown_origins_are_rejected() -> None:
    import backend.app.main as main_module

    preflight_headers = {
        "Origin": "http://tauri.localhost",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-geospectrum-process-key",
    }
    with TestClient(main_module.app) as client:
        response = client.options("/api/v1/auth/login", headers=preflight_headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"

        rejected = client.options(
            "/api/v1/auth/login",
            headers={**preflight_headers, "Origin": "http://untrusted.localhost"},
        )
        assert rejected.status_code == 400
        assert "access-control-allow-origin" not in rejected.headers


def test_process_key_is_read_from_anonymous_stdin_pipe() -> None:
    assert _read_process_key(io.BytesIO(b"0123456789abcdef0123456789abcdef\n")) == "0123456789abcdef0123456789abcdef"
    with pytest.raises(RuntimeError):
        _read_process_key(io.BytesIO(b"secret-from-command-line\n"))
    rust_source = (Path(__file__).parents[1] / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert 'env("GEOSPECTRUM_PROCESS_KEY"' not in rust_source
    assert "child.write" in rust_source


def test_windows_release_requires_embedded_offline_webview() -> None:
    config = json.loads((Path(__file__).parents[1] / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["bundle"]["windows"]["webviewInstallMode"]["type"] == "offlineInstaller"


def test_internal_release_requires_all_software_acceptance_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    acceptance = tmp_path / "docs" / "acceptance-reports"
    acceptance.mkdir(parents=True)
    statuses_fixture = {
        f"S{number:02d}": "deferred_external" if number in {1, 14, 15} else "passed"
        for number in range(21)
    }
    index = "\n".join(
        f"| {step} | `{status}` | report |" for step, status in statuses_fixture.items()
    )
    (acceptance / "README.md").write_text(index, encoding="utf-8")
    monkeypatch.setattr(build_release_manifest, "REPO_ROOT", tmp_path)
    statuses = build_release_manifest.acceptance_statuses()
    assert statuses["S17"] == statuses["S18"] == statuses["S19"] == statuses["S20"] == "passed"
    assert statuses["S14"] == statuses["S15"] == "deferred_external"

    (acceptance / "README.md").write_text(index.replace("| S17 | `passed` |", "| S17 | `in_progress` |"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="S17"):
        build_release_manifest.acceptance_statuses()
