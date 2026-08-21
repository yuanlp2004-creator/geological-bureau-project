from __future__ import annotations

import csv
import json
import struct
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database, utc_now
from backend.app.modules.postprocessing import PostProcessingError, PostProcessingService


def _fixture(tmp_path: Path) -> tuple[Database, PostProcessingService]:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    with database.write() as db:
        now = utc_now()
        db.execute(
            "INSERT INTO ccd_layouts(name,frame_count,ccds_per_frame,points_per_ccd,point_width,gap_points_json,ccd_indices_json,wavelength_min,wavelength_max,allow_drift_um,created_at) VALUES ('tiny',1,1,3,1,'[]','[0,1]',1,2,1,?)",
            (now,),
        )
        db.execute(
            "INSERT INTO spectrum_migration_runs(id,fingerprint,format,status,source_json,reader_json,staging_json,report_json,created_at,updated_at) VALUES ('s18-run','s18-source','edt','committed','{}','{}','{}','{}',?,?)",
            (now, now),
        )
        values = [value for frame in range(3) for value in (frame + 1, frame + 2, frame + 3, frame + 4, frame + 5, frame + 6)]
        blob = struct.pack("<18H", *values)
        db.execute(
            "INSERT INTO spectrum_bands(import_run_id,source_sha256,record_index,format,sample_name,band_name,measure_time,frame_count,ccds_per_frame,points_per_ccd,ccd_count,ccd_indices_json,layout_json,ignition_json,bad_frame_indices_json,mean_blob,burn_adcs_blob,dark_adcs_blob,sampled_values_json,details_json) VALUES ('s18-run','source-sha',0,'edt','S18 sample','band','2026-08-14T08:00:00+08:00',3,1,3,2,'[0,1]','{\"ccd_indices\":[0,1]}','{\"burn_count\":3,\"dark_count\":0}','[]',NULL,?,NULL,'{}','{}')",
            (blob,),
        )
    return database, PostProcessingService(database)


