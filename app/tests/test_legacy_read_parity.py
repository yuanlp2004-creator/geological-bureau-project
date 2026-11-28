"""Validate v1 history, conversion and recovery on migrated SQLite data."""

import ast
import hashlib
import json
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from backend import db as database_module
from backend.config import AppConfig
from backend.db import Database
from backend.main import create_app
from backend.migrations import MIGRATIONS, SCHEMA_VERSION
from backend.modules.acquisition import AcquisitionError, LegacyHardwareService
from backend.modules.devices import DeviceError, LegacyMercuryService
from backend.runtime import Runtime
from backend.schemas.auth import RoleCreate, UserCreate
from tests.legacy_history_fixture import HARDWARE, MERCURY, RETIRED_PERMISSIONS, seed_hardware_task, seed_mercury_history
from tests.test_legacy_d05_contract import _method, seed_method_history
from tests.test_methods import method_client


SAMPLE = {"sample_name": "T1", "sample_kind": "test", "name_length": 12}


def _copy_database(source, path):
    with source.read() as db, closing(sqlite3.connect(path)) as copy:
        db.backup(copy)
    return Database(path)


class ReadOnlyDatabase(Database):
    def connect(self):
        db = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db


@pytest.fixture
def history(method_client):
    client, runtime, headers = method_client
    method = _method(client, headers, runtime)
    saved = seed_method_history(runtime, method, "S1", .25)
    posted = client.post(f"{HARDWARE}/tasks/{saved}/analysis-sample", headers=headers,
                         json={"sample_name": "S1", "sample_kind": "standard"})
    assert posted.status_code == 200, posted.text
    applied, rolled_back = seed_mercury_history(runtime.database)
    return {
        "runtime": runtime, "client": client, "headers": headers,
        "auto": seed_hardware_task(runtime.database, "auto", retry=True),
        "manual": seed_hardware_task(runtime.database, "manual", manual=True),
        "saved": saved, "pending": seed_method_history(runtime, method),
        "applied": applied, "rolled_back": rolled_back,
    }


def _get_equal(history, path, expected):
    response = history["client"].get(path, headers=history["headers"])
    assert response.status_code == 200, response.text
    assert response.json() == expected


def _assert_points(frame, blob):
    points = struct.pack(f'<{frame["points_count"]}H', *frame["points"])
    assert points == blob
    assert hashlib.sha256(points).hexdigest() == frame["points_sha256"]


