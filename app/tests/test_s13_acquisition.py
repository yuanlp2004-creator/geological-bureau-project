from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database, utc_now
from backend.app.modules.acquisition import AcquisitionError, AcquisitionService, average_points
from backend.app.modules.analysis import AnalysisService


def _complete_seeded_task(service: AcquisitionService, *, name: str, seed: int, repeat_count: int = 1) -> dict:
    task = service.create_task(
        {
            "task_kind": "sample",
            "name": f"seed-{seed}-{name}",
            "sample_name": name,
            "sample_kind": "standard",
            "ccd_indices": [0],
            "repeat_count": repeat_count,
            "burn_frame_count": 3,
            "dark_frame_count": 1,
            "pre_excitation_seconds": 0,
            "seed": seed,
        }
    )
    current = service.start(task["id"])
    for _ in range(repeat_count * 6 + 2):
        if current["status"] == "completed":
            return current
        current = service.step(task["id"])
    raise AssertionError("seeded acquisition did not complete")


def test_s13_seeded_acquisition_is_replayable_and_varies_by_seed_repeat_and_phase(tmp_path: Path) -> None:
    database = Database(tmp_path / "seeded-acquisition.sqlite3")
    database.initialize()
    service = AcquisitionService(database)

    first = _complete_seeded_task(service, name="S1", seed=101, repeat_count=3)
    replay = _complete_seeded_task(service, name="S1-replay", seed=101, repeat_count=3)
    different = _complete_seeded_task(service, name="S2", seed=102)

    def band_hashes(task: dict) -> list[str]:
        return [service.band(sample["id"])[0]["mean_sha256"] for sample in task["samples"]]

    first_hashes = band_hashes(first)
    assert first_hashes == band_hashes(replay)
    assert len(set(first_hashes)) == 3
    assert different["samples"][0]["bands"][0]["mean_sha256"] != first_hashes[0]

    first_sample = first["samples"][0]
    frames = service.frames(first["id"], repeat_index=0, ccd_index=0)
    assert len({frame["points_sha256"] for frame in frames}) == 4
    mean_points = service.band(first_sample["id"], include_points=True)[0]["mean_points"]
    assert max(mean_points) > 0.1
    assert first["last_event"]["details"]["simulation_model"] == "seeded-acq-v1"
    assert first["last_event"]["details"]["source_sha256"]
    assert first["last_event"]["details"]["simulated_points_sha256"]


def test_s13_float32_average_and_evaporation_interval_golden(tmp_path: Path) -> None:
    database = Database(tmp_path / "acquisition.sqlite3")
    database.initialize()
    service = AcquisitionService(database)

    burn_a = struct.pack("<4H", 100, 200, 300, 400)
    burn_b = struct.pack("<4H", 120, 180, 320, 360)
    dark = struct.pack("<4H", 20, 40, 60, 80)
    mean = average_points([burn_a, burn_b], [dark], 4)
    assert struct.unpack("<4f", mean) == pytest.approx((90.0, 150.0, 250.0, 300.0))
    assert hashlib.sha256(mean).hexdigest() == hashlib.sha256(struct.pack("<4f", 90.0, 150.0, 250.0, 300.0)).hexdigest()
    low = average_points([struct.pack("<2H", 1, 1)], [struct.pack("<2H", 10, 10)], 2, burn_cycle_seconds=2, dark_cycle_seconds=1)
    assert struct.unpack("<2f", low) == (0.10000000149011612, 0.10000000149011612)

    task = service.create_task(
        {
            "task_kind": "evaporation",
            "name": "蒸发黄金探针",
            "device_profile_id": 1,
            "ccd_layout_id": "default",
            "burn_frame_count": 2,
            "dark_frame_count": 1,
            "pre_excitation_seconds": 1,
            "sampling_period_seconds": 1,
            "storage_mode": "full_interval",
            "simulator_sample": "280-288.acq",
        }
    )
    service.start(task["id"])
    for _ in range(4):
        completed = service.step(task["id"])
    assert completed["status"] == "completed"
    frames = service.frames(task["id"], include_points=True)
    assert len(frames) == 15
    assert all(frame["raw_byte_length"] == 24579 for frame in frames)
    assert all(frame["points_count"] == 2048 for frame in frames)
    assert all(frame["dtype"] == "uint16" and frame["endianness"] == "little" for frame in frames)

    analysis = service.mark_interval(task["id"], {"label": "有效段", "start_frame_index": 0, "end_frame_index": 1})
    assert all("points_blob" not in curve for curve in analysis["curves"])
    assert any(len(curve.get("points", [])) == 2048 for curve in analysis["curves"])
    json.dumps(analysis)
    stat = next(item for item in analysis["intervals"][0]["stats"] if item["ccd_index"] == 0)
    burn_points = [frame["points"] for frame in frames if frame["phase"] == "burn" and frame["ccd_index"] == 0]
    assert stat["frame_count"] == 2
    assert stat["point_mean"][0] == pytest.approx(sum(frame[0] for frame in burn_points[:2]) / 2)
    assert stat["point_mean_sha256"]
    band = service.band(completed["samples"][0]["id"])[0]
    assert band["storage_mode"] == "full_interval"
    assert band["burn_sha256"] and band["dark_sha256"]


