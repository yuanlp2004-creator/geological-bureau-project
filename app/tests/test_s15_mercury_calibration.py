"""HTTP and storage compatibility for historical mercury calibration sessions."""

import sqlite3

import pytest

from tests.legacy_history_fixture import MERCURY, seed_mercury_history
from tests.test_methods import method_client


def test_s15_reference_lines_and_version_history_remain_readable(method_client):
    client, runtime, headers = method_client
    applied_id, rolled_id = seed_mercury_history(runtime.database)
    options = client.get(f"{MERCURY}/options", headers=headers).json()
    assert any(line["wavelength_nm"] == 253.6517 for line in options["reference_lines"])
    assert options["real_protocol_available"] is False
    assert {session["id"] for session in client.get(f"{MERCURY}/sessions", headers=headers).json()} == {
        applied_id, rolled_id,
    }
    applied = client.get(f"{MERCURY}/sessions/{applied_id}", headers=headers).json()
    rolled = client.get(f"{MERCURY}/sessions/{rolled_id}", headers=headers, params={"include_points": "true"}).json()
    assert applied["status"] == "applied" and rolled["status"] == "rolled_back"
    assert applied["safe_off"] and rolled["safe_off"]
    assert "points" not in applied["frames"][0]
    assert rolled["frames"][0]["points"][1027] == 2500
    assert rolled["before_version"]["id"] == applied["candidate_version"]["id"] == rolled["active_version"]["id"]
    assert rolled["candidate_version"]["id"] != rolled["active_version"]["id"]
    assert options["active_alignments"][0]["version_id"] == rolled["active_version"]["id"]

    with runtime.database.write() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE mercury_frames SET points_blob=X'0000' WHERE session_id=?", (applied_id,))
    with runtime.database.write() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE mercury_alignment_versions SET offset_points=15 WHERE id=?", (rolled["candidate_version"]["id"],))


def test_s15_v1_routes_allow_history_only(method_client):
    client, runtime, headers = method_client
    applied_id, _ = seed_mercury_history(runtime.database)
    collection = f"{MERCURY}/sessions"
    detail = f"{collection}/{applied_id}"
    for path in (f"{MERCURY}/options", collection, detail):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers).status_code == 200
    assert client.post(collection, headers=headers).status_code == 405
    for action in ("start", "step", "apply", "rollback", "stop"):
        assert client.post(f"{detail}/{action}", headers=headers).status_code == 404
    assert client.get(detail, headers=headers).json()["status"] == "applied"

    paths = client.get("/openapi.json").json()["paths"]
    assert {path: set(verbs) for path, verbs in paths.items() if path.startswith(MERCURY)} == {
        f"{MERCURY}/options": {"get"},
        collection: {"get"},
        f"{collection}/{{session_id}}": {"get"},
    }
