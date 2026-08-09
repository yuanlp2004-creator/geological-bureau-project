from __future__ import annotations

import json
import hashlib
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db import Database, utc_now
from backend.app.modules.spectrum_viewer import SpectrumViewerError, SpectrumViewerService
from backend.app.main import app


def seed_database(path: Path) -> Database:
    database = Database(path)
    database.initialize()
    now = utc_now()
    layout = {
        "frame_count": 3,
        "ccds_per_frame": 2,
        "points_per_ccd": 8,
        "ccd_count": 2,
        "ccd_indices": [0, 1],
        "gap_points": [2.0] * 5,
        "ws_cof": [0.001, 1.0, 0.1, 0.1, 0.0, 100.0],
        "endianness": "little",
    }
    ignition = {"present": True, "burn_count": 2, "dark_count": 1, "pre_burn": 0, "burn_cyc": 1, "dark_cyc": 1}
    mean = struct.pack("<16f", *[float(index) for index in range(16)])
    burn = struct.pack("<32H", *[100 + index for index in range(32)])
    dark = struct.pack("<16H", *[200 + index for index in range(16)])
    result_payload = {
        "format": "dat",
        "measure_time": "2024-01-02T03:04:05+00:00",
        "sample_count": 3,
        "line_count": 2,
        "band_count": 3,
        "sample_names": ["S1", "S2", "S3"],
        "sample_reps": [1, 1, 1],
        "sample_rows": [{"expanded_index": index, "sample_index": index, "repeat_index": 1, "name": f"S{index + 1}"} for index in range(3)],
        "lines": [{"index": 0, "element": "Cu", "wavelength_nm": None, "back": None, "digits": 2}, {"index": 1, "element": "Fe", "wavelength_nm": None, "back": None, "digits": 2}],
        "matrix_kind": "value",
        "matrix_order": "line-major, expanded-sample-minor",
    }
    result_matrix = struct.pack("<6f", 1, 2, 3, 4, 5, 6)
    with database.write() as db:
        db.execute("INSERT INTO spectrum_migration_runs(id, fingerprint, format, status, source_json, reader_json, staging_json, report_json, created_at, updated_at) VALUES ('srun', 'sfingerprint', 'cdt', 'committed', '{}', '{}', '{}', '{}', ?, ?)", (now, now))
        db.execute("INSERT INTO spectrum_bands(import_run_id, source_sha256, record_index, format, band_id, sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, mean_blob, burn_adcs_blob, dark_adcs_blob, mean_sha256, burn_sha256, dark_sha256, sampled_values_json, details_json) VALUES ('srun', 'sfingerprint', 0, 'cdt', 7, 1, 'Raw sample', 'Cu band', '', ?, 0, 3, 2, 8, 2, ?, ?, ?, '[]', ?, ?, ?, '', '', '', '{}', ?)", (now, json.dumps([0, 1]), json.dumps(layout), json.dumps(ignition), mean, burn, dark, json.dumps({"angle_deg": 15.0})))
        db.execute("INSERT INTO result_migration_runs(id, fingerprint, format, status, source_json, parser_json, staging_json, report_json, created_at, updated_at) VALUES ('rrun', 'rfingerprint', 'dat', 'committed', '{}', '{}', '{}', '{}', ?, ?)", (now, now))
        db.execute("INSERT INTO result_matrices(import_run_id, source_sha256, record_index, format, payload_json, matrix_blob, matrix_sha256) VALUES ('rrun', 'rfingerprint', 0, 'dat', ?, ?, '')", (json.dumps(result_payload), result_matrix))
    return database


def test_s10_lists_complete_raw_and_result_records_and_converts_coordinates(tmp_path: Path) -> None:
    service = SpectrumViewerService(seed_database(tmp_path / "s10.sqlite3"))
    records = service.list()
    assert {item["id"] for item in records} == {"raw:1", "result:1"}
    raw = service.get("raw:1", ccd=1)
    assert len(raw["ccd"]["points"]) == 8
    assert raw["ccd"]["points"][0]["step"] == 10.0
    assert raw["ccd"]["points"][-1]["value"] == 15.0
    assert abs(raw["ccd"]["points"][0]["wavelength_nm"] - 9.805) < 0.5
    frame = service.get("raw:1", ccd=1, detail="frame", phase="dark", frame=0)
    assert frame["frame_detail"]["ccd"]["points"][0]["adc"] == 208
    result = service.get("result:1", line=1)
    assert len(result["line"]["points"]) == 3
    assert [point["value"] for point in result["line"]["points"]] == [4.0, 5.0, 6.0]


def test_s10_rejects_out_of_range_and_unknown_records(tmp_path: Path) -> None:
    service = SpectrumViewerService(seed_database(tmp_path / "s10.sqlite3"))
    with pytest.raises(SpectrumViewerError) as ccd_error:
        service.get("raw:1", ccd=2)
    assert ccd_error.value.code == "spectrum_ccd_invalid"
    with pytest.raises(SpectrumViewerError) as record_error:
        service.get("raw:99")
    assert record_error.value.code == "spectrum_record_not_found"
    with pytest.raises(SpectrumViewerError) as line_error:
        service.get("result:1", line=2)
    assert line_error.value.code == "spectrum_line_invalid"