def _seed_method_curve(database: Database) -> tuple[int, int, int]:
    with database.write() as db:
        now = utc_now()
        method_id = int(db.execute("INSERT INTO methods(name,description,work_type,status,created_at,updated_at) VALUES ('S18 exact','', 'analysis','active',?,?)", (now, now)).lastrowid)
        method_payload = {
            "conditions": {},
            "lines": [{
                "id": "L1", "line_type": "analysis", "element": "Cu", "wavelength_nm": 324.754,
                "enabled": True, "internal_standard_mode": "none", "standard_points": [],
            }],
        }
        method_version_id = int(db.execute(
            "INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (?,1,'published',?,?)",
            (method_id, json.dumps(method_payload), now),
        ).lastrowid)
        run_id = int(db.execute(
            "INSERT INTO analysis_runs(name,status,method_id,method_version_id,method_version,calculation_profile,intervention_timeout_seconds,input_snapshot_json,input_sha256,result_sha256,created_at,updated_at,completed_at) VALUES ('curve','completed',?,?,1,'legacy_2_0_2',300,'{}','input','result',?,?,?)",
            (method_id, method_version_id, now, now, now),
        ).lastrowid)
        qc_id = int(db.execute(
            "INSERT INTO analysis_qc_snapshots(run_id,sequence,groups_json,publishable,result_sha256,created_at) VALUES (?,1,'[]',1,'qc',?)",
            (run_id, now),
        ).lastrowid)
        adjustment_id = int(db.execute(
            "INSERT INTO analysis_curve_adjustment_sets(run_id,line_id,qc_snapshot_id,sequence,fit_mode,coordinate_type,points_json,workspace_sha256,created_at) VALUES (?,'L1',?,1,'linear','normal','[]','workspace',?)",
            (run_id, qc_id, now),
        ).lastrowid)
        fit = {"kind": "polynomial", "coefficients": [0.0, 2.0, 0.0, 0.0], "x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]}
        curve_id = int(db.execute(
            "INSERT INTO analysis_curve_snapshots(run_id,line_id,qc_snapshot_id,adjustment_set_id,sequence,fit_mode,coordinate_type,points_json,fit_json,diagnostics_json,chart_json,publishable,result_sha256,created_at) VALUES (?,'L1',?,?,1,'linear','normal','[]',?,'{}','[]',1,'curve-sha',?)",
            (run_id, qc_id, adjustment_id, json.dumps(fit), now),
        ).lastrowid)
    return method_id, method_version_id, curve_id


def test_interval_boundaries_keep_exact_adc_and_source_metadata(tmp_path: Path) -> None:
    database, service = _fixture(tmp_path)
    result = service.interval("raw:1", ccd=1, start_frame=2, end_frame=3)
    assert result["frames"][0]["adc"] == [5, 6, 7]
    assert result["mean"]["values"] == [5.5, 6.5, 7.5]
    assert result["source_sha256"] == "source-sha"
    assert result["measure_time"] == "2026-08-14T08:00:00+08:00"
    with pytest.raises(PostProcessingError, match="曝光区间"):
        service.interval("raw:1", start_frame=0, end_frame=2)
    with database.read() as db:
        assert tuple(db.execute("SELECT source_sha256, measure_time FROM spectrum_bands WHERE id=1").fetchone()) == ("source-sha", "2026-08-14T08:00:00+08:00")


def test_cmt_full_interval_is_listed_and_exported_without_resampling(tmp_path: Path) -> None:
    database, service = _fixture(tmp_path)
    with database.write() as db:
        source = db.execute("SELECT * FROM spectrum_bands WHERE id=1").fetchone()
        columns = [key for key in source.keys() if key != "id"]
        values = [source[key] for key in columns]
        values[columns.index("format")] = "cmt"
        values[columns.index("source_sha256")] = "cmt-source-sha"
        values[columns.index("record_index")] = 1
        placeholders = ",".join("?" for _ in columns)
        db.execute(f"INSERT INTO spectrum_bands({','.join(columns)}) VALUES ({placeholders})", values)
    records = service.edt_records()
    assert any(record["id"] == "raw:2" and record["format"] == "cmt" for record in records)
    interval = service.interval("raw:2", ccd=0, start_frame=1, end_frame=2)
    assert interval["frames"][0]["adc"] == [1, 2, 3]
    assert interval["mean"]["values"] == [1.5, 2.5, 3.5]
    assert interval["source_sha256"] == "cmt-source-sha"


def test_conversion_is_idempotent_and_preserves_source(tmp_path: Path) -> None:
    database, service = _fixture(tmp_path)
    payload = {"record_ids": ["raw:1"], "start_frame": 1, "end_frame": 2, "target_ccd_layout_id": 2, "target_ccd_indices": [0, 1]}
    first = service.convert_edt(payload)
    second = service.convert_edt(payload)
    assert first["id"] == second["id"]
    assert first["sample_ids"] == second["sample_ids"]
    with database.read() as db:
        source = db.execute("SELECT source_sha256, measure_time, burn_adcs_blob FROM spectrum_bands WHERE id=1").fetchone()
        assert source["source_sha256"] == "source-sha"
        assert source["measure_time"] == "2026-08-14T08:00:00+08:00"
        bands = db.execute(
            "SELECT ccd_index, burn_frames_blob, mean_blob, burn_frame_count FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index",
            (first["sample_ids"][0],),
        ).fetchall()
        assert bytes(bands[0]["burn_frames_blob"]) == struct.pack("<6H", 1, 2, 3, 2, 3, 4)
        assert bytes(bands[1]["burn_frames_blob"]) == struct.pack("<6H", 4, 5, 6, 5, 6, 7)
        assert [band["burn_frame_count"] for band in bands] == [2, 2]


def test_conversion_maps_non_leading_ccd_by_source_index(tmp_path: Path) -> None:
    database, service = _fixture(tmp_path)
    result = service.convert_edt(
        {
            "record_ids": ["raw:1"],
            "start_frame": 1,
            "end_frame": 2,
            "target_ccd_layout_id": 2,
            "target_ccd_indices": [1],
        }
    )
    with database.read() as db:
        band = db.execute(
            "SELECT burn_frames_blob FROM acquisition_sample_bands WHERE sample_id=? AND ccd_index=1",
            (result["sample_ids"][0],),
        ).fetchone()
    assert bytes(band["burn_frames_blob"]) == struct.pack("<6H", 4, 5, 6, 5, 6, 7)


def test_export_formats_have_stable_columns_and_atomic_same_name(tmp_path: Path) -> None:
    _, service = _fixture(tmp_path)
    csv_export = service.export({"record_ids": ["raw:1"], "kind": "processed_intensity", "format": "csv", "output_directory": str(tmp_path), "filename": "matrix", "same_name_strategy": "suffix"})
    txt_export = service.export({"record_ids": ["raw:1"], "kind": "processed_intensity", "format": "txt", "output_directory": str(tmp_path), "filename": "matrix", "same_name_strategy": "suffix"})
    excel_export = service.export({"record_ids": ["raw:1"], "kind": "processed_intensity", "format": "excel", "output_directory": str(tmp_path), "filename": "matrix", "same_name_strategy": "suffix"})
    assert Path(csv_export["path"]).read_bytes().startswith(b"\xef\xbb\xbf")
    assert Path(txt_export["path"]).read_bytes().startswith(b"\xef\xbb\xbf")
    assert Path(excel_export["path"]).read_bytes().startswith(b"<?xml")
    with Path(csv_export["path"]).open(encoding="utf-8-sig", newline="") as stream:
        assert next(csv.reader(stream)) == ["source_id", "source_sha256", "measure_time", "ccd", "frame_index", "point_index", "value"]
    assert Path(csv_export["path"]).name == "matrix.csv"
    assert Path(txt_export["path"]).name == "matrix.txt"
    assert Path(excel_export["path"]).name == "matrix.xls"


def test_recalculation_blocks_exact_method_mismatch_without_mutating_result(tmp_path: Path) -> None:
    database, service = _fixture(tmp_path)
    _, method_version_id, curve_id = _seed_method_curve(database)
    with database.write() as db:
        now = utc_now()
        db.execute("INSERT INTO result_migration_runs(id,fingerprint,format,status,source_json,parser_json,staging_json,report_json,created_at,updated_at) VALUES ('r18','rf','pdt','committed','{}','{}','{}','{}',?,?)", (now, now))
        db.execute("INSERT INTO result_matrices(import_run_id,source_sha256,record_index,format,payload_json,matrix_blob,matrix_sha256) VALUES ('r18','result-sha',0,'pdt',?,?,?)", (json.dumps({"method_target_id": 999, "lines": []}), b"x", "x"))
    result = service.recalculate({"source_record_ids": ["result:1"], "method_version_id": method_version_id, "calculation_profile": "legacy_2_0_2", "curve_snapshot_ids": [curve_id]})
    assert result["status"] == "blocked"
    assert result["result"]["blocked"][0]["code"] == "method_version_mismatch"
    with database.read() as db:
        assert db.execute("SELECT source_sha256 FROM result_matrices WHERE id=1").fetchone()[0] == "result-sha"


def test_recalculation_uses_exact_curve_and_preserves_pdt_source(tmp_path: Path) -> None:
    database, service = _fixture(tmp_path)
    method_id, method_version_id, curve_id = _seed_method_curve(database)
    with database.write() as db:
        now = utc_now()
        db.execute("INSERT INTO result_migration_runs(id,fingerprint,format,status,source_json,parser_json,staging_json,report_json,created_at,updated_at) VALUES ('pdt-run','pdt-fp','pdt','committed','{}','{}','{}','{}',?,?)", (now, now))
        matrix = struct.pack("<4f", 10.0, 1.0, 20.0, 2.0)
        payload = {
            "method_target_id": method_id, "method_match_status": "matched", "measure_time": "2026-08-14T08:00:00+08:00",
            "line_count": 1, "band_count": 2, "lines": [{"index": 0, "element": "Cu", "wavelength_nm": 324.754, "back": 1, "digits": 2}],
            "sample_rows": [{"expanded_index": 0, "repeat_index": 1, "name": "N1"}, {"expanded_index": 1, "repeat_index": 1, "name": "N2"}],
        }
        db.execute("INSERT INTO result_matrices(import_run_id,source_sha256,record_index,format,payload_json,matrix_blob,matrix_sha256) VALUES ('pdt-run','pdt-source',0,'pdt',?,?,?)", (json.dumps(payload), matrix, "matrix-sha"))
    result = service.recalculate({"source_record_ids": ["result:1"], "method_version_id": method_version_id, "calculation_profile": "legacy_2_0_2", "curve_snapshot_ids": [curve_id]})
    assert result["status"] == "completed"
    lines = result["result"]["sources"][0]["lines"]
    assert [line["quantitative_signal"] for line in lines] == [9.0, 18.0]
    assert [line["calculated_value"] for line in lines] == [18.0, 36.0]
    assert {line["curve_snapshot_id"] for line in lines} == {curve_id}
    with database.read() as db:
        source = db.execute("SELECT source_sha256, matrix_blob FROM result_matrices WHERE id=1").fetchone()
        assert source["source_sha256"] == "pdt-source" and bytes(source["matrix_blob"]) == matrix
