from __future__ import annotations

import json
import re
import sys
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.modules.manifest import NavigationEntry, ModuleManifest, registered_manifests, validate_manifests
from backend.db import Database
from backend.schemas import RuntimeEventCreate, SettingsPatch
from backend.services import AppService


def test_registered_manifests_have_unique_contracts() -> None:
    manifests = registered_manifests()
    validate_manifests(manifests)
    assert {manifest.key for manifest in manifests} == {
        "core",
        "about-diagnostics",
        "auth",
        "methods",
        "legacy-migration",
        "sample-queues",
        "spectrum-migration",
        "result-migration",
        "spectrum-viewer",
        "devices",
        "dispersion",
        "acquisition",
        "analysis",
        "postprocessing",
        "reports",
        "maintenance",
    }
    assert all(manifest.api_prefix == "/api/v1" for manifest in manifests)
    by_key = {manifest.key: manifest for manifest in manifests}
    acquisition, devices = by_key["acquisition"], by_key["devices"]
    assert {"hardware-acquisition.read", "hardware-acquisition.execute"} <= set(acquisition.permissions)
    assert "hardware.sample.save" in acquisition.audit_actions
    assert "confirmed-turn-analysis-sample" in acquisition.capabilities
    assert "mercury-calibration.read" in devices.permissions


def test_duplicate_keys_routes_permissions_and_missing_dependencies_are_rejected() -> None:
    base = ModuleManifest(key="same", version="1", title="A", api_prefix="/api/v1", route="/a", permissions=("read",))
    with pytest.raises(ValueError, match="duplicate module key"):
        validate_manifests((base, base))
    same_route = ModuleManifest(key="other", version="1", title="B", api_prefix="/api/v1", route="/a")
    with pytest.raises(ValueError, match="duplicate module route"):
        validate_manifests((base, same_route))
    same_permission = ModuleManifest(
        key="other", version="1", title="B", api_prefix="/api/v1", route="/b", permissions=("read",)
    )
    with pytest.raises(ValueError, match="duplicate permission"):
        validate_manifests((base, same_permission))
    missing = ModuleManifest(
        key="other", version="1", title="B", api_prefix="/api/v1", route="/b", dependencies=("missing",)
    )
    with pytest.raises(ValueError, match="unregistered"):
        validate_manifests((base, missing))
    with pytest.raises(ValueError, match="module dependency cycle"):
        validate_manifests((replace(base, dependencies=("other",)), replace(missing, dependencies=("same",))))


def test_generated_manifest_matches_registered_modules() -> None:
    manifest_file = APP_ROOT / "manifest.generated.json"
    if not manifest_file.exists():
        from tools.generate_manifest import main

        assert main() == 0
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["modules"] == [manifest.to_dict() for manifest in registered_manifests()]
    entries = [entry for module in payload["modules"] for entry in module["navigation_entries"]]
    for entry in entries:
        assert all(isinstance(entry[field], str) and entry[field].strip() for field in ("key", "group", "label", "page"))
        assert isinstance(entry["description"], str)
        assert isinstance(entry["section_label"], str)
        assert isinstance(entry["order"], int)
        assert isinstance(entry["required_any"], list) and all(isinstance(permission, str) for permission in entry["required_any"])
    migration_entries = [entry for entry in entries if entry["page"] == "migration"]
    assert len(migration_entries) == 1
    assert set(migration_entries[0]["required_any"]) == {
        "migration.read", "spectrum-migration.read", "result-migration.read"
    }
    assert not any(entry['page'] == 'hardware-acquisition' for entry in entries)
    connection_entry = next(entry for entry in entries if entry['key'] == 'tools.device-connection')
    assert connection_entry['view'] == 'connection' and connection_entry['required_any'] == ['devices.read']
    prepared_entry = next(entry for entry in entries if entry['key'] == 'tools.prepared-import')
    assert prepared_entry['page'] == 'prepared-import' and prepared_entry['required_context'] == 'current_method'
    device_entry = next(entry for entry in entries if entry["key"] == "tools.devices")
    assert set(device_entry["required_any"]) == {"devices.read", "settings.read"}
    assert not any(entry["key"] == "tools.mercury" for entry in entries)
    assert next(entry for entry in entries if entry["key"] == "analysis-tests.dispersion-curves")["view"] == "curve"
    assert next(entry for entry in entries if entry["key"] == "analysis-tests.evaporation-curves")["page"] == "evaporation-curves"
    assert {"postprocessing", "reports"} <= {entry["page"] for entry in entries if entry["group"] == "data"}
    assert len({entry["key"] for entry in entries}) == len(entries)
    assert {
        "workspace",
        "methods",
        "analysis-tests",
        "data",
        "tools",
        "system",
        "help",
    } <= {entry["group"] for entry in entries}


