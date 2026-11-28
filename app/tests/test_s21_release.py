from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import upgrade
from backend.config import AppConfig
from backend.runtime import Runtime
from backend.db import Database, SCHEMA_VERSION
from backend.modules.manifest import registered_manifests
from backend.upgrade import UpgradeError, prepare_database_upgrade, prepare_legacy_data_directory
from backend.sidecar_entry import _read_process_key
from tools import build_release_manifest
from tests.s21_test_build import create_test_build


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("source_changes", [False, True])
def test_upgrade_is_verified_on_copy_and_preserves_data(tmp_path: Path, monkeypatch, source_changes) -> None:
    path = tmp_path / "GeoSpectrum" / "geospectrum.sqlite3"
    path.parent.mkdir()
    database = Database(tmp_path / "wal-source.sqlite3")
    database.initialize()
    with closing(database.connect()) as connection:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            (
                "INSERT INTO methods(name, description, work_type, status, created_at, "
                "updated_at) VALUES ('upgrade-fixture', '', 'spectral', 'active', 'now', 'now')"
            )
        )
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,))
        connection.commit()
        shutil.copy2(database.path, path)
        shutil.copy2(database.path.with_suffix(".sqlite3-wal"), path.with_suffix(".sqlite3-wal"))
    if source_changes:
        initialize = Database.initialize

        def initialize_and_update_source(staged):
            initialize(staged)
            with Database(path).write() as connection:
                connection.execute("UPDATE methods SET description='new user data' WHERE name='upgrade-fixture'")

        monkeypatch.setattr(Database, "initialize", initialize_and_update_source)
        with pytest.raises(UpgradeError, match="database changed before switching"):
            prepare_database_upgrade(path)
        with Database(path).read() as connection:
            assert connection.execute("SELECT description FROM methods WHERE name='upgrade-fixture'").fetchone()[0] == (
                "new user data"
            )
            assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == SCHEMA_VERSION - 1
        return
    result = prepare_database_upgrade(path)
    assert result["status"] == "upgraded"
    assert result["to_schema_version"] == SCHEMA_VERSION
    assert Path(result["backup_path"]).exists()
    for preserved in (path, Path(result["backup_path"])):
        with closing(sqlite3.connect(preserved)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM methods WHERE name='upgrade-fixture'").fetchone()[0] == 1
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("version", [SCHEMA_VERSION, SCHEMA_VERSION + 1])
def test_upgrade_preflight_reads_live_wal_without_copy_hash_or_full_checks(tmp_path, monkeypatch, version):
    database = Database(tmp_path / "geospectrum.sqlite3")
    database.initialize()
    connect = upgrade._connect_readonly
    trace = []

    def traced_readonly(path):
        connection = connect(path)
        connection.set_trace_callback(trace.append)
        return connection

    def unexpected(*args, **kwargs):
        pytest.fail("preflight must not snapshot, copy, hash, or fully inspect the database")

    with closing(database.connect()) as writer:
        writer.execute("DELETE FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,))
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO schema_migrations VALUES (?, 'only in WAL')", (version,))
        writer.commit()
        wal = database.path.with_suffix(".sqlite3-wal")
        before = _hash(database.path), _hash(wal)
        with monkeypatch.context() as patch:
            patch.setattr(upgrade, "_connect_readonly", traced_readonly)
            for operation in ("_source_snapshot", "_sha256", "_inspect"):
                patch.setattr(upgrade, operation, unexpected)
            patch.setattr(upgrade.shutil, "copy2", unexpected)
            if version == SCHEMA_VERSION:
                assert prepare_database_upgrade(database.path) == {"status": "not_required", "schema_version": version}
            else:
                with pytest.raises(UpgradeError, match="newer than application schema"):
                    prepare_database_upgrade(database.path)
        assert trace and not any("integrity_check" in sql or "foreign_key_check" in sql for sql in trace)
        assert (_hash(database.path), _hash(wal)) == before


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


def test_manifest_only_test_module_connects_every_contract(tmp_path: Path) -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "s21-example-module"
    application = create_test_build(AppConfig(data_dir=tmp_path), fixture_root)
    database = application.state.runtime.database
    extension_route = "/test-s21-example"
    endpoint = "/api/v1/extensions/s21-example/execute"
    credentials = {"username": "admin", "password": "correct-horse"}
    with TestClient(application) as client:
        manifests = client.get("/test-build/manifest").json()["modules"]
        extension = next(item for item in manifests if item["key"] == "s21-example")
        assert extension["route"] == extension_route
        assert extension["permissions"] == ["s21-example.execute"]
        assert set(extension["capabilities"]) == {"event:s21-example.executed.v1", "tauri:dialog:allow-open"}
        assert extension["navigation_entries"][0]["required_any"] == extension["permissions"]
        assert f'href="{extension_route}"' in client.get("/test-build").text
        assert endpoint in client.get(extension_route).text

        assert client.post("/api/v1/auth/bootstrap", json=credentials).status_code == 201
        login = client.post("/api/v1/auth/login", json=credentials).json()
        assert "s21-example.execute" in login["user"]["permissions"]
        token = login["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post(endpoint).status_code == 401
        viewer = {"username": "viewer", "password": "correct-guest"}
        assert client.post("/api/v1/users", json=viewer, headers=headers).status_code == 201
        viewer_token = client.post("/api/v1/auth/login", json=viewer).json()["access_token"]
        assert client.post(endpoint, headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 403
        with client.websocket_connect(f"/ws/events?access_token={token}") as events:
            assert events.receive_json()["type"] == "ready"
            response = client.post(endpoint, headers=headers)
            assert response.status_code == 200
            assert response.json()["event_type"] == "s21-example.executed.v1"
            message = events.receive_json()
            assert message["type"] == "runtime_event"
            event = message["event"]
            assert event["type"] == "s21-example.executed.v1" and event["version"] == 1
            assert event["event"]["details"]["event_version"] == 1

    database.initialize()
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM s21_example_records").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM extension_schema_migrations").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='s21_example.execute'"
        ).fetchone()[0] == 1


def test_formal_startup_ignores_test_build_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import create_app

    fixture_root = Path(__file__).parent / "fixtures" / "s21-example-module"
    monkeypatch.setenv("GEOSPECTRUM_TEST_BUILD", "1")
    monkeypatch.setenv("GEOSPECTRUM_TEST_MODULES_DIR", str(fixture_root))
    config = AppConfig(data_dir=tmp_path)
    database = Database(config.database_path)
    database.initialize()
    manifests = registered_manifests()
    assert registered_manifests() is manifests
    assert all(not manifest.key.startswith("s21-") for manifest in manifests)
    app = create_app(config)
    assert "/api/v1/extensions/s21-example/execute" not in app.openapi()["paths"]
    credentials = {"username": "admin", "password": "correct-horse"}
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/capabilities").json()["capabilities"]
        assert [item["key"] for item in capabilities] == [manifest.key for manifest in manifests]
        assert client.post("/api/v1/auth/bootstrap", json=credentials).status_code == 201
        login = client.post("/api/v1/auth/login", json=credentials).json()
        assert "s21-example.execute" not in login["user"]["permissions"]
        assert client.get("/test-s21-example").status_code == 404
    with database.read() as connection:
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN ('s21_example_records', 'extension_schema_migrations')"
        ).fetchone()


def test_release_manifest_rejects_test_build_modules(tmp_path: Path) -> None:
    generated = Path(__file__).parents[1] / "manifest.generated.json"
    modules = json.loads(generated.read_text(encoding="utf-8"))["modules"]
    assert build_release_manifest.formal_module_keys(generated) == [module.key for module in registered_manifests()]
    contaminated = tmp_path / "manifest.json"
    for extension in ({"key": "s21-example"}, {"key": "other", "navigation_entries": [{"status": "test_only"}]}):
        contaminated.write_text(json.dumps({"modules": [*modules, extension]}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="test-only extension leaked"):
            build_release_manifest.formal_module_keys(contaminated)


def test_process_key_blocks_untrusted_loopback_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.main as main_module

    runtime = Runtime(AppConfig(data_dir=tmp_path), process_key="one-time-key")
    with TestClient(main_module.create_app(runtime=runtime)) as client:
        assert client.get("/health").status_code == 403
        assert client.get("/health", headers={"X-GeoSpectrum-Process-Key": "one-time-key"}).status_code == 200


def test_windows_tauri_origin_can_reach_login_preflight_while_unknown_origins_are_rejected(tmp_path: Path) -> None:
    import backend.main as main_module

    preflight_headers = {
        "Origin": "http://tauri.localhost",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-geospectrum-process-key",
    }
    with TestClient(main_module.create_app(AppConfig(data_dir=tmp_path))) as client:
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
    assert '"GEOSPECTRUM_PROCESS_KEY"' not in rust_source


def test_windows_release_requires_embedded_offline_webview() -> None:
    config = json.loads((Path(__file__).parents[1] / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["bundle"]["windows"]["webviewInstallMode"]["type"] == "offlineInstaller"


def test_internal_release_requires_all_software_acceptance_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "docs" / "acceptance-reports"
    acceptance.mkdir(parents=True)
    statuses_fixture = {
        f"S{number:02d}": "deferred_external" if number in {1, 14, 15} else "passed" for number in range(21)
    }
    index = "\n".join(f"| {step} | `{status}` | report |" for step, status in statuses_fixture.items())
    (acceptance / "README.md").write_text(index, encoding="utf-8")
    monkeypatch.setattr(build_release_manifest, "REPO_ROOT", tmp_path)
    statuses = build_release_manifest.acceptance_statuses()
    assert statuses["S17"] == statuses["S18"] == statuses["S19"] == statuses["S20"] == "passed"
    assert statuses["S14"] == statuses["S15"] == "deferred_external"

    (acceptance / "README.md").write_text(
        index.replace("| S17 | `passed` |", "| S17 | `in_progress` |"), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="S17"):
        build_release_manifest.acceptance_statuses()


@pytest.mark.parametrize(
    ("step_status", "expected_error"),
    [
        ("passed", None),
        (None, r"missing software gates: \['S17'\]"),
        ("failed", r"software acceptance gates are not closed: \{'S17': 'failed'\}"),
        ("deferred_external", r"software acceptance gates are not closed: \{'S17': 'deferred_external'\}"),
    ],
)
def test_acceptance_statuses_parse_linked_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step_status: str | None, expected_error: str | None
) -> None:
    acceptance = tmp_path / "docs" / "acceptance-reports"
    acceptance.mkdir(parents=True)
    statuses = {f"S{number:02d}": "passed" for number in range(21)}
    if step_status is None:
        del statuses["S17"]
    else:
        statuses["S17"] = step_status
    rows = ["| 步骤 | 当前状态 |", "|---|---|"]
    rows.extend(f"| [{step}]({step}/验收报告.md) | {status} |" for step, status in statuses.items())
    (acceptance / "README.md").write_text("\n".join(rows), encoding="utf-8")
    monkeypatch.setattr(build_release_manifest, "REPO_ROOT", tmp_path)

    if expected_error is None:
        assert build_release_manifest.acceptance_statuses() == statuses
    else:
        with pytest.raises(RuntimeError, match=expected_error):
            build_release_manifest.acceptance_statuses()


def test_acceptance_statuses_parse_repository_index() -> None:
    statuses = build_release_manifest.acceptance_statuses()
    assert set(statuses) == {f"S{number:02d}" for number in range(21)}
