"""合同新增三项的真实 API、公式复用、删除原子性与版本升级验证。"""

import sqlite3

import pytest

from backend.db import Database, SCHEMA_VERSION
from backend.modules.acquisition import AcquisitionError, AcquisitionService
from backend.modules.analysis import AnalysisError, AnalysisService
from backend.modules.methods import MethodService
from backend.modules.sample_queues import SampleQueueError
from tests.test_methods import method_client, _create, _publish
from tests.test_s16_analysis import _seed, _finish
from tests.contract_sync_support import checkpoint
from tests.test_spectral_lines import _line
from backend.modules.methods.geometry import MethodGeometry


# 完成指定采集任务并拒绝意外失败，复用真实状态机。
def complete(service, task):
    task = service.start(task["id"])
    for _ in range(30):
        if task["status"] == "completed":
            return task
        task = service.step(task["id"])
    raise AssertionError(task)


# 验证 12/20 位模式持久、缩短拒绝、旧 SAM 字节限制和后命名哈希不变。
def test_number_modes_and_linked_rename(method_client):
    client, runtime, headers = method_client
    name = "20261003000100000001"
    response = client.post("/api/v1/sample-queues", headers=headers, json={
        "name": "20位队列", "name_length": 20, "items": [{"pre_name": name, "repeats": 1}]})
    assert response.status_code == 201, response.text
    queue = response.json()
    assert queue["items"][0]["pre_name"] == name
    response = client.patch(f"/api/v1/sample-queues/{queue['id']}", headers=headers, json={
        "name_length": 12, "items": [{"id": queue["items"][0]["id"], "pre_name": name, "repeats": 1}]})
    assert response.status_code == 422
    assert runtime.sample_queue_service().get(queue["id"])["name_length"] == 20
    with pytest.raises(SampleQueueError, match="10 字节"):
        runtime.sample_queue_service().export_sam(queue["id"])
    method = _publish(client, headers, _create(client, headers)["id"])
    service = runtime.acquisition_service()
    task = complete(service, service.create_task({"queue_id": queue["id"], "queue_item_id": queue["items"][0]["id"],
        "method_id": method["id"], "method_version": method["current_version"], "burn_frame_count": 1, "dark_frame_count": 0}))
    fingerprint = task["samples"][0]["result_sha256"]
    renamed = service.rename(task["id"], task["samples"][0]["id"], "20261003000100000002", name_length=20)
    assert renamed["sample_name"] == "20261003000100000002"
    assert renamed["samples"][0]["result_sha256"] == fingerprint
    assert runtime.sample_queue_service().get(queue["id"])["items"][0]["post_name"] == renamed["sample_name"]
    for length in (12, 20):
        response = client.post("/api/v1/acquisitions/tasks", headers=headers,
            json={"sample_name": "1" * (length + 1), "name_length": length})
        assert response.status_code == 422


# 验证采集中删除立即收尾、在途互斥、已收帧保留以及重复删除不重复审计。
def test_discard_during_capture_preserves_frames_and_cannot_resume(tmp_path):
    database = Database(tmp_path / "capture.sqlite3")
    database.initialize()
    service = AcquisitionService(database)
    task = service.start(service.create_task({"burn_frame_count": 5, "dark_frame_count": 1,
        "pre_excitation_seconds": 0, "ccd_indices": [0]})["id"])
    while task["burn_frames_captured"] == 0:
        task = service.step(task["id"])
    before = service.frames(task["id"], include_points=True)
    with service._control_scope(task["id"]), pytest.raises(AcquisitionError, match="正在执行"):
        service.discard(task["id"], "能量不足")
    discarded = service.discard(task["id"], "能量不足")
    assert discarded["status"] == "stopped"
    assert all(sample["discarded"] for sample in discarded["samples"])
    assert service.frames(task["id"], include_points=True) == before
    with pytest.raises(AcquisitionError):
        service.step(task["id"])
    assert service.get_task(task["id"])["status"] == "stopped"
    service.discard(task["id"], "能量不足")
    with pytest.raises(AcquisitionError):
        service.resume(task["id"])
    with database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE action='acquisition.sample.discard'").fetchone()[0] == 1