def test_manifest_navigation_targets_are_rendered_by_frontend() -> None:
    frontend = APP_ROOT / "frontend" / "src"
    workspace = (frontend / "layout" / "WorkspaceApp.tsx").read_text(encoding="utf-8")
    spectroscopy = (frontend / "pages" / "acquisition" / "spectroscopySession.ts").read_text(encoding="utf-8")
    navigation = (frontend / "navigation.ts").read_text(encoding="utf-8")
    page_type = navigation.split("export type Page =", 1)[1].split("export type ", 1)[0]
    page_names = set(re.findall(r"'([a-z-]+)'", page_type))
    rendered_pages = set(re.findall(r"\bpage === '([a-z-]+)'", workspace))
    rendered_pages.update(re.findall(r"\bpage: '([a-z-]+)'", spectroscopy))
    for manifest in registered_manifests():
        for entry in manifest.navigation_entries:
            assert entry.page in page_names & rendered_pages, entry


def test_invalid_navigation_contracts_are_rejected() -> None:
    valid = NavigationEntry("entry", "tools", "", "Entry", "Description", "about", 1, ("read",))
    base = ModuleManifest(
        key="base",
        version="1",
        title="Base",
        api_prefix="/api/v1",
        route="/base",
        permissions=("read",),
        navigation_entries=(valid,),
    )
    validate_manifests((base,))
    invalid_group = NavigationEntry("bad-group", "unknown", "", "Entry", "Description", "about", 1, ("read",))
    with pytest.raises(ValueError, match="invalid navigation group"):
        validate_manifests(
            (
                ModuleManifest(
                    key="bad",
                    version="1",
                    title="Bad",
                    api_prefix="/api/v1",
                    route="/bad",
                    permissions=("read",),
                    navigation_entries=(invalid_group,),
                ),
            )
        )
    invalid_permission = NavigationEntry("bad-permission", "tools", "", "Entry", "Description", "about", 1, ("other",))
    with pytest.raises(ValueError, match="invalid navigation permission"):
        validate_manifests(
            (
                ModuleManifest(
                    key="bad",
                    version="1",
                    title="Bad",
                    api_prefix="/api/v1",
                    route="/bad",
                    permissions=("read",),
                    navigation_entries=(invalid_permission,),
                ),
            )
        )


def test_frontend_downloads_use_the_shared_adapter() -> None:
    source_root = APP_ROOT / "frontend" / "src"
    adapter = source_root / "platform" / "files.ts"
    create_anchor = re.compile(r"""\bdocument\s*\.\s*createElement\s*\(\s*['"`]a['"`]""")
    for pattern in ("*.ts", "*.tsx"):
        for path in source_root.rglob(pattern):
            if path != adapter:
                assert not create_anchor.search(path.read_text(encoding="utf-8")), path
    assert "save_export_file" in adapter.read_text(encoding="utf-8")


