from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.runtime import Runtime
from backend.config import AppConfig
from backend.db import Database, utc_now
from backend.modules.reports import ReportError, ReportService
from backend.printing import SystemPrinters
from backend.modules.method_printing import MethodPrintService


def _seed(tmp_path: Path, result_count: int = 1) -> tuple[Database, int]:
    database = Database(tmp_path / "reports.sqlite3")
    database.initialize()
    now = utc_now()
    with database.write() as db:
        profile = db.execute("SELECT id FROM device_profiles LIMIT 1").fetchone()[0]
        layout = db.execute("SELECT id FROM ccd_layouts WHERE name='default'").fetchone()[0]
        method_id = db.execute("INSERT INTO methods(name, description, work_type, status, current_version, created_at, updated_at) VALUES ('S19 test method', '', 'spectral', 'active', 1, ?, ?)", (now, now)).lastrowid
        payload = {"lines": [{"id": "Fe-line", "line_type": "analysis", "element": "Fe", "wavelength_nm": 248.3, "enabled": True, "unit": "ug/g"}]}
        version_id = db.execute("INSERT INTO method_versions(method_id, version, state, payload_json, validation_errors_json, created_at) VALUES (?, 1, 'published', ?, '[]', ?)", (method_id, json.dumps(payload), now)).lastrowid
        task_id = db.execute("INSERT INTO acquisition_tasks(task_kind,name,status,device_profile_id,ccd_layout_id,method_version_id,method_id,method_version,sample_name,sample_kind,naming_mode,storage_mode,repeat_count,burn_frame_count,dark_frame_count,countdown_seconds,countdown_remaining,pre_excitation_seconds,sampling_period_seconds,burn_cycle_seconds,dark_cycle_seconds,ccd_indices_json,created_at,updated_at) VALUES ('sample','S19 task','completed',?,?,?,?,1,'S19 sample','normal','pre_recorded','averaged',1,1,0,0,0,0,1,1,1,'[0]',?,?)", (profile, layout, version_id, method_id, now, now)).lastrowid
        sample_id = db.execute("INSERT INTO acquisition_samples(task_id,repeat_index,sample_name_original,sample_name,sample_kind,storage_mode,status,finalized,result_sha256,created_at,completed_at,updated_at) VALUES (?,0,'S19 sample','S19 sample','normal','averaged','completed',1,'sample-hash',?,?,?)", (task_id, now, now, now)).lastrowid
        run_id = db.execute("INSERT INTO analysis_runs(name,status,method_id,method_version_id,method_version,calculation_profile,slow_mode,intervention_timeout_seconds,input_snapshot_json,input_sha256,created_at,updated_at) VALUES ('S19 run','completed',?,?,1,'modern_v1',0,300,'{}','run-hash',?,?)", (method_id, version_id, now, now)).lastrowid
        db.execute("INSERT INTO analysis_run_samples(run_id,position,acquisition_sample_id,sample_name,input_sha256,result_matrix_json,result_sha256,completed_at) VALUES (?,0,?,'S19 sample','sample-input','[]','sample-result',?)", (run_id, sample_id, now))
        db.execute("INSERT INTO analysis_line_results(run_id,sample_position,line_position,line_id,line_type,element,wavelength_nm,ccd_index,expected_position,peak_position,peak_height,background,net_signal,quantitative_signal,calculation_profile,intermediates_json,result_sha256,created_at) VALUES (?,0,0,'Fe-line','analysis','Fe',248.3,0,10,10,20,1,19,12.5,'modern_v1','{}','line-hash',?)", (run_id, now))
        merged = [
            {"acquisition_task_id": int(task_id), "sample_name": f"S19 sample {index + 1:02d}", "sample_kind": "normal", "values": [{"element": "Fe", "line_id": "Fe-line", "wavelength_nm": 248.3, "curve_snapshot_id": 701, "value": 42.75 + index, "intensity": 12.5, "candidate_count": 1}]}
            for index in range(result_count)
        ]
        db.execute("INSERT INTO analysis_result_merges(run_id,sequence,curve_snapshot_ids_json,results_json,result_sha256,created_at) VALUES (?,1,'[701]',?,'merge-hash',?)", (run_id, json.dumps(merged), now))
    return database, int(run_id)


def test_report_model_and_outputs_are_consistent(tmp_path: Path) -> None:
    database, run_id = _seed(tmp_path)
    service = Runtime(AppConfig(data_dir=database.path.parent), database=database).reports_service()
    report = service.create({"analysis_run_ids": [run_id], "template_key": "analysis-standard", "arrangement": "standard", "filters": {}}, None)
    assert report["version"] == 1 and report["model"]["rows"][0]["report_number"] == report["report_number"]
    assert report["model"]["rows"][0]["calculated_value"] == 42.75
    assert report["model"]["rows"][0]["curve_snapshot_id"] == 701
    assert "quantitative_signal" not in report["model"]["columns"]
    assert service.preview(report["id"]).find(report["report_number"]) >= 0
    with pytest.raises(ReportError) as unconfirmed:
        service.export(report["id"], {"format": "pdf", "output_directory": str(tmp_path / "exports"), "filename": "blocked", "same_name_strategy": "suffix"}, None)
    assert unconfirmed.value.code == "report_not_confirmed"
    report = service.confirm(report["id"], None)
    output_dir = tmp_path / "exports"
    paths = []
    for fmt in ("txt", "csv", "excel", "pdf"):
        result = service.export(report["id"], {"format": fmt, "output_directory": str(output_dir), "filename": "result", "same_name_strategy": "suffix"}, None)
        paths.append(Path(result["path"]))
        assert result["byte_length"] == paths[-1].stat().st_size
    assert len(paths) == len({path.name for path in paths})
    assert paths[0].read_bytes().startswith(b"\xef\xbb\xbf")
    assert paths[-1].read_bytes().startswith(b"%PDF")
    print_result = service.export(report["id"], {"format": "print", "printer_name": "geospectrum-pdf", "same_name_strategy": "suffix"}, None)
    assert print_result["dispatch_status"] == "completed"
    assert Path(print_result["path"]).is_file()
    assert len(PdfReader(print_result["path"]).pages) == print_result["page_count"]


