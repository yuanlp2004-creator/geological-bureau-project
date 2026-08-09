from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database
from backend.app.modules.sample_queues import SampleQueueError, SampleQueueService, _parse_lines


def test_sam_roundtrip_expands_800_records_to_960_bands(tmp_path: Path) -> None:
    database = Database(tmp_path / "samples.sqlite3")
    database.initialize()
    service = SampleQueueService(database)
    items = [{"pre_name": f"A{i:03d}", "repeats": 1 if i < 640 else 2} for i in range(800)]
    queue = service.create("golden", items, None)
    assert queue["record_count"] == 800
    assert queue["expanded_bands"] == 960
    content, digest = service.export_sam(queue["id"])
    source = tmp_path / "golden.sam"
    source.write_bytes(content)
    imported = service.import_sam(source, None, "imported")
    assert imported["record_count"] == 800
    assert imported["expanded_bands"] == 960
    assert imported["source_sha256"] == digest
    repeated = service.import_sam(source, None, "another-name")
    assert repeated["id"] == imported["id"]


def test_old_standard_names_empty_samples_and_invalid_import(tmp_path: Path) -> None:
    database = Database(tmp_path / "samples.sqlite3")
    database.initialize()
    service = SampleQueueService(database)
    queue = service.create("standards", [{"pre_name": "sa", "repeats": 3}, {"pre_name": ",", "repeats": 0}, {"pre_name": "unknown", "repeats": 0}], None)
    assert [item["pre_name"] for item in queue["items"]] == ["S10", "", "unknown"]
    assert queue["expanded_bands"] == 5

    bad = tmp_path / "bad.sam"
    bad.write_text("ok\t1\ninvalid-line\n", encoding="utf-8")
    with pytest.raises(SampleQueueError) as error:
        service.import_sam(bad, None, "bad")
    assert error.value.code == "sam_import_invalid"
    assert service.list() and [queue["name"] for queue in service.list()] == ["standards"]


def test_post_acquisition_rename_preserves_spectrum_hash_and_audits(tmp_path: Path) -> None:
    database = Database(tmp_path / "samples.sqlite3")
    database.initialize()
    service = SampleQueueService(database)
    queue = service.create("rename", [{"pre_name": "A", "repeats": 1, "spectrum_hash": "a" * 64}], None)
    item_id = queue["items"][0]["id"]
    renamed = service.rename(queue["id"], item_id, "B", None)
    assert renamed["items"][0]["post_name"] == "B"
    assert renamed["items"][0]["spectrum_hash"] == "a" * 64
    audit = database.connect().execute("SELECT action, details_json FROM audit_events WHERE action='sample_queue.rename'").fetchone()
    assert audit[0] == "sample_queue.rename"
    assert '"spectrum_hash"' in audit[1]


def test_sample_queue_api_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = main_module.Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert client.get("/api/v1/sample-queues").status_code == 401
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = client.post("/api/v1/sample-queues", headers=headers, json={"name": "api", "items": [{"pre_name": "A", "repeats": 2}]})
        assert created.status_code == 201
        queue_id = created.json()["id"]
        imported = client.post("/api/v1/sample-queues/import", headers=headers, json={"filename": "upload.sam", "content": "S0\t1\n,\t0\n"})
        assert imported.status_code == 201
        assert imported.json()["expanded_bands"] == 2
        exported = client.get(f"/api/v1/sample-queues/{queue_id}/export", headers=headers)
        assert exported.status_code == 200
        assert exported.headers["x-source-sha256"]