def test_frontend_number_fields_use_editable_text_inputs() -> None:
    source_root = APP_ROOT / "frontend" / "src"
    sources = {path.name: path.read_text(encoding="utf-8") for path in source_root.rglob("*.tsx")}
    native_number = re.compile(r"""\btype\s*=\s*(?:\{\s*)?['"`]number['"`]""")
    for filename, source in sources.items():
        assert not native_number.search(source), filename
    for filename in (
        "MethodGeometry.tsx",
        "PreliminaryCaptureFields.tsx",
        "AnalysisIntervention.tsx",
    ):
        source = sources[filename]
        component = re.search(r"\bimport\s*\{[^}]*?\bNumericInput(?:\s+as\s+(\w+))?\s*[,}]", source)
        assert component is not None, filename
        assert re.search(rf"<{component.group(1) or 'NumericInput'}\b", source), filename


def test_retired_preferences_use_defaults_without_resetting_business_settings(tmp_path: Path) -> None:
    database = Database(tmp_path / 'app.sqlite3')
    database.initialize()
    service = AppService(database)
    persisted = {
        'display.theme': 'dark', 'display.density': 'compact', 'display.show_status_bar': False,
        'logging.level': 'warning', 'logging.retention_days': 1, 'logging.max_bytes': 1024,
        'time.timezone': 'UTC', 'analysis.wait_time_ms': 350,
        'analysis.dark_round_time_seconds': 12, 'display.screen_width_mm': 500.0,
        'directories.backups': 'chosen-backups', 'printing.copies': 2,
    }
    with database.write() as connection:
        connection.executemany('INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?)',
                               [(key, json.dumps(value), '2026-11-05') for key, value in persisted.items()])
    effective = service.get_settings()
    assert effective['display'] == {'theme': 'light', 'density': 'comfortable', 'show_status_bar': True,
                                    'screen_width_mm': 500.0, 'screen_resolution_px': 1920}
    assert effective['logging'] == {'level': 'info', 'retention_days': 30, 'max_bytes': 5242880}
    assert effective['time']['timezone'] == 'Asia/Shanghai'
    saved = service.update_settings(SettingsPatch.model_validate({
        'display': {'theme': 'dark', 'screen_width_mm': 510.0},
        'logging': {'level': 'debug'}, 'time': {'timezone': 'UTC'},
        'analysis': {'wait_time_ms': 450},
    }))
    assert saved['display']['theme'] == 'light' and saved['display']['screen_width_mm'] == 510.0
    assert saved['logging'] == effective['logging'] and saved['time'] == effective['time']
    assert saved['analysis']['wait_time_ms'] == 450
    assert saved['analysis']['dark_round_time_seconds'] == 12
    assert saved['directories']['backups'] == 'chosen-backups' and saved['printing']['copies'] == 2
    with database.read() as connection:
        rows = {row['key']: json.loads(row['value_json']) for row in connection.execute('SELECT * FROM app_settings')}
    assert rows == {**persisted, 'display.screen_width_mm': 510.0, 'analysis.wait_time_ms': 450}
    assert AppService(database).get_settings() == saved


def test_runtime_log_rotation_redacts_sensitive_details(tmp_path: Path, monkeypatch) -> None:
    from backend.services import DEFAULT_SETTINGS
    monkeypatch.setitem(DEFAULT_SETTINGS, 'logging', {'level': 'info', 'max_bytes': 1024, 'retention_days': 1})
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = AppService(database, tmp_path / "logs" / "runtime.jsonl")
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


def test_runtime_log_level_filters_file_output(tmp_path: Path, monkeypatch) -> None:
    from backend.services import DEFAULT_SETTINGS
    monkeypatch.setitem(DEFAULT_SETTINGS, 'logging', {'level': 'warning', 'max_bytes': 5242880, 'retention_days': 30})
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    log_path = tmp_path / "logs" / "runtime.jsonl"
    service = AppService(database, log_path)

    statements: list[str] = []
    connect = database.connect

    def trace_connection() -> sqlite3.Connection:
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(database, "connect", trace_connection)
    service.append_event(RuntimeEventCreate(category="system", severity="info", message="filtered info"))
    service.append_event(RuntimeEventCreate(category="system", severity="warning", message="kept warning"))

    assert not any("app_settings" in statement.lower() for statement in statements)
    content = log_path.read_text(encoding="utf-8")
    assert "filtered info" not in content
    assert "kept warning" in content


