"""HTTP and storage compatibility for historical turn acquisitions."""

import sqlite3

import pytest

from tests.legacy_history_fixture import HARDWARE, seed_hardware_task
from tests.test_methods import method_client


def test_s14_history_preserves_attempts_intervals_and_evidence(method_client):
    client, runtime, headers = method_client
    history = seed_hardware_task(runtime.database, "automatic", retry=True)
    manual = seed_hardware_task(runtime.database, "manual", manual=True)
    base = f"{HARDWARE}/tasks/{history}"
    response = client.get(base, headers=headers, params={"include_points": "true"})
    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "completed" and task["progress"] == 100
    failed, confirmed = task["exposures"]
    assert not failed["confirmed"] and confirmed["confirmed"]
    assert confirmed["attempt"] == 1
    assert (confirmed["start_frame"], confirmed["end_frame"]) == (2, 3)
    assert confirmed["mean_points"][1024] == 4100.5
    assert [frame[1024] for frame in confirmed["frames"]] == [4100, 4101]
    assert failed["mean_points"][1024] == 8100.5
    assert client.get(f"{base}/decisions", headers=headers).json()[0]["decision"] == "retry"
    assert client.get(f"{base}/traces", headers=headers).json()[0]["safe_state"] == "off"
    task = client.get(f"{HARDWARE}/tasks/{manual}", headers=headers).json()
    assert task["steps"][0]["captured_seconds"] == 0.5
    assert task["frames"] and all(frame["id"] < 0 for frame in task["frames"])

    with runtime.database.write() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM hardware_exposure_results WHERE task_id=?", (history,))


def test_s14_v1_routes_allow_history_and_conversion_only(method_client):
    client, runtime, headers = method_client
    task_id = seed_hardware_task(runtime.database, "automatic")
    collection = f"{HARDWARE}/tasks"
    detail = f"{collection}/{task_id}"
    for path in (f"{HARDWARE}/options", collection, detail, *(detail + suffix for suffix in ("/frames", "/traces", "/decisions"))):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers).status_code == 200
    assert client.post(collection, headers=headers).status_code == 405
    for action in ("start", "step", "pause", "resume", "stop", "intervene"):
        assert client.post(f"{detail}/{action}", headers=headers).status_code == 404
    response = client.post("/api/v1/devices/profiles/1/connection-test",
                           params={"purpose": "hardware-acquisition"}, headers=headers)
    assert response.status_code == 403

    with runtime.database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM hardware_tasks").fetchone()[0] == 1
    paths = client.get("/openapi.json").json()["paths"]
    assert {path: set(verbs) for path, verbs in paths.items() if path.startswith(HARDWARE)} == {
        f"{HARDWARE}/options": {"get"},
        collection: {"get"},
        f"{collection}/{{task_id}}": {"get"},
        **{f"{collection}/{{task_id}}/{resource}": {"get"} for resource in ("frames", "traces", "decisions")},
        f"{collection}/{{task_id}}/analysis-sample": {"post"},
    }
