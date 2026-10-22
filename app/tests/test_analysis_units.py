"""单位编辑、历史快照及实际曲线/报告消费者的隔离回归。"""
import json
from pathlib import Path

import pytest

from tests.test_spectral_lines import line_client, _method, _line
from tests.test_s17_quality_curves import _seed_completed_run
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from backend.modules.methods.units import convert_line_unit, unit_scale
from backend.modules.reports.service import _display_analysis_value


@pytest.mark.parametrize("unit,power", [("mg/g", 3), ("%", 4)])
def test_method_unit_converts_draft_and_preserves_published_snapshot(line_client, unit, power):
    client, runtime, headers = line_client
    method = _method(client, headers)
    points = [{"name": f"S{i}", "value": i * 1000, "active": True,
               "original_intensity": i * 20, "adjusted_intensity": i * 21, "intensity_valid": True}
              for i in range(1, 5)]
    response = client.post(f"/api/v1/methods/{method['id']}/lines", headers=headers,
                           json=_line(254, standard_points=points, valid_range_max=5000))
    assert response.status_code == 201, response.text
    published = client.post(f"/api/v1/methods/{method['id']}/publish", headers=headers, json={}).json()
    original = published["version"]
    response = client.patch(f"/api/v1/methods/{method['id']}", headers=headers,
                            json={"conditions": {"analysis_unit": unit}})
    assert response.status_code == 200, response.text
    draft = response.json()["version"]
    assert draft["validation_errors"] == []
    line = next(line for line in draft["lines"] if line["line_type"] == "analysis")
    assert line["unit"] == unit and line["decimal_places"] == 2 + power
    assert [p["value"] for p in line["standard_points"]] == pytest.approx([i * 1000 / 10**power for i in range(1, 5)])
    assert line["valid_range_max"] == 5000 / 10**power
    assert line["standard_points"][0]["original_intensity"] == 20
    assert line["standard_points"][0]["adjusted_intensity"] == 21
    assert line["standard_points"][0]["intensity_valid"]
    unchanged = client.patch(f"/api/v1/methods/{method['id']}", headers=headers,
                             json={"conditions": {"analysis_unit": unit}}).json()["version"]
    assert unchanged["lines"] == draft["lines"]
    with runtime.database.read() as db:
        saved = db.execute("SELECT payload_json FROM method_versions WHERE id=?", (original["id"],)).fetchone()[0]
    assert json.loads(saved)["lines"] == original["lines"]
    response = client.post(f"/api/v1/methods/{method['id']}/publish", headers=headers, json={})
    assert response.status_code == 200, response.text
    reverted = client.patch(f"/api/v1/methods/{method['id']}", headers=headers,
                            json={"conditions": {"analysis_unit": "ug/g"}}).json()["version"]
    assert reverted["lines"] == original["lines"]


def test_line_unit_keeps_intensity_only_for_equivalent_content(line_client):
    client, _, headers = line_client
    method = _method(client, headers)
    initial = _line(254, standard_points=[{"name": f"S{i}", "value": i, "active": True,
                     "original_intensity": i * 20, "adjusted_intensity": i * 20, "intensity_valid": True}
                    for i in range(1, 5)])
    created = client.post(f"/api/v1/methods/{method['id']}/lines", headers=headers, json=initial).json()
    line_id = created["changed_line_id"]
    converted = convert_line_unit(initial, "%")
    response = client.patch(f"/api/v1/methods/{method['id']}/lines/{line_id}", headers=headers, json=converted)
    assert response.status_code == 200, response.text
    line = next(line for line in response.json()["version"]["lines"] if line["id"] == line_id)
    assert line["standard_points"][0]["intensity_valid"]
    converted["standard_points"][0]["value"] += 0.00001
    response = client.patch(f"/api/v1/methods/{method['id']}/lines/{line_id}", headers=headers, json=converted)
    assert response.status_code == 200, response.text
    line = next(line for line in response.json()["version"]["lines"] if line["id"] == line_id)
    assert line["standard_points"][0]["original_intensity"] is None
    assert not line["standard_points"][0]["intensity_valid"]


