from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.db import Database
from backend.modules.sample_queues import SampleQueueError, SampleQueueService, read_sample_numbers


@pytest.mark.parametrize(('name', 'encoding'), [
    ('001', 'ascii'), ('样1', 'gb18030'), ('样1', 'utf-8'), ('Ǧ1', 'utf-8-sig'),
])
def test_sam_automatic_encoding(name: str, encoding: str) -> None:
    assert read_sample_numbers(f'{name}\t2\r\n'.encode(encoding)) == [{'name': name, 'repeats': 2}]


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
    queue = service.create(
        "standards",
        [{"pre_name": "sa", "repeats": 3}, {"pre_name": ",", "repeats": 0}, {"pre_name": "unknown", "repeats": 0}],
        None,
    )
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
    audit = (
        database.connect()
        .execute("SELECT action, details_json FROM audit_events WHERE action='sample_queue.rename'")
        .fetchone()
    )
    assert audit[0] == "sample_queue.rename"
    assert '"spectrum_hash"' in audit[1]


def test_sample_queue_api_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.config as config_module
    import backend.main as main_module

    test_config = config_module.AppConfig(data_dir=tmp_path)
    application = main_module.create_app(test_config)
    runtime = application.state.runtime
    with TestClient(application) as client:
        assert client.get("/api/v1/sample-queues").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}
            ).status_code
            == 201
        )
        login = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = client.post(
            "/api/v1/sample-queues", headers=headers, json={"name": "api", "items": [{"pre_name": "A", "repeats": 2}]}
        )
        assert created.status_code == 201
        queue_id = created.json()["id"]
        imported = client.post(
            "/api/v1/sample-queues/import", headers=headers, json={"filename": "upload.sam", "content": "S0\t1\n,\t0\n"}
        )
        assert imported.status_code == 201
        assert imported.json()["expanded_bands"] == 2
        ambiguous = b'001\t1\r\n' + '铅1\t2\r\n'.encode('gb18030')
        original_queues = client.get('/api/v1/sample-queues', headers=headers).json()
        encoded = {'content_base64': base64.b64encode(ambiguous).decode('ascii')}
        payload = {**encoded, 'filename': 'ambiguous.sam'}
        pending = client.post('/api/v1/sample-queues/import', headers=headers, json=payload)
        assert pending.status_code == 409
        assert pending.json()['detail']['code'] == 'sam_encoding_ambiguous'
        assert pending.json()['detail']['details']['differences'] == [{'line': 2, 'gb18030': '铅1', 'utf8': 'Ǧ1'}]
        assert client.get('/api/v1/sample-queues', headers=headers).json() == original_queues
        read_url = '/api/v1/analyses/sample-numbers/read'
        preview = client.post(read_url, headers=headers, json=encoded)
        assert preview.status_code == 409
        assert preview.json()['detail'] == pending.json()['detail']
        legacy = client.post(read_url, headers=headers, json={**encoded, 'encoding': 'gb18030'})
        assert legacy.json()['entries'] == [{'name': '001', 'repeats': 1}, {'name': '铅1', 'repeats': 2}]
        confirmed = client.post('/api/v1/sample-queues/import', headers=headers, json={**payload, 'encoding': 'utf-8-sig'})
        assert confirmed.status_code == 201
        assert confirmed.json()['items'][1]['pre_name'] == 'Ǧ1'
        reopened = client.post('/api/v1/sample-queues/import', headers=headers, json=payload)
        assert reopened.status_code == 201
        assert reopened.json()['id'] == confirmed.json()['id']
        exported = client.get(f"/api/v1/sample-queues/{queue_id}/export", headers=headers)
        assert exported.status_code == 200
        assert exported.headers["x-source-sha256"]
