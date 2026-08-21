from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database, utc_now
from backend.app.modules.acquisition import AcquisitionService
from backend.app.modules.analysis import AnalysisError, AnalysisService, evaluate_curve, fit_curve, repeat_statistics
from backend.app.modules.methods import MethodService


def test_s17_seeded_acquisition_produces_distinct_standard_and_repeat_intensities(tmp_path: Path) -> None:
    database = Database(tmp_path / "s17-seeded-acquisition.sqlite3")
    database.initialize()
    acquisition = AcquisitionService(database)
    methods = MethodService(database)
    with database.write() as db:
        layout = db.execute("SELECT * FROM ccd_layouts WHERE name='default'").fetchone()
        calibration = db.execute("SELECT * FROM dispersion_calibrations WHERE name='default'").fetchone()
        coefficients = json.loads(calibration["coefficients_json"])
        wavelength = methods._step_to_wave(900.0, coefficients)
        line = {
            "id": "seeded-L1",
            "order": 0,
            "line_type": "analysis",
            "element": "Cu",
            "wavelength_nm": wavelength,
            "actual_wavelength_nm": wavelength,
            "enabled": True,
            "scan_width_points": 9,
            "background_offset_points": 0,
            "peak_mode": "max_single_point",
            "peak_width_points": 1,
            "internal_standard_mode": "none",
            "standard_points": [
                {"name": "S1", "value": 1.0, "active": True},
                {"name": "S2", "value": 2.0, "active": True},
                {"name": "S3", "value": 3.0, "active": True},
                {"name": "S4", "value": 4.0, "active": True},
            ],
        }
        conditions = {
            "ccd_layout_id": layout["id"],
            "dispersion_calibration_id": calibration["id"],
            "selected_ccds": [0],
            "calculation_profile": "modern_v1",
        }
        payload = {"payload_schema": "method-v2-lines", "conditions": conditions, "lines": [line]}
        now = utc_now()
        method_id = int(
            db.execute(
                "INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES ('S17 种子回归', '', 'spectral', 'active', 1, ?, ?)",
                (now, now),
            ).lastrowid
        )
        version_id = int(
            db.execute(
                "INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at) VALUES (?, 1, 'published', ?, '[]', ?)",
                (method_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), now),
            ).lastrowid
        )

    sample_ids: list[int] = []
    for offset, name in enumerate(("S1", "S2", "S3", "S4", "QA-1")):
        task = acquisition.create_task(
            {
                "task_kind": "sample",
                "name": f"seeded-{name}",
                "method_id": method_id,
                "method_version": 1,
                "sample_name": name,
                "sample_kind": "standard" if name.startswith("S") else "test",
                "ccd_indices": [0],
                "repeat_count": 3 if name == "QA-1" else 1,
                "burn_frame_count": 3,
                "dark_frame_count": 1,
                "pre_excitation_seconds": 0,
                "seed": 101 + offset,
            }
        )
        current = acquisition.start(task["id"])
        for _ in range(24):
            if current["status"] == "completed":
                break
            current = acquisition.step(task["id"])
        assert current["status"] == "completed"
        sample_ids.extend(int(sample["id"]) for sample in current["samples"])

    analysis = AnalysisService(database)
    run = analysis.start(
        analysis.create_run(
            {
                "name": "S17 种子端到端回归",
                "acquisition_sample_ids": sample_ids,
                "method_version_id": version_id,
                "calculation_profile": "modern_v1",
            }
        )["id"]
    )
    for _ in range(32):
        if run["status"] == "completed":
            break
        run = analysis.step(run["id"])
    assert run["status"] == "completed"

    analysis_results = [item for item in run["line_results"] if item["line_id"] == "seeded-L1"]
    standards = [item["quantitative_signal"] for item in analysis_results if item["sample_position"] < 4]
    qa_repeats = [item["quantitative_signal"] for item in analysis_results if item["sample_position"] >= 4]
    assert len(set(standards)) == 4
    assert len(set(qa_repeats)) == 3

    quality = analysis.build_quality(run["id"])
    points = quality["curves"]["lines"][0]["workspace"]["points"]
    assert [point["name"] for point in points] == ["S1", "S2", "S3", "S4"]
    assert all(point["original_intensity"] is not None for point in points)
    assert len({point["original_intensity"] for point in points}) == 4