# 验证完成样品删除后不再出现在谱图或新分析来源，队列可重新采集。
def test_discard_completed_sample_blocks_new_analysis_and_releases_queue(method_client):
    client, runtime, headers = method_client
    method = _publish(client, headers, _create(client, headers)["id"])
    queue = runtime.sample_queue_service().create("重测队列", [{"pre_name": "A001", "repeats": 1}], None)
    service = runtime.acquisition_service()
    payload = {"method_id": method["id"], "method_version": method["current_version"],
        "queue_id": queue["id"], "queue_item_id": queue["items"][0]["id"], "burn_frame_count": 1, "dark_frame_count": 0}
    task = complete(service, service.create_task(payload))
    sample_id = task["samples"][0]["id"]
    response = client.post(f"/api/v1/acquisitions/tasks/{task['id']}/discard", headers=headers, json={"reason": "激发不足"})
    assert response.status_code == 200, response.text
    assert sample_id not in {sample["id"] for sample in service.spectrum_records()}
    assert sample_id not in {sample["id"] for sample in runtime.analysis_service().options()["samples"]}
    response = client.post("/api/v1/analyses/runs", headers=headers, json={"acquisition_sample_ids": [sample_id]})
    assert response.status_code == 409, response.text
    assert service.measurement_snapshot(task["id"])["samples"] == []
    assert runtime.sample_queue_service().get(queue["id"])["items"][0]["spectrum_hash"] is None
    assert complete(service, service.create_task(payload))["status"] == "completed"


# 已被分析引用的样品必须拒绝删除，检查记录与哈希整体不变。
def test_analyzed_sample_discard_is_atomic_and_forbidden(tmp_path):
    database = Database(tmp_path / "analyzed.sqlite3")
    version_id, sample_ids = _seed(database)
    analysis = AnalysisService(database, methods=MethodService(database))
    analysis.create_run({"acquisition_sample_ids": sample_ids, "method_version_id": version_id})
    service = AcquisitionService(database)
    with database.read() as db:
        task_id = db.execute("SELECT task_id FROM acquisition_samples WHERE id=?", (sample_ids[0],)).fetchone()[0]
        before = list(db.iterdump())
    with pytest.raises(AcquisitionError, match="分析引用"):
        service.discard(task_id, "能量不足")
    with database.read() as db:
        assert list(db.iterdump()) == before


# 即时结果逐项对照既有正式分析的峰位、净强度和内标/高斯信号，且读取零写入。
def test_measurement_matches_formal_algorithms_and_curve_version(tmp_path):
    database = Database(tmp_path / "measurement.sqlite3")
    version_id, sample_ids = _seed(database)
    analysis = AnalysisService(database, methods=MethodService(database))
    formal = _finish(analysis, analysis.create_run({"acquisition_sample_ids": sample_ids, "method_version_id": version_id}))
    service = AcquisitionService(database)
    with database.read() as db:
        task_id = db.execute("SELECT task_id FROM acquisition_samples WHERE id=?", (sample_ids[0],)).fetchone()[0]
        before = list(db.iterdump())
    measured = analysis.measurement_results(service.measurement_snapshot(task_id))
    assert len(measured["rows"]) == 3
    for row in measured["rows"]:
        expected = next(value for value in formal["line_results"] if value["sample_position"] == 0 and value["line_id"] == row["line_id"])
        for key in ("peak_position", "peak_height", "net_signal", "quantitative_signal"):
            assert row[key] == expected[key]
        assert row["concentration"] is None
    with database.read() as db:
        assert list(db.iterdump()) == before