def test_history_services_and_http_match_readonly_database(history, tmp_path, monkeypatch):
    runtime = history["runtime"]
    copy = _copy_database(runtime.database, tmp_path / "readonly.sqlite3")
    readonly = ReadOnlyDatabase(copy.path)
    hardware = LegacyHardwareService(readonly)
    mercury = LegacyMercuryService(readonly)
    monkeypatch.setattr(runtime, "database", readonly)

    for prefix, service, entity, list_method in (
        (HARDWARE, hardware, "tasks", "list_tasks"),
        (MERCURY, mercury, "sessions", "list_sessions"),
    ):
        _get_equal(history, prefix + "/options", service.options())
        for limit in (1, 200):
            expected = getattr(service, list_method)(limit)
            assert len(expected) == (1 if limit == 1 else (4 if entity == "tasks" else 2))
            _get_equal(history, f"{prefix}/{entity}?limit={limit}", expected)

    for key in ("auto", "manual", "saved", "pending"):
        task_id = history[key]
        path = f"{HARDWARE}/tasks/{task_id}"
        for include in (False, True):
            query = "?include_points=true" if include else ""
            expected = hardware.get_task(task_id, include_points=include)
            _get_equal(history, path + query, expected)
            assert (expected["analysis_sample"] is not None) == (key == "saved")
            for step_id in (None, expected["steps"][0]["id"]):
                frames = hardware.frames(task_id, step_id=step_id, include_points=include)
                params = {"include_points": str(include).lower()}
                if step_id is not None:
                    params["step_id"] = step_id
                response = history["client"].get(path + "/frames", headers=history["headers"], params=params)
                assert response.status_code == 200
                assert response.json() == frames
            if include:
                with readonly.read() as db:
                    for frame in expected["frames"]:
                        if "points" in frame:
                            table = "hardware_exposure_frames" if frame["id"] < 0 else "hardware_frames"
                            blob = db.execute(f"SELECT points_blob FROM {table} WHERE id=?", (abs(frame["id"]),)).fetchone()[0]
                            _assert_points(frame, blob)
                    for exposure in expected["exposures"]:
                        mean, full = db.execute(
                            "SELECT mean_blob,frames_blob FROM hardware_exposure_results WHERE id=?", (exposure["id"],)
                        ).fetchone()
                        count = exposure["points_count"]
                        assert struct.pack(f"<{count}f", *exposure["mean_points"]) == mean
                        assert hashlib.sha256(mean).hexdigest() == exposure["mean_sha256"]
                        if full is not None:
                            assert b"".join(struct.pack(f"<{count}H", *frame) for frame in exposure["frames"]) == full
                            assert hashlib.sha256(full).hexdigest() == exposure["frames_sha256"]
            else:
                assert all("points" not in frame for frame in expected["frames"])
                assert all("mean_points" not in exposure for exposure in expected["exposures"])
        for name in ("traces", "decisions"):
            expected = getattr(hardware, name)(task_id)
            _get_equal(history, f"{path}/{name}", expected)

    for key in ("applied", "rolled_back"):
        session_id = history[key]
        for include in (False, True):
            expected = mercury.session(session_id, include_points=include)
            query = "?include_points=true" if include else ""
            _get_equal(history, f"{MERCURY}/sessions/{session_id}{query}", expected)
            assert expected["status"] == key
            assert all(expected[key] for key in ("before_version", "candidate_version", "active_version"))
            with readonly.read() as db:
                for frame in expected["frames"]:
                    if include:
                        blob = db.execute("SELECT points_blob FROM mercury_frames WHERE id=?", (frame["id"],)).fetchone()[0]
                        _assert_points(frame, blob)
                    else:
                        assert "points" not in frame

    connect = readonly.connect

    def block_frame_blob_reads():
        db = connect()
        db.set_authorizer(lambda action, table, column, *_: sqlite3.SQLITE_DENY
                          if action == sqlite3.SQLITE_READ and column == "points_blob"
                          and table in {"mercury_frames", "hardware_frames"} else sqlite3.SQLITE_OK)
        return db

    monkeypatch.setattr(readonly, "connect", block_frame_blob_reads)
    _get_equal(history, f"{HARDWARE}/tasks/{history['manual']}", hardware.get_task(history["manual"]))
    _get_equal(history, f"{HARDWARE}/tasks/{history['auto']}/frames", hardware.frames(history["auto"]))
    _get_equal(history, f"{MERCURY}/sessions/{history['applied']}", mercury.session(history["applied"]))
    with readonly.read() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def _assert_error(call, error_type, request, status=None, code=None):
    with pytest.raises(error_type) as failure:
        call()
    expected = failure.value
    if status is not None:
        assert expected.status_code == status
    if code is not None:
        assert expected.code == code
    response = request()
    assert response.status_code == expected.status_code
    assert response.json() == {"detail": expected.detail()}


