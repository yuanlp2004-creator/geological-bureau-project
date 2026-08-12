from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database, utc_now
from backend.app.modules.analysis import AnalysisError, AnalysisService, _search_peak, legacy_gaussian
from backend.app.modules.methods import MethodService


def _seed(database: Database, *, flat_gaussian: bool = False) -> tuple[int, list[int]]:
    database.initialize()
    with database.write() as db:
        layout = db.execute("SELECT * FROM ccd_layouts WHERE name='default'").fetchone()
        calibration = db.execute("SELECT * FROM dispersion_calibrations WHERE name='default'").fetchone()
        profile = db.execute("SELECT id FROM device_profiles ORDER BY id LIMIT 1").fetchone()[0]
        coefficients = json.loads(calibration["coefficients_json"])
        method_service = MethodService(database)

        def wave(point: int) -> float:
            return method_service._step_to_wave(float(point), coefficients)

        peak_points = {"reference-baseline": 500, "AL": 600, "IS": 700, "A-none": 900, "A-background": 1100, "A-gaussian": 1300}
        lines = [
            {"id": "reference-baseline", "order": 0, "line_type": "baseline", "element": "基线", "wavelength_nm": wave(500), "actual_wavelength_nm": wave(500), "enabled": True, "scan_width_points": 21, "background_offset_points": 0, "peak_mode": "max_single_point", "peak_width_points": 1, "internal_standard_mode": "none"},
            {"id": "AL", "order": 1, "line_type": "positioning", "element": "Mn", "wavelength_nm": wave(600), "actual_wavelength_nm": wave(600), "enabled": True, "scan_width_points": 9, "background_offset_points": 0, "peak_mode": "max_single_point", "peak_width_points": 1, "lower_peak": 100, "minimum_peak_ratio": 1.1, "internal_standard_mode": "none"},
            {"id": "IS", "order": 2, "line_type": "internal_standard", "element": "Fe", "wavelength_nm": wave(700), "actual_wavelength_nm": wave(700), "enabled": True, "scan_width_points": 9, "background_offset_points": 20, "peak_mode": "max_single_point", "peak_width_points": 1, "lower_peak": 100, "minimum_peak_ratio": 1.1, "internal_standard_mode": "none"},
            {"id": "A-none", "order": 3, "line_type": "analysis", "element": "Cu", "wavelength_nm": wave(900), "actual_wavelength_nm": wave(900), "enabled": True, "scan_width_points": 9, "background_offset_points": 20, "peak_mode": "max_single_point", "peak_width_points": 1, "lower_peak": 100, "minimum_peak_ratio": 1.1, "internal_standard_mode": "none", "alignment_line_id": "AL", "standard_points": []},
            {"id": "A-background", "order": 4, "line_type": "analysis", "element": "Zn", "wavelength_nm": wave(1100), "actual_wavelength_nm": wave(1100), "enabled": True, "scan_width_points": 9, "background_offset_points": 20, "peak_mode": "max_single_point", "peak_width_points": 1, "lower_peak": 100, "minimum_peak_ratio": 1.1, "internal_standard_mode": "background", "background_line_id": "reference-baseline", "standard_points": []},
            {"id": "A-gaussian", "order": 5, "line_type": "analysis", "element": "Ni", "wavelength_nm": wave(1300), "actual_wavelength_nm": wave(1300), "enabled": True, "scan_width_points": 9, "background_offset_points": 20, "peak_mode": "gaussian", "peak_width_points": 5, "lower_peak": 100, "minimum_peak_ratio": 1.1, "internal_standard_mode": "line", "internal_standard_line_id": "IS", "standard_points": []},
        ]
        conditions = {"ccd_layout_id": layout["id"], "dispersion_calibration_id": calibration["id"], "selected_ccds": [0], "reference_wavelength_nm": wave(500), "actual_reference_wavelength_nm": wave(500), "reference_width_points": 21, "analysis_unit": "ug/g", "calculation_profile": "modern_v1"}
        payload = {"payload_schema": "method-v2-lines", "conditions": conditions, "lines": lines}
        now = utc_now()
        method_id = db.execute("INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES ('S16 测试方法', '', 'spectral', 'active', 1, ?, ?)", (now, now)).lastrowid
        version_id = db.execute("INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at) VALUES (?, 1, 'published', ?, '[]', ?)", (method_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), now)).lastrowid
        sample_ids: list[int] = []
        for sample_index, sample_name in enumerate(("S16-A", "S16-B")):
            task_id = db.execute("INSERT INTO acquisition_tasks(task_kind, name, status, device_profile_id, ccd_layout_id, method_version_id, method_id, method_version, sample_name, sample_kind, naming_mode, storage_mode, repeat_count, burn_frame_count, dark_frame_count, countdown_seconds, countdown_remaining, pre_excitation_seconds, sampling_period_seconds, burn_cycle_seconds, dark_cycle_seconds, ccd_indices_json, created_at, updated_at) VALUES ('sample', ?, 'completed', ?, ?, ?, ?, 1, ?, 'normal', 'pre_recorded', 'averaged', 1, 1, 0, 0, 0, 0, 1, 1, 1, '[0]', ?, ?)", (f"task-{sample_index}", profile, layout["id"], version_id, method_id, sample_name, now, now)).lastrowid
            sample_id = db.execute("INSERT INTO acquisition_samples(task_id, repeat_index, sample_name_original, sample_name, sample_kind, storage_mode, status, finalized, result_sha256, created_at, completed_at, updated_at) VALUES (?, 0, ?, ?, 'normal', 'averaged', 'completed', 1, ?, ?, ?, ?)", (task_id, sample_name, sample_name, hashlib.sha256(sample_name.encode()).hexdigest(), now, now, now)).lastrowid
            values = [10.0] * int(layout["points_per_ccd"])
            shift = 2
            amplitudes = {"reference-baseline": 1200.0, "AL": 700.0, "IS": 600.0, "A-none": 800.0, "A-background": 1000.0}
            for line_id, amplitude in amplitudes.items():
                position = peak_points[line_id] + shift
                values[position - 1:position + 2] = [amplitude / 3, amplitude, amplitude / 3]
            position = peak_points["A-gaussian"] + shift
            gaussian_values = [10.0] * 5 if flat_gaussian else [100.0, 400.0, 1000.0, 400.0, 100.0]
            values[position - 2:position + 3] = gaussian_values
            blob = struct.pack(f"<{len(values)}f", *values)
            db.execute("INSERT INTO acquisition_sample_bands(sample_id, ccd_index, storage_mode, points_count, burn_frame_count, dark_frame_count, mean_blob, mean_sha256, created_at) VALUES (?, 0, 'averaged', ?, 1, 0, ?, ?, ?)", (sample_id, len(values), blob, hashlib.sha256(blob).hexdigest(), now))
            sample_ids.append(int(sample_id))
    return int(version_id), sample_ids


