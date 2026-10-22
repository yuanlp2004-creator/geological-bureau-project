from __future__ import annotations

import io
import json
import re
from html.parser import HTMLParser
import sys
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from backend.runtime import Runtime
from backend.config import AppConfig
from backend.modules.method_printing import MethodPrintService
from backend.printing import SystemPrinters
from pypdf import PdfReader

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def print_client(tmp_path, monkeypatch):
    monkeypatch.setattr(SystemPrinters, "_system_printers", staticmethod(lambda: [
        {"name": "test-system-printer", "display_name": "Test Windows printer", "virtual": False, "system": True, "default": True}]))
    monkeypatch.setattr(SystemPrinters, "papers", staticmethod(lambda name: [
        {"code": code, "display_name": code, "width_mm": size[0], "height_mm": size[1]}
        for code,size in {"A4": (210,297), "A3": (297,420), "Letter": (215.9,279.4), "win:11:1480:2100": (148,210)}.items()]))
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.config as config_module
    import backend.main as main_module

    test_config = config_module.AppConfig(data_dir=tmp_path)
    application = main_module.create_app(test_config)
    runtime = application.state.runtime
    with TestClient(application) as client:
        bootstrap = client.post(
            "/api/v1/auth/bootstrap",
            json={"username": "print-admin", "password": "correct-horse"},
        )
        assert bootstrap.status_code == 201
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "print-admin", "password": "correct-horse"},
        )
        token = login.json()["access_token"]
        yield client, runtime, {"Authorization": f"Bearer {token}"}, tmp_path


