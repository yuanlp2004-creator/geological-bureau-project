from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.config import AppConfig
from backend.main import create_app
from backend.runtime import Runtime


def test_two_apps_keep_database_sessions_keys_and_events_separate(tmp_path: Path) -> None:
    first = Runtime(AppConfig(data_dir=tmp_path / "first"), process_key="first-key")
    second = Runtime(AppConfig(data_dir=tmp_path / "second"), process_key="second-key")
    first_app = create_app(runtime=first)
    second_app = create_app(runtime=second)
    # Constructing apps does not open the database or initialize either directory.
    assert not first.config.data_dir.exists()
    assert not second.config.data_dir.exists()
    with TestClient(first_app) as a, TestClient(second_app) as b:
        ka = {"X-GeoSpectrum-Process-Key": "first-key"}
        kb = {"X-GeoSpectrum-Process-Key": "second-key"}
        assert a.get("/health", headers=kb).status_code == 403
        assert b.get("/health", headers=ka).status_code == 403
        assert a.get("/health", headers=ka).status_code == 200
        assert b.get("/health", headers=kb).status_code == 200
        assert a.post("/api/v1/auth/bootstrap", headers=ka, json={"username": "admin", "password": "correct-horse"}).status_code == 201
        assert b.get("/api/v1/auth/status", headers=kb).json() == {"bootstrapped": False}
        token = a.post("/api/v1/auth/login", headers=ka, json={"username": "admin", "password": "correct-horse"}).json()["access_token"]
        authorization = {"Authorization": f"Bearer {token}"}
        assert a.get("/api/v1/auth/me", headers=ka | authorization).status_code == 200
        assert b.get("/api/v1/auth/me", headers=kb | authorization).status_code == 401
        assert a.patch("/api/v1/settings", headers=ka | authorization, json={"display": {"density": "compact"}}).status_code == 200
        assert first.service.get_settings()["display"]["density"] == "compact"
        assert second.service.get_settings()["display"]["density"] == "comfortable"
        # Cached device state belongs to the app, not a module singleton.
        assert first.devices_service() is first.devices_service()
        assert first.devices_service() is not second.devices_service()
        assert first.event_subscribers is not second.event_subscribers
        session = first.auth_service.sessions[token]
        first.auth_service.sessions[token] = replace(session, permissions=frozenset())
        assert a.get("/api/v1/settings", headers=ka | authorization).status_code == 403
        first.auth_service.sessions[token] = session
    assert not first.event_subscribers and not second.event_subscribers


def test_websocket_uses_same_runtime_key_and_session_as_http(tmp_path: Path) -> None:
    runtime = Runtime(AppConfig(data_dir=tmp_path), process_key="desktop-key")
    with TestClient(create_app(runtime=runtime)) as client:
        headers = {"X-GeoSpectrum-Process-Key": "desktop-key"}
        client.post("/api/v1/auth/bootstrap", headers=headers, json={"username": "admin", "password": "correct-horse"})
        token = client.post("/api/v1/auth/login", headers=headers, json={"username": "admin", "password": "correct-horse"}).json()["access_token"]
        with client.websocket_connect(f"/ws/events?access_token={token}&process_key=wrong") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4403
        with client.websocket_connect("/ws/events?process_key=desktop-key&access_token=unknown") as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4401
        with client.websocket_connect(f"/ws/events?access_token={token}&process_key=desktop-key") as ws:
            assert ws.receive_json() == {"type": "ready", "api_version": "v1"}
            assert len(runtime.event_subscribers) == 1
    assert not runtime.event_subscribers


def test_api_and_auth_do_not_import_entrypoint_or_construct_shared_runtime() -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    for path in [backend / "auth.py", *sorted((backend / "api").glob("*.py"))]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {"main", "backend.main"}, path
                assert not any(alias.name == "main" for alias in node.names), path
            elif isinstance(node, ast.Import):
                assert not any(alias.name == "backend.main" for alias in node.names), path
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
                assert not (isinstance(node.value.func, ast.Name) and node.value.func.id == "Runtime"), path


def test_selected_dependencies_are_explicit_and_scoped_to_each_runtime(tmp_path):
    for label in ("first", "second"):
        runtime = Runtime(AppConfig(data_dir=tmp_path / label))
        analysis = runtime.analysis_service()
        post = runtime.postprocessing_service()
        printing = runtime.method_print_service()
        assert analysis.methods.database is runtime.database
        assert post.recalculation.analysis.database is runtime.database
        assert printing.methods.database is runtime.database
        assert analysis is not runtime.analysis_service()
        assert post.recalculation.analysis is not runtime.postprocessing_service().recalculation.analysis
        assert printing.printer_backend is not runtime.reports_service().printer_backend
        assert not runtime.config.data_dir.exists()
    backend = Path(__file__).resolve().parents[1] / "backend"
    for relative in ("modules/analysis/service.py", "modules/method_printing/service.py",
                     "modules/reports.py", "modules/postprocessing/recalculation.py"):
        tree = ast.parse((backend / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"MethodService", "AnalysisService", "SystemPrinters"}, relative