def test_report_filter_and_same_name_error(tmp_path: Path) -> None:
    database, run_id = _seed(tmp_path)
    service = Runtime(AppConfig(data_dir=database.path.parent), database=database).reports_service()
    with pytest.raises(ReportError) as error:
        service.create({"analysis_run_ids": [run_id], "template_key": "analysis-standard", "arrangement": "standard", "filters": {"element": "missing"}}, None)
    assert error.value.code == "report_rows_empty"
    report = service.create({"analysis_run_ids": [run_id], "template_key": "analysis-standard", "arrangement": "exchange", "filters": {}}, None)
    assert report["model"]["columns"][:4] == ["report_number", "element", "wavelength_nm", "sample_name"]
    assert report["model"]["rows"][0]["element"] == "Fe"
    assert report["model"]["rows"][0]["wavelength_nm"] == 248.3
    assert report["model"]["rows"][0]["sample_name"] == "S19 sample 01"
    assert service.preview(report["id"]).find("元素") >= 0
    report = service.confirm(report["id"], None)
    payload = {"format": "csv", "output_directory": str(tmp_path / "exports"), "filename": "fixed", "same_name_strategy": "error"}
    exported = service.export(report["id"], payload, None)
    csv_text = Path(exported["path"]).read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0].split(",")[:4] == ["报告编号", "元素", "波长 (nm)", "样品名称"]
    assert csv_text.splitlines()[1].split(",")[1:4] == ["Fe", "248.3", "S19 sample 01"]
    with pytest.raises(ReportError) as duplicate:
        service.export(report["id"], payload, None)
    assert duplicate.value.code == "report_export_exists"


def test_report_pdf_paginates_without_dropping_last_row(tmp_path: Path) -> None:
    database, run_id = _seed(tmp_path, result_count=45)
    service = Runtime(AppConfig(data_dir=database.path.parent), database=database).reports_service()
    report = service.create({"analysis_run_ids": [run_id], "template_key": "analysis-standard", "arrangement": "standard", "filters": {}}, None)
    report = service.confirm(report["id"], None)
    result = service.export(report["id"], {"format": "pdf", "output_directory": str(tmp_path), "filename": "many", "same_name_strategy": "suffix"}, None)
    reader = PdfReader(result["path"])
    assert result["page_count"] == 3 == len(reader.pages)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "S19 sample 45" in extracted


def test_report_system_dispatch_failure_retains_pdf_record_and_defaults(tmp_path, monkeypatch):
    database, run_id = _seed(tmp_path)
    service = Runtime(AppConfig(data_dir=database.path.parent), database=database).reports_service()
    methods = Runtime(AppConfig(data_dir=database.path.parent), database=database).method_print_service()
    defaults = methods.get_settings()
    printer = {"name": "Failing-Printer", "display_name": "Failing Printer",
               "virtual": False, "system": True, "default": False}
    monkeypatch.setattr(SystemPrinters, "_system_printers", staticmethod(lambda: [printer]))
    assert service.printers() == methods.printers()
    assert service.printers()[0]["name"] == "geospectrum-pdf"
    report = service.create({"analysis_run_ids": [run_id], "template_key": "analysis-standard",
                             "arrangement": "standard", "filters": {}}, None)
    report = service.confirm(report["id"], None)
    calls = []

    def fail_dispatch(pdf_path, printer_name):
        assert pdf_path.read_bytes().startswith(b"%PDF")
        calls.append((pdf_path, printer_name))
        raise RuntimeError("test spooler unavailable")

    monkeypatch.setattr(SystemPrinters, "dispatch_pdf", staticmethod(fail_dispatch))
    payload = {"format": "print", "printer_name": printer["name"]}
    with pytest.raises(ReportError) as failed:
        service.export(report["id"], payload, None)
    error = failed.value
    assert error.code == "print_dispatch_failed" and error.status_code == 500
    pdf_path = Path(error.details["pdf_path"])
    assert calls == [(pdf_path, printer["name"])]
    assert pdf_path.is_file()
    with database.read() as db:
        job = dict(db.execute("SELECT * FROM report_exports WHERE report_id=?", (report["id"],)).fetchone())
        audit = dict(db.execute("SELECT * FROM audit_events WHERE action='report.print'").fetchone())
    assert job["status"] == "failed"
    assert job["error_code"] == error.code
    assert job["error_message"] == "test spooler unavailable"
    assert job["actual_path"] == str(pdf_path)
    assert job["content_sha256"] == hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert job["byte_length"] == pdf_path.stat().st_size
    assert job["page_count"] == len(PdfReader(pdf_path).pages)
    assert json.loads(job["report_json"]) == {"printer_name": printer["name"], "model_sha256": report["model_sha256"]}
    assert json.loads(audit["details_json"]) == {"export_id": job["id"], "printer_name": printer["name"],
                                              "status": "failed", "error_code": error.code}
    assert service.get(report["id"]) == report
    assert methods.get_settings() == defaults
    monkeypatch.setattr(SystemPrinters, "dispatch_pdf", staticmethod(lambda path, name: calls.append((path, name))))
    retried = service.export(report["id"], payload, None)
    assert retried["dispatch_status"] == "queued"
    assert retried["id"] != job["id"]
    assert pdf_path.is_file()