def _create_method(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/methods",
        headers=headers,
        json={
            "name": "S05 多元素方法",
            "description": "用于校验方法条件、谱线、标准点与分页一致性",
            "work_type": "routine",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _analysis_line(element: str, wavelength: float) -> dict:
    return {
        "line_type": "analysis",
        "element": element,
        "wavelength_nm": wavelength,
        "actual_wavelength_nm": wavelength,
        "enabled": True,
        "critical_band": False,
        "priority": 10,
        "background_line_id": None,
        "alignment_line_id": None,
        "internal_standard_mode": "none",
        "internal_standard_line_id": None,
        "scan_width_points": 9,
        "background_offset_points": 0,
        "peak_mode": "max_single_point",
        "peak_width_points": 1,
        "fit_mode": "linear",
        "coordinate_type": "normal",
        "unit": "ug/g",
        "value_kind": "content",
        "decimal_places": 2,
        "lower_peak": 300,
        "minimum_peak_ratio": 1.5,
        "valid_range_min": 0,
        "valid_range_max": 1000,
        "over_limit_tolerance_percent": 5,
        "standard_points": [{"name": f"STD-{index}", "value": index * 10, "active": True} for index in range(1, 5)],
    }


def _create_printable_method(client: TestClient, headers: dict[str, str]) -> dict:
    method = _create_method(client, headers)
    for element, wavelength in (("Fe", 254.0), ("Mn", 257.0), ("Cr", 260.0)):
        response = client.post(
            f"/api/v1/methods/{method['id']}/lines",
            headers=headers,
            json=_analysis_line(element, wavelength),
        )
        assert response.status_code == 201, response.text
        method = response.json()
    return method


def test_print_settings_persist_and_reject_unknown_printer(print_client) -> None:
    client, runtime, headers, _ = print_client
    response = client.get("/api/v1/method-print/settings", headers=headers)
    assert response.status_code == 200
    settings = response.json()
    assert settings["default_printer"] == "test-system-printer"

    printers = client.get("/api/v1/method-print/printers", headers=headers)
    assert printers.status_code == 200
    assert any(item["name"] == "test-system-printer" for item in printers.json()["printers"])

    changed = {
        **settings,
        "paper": "A3",
        "orientation": "landscape",
        "margin_left_mm": 18,
        "layout": "compact",
        "font_size_pt": 10,
        "copies": 2,
        "duplex": "long_edge",
        "color": True,
        "preview_before_print": False,
    }
    saved = client.patch("/api/v1/method-print/settings", headers=headers, json=changed)
    assert saved.status_code == 200, saved.text
    assert saved.json() == changed

    restarted_service = Runtime(
        AppConfig(data_dir=runtime.database.path.parent), database=runtime.database
    ).method_print_service()
    assert restarted_service.get_settings() == changed

    rejected = client.patch(
        "/api/v1/method-print/settings",
        headers=headers,
        json={**changed, "default_printer": "missing-printer"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "printer_not_found"
    assert restarted_service.get_settings() == changed


def test_html_preview_and_pdf_share_pages_fields_and_text(print_client) -> None:
    client, _, headers, _ = print_client
    method = _create_printable_method(client, headers)
    payload = {"version": method["latest_version"]}

    preview = client.post(f"/api/v1/methods/{method['id']}/preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("text/html")
    assert 'data-page-count="' in preview.text
    assert "S05 多元素方法" in preview.text
    assert "方法条件" in preview.text
    assert "标准点（12 个）" in preview.text
    assert "最大值" in preview.text
    assert "普通坐标" in preview.text.replace("<br>", "")
    preview_pages = int(preview.headers["x-page-count"])
    preview_fields = int(preview.headers["x-field-count"])
    assert preview_pages >= 2
    assert preview_fields >= 40

    pdf = client.post(f"/api/v1/methods/{method['id']}/pdf", headers=headers, json=payload)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert int(pdf.headers["x-page-count"]) == preview_pages
    assert int(pdf.headers["x-field-count"]) == preview_fields
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) == preview_pages

    with pdfplumber.open(io.BytesIO(pdf.content)) as document:
        extracted = "".join(page.extract_text() or "" for page in document.pages).replace("\n", "")
    for expected in (
        "S05 多元素方法",
        "方法条件",
        "Fe 254.0000 nm",
        "最大值",
        "普通坐标",
        "STD-4",
    ):
        assert expected in extracted


def test_compatibility_appendix_preserves_values_and_printable_line_parameters(print_client) -> None:
    client, _, headers, _ = print_client
    method = _create_printable_method(client, headers)
    hidden = {"standard_sample_name": "保留原名称", "calibration_threshold": 8.25,
              "qc_threshold": 9.5, "abnormal_threshold": 11.75}
    updated = client.patch(f"/api/v1/methods/{method['id']}", headers=headers, json={"conditions": hidden})
    assert updated.status_code == 200, updated.text
    line = _analysis_line("Fe", 254.0)
    line.update({"value_kind": "concentration", "over_limit_tolerance_percent": 17.5, "priority": 42})
    line_id = next(item["id"] for item in updated.json()["version"]["lines"] if item["element"] == "Fe")
    updated = client.patch(f"/api/v1/methods/{method['id']}/lines/{line_id}", headers=headers, json=line)
    assert updated.status_code == 200, updated.text
    before = updated.json()["version"]["content_sha256"]

    class VisibleText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)

    preview = client.post(f"/api/v1/methods/{method['id']}/preview", headers=headers, json={})
    assert preview.status_code == 200, preview.text
    parser = VisibleText()
    parser.feed(preview.text)
    text = re.sub(r"\s+", "", "".join(parser.parts))
    appendix = text.index("兼容参数（保留原值）")
    assert text.rindex("STD-4") < appendix
    assert text.index("工作类型") > appendix and text.index("超限容差") > appendix
    expected = ["扫描点数=9", "背景位置=0", "拟合方式=直线函数", "最低峰值=300", "最小倍数=1.5",
                "定位谱线=参考线定位", "保留原名称", "8.25", "9.5", "11.75", "concentration", "17.5%", "优先级=42"]
    for value in expected:
        assert value in text
    pdf = client.post(f"/api/v1/methods/{method['id']}/pdf", headers=headers, json={})
    assert pdf.status_code == 200, pdf.text
    with pdfplumber.open(io.BytesIO(pdf.content)) as document:
        printed = re.sub(r"\s+", "", "".join(page.extract_text() or "" for page in document.pages))
    for value in expected:
        assert value in printed
    assert client.get(f"/api/v1/methods/{method['id']}", headers=headers).json()["version"]["content_sha256"] == before


def test_system_print_retains_input_and_submits_rendered_pdf(print_client, monkeypatch) -> None:
    client, _, headers, tmp_path = print_client
    method = _create_printable_method(client, headers)
    settings = client.get("/api/v1/method-print/settings", headers=headers).json()
    settings.update({"copies": 3, "color": True, "duplex": "short_edge"})
    calls = []
    monkeypatch.setattr(SystemPrinters, "dispatch_pdf", staticmethod(lambda path, printer, applied: calls.append((path, printer, applied))))

    printed = client.post(
        f"/api/v1/methods/{method['id']}/print",
        headers=headers,
        json={"settings": settings, "printer_name": "test-system-printer"},
    )
    assert printed.status_code == 200, printed.text
    job = printed.json()
    assert job["status"] == "queued"
    assert Path(job["pdf_path"]).is_file()
    assert job["output_path"] is None
    assert calls == [(Path(job["pdf_path"]), "test-system-printer", settings)]
    assert Path(job["pdf_path"]).is_relative_to(tmp_path)

    input_path = Path(job["pdf_path"]).with_name("render-input.json")
    snapshot = json.loads(input_path.read_text(encoding="utf-8"))
    assert snapshot["settings"]["copies"] == 3
    assert snapshot["settings"]["duplex"] == "short_edge"
    assert len(PdfReader(job["pdf_path"]).pages) == job["page_count"]

    jobs = client.get(f"/api/v1/methods/{method['id']}/print-jobs", headers=headers)
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["id"] == job["id"]


def test_failed_system_dispatch_keeps_render_inputs_without_changing_defaults(print_client, monkeypatch) -> None:
    client, runtime, headers, _ = print_client
    method = _create_method(client, headers)
    original_settings = client.get("/api/v1/method-print/settings", headers=headers).json()
    assert client.patch("/api/v1/method-print/settings", headers=headers, json=original_settings).status_code == 200

    monkeypatch.setattr(
        SystemPrinters,
        "_system_printers",
        staticmethod(
            lambda: [
                {
                    "name": "S05-Failing-Printer",
                    "display_name": "S05 Failing Printer",
                    "virtual": False,
                    "system": True,
                    "default": False,
                }
            ]
        ),
    )

    def fail_dispatch(_pdf_path, _printer_name, _settings):
        raise RuntimeError("test spooler unavailable")

    monkeypatch.setattr(SystemPrinters, "dispatch_pdf", staticmethod(fail_dispatch))
    failed = client.post(
        f"/api/v1/methods/{method['id']}/print",
        headers=headers,
        json={"printer_name": "S05-Failing-Printer"},
    )
    assert failed.status_code == 502
    detail = failed.json()["detail"]
    assert detail["code"] == "print_dispatch_failed"
    assert Path(detail["details"]["input_path"]).is_file()
    assert Path(detail["details"]["pdf_path"]).is_file()

    job = client.get(f"/api/v1/method-print/jobs/{detail['details']['job_id']}", headers=headers)
    assert job.status_code == 200
    assert job.json()["status"] == "failed"
    assert job.json()["error_code"] == "print_dispatch_failed"
    assert client.get("/api/v1/method-print/settings", headers=headers).json() == original_settings


def test_print_permissions_follow_method_read_and_write(print_client) -> None:
    client, _, headers, _ = print_client
    method = _create_method(client, headers)
    roles = client.get("/api/v1/roles", headers=headers)
    analyst_role = next(item for item in roles.json() if item["name"] == "analyst")
    user = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "s05-analyst", "password": "analyst-pass", "role_ids": [analyst_role["id"]]},
    )
    assert user.status_code == 201, user.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "s05-analyst", "password": "analyst-pass"},
    )
    analyst_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.post(f"/api/v1/methods/{method['id']}/preview", headers=analyst_headers, json={}).status_code == 200
    assert client.post(f"/api/v1/methods/{method['id']}/pdf", headers=analyst_headers, json={}).status_code == 200
    assert client.post(f"/api/v1/methods/{method['id']}/print", headers=analyst_headers, json={}).status_code == 403
    assert client.patch("/api/v1/method-print/settings", headers=analyst_headers, json={}).status_code == 403
    assert client.get("/api/v1/method-print/settings").status_code == 401