def _seed_completed_run(database: Database) -> tuple[int, int]:
    database.initialize()
    with database.write() as db:
        layout_id = int(db.execute("SELECT id FROM ccd_layouts WHERE name='default'").fetchone()[0])
        profile_id = int(db.execute("SELECT id FROM device_profiles ORDER BY id LIMIT 1").fetchone()[0])
        now = utc_now()
        line = {
            "id": "L1", "order": 1, "line_type": "analysis", "element": "Cu", "wavelength_nm": 324.754,
            "actual_wavelength_nm": 324.754, "enabled": True, "fit_mode": "linear", "coordinate_type": "normal",
            "unit": "ug/g", "valid_range_min": 0.0, "valid_range_max": 100.0,
            "standard_points": [
                {"name": "S1", "value": 5.0, "active": True}, {"name": "S2", "value": 8.0, "active": True},
                {"name": "S3", "value": 11.0, "active": True}, {"name": "S4", "value": 14.0, "active": True},
            ],
        }
        conditions = {"maximum_id_deviation": 1.0, "rsd_enabled": True, "rsd_threshold": 1.0}
        payload = {"payload_schema": "method-v2-lines", "conditions": conditions, "lines": [line]}
        method_id = int(db.execute("INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES ('S17 测试方法', '', 'spectral', 'active', 1, ?, ?)", (now, now)).lastrowid)
        version_id = int(db.execute("INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at) VALUES (?, 1, 'published', ?, '[]', ?)", (method_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), now)).lastrowid)
        sample_specs = {
            "S1": [0.98, 1.00, 1.02], "S2": [1.98, 2.00, 2.02], "S3": [2.98, 3.00, 3.02],
            "S4": [3.98, 4.00, 4.02], "N1": [2.49, 2.51],
        }
        run_samples: list[tuple[int, str, float]] = []
        for task_index, (sample_name, values) in enumerate(sample_specs.items()):
            task_id = int(db.execute(
                "INSERT INTO acquisition_tasks(task_kind, name, status, device_profile_id, ccd_layout_id, method_version_id, method_id, method_version, sample_name, sample_kind, naming_mode, storage_mode, repeat_count, burn_frame_count, dark_frame_count, countdown_seconds, countdown_remaining, pre_excitation_seconds, sampling_period_seconds, burn_cycle_seconds, dark_cycle_seconds, ccd_indices_json, created_at, updated_at) VALUES ('sample', ?, 'completed', ?, ?, ?, ?, 1, ?, ?, 'pre_recorded', 'averaged', ?, 1, 0, 0, 0, 0, 1, 1, 1, '[0]', ?, ?)",
                (f"task-{task_index}", profile_id, layout_id, version_id, method_id, sample_name, "standard" if sample_name.startswith("S") else "normal", len(values), now, now),
            ).lastrowid)
            for repeat_index, value in enumerate(values):
                sample_id = int(db.execute(
                    "INSERT INTO acquisition_samples(task_id, repeat_index, sample_name_original, sample_name, sample_kind, storage_mode, status, finalized, result_sha256, created_at, completed_at, updated_at) VALUES (?, ?, ?, ?, ?, 'averaged', 'completed', 1, ?, ?, ?, ?)",
                    (task_id, repeat_index, sample_name, sample_name, "standard" if sample_name.startswith("S") else "normal", hashlib.sha256(f"{sample_name}-{repeat_index}".encode()).hexdigest(), now, now, now),
                ).lastrowid)
                run_samples.append((sample_id, sample_name, value))
        snapshot = {"method_version_id": version_id, "samples": [item[0] for item in run_samples]}
        run_id = int(db.execute(
            "INSERT INTO analysis_runs(name, status, method_id, method_version_id, method_version, calculation_profile, slow_mode, intervention_timeout_seconds, current_sample_position, current_line_position, input_snapshot_json, input_sha256, result_sha256, created_at, updated_at, started_at, completed_at) VALUES ('S17 完成批次', 'completed', ?, ?, 1, 'modern_v1', 0, 300, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (method_id, version_id, len(run_samples), json.dumps(snapshot), hashlib.sha256(json.dumps(snapshot).encode()).hexdigest(), "s16-result", now, now, now, now),
        ).lastrowid)
        for position, (sample_id, sample_name, signal) in enumerate(run_samples):
            db.execute("INSERT INTO analysis_run_samples(run_id, position, acquisition_sample_id, sample_name, input_sha256, result_matrix_json, result_sha256, completed_at) VALUES (?, ?, ?, ?, ?, '[]', ?, ?)", (run_id, position, sample_id, sample_name, f"input-{position}", f"sample-result-{position}", now))
            source = {"position": position, "signal": signal}
            db.execute(
                "INSERT INTO analysis_line_results(run_id, sample_position, line_position, line_id, line_type, element, wavelength_nm, ccd_index, expected_position, peak_position, peak_height, background, net_signal, quantitative_signal, calculation_profile, intermediates_json, result_sha256, created_at) VALUES (?, ?, 0, 'L1', 'analysis', 'Cu', 324.754, 0, 100, 100, ?, 0, ?, ?, 'modern_v1', '{}', ?, ?)",
                (run_id, position, signal, signal, signal, hashlib.sha256(json.dumps(source).encode()).hexdigest(), now),
            )
    return run_id, version_id


