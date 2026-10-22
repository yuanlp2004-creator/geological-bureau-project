import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from backend.auth import AuthError
from backend.schemas.auth import UserUpdate, UserCreate, RoleCreate, RoleUpdate
from backend.modules.acquisition import AcquisitionService
from backend.modules.dispersion import DispersionService, DispersionError
from backend.modules.sample_queues import SampleQueueError
from backend.modules.spectrum_viewer import SpectrumViewerService, SpectrumViewerError
from tests.test_s10_spectrum_viewer import seed_database
from tests.test_s13_acquisition import _complete_seeded_task


def test_queue_append_reorder_and_remove_preserve_real_capture(tmp_path):
    database = Database(tmp_path / "queue.sqlite3")
    database.initialize()
    acquisition = AcquisitionService(database)
    queues = acquisition.sample_queues
    queue = queues.create("queue", [{"pre_name": "N1", "repeats": 1}], None)
    first = queue["items"][0]
    task = acquisition.create_task(
        {
            "task_kind": "sample",
            "name": "capture",
            "queue_id": queue["id"],
            "queue_item_id": first["id"],
            "burn_frame_count": 1,
            "dark_frame_count": 0,
            "pre_excitation_seconds": 0,
        }
    )
    with pytest.raises(SampleQueueError, match="已关联采集"):
        queues.delete_item(queue["id"], first["id"], None)
    task = acquisition.start(task["id"])
    while task["status"] not in ["completed", "failed"]:
        task = acquisition.step(task["id"])
    assert task["status"] == "completed"
    request = {"id": first["id"], "pre_name": "N1", "repeats": 1}
    saved = queues.update(queue["id"], [request, {"pre_name": "N1", "repeats": 1}], None)
    second = saved["items"][1]
    saved = queues.update(queue["id"], [{"id": second["id"], "pre_name": "N1", "repeats": 1}, request], None)
    assert saved["items"][1]["id"] == first["id"]
    assert saved["items"][1]["spectrum_hash"] == task["result_sha256"]
    for call in [
        lambda: queues.delete_item(queue["id"], first["id"], None),
        lambda: queues.clear(queue["id"], None),
        lambda: queues.update(queue["id"], [request, request], None),
        lambda: queues.update(queue["id"], [{"pre_name": "N2"}], None),
    ]:
        with pytest.raises(SampleQueueError):
            call()
        assert queues.get(queue["id"]) == saved
    assert next(item for item in acquisition.list_tasks() if item["id"] == task["id"])["queue_item_id"] == first["id"]


def test_dispersion_command_busy_and_exception_release(tmp_path, monkeypatch):
    database = Database(tmp_path / "dispersion.sqlite3")
    database.initialize()
    service = DispersionService(database)
    entered, release = Event(), Event()

    def slow(task_id, *args):
        if task_id != 123:
            return {"independent": True}
        entered.set()
        assert release.wait(5)
        raise RuntimeError("device failure")

    monkeypatch.setattr(service, "_advance_once", slow)
    with ThreadPoolExecutor() as executor:
        work = executor.submit(service.step_task, 123)
        assert entered.wait(5)
        for command in [
            service.start_task,
            service.step_task,
            service.pause_task,
            service.resume_task,
            service.stop_task,
        ]:
            with pytest.raises(DispersionError) as error:
                command(123)
            assert error.value.code == "dispersion_task_busy"
        assert service.step_task(124) == {"independent": True}
        release.set()
        with pytest.raises(RuntimeError):
            work.result()
    monkeypatch.setattr(service, "_advance_once", lambda *args: {"retried": True})
    assert service.step_task(123) == {"retried": True}
    assert service.step_task(124) == {"retried": True}


def test_last_manager_permissions_and_committed_session_revocation(tmp_path):
    database = Database(tmp_path / "auth.sqlite3")
    database.initialize()
    auth = Runtime(AppConfig(data_dir=tmp_path), database=database).auth_service
    auth.bootstrap("manager", "correct-horse")
    token, session = auth.login("manager", "correct-horse")
    with pytest.raises(AuthError):
        auth.update_user(session.user_id, UserUpdate(role_ids=[]), session.user_id)
    assert token in auth.sessions
    role = auth.create_role(
        RoleCreate(name="delegated", permission_keys=["users.write", "roles.write"]), session.user_id
    )
    other = auth.create_user(
        UserCreate(username="backup", password="correct-horse", role_ids=[role["id"]]), session.user_id
    )
    auth.update_user(session.user_id, UserUpdate(role_ids=[]), session.user_id)
    assert token not in auth.sessions
    with pytest.raises(AuthError):
        auth.update_role(role["id"], RoleUpdate(permission_keys=["users.write"]), other["id"])
    with pytest.raises(AuthError):
        auth.update_user(other["id"], UserUpdate(enabled=False), session.user_id)


def test_new_sample_spectrum_and_stable_pagination(tmp_path):
    database = seed_database(tmp_path / "spectra.sqlite3")
    acquisition = AcquisitionService(database)
    task = _complete_seeded_task(acquisition, name="New", seed=77)
    service = SpectrumViewerService(database)
    sample_id = task["samples"][0]["id"]
    record_id = f"sample:{sample_id}"
    assert service.list(kind="sample")[0]["id"] == record_id
    record = service.get(record_id)
    expected = acquisition.band(sample_id, include_points=True)[0]["mean_points"]
    assert [point["value"] for point in record["ccd"]["points"]] == expected
    assert record["coordinate_system"].startswith("ccd_pixel:")
    with database.write() as db:
        raw = dict(db.execute("SELECT * FROM spectrum_bands WHERE id=1").fetchone())
        matrix = dict(db.execute("SELECT * FROM result_matrices WHERE id=1").fetchone())
        for table, original, count in [("spectrum_bands", raw, 100), ("result_matrices", matrix, 99)]:
            original.pop("id")
            for index in range(count):
                copy = dict(original)
                copy["record_index"] = index + 1
                if table == "spectrum_bands":
                    copy["details_json"] = "{}"
                db.execute(
                    f"INSERT INTO {table} ({','.join(copy)}) VALUES ({','.join('?' for _ in copy)})",
                    list(copy.values()),
                )
    ids = [item["id"] for offset in range(0, 300, 100) for item in service.list(offset=offset)]
    assert len(ids) == len(set(ids)) == 202
    assert service.list(angle_deg=15)[0]["id"] == "raw:1"
    assert len(service.list(kind="result")) == 100