def test_history_errors_and_corrupt_points(history, tmp_path, monkeypatch):
    runtime, client, headers = (history[key] for key in ("runtime", "client", "headers"))
    copy = _copy_database(runtime.database, tmp_path / "corrupt.sqlite3")
    monkeypatch.setattr(runtime, "database", copy)
    hardware = LegacyHardwareService(copy)
    mercury = LegacyMercuryService(copy)
    for name, suffix in (("get_task", ""), ("frames", "/frames"), ("traces", "/traces"), ("decisions", "/decisions")):
        _assert_error(lambda: getattr(hardware, name)(9999), AcquisitionError,
                      lambda: client.get(f"{HARDWARE}/tasks/9999{suffix}", headers=headers),
                      404, "hardware_task_not_found")
    _assert_error(lambda: mercury.session(9999), DeviceError,
                  lambda: client.get(f"{MERCURY}/sessions/9999", headers=headers),
                  404, "mercury_session_not_found")

    for table, parent_column, item_id, code, status, read, error_type, path in (
        ("hardware_frames", "task_id", history["auto"], "hardware_frame_invalid", 422, hardware.frames,
         AcquisitionError, f"{HARDWARE}/tasks/{history['auto']}/frames"),
        ("mercury_frames", "session_id", history["applied"], "mercury_frame_invalid", 409, mercury.session,
         DeviceError, f"{MERCURY}/sessions/{history['applied']}"),
    ):
        with copy.write() as db:
            trigger = "hardware_frames_raw_immutable_update" if table == "hardware_frames" else "mercury_frames_immutable_update"
            db.execute(f"DROP TRIGGER {trigger}")
            frame = db.execute(
                f"SELECT id,points_blob FROM {table} WHERE {parent_column}=? AND points_blob IS NOT NULL LIMIT 1",
                (item_id,),
            ).fetchone()
        blob = frame["points_blob"]
        for corrupted in (blob[2:], bytes([blob[0] ^ 1]) + blob[1:]):
            with copy.write() as db:
                db.execute(f"UPDATE {table} SET points_blob=? WHERE id=?", (corrupted, frame["id"]))
            assert client.get(path, headers=headers).status_code == 200
            _assert_error(lambda: read(item_id, include_points=True), error_type,
                          lambda: client.get(path + "?include_points=true", headers=headers), status, code)

    task_id = history["pending"]
    task_path = f"{HARDWARE}/tasks/{task_id}"
    with copy.write() as db:
        db.execute("DROP TRIGGER hardware_exposure_results_immutable_update")
        db.execute("UPDATE hardware_exposure_results SET mean_sha256=? WHERE task_id=?", ("0" * 64, task_id))
    _assert_error(lambda: hardware.get_task(task_id), AcquisitionError,
                  lambda: client.get(task_path, headers=headers), code="hardware_exposure_integrity_failed")
    _assert_error(lambda: hardware.save_analysis_sample(task_id, SAMPLE, 1), AcquisitionError,
                  lambda: client.post(task_path + "/analysis-sample", headers=headers, json=SAMPLE),
                  code="hardware_exposure_integrity_failed")


def test_analysis_sample_rejects_invalid_historical_evidence(history, tmp_path, monkeypatch):
    runtime, client, headers = (history[key] for key in ("runtime", "client", "headers"))
    task_id = history["pending"]
    mutations = {
        "hardware_sample_incomplete": ("UPDATE hardware_tasks SET completed_steps=0 WHERE id=?", (task_id,)),
        "hardware_sample_method_changed": (
            "UPDATE hardware_tasks SET plan_json=json_set(plan_json, '$[0].method_content_sha256', ?) WHERE id=?",
            ("0" * 64, task_id),
        ),
        "hardware_sample_frames_missing": (
            "DELETE FROM hardware_exposure_frames WHERE task_id=? AND frame_index=1", (task_id,),
        ),
        "hardware_exposure_integrity_failed": (
            "UPDATE hardware_exposure_frames SET points_sha256=? WHERE task_id=?", ("0" * 64, task_id),
        ),
    }
    for code, (statement, params) in mutations.items():
        database = _copy_database(runtime.database, tmp_path / (code + ".sqlite3"))
        with database.write() as db:
            if code == "hardware_sample_frames_missing":
                db.execute("DROP TRIGGER hardware_exposure_frames_immutable_delete")
            if code == "hardware_exposure_integrity_failed":
                db.execute("DROP TRIGGER hardware_exposure_frames_immutable_update")
            db.execute(statement, params)
            before = list(db.iterdump())
        with monkeypatch.context() as patch:
            patch.setattr(runtime, "database", database)
            _assert_error(
                lambda: LegacyHardwareService(database).save_analysis_sample(task_id, SAMPLE, 1),
                AcquisitionError, lambda: client.post(f"{HARDWARE}/tasks/{task_id}/analysis-sample",
                                                      headers=headers, json=SAMPLE), code=code,
            )
        with database.read() as db:
            assert list(db.iterdump()) == before