def test_s10_angle_filter_exposure_interval_and_visible_csv_are_exact(tmp_path: Path) -> None:
    service = SpectrumViewerService(seed_database(tmp_path / "s10.sqlite3"))
    assert [item["id"] for item in service.list(kind="raw", angle_deg=15.0)] == ["raw:1"]
    assert service.list(kind="raw", angle_deg=20.0) == []

    exposure = service.get("raw:1", ccd=0, exposure_start=1, exposure_end=2)
    assert exposure["angle_deg"] == 15.0
    assert exposure["exposure_segment"] == {"start": 1, "end": 2, "count": 2}
    assert exposure["ccd"]["points"][0]["value"] == 108.0

    points = exposure["ccd"]["points"]
    x_min = float(points[2]["wavelength_nm"])
    x_max = float(points[4]["wavelength_nm"])
    content, digest, point_count = service.export_csv(
        "raw:1", ccd=0, exposure_start=1, exposure_end=2, x_min=x_min, x_max=x_max
    )
    assert point_count == 3
    assert hashlib.sha256(content).hexdigest() == digest
    assert len(content.decode("utf-8-sig").strip().splitlines()) == 4


def test_s10_full_six_ccd_first_view_is_not_sampled(tmp_path: Path) -> None:
    database = seed_database(tmp_path / "large.sqlite3")
    now = utc_now()
    layout = {"frame_count": 3, "ccds_per_frame": 2, "points_per_ccd": 2048, "ccd_count": 6, "ccd_indices": [0, 1, 2, 3, 4, 5], "gap_points": [2.0] * 5, "ws_cof": [0.001, 1.0, 0.1, 0.1, 0.0, 100.0], "endianness": "little"}
    mean = struct.pack("<" + "f" * (6 * 2048), *[float(index % 4096) for index in range(6 * 2048)])
    with database.write() as db:
        db.execute("INSERT INTO spectrum_bands(import_run_id, source_sha256, record_index, format, band_id, sample_no, sample_name, band_name, long_name, measure_time, real_ref_step, frame_count, ccds_per_frame, points_per_ccd, ccd_count, ccd_indices_json, layout_json, ignition_json, bad_frame_indices_json, mean_blob, sampled_values_json, details_json) VALUES ('srun', 'large', 1, 'cdt', 8, 1, 'Large', 'Large', '', ?, 0, 3, 2, 2048, 6, ?, ?, ?, '[]', ?, '{}', '{}')", (now, json.dumps(layout["ccd_indices"]), json.dumps(layout), json.dumps({"burn_count": 0, "dark_count": 0}), mean))
    started = time.perf_counter()
    view = SpectrumViewerService(database).get("raw:2", ccd=5)
    elapsed = time.perf_counter() - started
    assert len(view["ccd"]["points"]) == 2048
    assert elapsed < 0.5


def test_s10_api_requires_view_permission() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/spectra/records")
    assert response.status_code == 401


def test_s10_api_audits_view_export_and_print_visible_range(tmp_path: Path) -> None:
    import backend.app.main as main_module

    database = seed_database(tmp_path / "api.sqlite3")
    main_module.database = database
    main_module.service = main_module.AppService(database, tmp_path / "runtime.jsonl")
    main_module.auth_service = main_module.AuthService(database)
    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/auth/bootstrap", json={"username": "operator", "password": "correct-horse"}).status_code == 201
        token = client.post("/api/v1/auth/login", json={"username": "operator", "password": "correct-horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        view = client.get("/api/v1/spectra/raw:1?ccd=0&exposure_start=1&exposure_end=2", headers=headers)
        assert view.status_code == 200
        points = view.json()["ccd"]["points"]
        exported = client.get(
            "/api/v1/spectra/raw:1/export",
            headers=headers,
            params={"ccd": 0, "exposure_start": 1, "exposure_end": 2, "x_min": points[1]["wavelength_nm"], "x_max": points[3]["wavelength_nm"]},
        )
        assert exported.status_code == 200
        assert len(exported.text.strip().splitlines()) == 4
        printed = client.post(
            "/api/v1/spectra/raw:1/print-pdf",
            headers=headers,
            json={"visible_x_min": 1, "visible_x_max": 2, "visible_y_min": 3, "visible_y_max": 4, "ccd": 0, "line": 0, "mode": "mean", "reference_shift": 0, "selected_record_ids": ["raw:1"]},
        )
        assert printed.status_code == 200
        assert printed.headers["content-type"] == "application/pdf"
        assert printed.content.startswith(b"%PDF-")
        assert printed.headers["x-curve-count"] == "1"
        actions = [item["action"] for item in client.get("/api/v1/audit", headers=headers).json()]
        assert {"spectrum.view", "spectrum.export", "spectrum.print"}.issubset(actions)