# 通过实际采集、质控、拟合与发布证明浓度沿用精确方法版本的曲线。
def test_measurement_concentration_uses_published_curve(method_client):
    import json
    client, runtime, headers = method_client
    method = _create(client, headers, "即时浓度方法")
    with runtime.database.read() as db:
        coefficients = json.loads(db.execute("SELECT coefficients_json FROM dispersion_calibrations WHERE name='default'").fetchone()[0])
    response = client.post(f"/api/v1/methods/{method['id']}/lines", headers=headers, json=_line(
        MethodGeometry._step_to_wave(900.0, coefficients), background_offset_points=20,
        standard_points=[{"name": "S1", "value": 10.0, "active": True}, {"name": "S2", "value": 20.0, "active": True},
                         {"name": "S3", "value": 30.0, "active": True}, {"name": "S4", "value": 40.0, "active": True}]))
    assert response.status_code == 201, response.text
    line_id = response.json()["changed_line_id"]
    method = _publish(client, headers, method["id"])
    acquisition = runtime.acquisition_service()
    tasks = [complete(acquisition, acquisition.create_task({"sample_name": name, "sample_kind": kind,
        "method_id": method["id"], "method_version": method["current_version"], "seed": seed,
        "burn_frame_count": 2, "dark_frame_count": 1, "pre_excitation_seconds": 0, "ccd_indices": [0]}))
        for name, kind, seed in [("S1", "standard", 10), ("S2", "standard", 20), ("S3", "standard", 30),
                                 ("S4", "standard", 40), ("N1", "normal", 50)]]
    analysis = runtime.analysis_service()
    run = _finish(analysis, analysis.create_run({"acquisition_sample_ids": [task["samples"][0]["id"] for task in tasks]}))
    assert run["status"] == "completed", run
    run = analysis.build_quality(run["id"])
    run = analysis.fit_standard_curve(run["id"], line_id, {"reason": "验证即时浓度", "fit_mode": "linear", "coordinate_type": "normal"})
    curve_id = run["curves"]["lines"][0]["snapshots"][-1]["id"]
    run = analysis.publish_standard_curve(run["id"], line_id, curve_id, "验证即时浓度")
    measured = analysis.measurement_results(acquisition.measurement_snapshot(tasks[-1]["id"]))
    expected = next(row for row in run["curves"]["results"] if row["sample_name"] == "N1")
    assert measured["rows"][0]["concentration"] == pytest.approx(expected["calculated_value"])
    assert measured["rows"][0]["curve_snapshot_id"] == curve_id
    assert measured["rows"][0]["unit"] == "ug/g"
    # 不同方法版本没有对应已发布曲线，不得借用旧版本浓度。
    snapshot = acquisition.measurement_snapshot(tasks[-1]["id"])
    snapshot["method_version_id"] = None
    assert analysis.measurement_results(snapshot)["rows"] == []


# 新版模式升级失败整笔回滚，v13 的正式内容与用户设置保留。
def test_contract_v22_upgrade_and_failure_rollback(tmp_path, monkeypatch):
    import backend.migrations.v22_contract_samples as db_module
    path = tmp_path / "v13.sqlite3"
    checkpoint(path, 21)
    database = Database(path)
    with database.read() as db:
        before = list(db.iterdump())
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "SQL", db_module.SQL + "\nINVALID SQL;")
        with pytest.raises(sqlite3.OperationalError):
            database.initialize()
    with database.read() as db:
        assert list(db.iterdump()) == before
    database.initialize()
    with database.read() as db:
        assert int(db.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0]) == SCHEMA_VERSION == 23
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


# 验证只读采集账户可看测量但不能删除，未登录请求仍被拒绝。
def test_measurement_and_discard_permission_boundaries(method_client):
    client, runtime, headers = method_client
    task = runtime.acquisition_service().create_task({"sample_name": "权限验证"})
    role = client.post("/api/v1/roles", headers=headers, json={"name": "contract-reader", "permission_keys": ["acquisition.read"]})
    assert role.status_code == 201, role.text
    response = client.post("/api/v1/users", headers=headers, json={"username": "contract-reader", "password": "reader-test-password", "role_ids": [role.json()["id"]]})
    assert response.status_code == 201, response.text
    token = client.post("/api/v1/auth/login", json={"username": "contract-reader", "password": "reader-test-password"}).json()["access_token"]
    reader = {"Authorization": f"Bearer {token}"}
    measurements = f"/api/v1/acquisitions/tasks/{task['id']}/measurements"
    discard = f"/api/v1/acquisitions/tasks/{task['id']}/discard"
    assert client.get(measurements, headers=reader).status_code == 200
    assert client.post(discard, headers=reader, json={"reason": "能量不足"}).status_code == 403
    assert client.get(measurements).status_code == 401
    assert client.post(discard, json={"reason": "能量不足"}).status_code == 401
