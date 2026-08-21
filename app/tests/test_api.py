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
        assert client.get("/about", headers=headers).json()["stage"] == "S21 · Windows 内部测试发布"
        capabilities = client.get("/api/v1/capabilities")
        assert capabilities.status_code == 200
        assert {item["key"] for item in capabilities.json()["capabilities"]} == {
                "core", "about-diagnostics", "auth", "methods", "legacy-migration", "sample-queues", "spectrum-migration", "result-migration", "spectrum-viewer", "devices", "dispersion", "acquisition", "hardware-acquisition", "mercury-calibration", "analysis", "postprocessing", "reports", "maintenance"
        }
        navigation = [entry for item in capabilities.json()["capabilities"] for entry in item["navigation_entries"]]
        assert len(navigation) == 28
        assert next(entry for entry in navigation if entry["key"] == "analysis-tests.hardware")["status"] == "deferred_external"
        diagnostics = client.get("/api/v1/diagnostics", headers=headers)
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
        assert invalid.json()["detail"]["code"] == "request_validation_failed"
        invalid_payloads = [
            {"logging": {"retention_days": 0}},
            {"logging": {"retention_days": 366}},
            {"logging": {"max_bytes": 1023}},
            {"logging": {"level": "trace"}},
            {"display": {"theme": "solarized"}},
            {"display": {"density": "dense"}},
            {"display": {"show_status_bar": "yes"}},
            {"directories": {"data": ""}},
            {"printing": {"paper": "Legal"}},
            {"printing": {"copies": 0}},
            {"time": {"timezone": "Europe/London"}},
        ]
        for payload in invalid_payloads:
            rejected = client.patch("/api/v1/settings", headers=headers, json=payload)
            assert rejected.status_code == 422
            assert rejected.json()["detail"]["code"] == "request_validation_failed"
        unchanged = client.get("/api/v1/settings", headers=headers).json()
        assert unchanged["display"]["density"] == "compact"
        assert unchanged["logging"]["retention_days"] == 30
        assert unchanged["logging"]["max_bytes"] == 5_242_880
        with main_module.database.read() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action='settings.update'"
            ).fetchone()[0] == 1
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
