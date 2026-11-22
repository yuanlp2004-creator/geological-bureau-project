import json

import pytest

from tests.test_contract_additions import complete
from tests.test_methods import method_client


@pytest.mark.parametrize("kind", ["dispersion", "evaporation", "sample"])
def test_discard_staged_and_stopped_capture_tasks(method_client, kind):
    client, runtime, headers = method_client
    is_dispersion = kind == "dispersion"
    service = runtime.dispersion_service() if is_dispersion else runtime.acquisition_service()
    prefix = "dispersion" if is_dispersion else "acquisitions"
    base = f"/api/v1/{prefix}/tasks"
    payload = {"name": f"{kind}-删除验收", "ccd_indices": [0], "pre_excitation_seconds": 0,
               "dark_frame_count": 0}
    payload.update({"frame_count": 2} if is_dispersion else {"task_kind": kind, "burn_frame_count": 2})
    draft = service.create_task(payload)
    active = service.create_task(payload)
    active_path = f"{base}/{active['id']}"
    draft_path = f"{base}/{draft['id']}"
    assert client.delete(draft_path).status_code == 401
    assert client.post(active_path + "/start", headers=headers).status_code == 200
    assert client.delete(active_path, headers=headers).status_code == 409
    assert client.delete(draft_path, headers=headers).status_code == 204
    assert client.post(draft_path + "/start", headers=headers).status_code == 409
    assert client.post(active_path + "/stop", headers=headers).status_code == 200
    assert client.delete(active_path, headers=headers).status_code == 204
    assert client.delete(active_path, headers=headers).status_code == 204
    assert client.get(base, headers=headers, params={"include_discarded": "false"}).json() == []
    with runtime.database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action=?",
                          ("dispersion.task.discard" if is_dispersion else "acquisition.task.discard",)).fetchone()[0] == 2


def test_native_dispersion_group_uses_real_frames_and_archives_atomically(method_client):
    client, runtime, headers = method_client
    service = runtime.dispersion_service()
    ids = []
    for index, angle in enumerate((17, 4)):
        task = service.create_task({"name": "双角度色散", "ccd_indices": [0, 1], "frame_count": 2,
                                    "dark_frame_count": 1, "pre_excitation_seconds": 0},
                                   capture_turn={"group": "test-turns", "angle_deg": angle, "turn_index": index,
                                                 "multiple": True, "reference_coefficients": [0, 1, 0]})
        task = service.start_task(task["id"])
        for _ in range(12):
            if task["status"] == "completed":
                break
            task = service.step_task(task["id"])
        assert task["status"] == "completed"
        ids.append(task["id"])
    group = "dispersion:test-turns"
    group_records = client.get("/api/v1/spectra/records", params={"group": group}, headers=headers).json()
    assert {(row["angle_deg"], row["turn_index"], row["format"]) for row in group_records} == {
        (17, 0, "dispersion"), (4, 1, "dispersion")}
    assert {row["key"]: row["record_count"] for row in client.get("/api/v1/spectra/files", headers=headers).json()}[group] == 2
    before = [service.frames(identifier) for identifier in ids]
    for identifier in ids:
        detail = client.get(f"/api/v1/spectra/dispersion:{identifier}", headers=headers,
                            params={"ccd": 1, "exposure_start": 1, "exposure_end": 2}).json()
        expected = service.observation_spectrum(identifier, 1, 1, 2)["points"]
        assert [point["value"] for point in detail["ccd"]["points"]] == expected
    assert client.delete(f"/api/v1/dispersion/tasks/{ids[0]}", headers=headers).status_code == 204
    assert service.list_tasks() == []
    assert client.get("/api/v1/spectra/records", params={"group": group}, headers=headers).json() == []
    assert client.get(f"/api/v1/spectra/dispersion:{ids[1]}", headers=headers).status_code == 404
    assert [service.frames(identifier) for identifier in ids] == before


def test_sample_task_shortcut_and_prepared_collection_protection(method_client):
    client, runtime, headers = method_client
    service = runtime.acquisition_service()
    task = complete(service, service.create_task({"task_kind": "sample", "sample_name": "待保护样品",
        "ccd_indices": [0], "burn_frame_count": 1, "dark_frame_count": 0, "pre_excitation_seconds": 0}))
    task_id, sample_id = task["id"], task["samples"][0]["id"]
    with runtime.database.write() as db:
        db.execute("""INSERT INTO postprocessing_prepared_targets
            (id,name,storage_mode,layout_json,ignition_json,records_json,created_at,updated_at)
            VALUES ('fixture','已保存输出集','averaged','{}','{}',?,'fixture','fixture')""",
                   (json.dumps([{"id": sample_id, "task_id": task_id}]),))
    rows = client.get("/api/v1/spectra/records", params={"group": f"task:{task_id}"}, headers=headers).json()
    assert [(row["id"], row["file_group_key"]) for row in rows] == [(f"sample:{sample_id}", "prepared:fixture")]
    result = client.delete(f"/api/v1/acquisitions/tasks/{task_id}", headers=headers)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "sample_used_in_prepared_collection"
    assert service.get_task(task_id)["discarded_at"] is None
