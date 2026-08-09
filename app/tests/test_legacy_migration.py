from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parent
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.legacy_migration import LegacyMigrationError, LegacyMigrationService


SOURCES = {
    "mtd": PROJECT_ROOT / "Spec2.02" / "DIRECT.MTD",
    "cfg": PROJECT_ROOT / "Spec2.02" / "DIRECT.CFG",
    "opt": PROJECT_ROOT / "Spec2.02" / "DIRECT.OPT",
}


def _facts(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def _real_reader_or_skip(service: LegacyMigrationService) -> None:
    diagnostic = service.diagnostics()
    if not diagnostic["available"]:
        pytest.skip(diagnostic["message"])


def test_real_direct_source_set_is_read_only_validated_and_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "migration.sqlite3")
    database.initialize()
    service = LegacyMigrationService(database)
    _real_reader_or_skip(service)
    before = {name: _facts(path) for name, path in SOURCES.items()}
    lock_files_before = {path.name for path in SOURCES["mtd"].parent.glob("*.ldb")}

    staged = service.stage(*(str(SOURCES[name]) for name in ("mtd", "cfg", "opt")), None)
    assert staged["status"] == "staged"
    assert staged["staging"]["counts"] == {
        "methods": 3,
        "spectral_lines": 20,
        "dispersion_curves": 5,
        "users_ignored": 0,
    }
    assert all(staged["staging"]["checks"].values())
    standard_blobs = [
        line["standards_blob"]
        for method in staged["staging"]["methods"]
        for line in method["evidence"]["lines"]
    ]
    assert {item["byte_length"] for item in standard_blobs} == {224, 700}
    assert all(len(item["sha256"]) == 64 for item in standard_blobs)
    assert staged["staging"]["configuration"]["opt"]["normalized"]["communication"] == {
        "port": 3,
        "baud": 460800,
    }

    committed = service.commit(staged["id"], None)
    assert committed["status"] == "committed"
    assert committed["report"]["checks"]["atomic_commit"] is True
    assert committed["report"]["checks"]["target_validation_passed"] is True
    with database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM methods").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM legacy_configuration_profiles").fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM legacy_import_entities WHERE entity_type='dispersion_calibration'"
        ).fetchone()[0] == 5
        payloads = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM method_versions").fetchall()]
        assert sum(len(payload["lines"]) - 1 for payload in payloads) == 20
        assert all(row[0] == "[]" for row in db.execute("SELECT validation_errors_json FROM method_versions"))
        counts_before_repeat = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("methods", "method_versions", "dispersion_calibrations", "legacy_import_entities")
        }

    repeated = service.stage(*(str(SOURCES[name]) for name in ("mtd", "cfg", "opt")), None)
    assert repeated["status"] == "committed"
    assert repeated["already_committed"] is True
    with database.read() as db:
        assert counts_before_repeat == {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in counts_before_repeat
        }

    assert before == {name: _facts(path) for name, path in SOURCES.items()}
    assert lock_files_before == {path.name for path in SOURCES["mtd"].parent.glob("*.ldb")}


def test_commit_failure_rolls_back_every_target_record(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "rollback.sqlite3")
    database.initialize()
    service = LegacyMigrationService(database)
    _real_reader_or_skip(service)
    staged = service.stage(*(str(SOURCES[name]) for name in ("mtd", "cfg", "opt")), None)

    def fail_after_first_method(entity_type: str, _legacy_key: str) -> None:
        if entity_type == "method":
            raise RuntimeError("injected atomic rollback")

    monkeypatch.setattr(service, "_after_entity_insert", fail_after_first_method)
    with pytest.raises(LegacyMigrationError) as failure:
        service.commit(staged["id"], None)
    assert failure.value.code == "legacy_commit_failed"
    with database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM methods").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM dispersion_calibrations").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ccd_layouts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM legacy_import_entities").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM legacy_configuration_profiles").fetchone()[0] == 0
        run = db.execute("SELECT status, error_code FROM legacy_migration_runs WHERE id=?", (staged["id"],)).fetchone()
        assert tuple(run) == ("failed", "legacy_commit_failed")


def test_missing_jet_is_stable_and_does_not_affect_api_startup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(LegacyMigrationService, "_reader_candidates", staticmethod(lambda: []))
    database = Database(tmp_path / "no-jet.sqlite3")
    database.initialize()
    diagnostic = LegacyMigrationService(database).diagnostics()
    assert diagnostic["available"] is False
    assert diagnostic["code"] == "legacy_reader_unavailable"

    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path / "api"))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path / "api")
    main_module.config = config_module.config
    main_module.database = main_module.Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, config_module.config.runtime_log_path)
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/legacy-migration/diagnostics").status_code == 401
        assert client.post(
            "/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}
        ).status_code == 201
        login = client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get("/api/v1/legacy-migration/diagnostics", headers=headers)
        assert response.status_code == 200
        assert response.json()["code"] == "legacy_reader_unavailable"
