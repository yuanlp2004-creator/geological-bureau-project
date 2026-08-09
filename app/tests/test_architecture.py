from __future__ import annotations

import json
import sys
import sqlite3
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.modules.manifest import ModuleManifest, registered_manifests, validate_manifests
from backend.app.db import Database
from backend.app.schemas import RuntimeEventCreate, SettingsPatch
from backend.app.services import AppService


def test_registered_manifests_have_unique_contracts() -> None:
    manifests = registered_manifests()
    validate_manifests(manifests)
    assert {manifest.key for manifest in manifests} == {
        "core", "about-diagnostics", "auth", "methods", "legacy-migration", "sample-queues", "spectrum-migration", "result-migration", "spectrum-viewer"
    }
    assert all(manifest.api_prefix == "/api/v1" for manifest in manifests)


def test_duplicate_keys_routes_permissions_and_missing_dependencies_are_rejected() -> None:
    base = ModuleManifest(key="same", version="1", title="A", api_prefix="/api/v1", route="/a", permissions=("read",))
    with pytest.raises(ValueError, match="duplicate module key"):
        validate_manifests((base, base))
    same_route = ModuleManifest(key="other", version="1", title="B", api_prefix="/api/v1", route="/a")
    with pytest.raises(ValueError, match="duplicate module route"):
        validate_manifests((base, same_route))
    same_permission = ModuleManifest(key="other", version="1", title="B", api_prefix="/api/v1", route="/b", permissions=("read",))
    with pytest.raises(ValueError, match="duplicate permission"):
        validate_manifests((base, same_permission))
    missing = ModuleManifest(key="other", version="1", title="B", api_prefix="/api/v1", route="/b", dependencies=("missing",))
    with pytest.raises(ValueError, match="unregistered"):
        validate_manifests((base, missing))


def test_generated_manifest_matches_registered_modules() -> None:
    manifest_file = APP_ROOT / "manifest.generated.json"
    if not manifest_file.exists():
        from tools.generate_manifest import main

        assert main() == 0
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert [module["key"] for module in payload["modules"]] == [manifest.key for manifest in registered_manifests()]
    modules_by_key = {module["key"]: module for module in payload["modules"]}
    assert modules_by_key["spectrum-migration"]["title"] == "旧谱数据迁移"


def test_frontend_number_inputs_allow_an_empty_editing_state() -> None:
    source = (APP_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert source.count('type="number"') == 1
    assert "function EmptyableNumberInput" in source
    assert "if (nextText === '') return" in source
    assert "if (text === '') setText" in source


def test_runtime_log_rotation_redacts_sensitive_details(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = AppService(database, tmp_path / "logs" / "runtime.jsonl")
    service.update_settings(SettingsPatch(logging={"max_bytes": 1024, "retention_days": 1}))
    service.append_event(
        RuntimeEventCreate(
            category="action",
            severity="info",
            message="rotation test",
            details={"token": "do-not-write", "nested": {"password": "also-secret"}},
        )
    )
    service.append_event(RuntimeEventCreate(category="action", severity="info", message="x" * 480))
    service.append_event(RuntimeEventCreate(category="action", severity="info", message="y" * 480))
    log_path = tmp_path / "logs" / "runtime.jsonl"
    rotated = tmp_path / "logs" / "runtime.jsonl.1"
    assert log_path.exists() and rotated.exists()
    assert "do-not-write" not in rotated.read_text(encoding="utf-8")
    assert "also-secret" not in rotated.read_text(encoding="utf-8")


def test_runtime_log_level_filters_file_output(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    log_path = tmp_path / "logs" / "runtime.jsonl"
    service = AppService(database, log_path)
    service.update_settings(SettingsPatch(logging={"level": "warning"}))

    service.append_event(RuntimeEventCreate(category="system", severity="info", message="filtered info"))
    service.append_event(RuntimeEventCreate(category="system", severity="warning", message="kept warning"))

    content = log_path.read_text(encoding="utf-8")
    assert "filtered info" not in content
    assert "kept warning" in content


def test_service_validation_filters_and_selective_clear(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = AppService(database, tmp_path / "logs" / "runtime.jsonl")

    with database.write() as connection:
        connection.executemany(
            "INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?)",
            [
                ("not-a-group", "true", "2026-01-01T00:00:00+00:00"),
                ("display.density", "{not-json", "2026-01-01T00:00:00+00:00"),
            ],
        )
    assert service.get_settings()["display"]["density"] == "comfortable"

    with pytest.raises(ValueError, match="unknown settings group"):
        service.update_settings(SettingsPatch.model_construct(extra={"value": True}))
    with pytest.raises(ValueError, match="unknown setting"):
        service.update_settings(SettingsPatch.model_construct(display={"missing": True}))
    class InvalidPatch:
        def model_dump(self, *, exclude_none: bool = True) -> dict[str, object]:
            return {"display": "invalid"}

    with pytest.raises(ValueError, match="must be an object"):
        service.update_settings(InvalidPatch())

    event = service.append_event(
        RuntimeEventCreate(
            category="analysis",
            severity="warning",
            message="filter me",
            details={"items": [{"token": "hidden"}], "authorization": "secret"},
        )
    )
    assert AppService._redact(["Bearer abc", {"private-key": "hidden"}]) == [
        "Bearer [REDACTED]",
        {"private-key": "[REDACTED]"},
    ]
    assert service.list_events(category="analysis", severity="warning", limit=10)[0]["id"] == event["id"]
    assert service.clear_events([]) == 0
    assert service.clear_events([event["id"]]) == 1

    with database.write() as connection:
        connection.execute(
            "INSERT INTO runtime_events(category, severity, message, details_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("system", "info", "malformed details", "{not-json", "2026-01-01T00:00:00+00:00"),
        )
    assert service.list_events()[0]["details"] is None


def test_log_rotation_replaces_previous_archive_and_expires_old_files(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = AppService(database, tmp_path / "logs" / "runtime.jsonl")
    service.update_settings(SettingsPatch(logging={"max_bytes": 1024, "retention_days": 1}))
    service.log_path.parent.mkdir(parents=True, exist_ok=True)
    service.log_path.write_text("old" * 400, encoding="utf-8")
    service.log_path.with_suffix(".jsonl.1").write_text("previous", encoding="utf-8")
    expired = service.log_path.with_suffix(".jsonl.2")
    expired.write_text("expired", encoding="utf-8")
    import os

    os.utime(expired, (0, 0))
    service.append_event(RuntimeEventCreate(category="system", severity="info", message="rotate again"))
    assert service.log_path.with_suffix(".jsonl.1").exists()
    assert not expired.exists()


def test_sidecar_entry_passes_host_and_port_to_uvicorn(monkeypatch) -> None:
    import backend.sidecar_entry as sidecar_entry

    captured: dict[str, object] = {}
    monkeypatch.setattr(sidecar_entry.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["sidecar_entry", "--host", "0.0.0.0", "--port", "9876"])
    sidecar_entry.main()
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9876