def test_service_validation_filters_and_selective_clear(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = AppService(database, tmp_path / "logs" / "runtime.jsonl")

    settings_rows = [
        ("not-a-group", "true", "2026-01-01T00:00:00+00:00"),
        ("display.density", "{not-json", "2026-01-01T00:00:00+00:00"),
        ("display.screen_resolution_px", "{not-json", "2026-01-01T00:00:00+00:00"),
        ("display.screen_width_mm", "500.0", "2026-01-01T00:00:00+00:00"),
        ("logging.retention_days", "0", "2026-01-01T00:00:00+00:00"),
        ("printing.copies", "0", "2026-01-01T00:00:00+00:00"),
        ("printing.paper", '"A3"', "2026-01-01T00:00:00+00:00"),
        ("analysis.dark_round_time_seconds", "null", "2026-01-01T00:00:00+00:00"),
        ("analysis.wait_time_ms", "350", "2026-01-01T00:00:00+00:00"),
    ]
    with database.write() as connection:
        connection.executemany(
            "INSERT INTO app_settings(key, value_json, updated_at) VALUES (?, ?, ?)",
            settings_rows,
        )
    settings = service.get_settings()
    assert settings["display"]["density"] == "comfortable"
    assert settings["display"]["screen_resolution_px"] == 1920
    assert settings["display"]["screen_width_mm"] == 500.0
    assert settings["logging"]["retention_days"] == 30
    assert settings["printing"]["copies"] == 1
    assert settings["printing"]["paper"] == "A3"
    assert settings["analysis"]["dark_round_time_seconds"] == 8
    assert settings["analysis"]["wait_time_ms"] == 350
    with database.read() as connection:
        rows = connection.execute("SELECT key, value_json, updated_at FROM app_settings ORDER BY key")
        assert [tuple(row) for row in rows] == sorted(settings_rows)
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0

    class InvalidPatch:
        def __init__(self, payload: dict[str, object]):
            self.payload = payload

        def model_dump(self, *, exclude_none: bool = True) -> dict[str, object]:
            return self.payload

    with pytest.raises(ValueError, match="unknown settings group"):
        service.update_settings(InvalidPatch({"extra": {"value": True}}))
    with pytest.raises(ValueError, match="unknown setting"):
        service.update_settings(InvalidPatch({"display": {"missing": True}}))
    with pytest.raises(ValueError, match="must be an object"):
        service.update_settings(InvalidPatch({"display": "invalid"}))

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
            "INSERT INTO runtime_events(category, severity, message, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
            ("system", "info", "malformed details", "{not-json", "2026-01-01T00:00:00+00:00"),
        )
    assert service.list_events()[0]["details"] is None


def test_log_rotation_replaces_previous_archive_and_expires_old_files(tmp_path: Path, monkeypatch) -> None:
    from backend.services import DEFAULT_SETTINGS
    monkeypatch.setitem(DEFAULT_SETTINGS, 'logging', {'level': 'info', 'max_bytes': 1024, 'retention_days': 1})
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = AppService(database, tmp_path / "logs" / "runtime.jsonl")
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


def test_sidecar_entry_passes_host_and_port_to_uvicorn(tmp_path, monkeypatch) -> None:
    import backend.sidecar_entry as sidecar_entry

    captured: dict[str, object] = {}
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sidecar_entry.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(sidecar_entry, "_read_process_key", lambda: "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(sys, "argv", ["sidecar_entry", "--host", "0.0.0.0", "--port", "9876"])
    sidecar_entry.main()
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9876