def test_analysis_sample_dual_permission_idempotency_and_rollback(history):
    runtime, client, headers = (history[key] for key in ("runtime", "client", "headers"))
    task_id = history["pending"]
    path = f"{HARDWARE}/tasks/{task_id}/analysis-sample"
    database = runtime.database

    def post(auth=headers):
        return client.post(path, headers=auth, json=SAMPLE)

    for index, permission in enumerate(("hardware-acquisition.execute", "acquisition.write")):
        role = runtime.auth_service.create_role(RoleCreate(name=f"单项权限 {index}", permission_keys=[permission]), 1)
        username, password = f"limited-{index}", "limited-user-password"
        runtime.auth_service.create_user(UserCreate(username=username, password=password, role_ids=[role["id"]]), 1)
        token, _ = runtime.auth_service.login(username, password)
        response = post({"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        assert response.json() == {"detail": "permission denied"}

    with LegacyHardwareService(database).control_scope(task_id):
        response = post()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "hardware_task_busy"

    with database.write() as db:
        db.execute("""CREATE TRIGGER fail_hardware_sample_audit BEFORE INSERT ON audit_events
                      WHEN NEW.action='hardware.sample.save' BEGIN
                        SELECT RAISE(ABORT, 'audit write failed')
                        WHERE EXISTS (SELECT 1 FROM acquisition_sample_bands WHERE sample_id =
                            json_extract(NEW.details_json, '$.acquisition_sample_id'));
                      END""")
        before = list(db.iterdump())
    with pytest.raises(sqlite3.IntegrityError, match="audit write failed"):
        post()
    with database.write() as db:
        assert list(db.iterdump()) == before
        db.execute("DROP TRIGGER fail_hardware_sample_audit")

    saved = post()
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert not result["already_saved"]
    assert post().json() == {**result, "already_saved": True}
    with database.read() as db:
        metadata = db.execute("SELECT simulator_json FROM acquisition_tasks WHERE id=?",
                              (result["acquisition_task_id"],)).fetchone()[0]
        assert json.loads(metadata)["source_record_id"] == f"hardware-task:{task_id}"
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='hardware.sample.save' AND target_id=?",
                          (task_id,)).fetchone()[0] == 1
    with database.write() as db:
        db.execute("UPDATE hardware_tasks SET result_sha256=? WHERE id=?", ("f" * 64, task_id))
    response = post()
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "hardware_sample_source_changed"


def _history_rows(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND "
        "(name GLOB 'hardware_*' OR name GLOB 'mercury_*') ORDER BY name"
    ).fetchall()
    return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for (table,) in tables}