def test_s13_queue_repeats_pause_resume_and_post_name_preserve_hash(tmp_path: Path) -> None:
    database = Database(tmp_path / "queue.sqlite3")
    database.initialize()
    service = AcquisitionService(database)
    queue = service.sample_queues.create("S13 队列", [{"pre_name": "A001", "repeats": 2}], None)
    item = queue["items"][0]
    task = service.create_task({"task_kind": "sample", "name": "重复任务", "queue_id": queue["id"], "queue_item_id": item["id"], "burn_frame_count": 1, "dark_frame_count": 0, "pre_excitation_seconds": 0}, None)
    service.start(task["id"])
    first = service.step(task["id"])
    assert first["status"] == "between_repeats" and first["completed_repeats"] == 1
    service.step(task["id"])
    paused = service.pause(task["id"])
    assert paused["status"] == "paused"
    assert service.pause(task["id"])["status"] == "paused"
    assert service.resume(task["id"])["status"] == "pre_excitation"
    final = service.step(task["id"])
    assert final["status"] == "completed" and final["completed_repeats"] == 2
    queue_after = service.sample_queues.get(queue["id"])
    assert queue_after["items"][0]["spectrum_hash"] == final["result_sha256"]
    sample_id = final["samples"][0]["id"]
    before = service.band(sample_id)[0]["mean_sha256"]
    renamed = service.rename(final["id"], sample_id, "A001-post", None)
    assert renamed["sample_name"] == "A001-post"
    assert service.band(sample_id)[0]["mean_sha256"] == before
    with pytest.raises(AcquisitionError) as blocked:
        service.rename(final["id"], sample_id, "", None)
    assert blocked.value.code == "sample_name_invalid"


def test_s13_queue_repeat_counts_and_sampling_period_contract(tmp_path: Path) -> None:
    database = Database(tmp_path / "queue-repeat-contract.sqlite3")
    database.initialize()
    service = AcquisitionService(database)
    queue = service.sample_queues.create(
        "重复次数契约",
        [{"pre_name": "R1", "repeats": 1}, {"pre_name": "R3", "repeats": 3}, {"pre_name": "R10", "repeats": 10}],
        None,
    )
    for item, expected in zip(queue["items"], (1, 3, 10), strict=True):
        task = service.create_task({
            "task_kind": "sample",
            "name": f"队列重复 {expected}",
            "queue_id": queue["id"],
            "queue_item_id": item["id"],
            "repeat_count": 1,
        })
        assert task["repeat_count"] == expected

    assert service.create_task({"task_kind": "sample", "name": "默认周期"})["sampling_period_seconds"] == 1
    assert service.create_task({"task_kind": "sample", "name": "最小周期", "sampling_period_seconds": 0.01})["sampling_period_seconds"] == 0.01
    assert service.create_task({"task_kind": "sample", "name": "最大周期", "sampling_period_seconds": 60})["sampling_period_seconds"] == 60
    for value in (0, -1, 0.009, 0.015, 60.01, float("inf")):
        with pytest.raises(AcquisitionError):
            service.create_task({"task_kind": "sample", "name": "非法周期", "sampling_period_seconds": value})


