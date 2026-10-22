import json
import hashlib
import sqlite3
from pathlib import Path
import pytest
from backend.config import AppConfig
from backend.modules.reports.rendering import _table as report_table
from backend.db import utc_now
from backend.runtime import Runtime
from backend.modules.dispersion import DispersionService, DispersionError
from backend.modules.analysis import AnalysisError
from tests.test_spectral_lines import line_client, _method, _line, _collection
from tests.test_s19_reports import _seed
from tests.test_s10_spectrum_viewer import seed_database


def test_custom_units_save_and_invalid_text_rejected(line_client):
    client, runtime, headers = line_client
    method = _method(client, headers)
    endpoint = f"/api/v1/methods/{method['id']}/lines"
    created = client.post(endpoint, headers=headers, json=_line(260.1234, unit="mg/L"))
    assert created.status_code == 201, created.text
    assert any(line["unit"] == "mg/L" for line in _collection(client, headers, method["id"])["lines"])
    published = client.post(f"/api/v1/methods/{method['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    preview = client.post(f"/api/v1/methods/{method['id']}/preview", headers=headers, json={})
    assert preview.status_code == 200 and "mg/L" in preview.text
    for unit in ["a\nb", "x" * 33, " units ", ""]:
        response = client.post(endpoint, headers=headers, json=_line(270.1234, unit=unit))
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("places,expected", [(0, "-1"), (2, "-1.23"), (4, "-1.2250")])
def test_report_fixed_precision_preserves_raw_value(tmp_path, places, expected):
    database, run_id = _seed(tmp_path, decimal_places=places, unit="mg/L", base_value=-1.225)
    service = Runtime(AppConfig(data_dir=tmp_path), database=database).reports_service()
    report = service.create({"analysis_run_ids": [run_id]})
    row = report["model"]["rows"][0]
    assert row["calculated_value"] == -1.225 and row["display_value"] == expected
    assert row["unit"] == "mg/L"
    assert expected in service.preview(report["id"])
    service.confirm(report["id"])
    for fmt in ["txt", "csv", "excel"]:
        exported = service.export(
            report["id"], {"format": fmt, "output_directory": str(tmp_path / "exports"), "filename": fmt}
        )
        assert expected in Path(exported["path"]).read_text(encoding="utf-8-sig")
    legacy = {"columns": ["calculated_value"], "rows": [{"calculated_value": 1.234567}]}
    assert report_table(legacy)[1][0] == 1.234567


def _source_and_layout(database):
    with database.write() as db:
        source = dict(db.execute("SELECT * FROM spectrum_bands WHERE id=1").fetchone())
        geometry = json.loads(source["layout_json"])
        layout = dict(db.execute("SELECT * FROM ccd_layouts WHERE name='default'").fetchone())
        layout.pop("id")
        layout.update(
            name="legacy-test-layout",
            points_per_ccd=geometry["points_per_ccd"],
            ccd_indices_json=json.dumps(geometry["ccd_indices"]),
            gap_points_json=json.dumps(geometry["gap_points"]),
        )
        layout_id = db.execute(
            f"INSERT INTO ccd_layouts ({','.join(layout)}) VALUES ({','.join('?' for _ in layout)})",
            list(layout.values()),
        ).lastrowid
    return source, geometry, layout_id


def test_wdt_manual_calibration_catalogue_and_atomic_audit(tmp_path):
    database = seed_database(tmp_path / "wdt.sqlite3")
    source, geometry, layout_id = _source_and_layout(database)
    with database.write() as db:
        source.pop("id")
        source.update(format="wdt", record_index=2)
        source_id = db.execute(
            f"INSERT INTO spectrum_bands ({','.join(source)}) VALUES ({','.join('?' for _ in source)})",
            list(source.values()),
        ).lastrowid
    service = DispersionService(database)
    with pytest.raises(DispersionError):
        service.create_task({"source_record_id": source_id})
    task = service.create_task({"source_record_id": source_id, "ccd_layout_id": layout_id})
    assert task["status"] == "completed" and len(service.frames(task["id"])) == 6
    for wavelength, position in [(260, 1), (270, 3), (280, 5)]:
        line = service.add_line(task["id"], {"element": "Fe", "wavelength_nm": wavelength, "ccd_index": 0})
        service.set_line_position(task["id"], line["id"], position)
        service.save_line_position(task["id"], line["id"])
    calibration = service.fit_calibration(task["id"], {"degree": 2, "name": "catalogue"})
    discardable = service.fit_calibration(task["id"], {"degree": 2, "name": "discardable"})
    service.manage_calibration(discardable["id"], "delete", None, None)
    with pytest.raises(DispersionError):
        service.calibration(discardable["id"])
    published = service.publish_calibration(calibration["id"])
    service.manage_calibration(published["id"], "rename", "renamed", None)
    service.manage_calibration(published["id"], "archive", None, None)
    current = service.get_task(task["id"])["calibrations"][0]
    assert current["archived"] and current["display_name"] == "renamed"
    assert current["coefficients"] == published["coefficients"]
    with pytest.raises(DispersionError):
        service.manage_calibration(published["id"], "delete", None, None)
    with database.write() as db:
        db.execute(
            (
                "CREATE TRIGGER reject_archive BEFORE INSERT ON audit_events WHEN "
                "NEW.action='dispersion.calibration.restore' BEGIN SELECT RAISE(ABORT,'audit "
                "failure'); END"
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        service.manage_calibration(published["id"], "restore", None, None)
    assert service.get_task(task["id"])["calibrations"][0]["archived"]


def test_legacy_sample_adapter_preserves_means_and_rejects_method_mismatch(tmp_path):
    database = seed_database(tmp_path / "legacy.sqlite3")
    source, geometry, layout_id = _source_and_layout(database)
    now = utc_now()
    with database.write() as db:
        calibration = db.execute(
            (
                "INSERT INTO dispersion_calibrations(name,ccd_layout_id,wavelength_min,wavelength"
                "_max,coefficients_json,enabled,created_at) VALUES ('legacy',?,160,800,?,1,?)"
            ),
            (layout_id, json.dumps(geometry["ws_cof"]), now),
        ).lastrowid
        method = db.execute(
            (
                "INSERT INTO methods(name,description,work_type,status,current_version,created_at"
                ",updated_at) VALUES ('legacy','','spectral','active',1,?,?)"
            ),
            (now, now),
        ).lastrowid
        payload = {
            "conditions": {
                "ccd_layout_id": layout_id,
                "dispersion_calibration_id": calibration,
                "calculation_profile": "legacy_2_0_2",
            },
            "lines": [],
        }
        version = db.execute(
            "INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (?,1,'published',?,?)",
            (method, json.dumps(payload), now),
        ).lastrowid
        # CDT contains only its recorded average, not invented burn/dark exposures.
        source.pop("id")
        source.update(
            record_index=3,
            ignition_json=json.dumps({"burn_count": 0, "dark_count": 0}),
            burn_adcs_blob=None,
            dark_adcs_blob=None,
        )
        identifier = db.execute(
            f"INSERT INTO spectrum_bands ({','.join(source)}) VALUES ({','.join('?' for _ in source)})",
            list(source.values()),
        ).lastrowid
    analysis = Runtime(AppConfig(data_dir=tmp_path), database=database).analysis_service()
    result = analysis.import_legacy_sources([identifier], version)
    with database.read() as db:
        bands = db.execute(
            "SELECT mean_blob FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index",
            (result["sample_ids"][0],),
        ).fetchall()
        assert b"".join(row[0] for row in bands) == source["mean_blob"]
        assert db.execute("SELECT COUNT(*) FROM acquisition_frames").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    from backend.modules.spectrum_viewer import SpectrumViewerService

    viewer = SpectrumViewerService(database)
    assert viewer.list(kind="sample")[0]["frame_count"] is None
    assert viewer.get(f"sample:{result['sample_ids'][0]}")["ignition"]["burn_count"] is None
    with pytest.raises(AnalysisError):
        analysis.import_legacy_sources([identifier], 999999)


@pytest.mark.parametrize("source_name,expected", [("S0", "S1"), ("S9", "S10")])
def test_migrated_standard_indices_keep_original_name(tmp_path, source_name, expected):
    database = seed_database(tmp_path / "names.sqlite3")
    source, geometry, layout_id = _source_and_layout(database)
    now = utc_now()
    with database.write() as db:
        calibration = db.execute(
            (
                "INSERT INTO dispersion_calibrations(name,ccd_layout_id,wavelength_min,wavelength"
                "_max,coefficients_json,enabled,created_at) VALUES ('legacy',?,160,800,?,1,?)"
            ),
            (layout_id, json.dumps(geometry["ws_cof"]), now),
        ).lastrowid
        method = db.execute(
            (
                "INSERT INTO methods(name,description,work_type,status,current_version,created_at"
                ",updated_at) VALUES ('indexed','','spectral','active',1,?,?)"
            ),
            (now, now),
        ).lastrowid
        payload = {
            "conditions": {
                "ccd_layout_id": layout_id,
                "dispersion_calibration_id": calibration,
                "storage_profile": "legacy_specdirect_202",
            },
            "lines": [{"standard_points": [{"name": expected, "value": 123}]}],
        }
        version = db.execute(
            "INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (?,1,'published',?,?)",
            (method, json.dumps(payload), now),
        ).lastrowid
        source.pop("id")
        source.update(
            record_index=3,
            sample_name=source_name,
            ignition_json=json.dumps({"burn_count": 0, "dark_count": 0}),
            burn_adcs_blob=None,
            dark_adcs_blob=None,
        )
        identifier = db.execute(
            f"INSERT INTO spectrum_bands ({','.join(source)}) VALUES ({','.join('?' for _ in source)})",
            list(source.values()),
        ).lastrowid
    analysis = Runtime(AppConfig(data_dir=tmp_path), database=database).analysis_service()
    imported = analysis.import_legacy_sources([identifier], version)
    assert analysis.import_legacy_sources([identifier], version) == imported
    assert imported["name_mappings"] == [
        {"source_name": source_name, "analysis_name": expected, "sample_kind": "standard"}
    ]
    with database.read() as db:
        sample = db.execute("SELECT * FROM acquisition_samples WHERE id=?", (imported["sample_ids"][0],)).fetchone()
        assert sample["sample_name_original"] == source_name and sample["sample_name"] == expected
        assert sample["sample_kind"] == "standard"