def _check_sqlite(db):
    assert [tuple(row) for row in db.execute("PRAGMA integrity_check")] == [("ok",)]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def _login(client):
    response = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_v32_history_and_custom_grants_survive_upgrade_and_restore(tmp_path, monkeypatch):
    old_runtime = Runtime(AppConfig(data_dir=tmp_path / "old"))
    with monkeypatch.context() as patch:
        patch.setattr(database_module, "SCHEMA_VERSION", 32)
        patch.setattr(database_module, "MIGRATIONS", tuple(step for step in MIGRATIONS if step[0] <= 32))
        matrix = old_runtime.auth_service.builtin_roles
        patch.setattr(old_runtime.auth_service, "builtin_roles", tuple(
            (name, description, keys + tuple(sorted(RETIRED_PERMISSIONS)) if name == "system_administrator" else keys)
            for name, description, keys in matrix
        ))
        with TestClient(create_app(runtime=old_runtime)) as client:
            response = client.post("/api/v1/auth/bootstrap",
                                   json={"username": "operator", "password": "correct-horse"})
            assert response.status_code == 201
            headers = _login(client)
            method = _method(client, headers, old_runtime)
            task = seed_method_history(old_runtime, method, retry=True)
            applied, rolled_back = seed_mercury_history(old_runtime.database)
            role = client.post("/api/v1/roles", headers=headers, json={
                "name": "legacy-reviewer", "permission_keys": sorted(RETIRED_PERMISSIONS),
            })
            assert role.status_code == 201, role.text
            role_id = role.json()["id"]

    with old_runtime.database.read() as db:
        _check_sqlite(db)
        assert db.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0] == "32"
        original_rows = _history_rows(db)
        original_keys = dict(db.execute("SELECT key,id FROM permissions").fetchall())

    database = _copy_database(old_runtime.database, tmp_path / "upgrade.sqlite3")
    runtime = Runtime(AppConfig(data_dir=tmp_path / "upgraded"), database=database)
    with TestClient(create_app(runtime=runtime)) as client:
        headers = _login(client)
        with database.read() as db:
            _check_sqlite(db)
            assert db.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
            assert _history_rows(db) == original_rows
            keys = dict(db.execute("SELECT key,id FROM permissions").fetchall())
            assert {key: keys[key] for key in RETIRED_PERMISSIONS} == {key: original_keys[key] for key in RETIRED_PERMISSIONS}

        roles = client.get("/api/v1/roles", headers=headers).json()
        builtin = [role for role in roles if role["built_in"]]
        assert len(builtin) == 4
        assert all(RETIRED_PERMISSIONS.isdisjoint(role["permission_keys"]) for role in builtin)
        assert {"hardware-acquisition.read", "hardware-acquisition.execute", "mercury-calibration.read"} <= set(
            next(role for role in builtin if role["name"] == "analyst")["permission_keys"]
        )
        assert set(next(role for role in roles if role["id"] == role_id)["permission_keys"]) == RETIRED_PERMISSIONS
        edited_keys = sorted(RETIRED_PERMISSIONS | {"hardware-acquisition.read"})
        response = client.patch(f"/api/v1/roles/{role_id}", headers=headers, json={"permission_keys": edited_keys})
        assert response.status_code == 200, response.text
        assert next(role for role in client.get("/api/v1/roles", headers=headers).json()
                    if role["id"] == role_id)["permission_keys"] == edited_keys

        detail = f"{HARDWARE}/tasks/{task}"
        original_task = client.get(detail, headers=headers, params={"include_points": "true"}).json()
        assert original_task["status"] == "completed" and original_task["analysis_sample"] is None
        assert client.get(f"{MERCURY}/sessions/{applied}", headers=headers).json()["status"] == "applied"
        assert client.get(f"{MERCURY}/sessions/{rolled_back}", headers=headers).json()["status"] == "rolled_back"
        saved = client.post(detail + "/analysis-sample", headers=headers, json=SAMPLE)
        assert saved.status_code == 200, saved.text
        sample = saved.json()
        assert not sample["already_saved"]

        maintenance = runtime.maintenance_service()
        backup = maintenance.backup(str(tmp_path / "backup"))
        assert {"hardware_frames", "mercury_frames"} <= {row["table"] for row in backup["verification"]["blob_samples"]}
        verification = maintenance.verify_backup(backup["id"])["verification"]
        assert verification == backup["verification"]

        verify_path = maintenance._verify_path
        restored = []

        def verify_restore(path, expected):
            with ReadOnlyDatabase(path).read() as db, database.read() as live:
                _check_sqlite(db)
                assert _history_rows(db) == _history_rows(live) == original_rows
                for table in ("acquisition_tasks", "acquisition_samples", "acquisition_sample_bands",
                              "acquisition_frames", "permissions", "role_permissions"):
                    query = f"SELECT * FROM {table} ORDER BY rowid"
                    assert [tuple(row) for row in db.execute(query)] == [tuple(row) for row in live.execute(query)]
            restored.append(path)
            return verify_path(path, expected)

        monkeypatch.setattr(maintenance, "_verify_path", verify_restore)
        rehearsal = maintenance.restore_rehearsal(backup["id"])
        assert rehearsal["status"] == "verified" and rehearsal["verification"] == verification
        assert len(restored) == 1 and not restored[0].exists()
        with database.read() as db:
            _check_sqlite(db)


@pytest.mark.parametrize("path", ("acquisition/legacy_hardware.py", "devices/legacy_mercury.py"))
def test_history_has_no_reverse_module_dependency(path):
    source = (Path(__file__).resolve().parents[1] / "backend" / "modules" / path).read_text(encoding="utf-8")
    forbidden = ("hardware_acquisition", "mercury_calibration")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert not any(name in ast.unparse(node) for name in forbidden)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(name in node.value for name in forbidden)