def test_s17_repeat_statistics_boundaries() -> None:
    assert repeat_statistics([]) == {"effective_count": 0, "mean": None, "minimum": None, "maximum": None, "range": None, "stddev": None, "rsd": None, "id": None}
    assert repeat_statistics([4.0]) == {"effective_count": 1, "mean": 4.0, "minimum": 4.0, "maximum": 4.0, "range": 0.0, "stddev": 0.0, "rsd": 0.0, "id": 0.0}
    stats = repeat_statistics([1.0, 2.0, 3.0])
    assert stats["mean"] == 2.0 and stats["stddev"] == 1.0 and stats["range"] == 2.0
    assert stats["rsd"] == 50.0 and stats["id"] == pytest.approx(21.7147 * 1.0986122886681098)
    assert repeat_statistics([-1.0, 1.0])["id"] == 999.0


def test_s17_four_fits_coordinates_and_failure_boundaries() -> None:
    golden = json.loads((APP_ROOT.parent / "docs" / "s00-baseline" / "golden" / "legacy-curve-fit.json").read_text(encoding="utf-8"))
    for case in golden["least_squares_cases"]:
        fit = fit_curve(case["x"], case["y"], case["mode"])
        assert fit["coefficients"] == pytest.approx(case["expected_coefficients_c0_to_c3_float32"], abs=1e-5)
        assert evaluate_curve(fit, 2.5) == pytest.approx(case["expected_at_2_5"], abs=1e-5)
    spline_case = golden["natural_spline_case"]
    spline = fit_curve(spline_case["x"], spline_case["y"], "spline")
    assert spline["second_derivatives"] == pytest.approx(spline_case["second_derivatives"], abs=1e-5)
    for item in spline_case["evaluations"]:
        assert evaluate_curve(spline, item["x"]) == pytest.approx(item["expected_y_float32"], abs=1e-5)
    log_fit = fit_curve([1, 10, 100, 1000], [10, 100, 1000, 10000], "linear", "logarithmic")
    assert evaluate_curve(log_fit, 50, "logarithmic") == pytest.approx(500, rel=1e-6)
    with pytest.raises(AnalysisError, match="至少需要 4"):
        fit_curve([1, 2, 3], [1, 2, 3], "linear")
    with pytest.raises(AnalysisError) as duplicate:
        fit_curve([1, 1, 2, 3], [1, 2, 3, 4], "spline")
    assert duplicate.value.code == "analysis_curve_duplicate_x"
    with pytest.raises(AnalysisError) as nonpositive:
        fit_curve([0, 1, 2, 3], [1, 2, 3, 4], "linear", "logarithmic")
    assert nonpositive.value.code == "analysis_curve_log_nonpositive"
    with pytest.raises(AnalysisError) as ill_conditioned:
        fit_curve([1e12, 1e12 + 1, 1e12 + 2, 1e12 + 3], [1, 2, 3, 4], "cubic")
    assert ill_conditioned.value.code == "analysis_curve_ill_conditioned"