def test_percentage_tiny_standards_and_duplicate_failure(line_client):
    client, _, headers = line_client
    method = _method(client, headers)
    line = convert_line_unit(_line(254, decimal_places=6,
        standard_points=[{"name": f"S{i}", "value": i * 1e-6, "active": True} for i in range(1, 5)]), "%")
    response = client.post(f"/api/v1/methods/{method['id']}/lines", headers=headers, json=line)
    assert response.status_code == 201, response.text
    assert response.json()["version"]["validation_errors"] == []
    line["wavelength_nm"] = line["actual_wavelength_nm"] = 254.5
    line["standard_points"][1]["value"] = line["standard_points"][0]["value"]
    response = client.post(f"/api/v1/methods/{method['id']}/lines", headers=headers, json=line)
    assert response.status_code == 422, response.text
    assert "standard_value_duplicate" in response.text


def test_custom_unit_is_preserved(line_client):
    client, _, headers = line_client
    method = _method(client, headers)
    response = client.post(f"/api/v1/methods/{method['id']}/lines", headers=headers, json=_line(254, unit="mg/kg"))
    assert response.status_code == 201, response.text
    original = response.json()["version"]["lines"][1]
    response = client.patch(f"/api/v1/methods/{method['id']}", headers=headers, json={"conditions": {"analysis_unit": "%"}})
    assert response.json()["version"]["lines"][1] == original


@pytest.mark.parametrize("unit", ["ug/g", "mg/g", "%"])
@pytest.mark.parametrize("profile", ["modern_v1", "legacy_2_0_2"])
@pytest.mark.parametrize("coordinate", ["normal", "logarithmic"])
def test_units_flow_through_curve_merge_report_and_export(tmp_path: Path, unit, profile, coordinate):
    database = Database(tmp_path / "units.sqlite3")
    # 构造固定强度黄金输入；不代表真实设备或旧 EXE 测量。
    def transform(payload):
        payload["lines"][0]["decimal_places"] = 2
        payload["lines"][0] = convert_line_unit(payload["lines"][0], unit)
        payload["lines"][0]["coordinate_type"] = coordinate
        payload["conditions"]["analysis_unit"] = unit
        payload["conditions"]["calculation_profile"] = profile
        return payload
    run_id, _ = _seed_completed_run(database, payload_transform=transform, calculation_profile=profile)
    runtime = Runtime(AppConfig(data_dir=tmp_path), database=database)
    service = runtime.analysis_service()
    service.build_quality(run_id)
    run = service.fit_standard_curve(run_id, "L1", {"reason": "单位黄金输入"})
    snapshot = run["curves"]["lines"][0]["snapshots"][-1]
    run = service.publish_standard_curve(run_id, "L1", snapshot["id"], "复核单位")
    run = service.merge_results(run_id, "单位结果")
    result = run["curves"]["merges"][-1]["results"][0]["values"][0]
    assert result["unit"] == unit
    assert result["value"] > 0
    if coordinate == "normal":
        assert result["value"] * unit_scale(unit) == pytest.approx(9.5, rel=1e-5)
    assert f"分析值 ({unit})" in service.curve_preview(run_id, snapshot["id"], "text")
    reports = runtime.reports_service()
    report = reports.create({"analysis_run_ids": [run_id], "template_key": "analysis-standard", "arrangement": "standard",'table_layout':'detail'})
    rows = report["model"]["rows"]
    assert all(row["unit"] == unit for row in rows)
    assert float(rows[0]["display_value"]) > 0
    reports.confirm(report["id"])
    for fmt in ("csv", "excel", "pdf"):
        exported = reports.export(report["id"], {"format": fmt, "output_directory": str(tmp_path / "exports"),
                                  "filename": f"unit-{fmt}", "same_name_strategy": "suffix"})
        content = Path(exported["path"]).read_bytes()
        if fmt == "pdf":
            assert content.startswith(b"%PDF-")
        else:
            assert unit.encode() in content


def test_nonzero_report_value_does_not_round_to_zero():
    assert float(_display_analysis_value(1e-12, 6)) == 1e-12