def test_driver_papers_and_connection_probe_do_not_submit_or_change_defaults(print_client, monkeypatch):
    client, runtime, headers, _ = print_client
    settings = client.get('/api/v1/method-print/settings', headers=headers).json()
    def forbidden(*args):
        raise AssertionError('connection probe must never submit a print job')
    monkeypatch.setattr(SystemPrinters, 'dispatch_pdf', staticmethod(forbidden))
    monkeypatch.setattr(SystemPrinters, 'check_connection', staticmethod(lambda name, settings: {
        'connected': True, 'printer_name': name, 'submitted': False}))
    papers = client.get('/api/v1/method-print/papers', params={'printer_name':settings['default_printer']}, headers=headers)
    assert papers.status_code == 200
    assert any(p['code'] == 'win:11:1480:2100' for p in papers.json()['papers'])
    changed = {**settings, 'paper':'win:11:1480:2100', 'orientation':'landscape', 'font_size_pt':13}
    probe = client.post('/api/v1/method-print/check-connection', json=changed, headers=headers)
    assert probe.status_code == 200 and probe.json()['submitted'] is False
    assert client.get('/api/v1/method-print/settings', headers=headers).json() == settings
    assert client.post('/api/v1/method-print/check-connection', json=changed).status_code == 401
    assert client.patch('/api/v1/method-print/settings', json=changed, headers=headers).status_code == 200
    assert runtime.method_print_service().get_settings() == changed
    method = _create_printable_method(client, headers)
    pdf = client.post(f"/api/v1/methods/{method['id']}/pdf", json={}, headers=headers)
    assert pdf.status_code == 200
    page = PdfReader(io.BytesIO(pdf.content)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(210*72/25.4, abs=.01)
    assert float(page.mediabox.height) == pytest.approx(148*72/25.4, abs=.01)
    with pdfplumber.open(io.BytesIO(pdf.content)) as rendered:
        clipped = [char['text'] for sheet in rendered.pages for char in sheet.chars
                   if char['x1'] > sheet.width-12*72/25.4+1]
        assert not clipped, f'字体13的A5页内容越过右边距: {clipped[:12]}'

    rejected = client.patch('/api/v1/method-print/settings', json={**changed,'paper':'win:999:2100:2970'},headers=headers)
    assert rejected.status_code == 422
    assert runtime.method_print_service().get_settings() == changed


def test_cancelled_windows_dialog_records_cancellation_without_success(print_client, monkeypatch):
    from backend.printing import PrintCancelled
    client, runtime, headers, _ = print_client
    method = _create_method(client, headers)
    def cancel(*args):
        raise PrintCancelled('已取消 Windows 打印')
    monkeypatch.setattr(SystemPrinters, 'dispatch_pdf', staticmethod(cancel))
    response = client.post(f"/api/v1/methods/{method['id']}/print",json={},headers=headers)
    assert response.status_code == 200
    assert response.json()['status'] == 'failed'
    assert response.json()['error_code'] == 'print_cancelled'
    assert response.json()['output_path'] is None
    with runtime.database.read() as db:
        event = json.loads(db.execute("SELECT details_json FROM audit_events WHERE action='method.print'").fetchone()[0])
    assert event['status'] == 'failed' and event['error_code'] == 'print_cancelled'
