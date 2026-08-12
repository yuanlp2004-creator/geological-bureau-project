from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pdfplumber
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))


@pytest.fixture()
def print_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRUM_DATA_DIR", str(tmp_path))
    import backend.app.config as config_module
    import backend.app.main as main_module

    config_module.config = config_module.AppConfig(data_dir=tmp_path)
    main_module.config = config_module.config
    main_module.database = main_module.Database(config_module.config.database_path)
    main_module.service = main_module.AppService(
        main_module.database, tmp_path / "logs" / "runtime.jsonl"
    )
    main_module.auth_service = main_module.AuthService(main_module.database)
    with TestClient(main_module.app) as client:
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
        yield client, main_module, {"Authorization": f"Bearer {token}"}, tmp_path


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
        "standard_points": [
            {"name": f"STD-{index}", "value": index * 10, "active": True}
            for index in range(1, 5)
        ],
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
    client, main_module, headers, _ = print_client
    response = client.get("/api/v1/method-print/settings", headers=headers)
    assert response.status_code == 200
    settings = response.json()
    assert settings["default_printer"] == "geospectrum-pdf"

    printers = client.get("/api/v1/method-print/printers", headers=headers)
    assert printers.status_code == 200
    assert any(item["name"] == "geospectrum-pdf" for item in printers.json()["printers"])

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

    restarted_service = main_module.MethodPrintService(main_module.database)
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

    preview = client.post(
        f"/api/v1/methods/{method['id']}/preview", headers=headers, json=payload
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("text/html")
    assert 'data-page-count="' in preview.text
    assert "S05 多元素方法" in preview.text
    assert "方法条件" in preview.text
    assert "标准点（12 个）" in preview.text
    assert "最大单点" in preview.text
    assert "普通坐标" in preview.text
    preview_pages = int(preview.headers["x-page-count"])
    preview_fields = int(preview.headers["x-field-count"])
    assert preview_pages >= 2
    assert preview_fields >= 40

    pdf = client.post(
        f"/api/v1/methods/{method['id']}/pdf", headers=headers, json=payload
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert int(pdf.headers["x-page-count"]) == preview_pages
    assert int(pdf.headers["x-field-count"]) == preview_fields
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) == preview_pages

    with pdfplumber.open(io.BytesIO(pdf.content)) as document:
        extracted = "\n".join(page.extract_text() or "" for page in document.pages)
    for expected in (
        "S05 多元素方法",
        "方法条件",
        "Fe 254.0000 nm",
        "最大单点",
        "普通坐标",
        "STD-4",
    ):
        assert expected in extracted


def test_virtual_print_retains_input_and_completed_pdf(print_client) -> None:
    client, _, headers, tmp_path = print_client
    method = _create_printable_method(client, headers)
    settings = client.get("/api/v1/method-print/settings", headers=headers).json()
    settings.update({"copies": 3, "color": True, "duplex": "short_edge"})

    printed = client.post(
        f"/api/v1/methods/{method['id']}/print",
        headers=headers,
        json={"settings": settings, "printer_name": "geospectrum-pdf"},
    )
    assert printed.status_code == 200, printed.text
    job = printed.json()
    assert job["status"] == "completed"
    assert Path(job["pdf_path"]).is_file()
    assert Path(job["output_path"]).is_file()
    assert Path(job["pdf_path"]).read_bytes() == Path(job["output_path"]).read_bytes()
    assert Path(job["pdf_path"]).is_relative_to(tmp_path)

    input_path = Path(job["pdf_path"]).with_name("render-input.json")
    snapshot = json.loads(input_path.read_text(encoding="utf-8"))
    assert snapshot["settings"]["copies"] == 3
    assert snapshot["settings"]["duplex"] == "short_edge"
    assert len(PdfReader(job["output_path"]).pages) == job["page_count"]

    jobs = client.get(
        f"/api/v1/methods/{method['id']}/print-jobs", headers=headers
    )
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["id"] == job["id"]


def test_failed_system_dispatch_keeps_render_inputs_without_changing_defaults(
    print_client, monkeypatch
) -> None:
    client, main_module, headers, _ = print_client
    method = _create_method(client, headers)
    original_settings = client.get("/api/v1/method-print/settings", headers=headers).json()

    monkeypatch.setattr(
        main_module.MethodPrintService,
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

    def fail_dispatch(_pdf_path, _printer_name):
        raise RuntimeError("test spooler unavailable")

    monkeypatch.setattr(
        main_module.MethodPrintService, "_dispatch_system_print", staticmethod(fail_dispatch)
    )
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

    job = client.get(
        f"/api/v1/method-print/jobs/{detail['details']['job_id']}", headers=headers
    )
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

    assert client.post(
        f"/api/v1/methods/{method['id']}/preview", headers=analyst_headers, json={}
    ).status_code == 200
    assert client.post(
        f"/api/v1/methods/{method['id']}/pdf", headers=analyst_headers, json={}
    ).status_code == 200
    assert client.post(
        f"/api/v1/methods/{method['id']}/print", headers=analyst_headers, json={}
    ).status_code == 403
    assert client.patch(
        "/api/v1/method-print/settings", headers=analyst_headers, json={}
    ).status_code == 403
    assert client.get("/api/v1/method-print/settings").status_code == 401