def _finish(service: AnalysisService, run: dict) -> dict:
    current = service.start(run["id"])
    for _ in range(30):
        if current["status"] in {"completed", "failed"}:
            return current
        current = service.step(run["id"])
    raise AssertionError("analysis did not settle")


def test_s16_legacy_gaussian_golden_vectors() -> None:
    assert AnalysisService._profile({"storage_profile": "legacy_specdirect_202"}) == "legacy_2_0_2"
    assert AnalysisService._profile({}) == "modern_v1"
    golden = json.loads((APP_ROOT.parent / "docs" / "s00-baseline" / "golden" / "legacy-gaussian.json").read_text(encoding="utf-8"))
    for case in golden["cases"]:
        actual = legacy_gaussian(case["input"])
        assert actual["ok"] is case["expected"]["ok"]
        if actual["ok"]:
            assert actual["center"] == pytest.approx(case["expected"]["center"], abs=1e-9)
            assert actual["peak_height"] == pytest.approx(case["expected"]["peak_double"], abs=1e-9)
            assert actual["sigma"] == pytest.approx(case["expected"]["sigma"], abs=1e-9)


def _independent_weighted_quadratic_gaussian(values: list[float]) -> tuple[float, float, float]:
    multiplier = 3 if len(values) == 3 else 2 if len(values) == 5 else 1
    count = 7 if len(values) == 3 else 9 if len(values) == 5 else len(values)
    samples: list[tuple[float, float]] = []
    for index in range(count):
        x = index / multiplier
        left = index // multiplier
        fraction = (index % multiplier) / multiplier
        weight = values[left] if fraction == 0 else values[left] + (values[left + 1] - values[left]) * fraction
        samples.append((x, weight))
    matrix = [[sum(weight * x ** (row + column) for x, weight in samples) for column in range(3)] for row in range(3)]
    vector = [sum(weight * math.log(weight) * x ** row for x, weight in samples) for row in range(3)]
    augmented = [matrix[row] + [vector[row]] for row in range(3)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [value - factor * pivot_value for value, pivot_value in zip(augmented[row], augmented[column], strict=True)]
    a0, a1, a2 = (augmented[row][3] for row in range(3))
    sigma = math.sqrt(-0.5 / a2)
    center = -0.5 * a1 / a2
    peak = math.exp(a0 + 0.5 * center * a1)
    return center, peak, sigma


def test_s16_independent_gaussian_cross_check_and_legacy_peak_boundaries() -> None:
    golden = json.loads((APP_ROOT.parent / "docs" / "s00-baseline" / "golden" / "legacy-gaussian.json").read_text(encoding="utf-8"))
    for case in golden["cases"]:
        if not case["expected"]["ok"]:
            continue
        center, peak, sigma = _independent_weighted_quadratic_gaussian(case["input"])
        product = legacy_gaussian(case["input"])
        assert product["center"] == pytest.approx(center, abs=1e-9)
        assert product["peak_height"] == pytest.approx(peak, abs=1e-9)
        assert product["sigma"] == pytest.approx(sigma, abs=1e-9)

    vectors = json.loads((APP_ROOT.parent / "docs" / "s00-baseline" / "golden" / "legacy-signal-processing.json").read_text(encoding="utf-8"))["peak_search"]
    checked = vectors[0]
    result = _search_peak(checked["values"], checked["initial_index"], len(checked["values"]), checked=True, lower_peak=checked["low_peak"], minimum_ratio=checked["low_ratio"])
    assert (result["position"], result["peak"], result["minimum"]) == (checked["expected_index"], checked["expected_peak"], checked["expected_min"])
    fallback = vectors[1]
    result = _search_peak(fallback["values"], fallback["initial_index"], len(fallback["values"]), checked=False, lower_peak=0, minimum_ratio=0)
    assert (result["position"], result["peak"], result["minimum"]) == (fallback["expected_index"], fallback["expected_peak"], fallback["expected_min"])
    tied = vectors[2]
    result = _search_peak(tied["values"], 0, len(tied["values"]), checked=False, lower_peak=0, minimum_ratio=0, maximum=True)
    assert (result["position"], result["peak"], result["minimum"]) == (tied["expected_index"], tied["expected_peak"], tied["expected_min"])


def test_s16_multi_sample_profiles_internal_standards_and_replay(tmp_path: Path) -> None:
    database = Database(tmp_path / "analysis.sqlite3")
    version_id, sample_ids = _seed(database)
    service = AnalysisService(database)
    modern = _finish(service, service.create_run({"name": "modern", "acquisition_sample_ids": sample_ids, "method_version_id": version_id, "calculation_profile": "modern_v1"}))
    assert modern["status"] == "completed"
    assert [sample["sample_name"] for sample in modern["samples"]] == ["S16-A", "S16-B"]
    assert [item["line_id"] for item in modern["samples"][0]["result_matrix"]] == ["A-none", "A-background", "A-gaussian"]
    gaussian = next(item for item in modern["line_results"] if item["line_id"] == "A-gaussian")
    assert gaussian["gaussian_center"] == pytest.approx(1302, abs=1e-9)
    assert gaussian["gaussian_sigma"] is not None and gaussian["gaussian_area"] is not None
    assert gaussian["quantitative_signal"] == pytest.approx(gaussian["gaussian_area"] / 590.0)
    background = next(item for item in modern["line_results"] if item["line_id"] == "A-background")
    assert background["quantitative_signal"] == pytest.approx(100.0)
    aligned = next(item for item in modern["line_results"] if item["line_id"] == "A-none")
    assert aligned["peak_position"] == 902
    assert aligned["intermediates"]["reference_correction_points"] == 2

    legacy = _finish(service, service.create_run({"name": "legacy", "acquisition_sample_ids": sample_ids[:1], "method_version_id": version_id, "calculation_profile": "legacy_2_0_2"}))
    legacy_gauss = next(item for item in legacy["line_results"] if item["line_id"] == "A-gaussian")
    single = lambda value: struct.unpack("<f", struct.pack("<f", value))[0]
    expected_peak = single(848.1213921230479)
    expected_net = single(expected_peak - single(10.0))
    expected_internal = single(single(600.0) - single(10.0))
    expected_quantitative = single(expected_net / expected_internal)
    assert legacy_gauss["peak_height"] == expected_peak
    assert legacy_gauss["net_signal"] == expected_net
    assert legacy_gauss["quantitative_signal"] == expected_quantitative
    assert legacy_gauss["quantitative_signal"] != pytest.approx(legacy_gauss["gaussian_area"] / 590.0)
    replay = _finish(service, service.create_run({"name": "replay", "acquisition_sample_ids": sample_ids, "method_version_id": version_id, "calculation_profile": "modern_v1"}))
    assert replay["input_sha256"] == modern["input_sha256"]
    assert replay["result_sha256"] == modern["result_sha256"]


def test_s16_slow_checkpoint_adjust_continue_cancel_and_timeout(tmp_path: Path) -> None:
    database = Database(tmp_path / "slow.sqlite3")
    version_id, sample_ids = _seed(database)
    service = AnalysisService(database)
    run = service.create_run({"name": "slow", "acquisition_sample_ids": sample_ids[:1], "method_version_id": version_id, "slow_mode": True, "intervention_timeout_seconds": 60})
    service.start(run["id"])
    paused = service.step(run["id"])
    assert paused["status"] == "paused" and paused["line_results"] == []
    current = service.intervene(run["id"], "discard", None, "采用自动参考线")
    assert current["line_results"][0]["line_id"] == "reference-baseline"
    current = service.step(run["id"])
    adjusted = current["checkpoint"]["automatic_position"] + 1
    current = service.intervene(run["id"], "accept", adjusted, "人工复核后向长波移动 1 点")
    assert current["line_results"][-1]["peak_position"] == adjusted
    assert current["interventions"][-1]["before_position"] != current["interventions"][-1]["after_position"]
    for _ in range(20):
        if current["status"] == "completed":
            break
        current = service.step(run["id"])
        if current["status"] == "paused":
            current = service.intervene(run["id"], "discard", None, "后续谱线采用自动定位")
    assert current["status"] == "completed"
    with database.read() as db:
        details = [json.loads(row[0]) for row in db.execute("SELECT details_json FROM audit_events WHERE action='analysis.intervention.accept'").fetchall()]
    assert details[-1]["reason"] == "人工复核后向长波移动 1 点"

    cancelled = service.create_run({"name": "cancel", "acquisition_sample_ids": sample_ids[:1], "method_version_id": version_id, "slow_mode": True})
    service.start(cancelled["id"]); service.step(cancelled["id"])
    cancelled = service.cancel(cancelled["id"])
    assert cancelled["status"] == "cancelled" and cancelled["line_results"] == []

    timeout = service.create_run({"name": "timeout", "acquisition_sample_ids": sample_ids[:1], "method_version_id": version_id, "slow_mode": True, "intervention_timeout_seconds": 1})
    service.start(timeout["id"]); service.step(timeout["id"])
    with database.write() as db:
        db.execute("UPDATE analysis_checkpoints SET deadline_at='2000-01-01T00:00:00+00:00' WHERE run_id=? AND status='pending'", (timeout["id"],))
    timeout = service.step(timeout["id"])
    assert timeout["status"] == "failed" and timeout["failure_code"] == "analysis_intervention_timeout"
    assert timeout["line_results"] == []


def test_s16_failure_has_stable_code_intermediates_and_immutable_results(tmp_path: Path) -> None:
    database = Database(tmp_path / "failure.sqlite3")
    version_id, sample_ids = _seed(database, flat_gaussian=True)
    service = AnalysisService(database)
    failed = _finish(service, service.create_run({"name": "fail", "acquisition_sample_ids": sample_ids[:1], "method_version_id": version_id}))
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "analysis_gaussian_fit_failed"
    assert failed["failure_details"]["values"] == [10.0] * 5
    assert all(item["line_id"] != "A-gaussian" for item in failed["line_results"])
    with pytest.raises(sqlite3.IntegrityError):
        with database.write() as db:
            db.execute("UPDATE analysis_line_results SET peak_height=0 WHERE run_id=?", (failed["id"],))


def test_s16_api_permissions_and_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = Database(config_module.config.database_path)
    main_module.service = main_module.AppService(main_module.database, tmp_path / "logs" / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
        assert client.get("/api/v1/analyses/options").status_code == 401
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        version_id, sample_ids = _seed(main_module.database)
        created = client.post("/api/v1/analyses/runs", headers=headers, json={"name": "api", "acquisition_sample_ids": sample_ids[:1], "method_version_id": version_id})
        assert created.status_code == 201
        run_id = created.json()["id"]
        assert client.post(f"/api/v1/analyses/runs/{run_id}/start", headers=headers).status_code == 200
        capability = next(item for item in client.get("/api/v1/capabilities").json()["capabilities"] if item["key"] == "analysis")
        assert {"analysis.read", "analysis.execute", "analysis.intervene"}.issubset(capability["permissions"])