def test_s13_published_method_binding_makes_completed_sample_available_to_s16(tmp_path: Path) -> None:
    database = Database(tmp_path / "method-binding.sqlite3")
    database.initialize()
    service = AcquisitionService(database)
    now = utc_now()
    with database.write() as db:
        method_id = int(db.execute(
            "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES ('S13-S16 方法', '', 'spectral', 'active', 3, ?, ?)",
            (now, now),
        ).lastrowid)
        method_version_id = int(db.execute(
            "INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at) VALUES (?, 3, 'published', '{}', '[]', ?)",
            (method_id, now),
        ).lastrowid)

    method_option = next(item for item in service.options()["methods"] if item["method_id"] == method_id)
    assert method_option == {"method_id": method_id, "method_version": 3, "name": "S13-S16 方法"}

    task = service.create_task({
        "task_kind": "sample",
        "name": "方法绑定样品",
        "method_id": method_id,
        "method_version": 3,
        "burn_frame_count": 1,
        "dark_frame_count": 0,
        "pre_excitation_seconds": 0,
    })
    assert task["method_version_id"] == method_version_id
    assert task["method_id"] == method_id
    assert task["method_version"] == 3

    service.start(task["id"])
    completed = service.step(task["id"])
    assert completed["status"] == "completed"
    analysis_sample = next(item for item in AnalysisService(database).options()["samples"] if item["acquisition_task_id"] == task["id"])
    assert analysis_sample["method_version_id"] == method_version_id
    assert analysis_sample["method_id"] == method_id
    assert analysis_sample["method_version"] == 3


def test_s13_api_permissions_and_damaged_frame_is_marked_not_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    main_module._device_service_instance = None
    main_module._dispersion_service_instance = None
    main_module._acquisition_service_instance = None
    with TestClient(main_module.app) as client:
        assert client.get("/api/v1/acquisitions/tasks").status_code == 401
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        options = client.get("/api/v1/acquisitions/options", headers=headers)
        assert options.status_code == 200
        capability = next(item for item in client.get("/api/v1/capabilities").json()["capabilities"] if item["key"] == "acquisition")
        assert {"acquisition.read", "acquisition.write", "acquisition.execute"}.issubset(capability["permissions"])
        default_task = client.post(
            "/api/v1/acquisitions/tasks",
            headers=headers,
            json={"task_kind": "sample", "name": "默认参数任务"},
        )
        assert default_task.status_code == 201
        assert default_task.json()["sampling_period_seconds"] == 1
        for period in (0, -1, 0.009, 0.015, 60.01):
            rejected = client.post(
                "/api/v1/acquisitions/tasks",
                headers=headers,
                json={"task_kind": "sample", "name": "非法周期", "sampling_period_seconds": period},
            )
            assert rejected.status_code == 422
            assert rejected.json()["detail"]["code"] == "request_validation_failed"
        task = client.post("/api/v1/acquisitions/tasks", headers=headers, json={"task_kind": "sample", "name": "故障任务", "device_profile_id": 1, "ccd_layout_id": "default", "burn_frame_count": 2, "dark_frame_count": 0, "pre_excitation_seconds": 0, "fault_frame": 0}).json()
        assert client.post(f"/api/v1/acquisitions/tasks/{task['id']}/start", headers=headers).status_code == 200
        first = client.post(f"/api/v1/acquisitions/tasks/{task['id']}/step", headers=headers)
        assert first.json()["burn_frames_captured"] == 1
        failed = client.post(f"/api/v1/acquisitions/tasks/{task['id']}/step", headers=headers)
        assert failed.status_code == 200 and failed.json()["status"] == "failed"
        frames = client.get(f"/api/v1/acquisitions/tasks/{task['id']}/frames", headers=headers).json()
        assert len(frames) == 10
        assert sum(int(frame["damaged"]) for frame in frames) == 5
        assert sum(1 for frame in frames if not frame["damaged"]) == 5
        with main_module.database.read() as db:
            assert db.execute("SELECT COUNT(*) FROM acquisition_sample_bands").fetchone()[0] == 0
            actions = {row[0] for row in db.execute("SELECT action FROM audit_events WHERE target_type='acquisition'")}
        assert {"acquisition.task.create", "acquisition.task.start", "acquisition.frame.capture", "acquisition.task.failed"}.issubset(actions)
