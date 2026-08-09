from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))


def test_s01_api_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    import backend.app.main as main_module

    main_module.config = config_module.config
    main_module.database = main_module.Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/health").status_code == 200
        assert client.get("/about").json()["stage"].startswith("S10")
        capabilities = client.get("/api/v1/capabilities")
        assert capabilities.status_code == 200
        assert {item["key"] for item in capabilities.json()["capabilities"]} == {
            "core", "about-diagnostics", "auth", "methods", "legacy-migration", "sample-queues", "spectrum-migration", "result-migration", "spectrum-viewer"
        }
        diagnostics = client.get("/api/v1/diagnostics")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["sqlite_integrity"] == "ok"
        assert diagnostics.json()["journal_mode"].lower() == "wal"
        settings = client.get("/api/v1/settings", headers=headers)
        assert settings.status_code == 200
        assert settings.json()["directories"]["data"] == "data"
        updated = client.patch("/api/v1/settings", headers=headers, json={"display": {"density": "compact"}})
        assert updated.status_code == 200
        assert updated.json()["display"]["density"] == "compact"
        invalid = client.patch("/api/v1/settings", headers=headers, json={"display": {"unknown": True}})
        assert invalid.status_code == 422
        reset = client.post("/api/v1/settings/reset", headers=headers)
        assert reset.status_code == 200
        assert reset.json()["display"]["density"] == "comfortable"
        created = client.post("/api/v1/logs", headers=headers, json={"category": "action", "severity": "info", "message": "测试事件"})
        assert created.status_code == 201
        assert client.get("/api/v1/logs?severity=info", headers=headers).json()[0]["message"] == "测试事件"
        assert client.delete("/api/v1/logs", headers=headers).status_code == 200

        with client.websocket_connect(f"/ws/events?access_token={token}") as websocket:
            assert websocket.receive_json() == {"type": "ready", "api_version": "v1"}
            streamed = client.post("/api/v1/logs", headers=headers, json={"category": "import", "severity": "info", "message": "推送事件"})
            assert streamed.status_code == 201
            pushed = websocket.receive_json()
            assert pushed["type"] == "runtime_event"
            assert pushed["event"]["message"] == "推送事件"