def test_s17_quality_adjust_fit_publish_merge_and_print_replay(tmp_path: Path) -> None:
    database = Database(tmp_path / "s17.sqlite3")
    run_id, _ = _seed_completed_run(database)
    service = AnalysisService(database)
    run = service.build_quality(run_id)
    assert run["quality"]["latest_snapshot"]["publishable"] is True
    s1 = next(item for item in run["quality"]["latest_snapshot"]["groups"] if item["sample_name"] == "S1")
    assert s1["statistics"]["effective_count"] == 3 and s1["warnings"]
    run = service.decide_quality(run_id, {"acquisition_task_id": s1["acquisition_task_id"], "line_id": "L1", "action": "accept", "line_result_id": None, "reason": "复核重复波动后接受"})
    assert next(item for item in run["quality"]["latest_snapshot"]["groups"] if item["sample_name"] == "S1")["warning_accepted"] is True
    member_ids = [item["line_result_id"] for item in s1["members"]]
    for member_id in member_ids:
        run = service.decide_quality(run_id, {"acquisition_task_id": s1["acquisition_task_id"], "line_id": "L1", "action": "exclude", "line_result_id": member_id, "reason": "边界测试剔除"})
    s1_empty = next(item for item in run["quality"]["latest_snapshot"]["groups"] if item["sample_name"] == "S1")
    assert s1_empty["statistics"]["effective_count"] == 0 and run["quality"]["latest_snapshot"]["publishable"] is False
    with pytest.raises(AnalysisError) as no_fit:
        service.fit_standard_curve(run_id, "L1", {"reason": "无有效重复时拟合"})
    assert no_fit.value.code == "analysis_curve_points_insufficient"
    for member_id in member_ids:
        run = service.decide_quality(run_id, {"acquisition_task_id": s1["acquisition_task_id"], "line_id": "L1", "action": "restore", "line_result_id": member_id, "reason": "恢复原始重复"})
    assert run["quality"]["latest_snapshot"]["publishable"] is True
    points = run["curves"]["lines"][0]["workspace"]["points"]
    assert [(point["name"], point["original_intensity"]) for point in points] == [
        ("S1", 1.0), ("S2", 2.0), ("S3", 3.0), ("S4", 4.0)
    ]

    run = service.curve_action(run_id, "L1", {"action": "adjust", "point_index": 1, "adjusted_intensity": 2.05, "reason": "标准点图形复核"})
    assert run["curves"]["lines"][0]["workspace"]["points"][1]["original_intensity"] == 2.0
    assert run["curves"]["lines"][0]["workspace"]["points"][1]["adjusted_intensity"] == 2.05
    run = service.fit_standard_curve(run_id, "L1", {"fit_mode": "quadratic", "coordinate_type": "normal", "reason": "二次拟合"})
    first_snapshot = run["curves"]["lines"][0]["snapshots"][-1]
    with database.read() as db:
        adjustment = db.execute("SELECT fit_mode, coordinate_type, points_json FROM analysis_curve_adjustment_sets WHERE id=?", (first_snapshot["adjustment_set_id"],)).fetchone()
        assert adjustment["fit_mode"] == "quadratic" and adjustment["coordinate_type"] == "normal"
        assert json.loads(adjustment["points_json"]) == first_snapshot["points"]
    run = service.publish_standard_curve(run_id, "L1", first_snapshot["id"], "发布首个有效快照")
    assert run["curves"]["lines"][0]["active_curve_snapshot_id"] == first_snapshot["id"]
    n1 = next(item for item in run["curves"]["results"] if item["curve_snapshot_id"] == first_snapshot["id"] and item["sample_name"] == "N1")
    assert n1["effective_count"] == 2 and n1["calculated_value"] == pytest.approx(evaluate_curve(first_snapshot["fit"], 2.5), rel=1e-9)
    run = service.merge_results(run_id, "保存当前谱线合并结果")
    merge = run["curves"]["merges"][-1]
    assert merge["curve_snapshot_ids"] == [first_snapshot["id"]]
    assert merge["results"][0]["values"][0]["curve_snapshot_id"] == first_snapshot["id"]

    html = service.curve_preview(run_id, first_snapshot["id"], "text")
    assert f"曲线快照 #{first_snapshot['id']}" in html and first_snapshot["result_sha256"] in html
    pdf, metadata = service.print_curve(run_id, first_snapshot["id"], "image")
    assert pdf.startswith(b"%PDF") and hashlib.sha256(pdf).hexdigest() == metadata["sha256"]
    replay_pdf, replay_metadata = service.print_curve(run_id, first_snapshot["id"], "image")
    assert replay_pdf == pdf and replay_metadata["sha256"] == metadata["sha256"]
    with database.read() as db:
        saved = db.execute("SELECT content_blob, content_sha256 FROM analysis_curve_print_jobs WHERE id=?", (metadata["job_id"],)).fetchone()
        assert bytes(saved["content_blob"]) == pdf and saved["content_sha256"] == metadata["sha256"]
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE analysis_curve_snapshots SET result_sha256='changed' WHERE id=?", (first_snapshot["id"],))

    run = service.curve_action(run_id, "L1", {"action": "set_active", "point_index": 3, "active": False, "reason": "停用边界"})
    with pytest.raises(AnalysisError) as insufficient:
        service.fit_standard_curve(run_id, "L1", {"reason": "有效点不足"})
    assert insufficient.value.code == "analysis_curve_points_insufficient"
    assert service.run(run_id)["curves"]["lines"][0]["active_curve_snapshot_id"] == first_snapshot["id"]
    run = service.curve_action(run_id, "L1", {"action": "restore_all", "reason": "全部恢复"})
    assert all(item["adjusted_intensity"] == item["original_intensity"] and item["active"] == item["original_active"] for item in run["curves"]["lines"][0]["workspace"]["points"])


def test_s17_api_permissions_manifest_and_print(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/analyses/runs/1/quality/recalculate").status_code == 401
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        run_id, _ = _seed_completed_run(main_module.database)
        quality = client.post(f"/api/v1/analyses/runs/{run_id}/quality/recalculate", headers=headers)
        assert quality.status_code == 200, quality.text
        fitted = client.post(f"/api/v1/analyses/runs/{run_id}/curves/L1/fit", headers=headers, json={"reason": "API 拟合"})
        assert fitted.status_code == 201, fitted.text
        snapshot_id = fitted.json()["curves"]["lines"][0]["snapshots"][-1]["id"]
        assert client.get(f"/api/v1/analyses/runs/{run_id}/curves/{snapshot_id}/preview?mode=image", headers=headers).status_code == 200
        printed = client.post(f"/api/v1/analyses/runs/{run_id}/curves/{snapshot_id}/print?mode=text", headers=headers)
        assert printed.status_code == 200 and printed.content.startswith(b"%PDF") and printed.headers["x-print-job-id"]
        capability = next(item for item in client.get("/api/v1/capabilities").json()["capabilities"] if item["key"] == "analysis")
        assert {"analysis.quality", "analysis.curve", "analysis.print"}.issubset(capability["permissions"])
