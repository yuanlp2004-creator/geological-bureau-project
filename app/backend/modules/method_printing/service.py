"""方法打印设置、快照和任务事务的统一编排入口。"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from typing import Any
from ...db import Database, utc_now
from ...schemas.system import SettingsPatch
from ...schemas.methods import MethodPrintSettings
from ...services import AppService
from ..methods import MethodDomainError, MethodService, _json
from ...printing import SystemPrinters, VIRTUAL_PDF_PRINTER
from .document import MethodDocument
from .settings import PrintSettings
from .rendering import MethodRenderer



class MethodPrintService:
    def __init__(self, database: Database, *, methods: MethodService, printers: SystemPrinters):
        self.database = database
        self.methods = methods
        self.app_service = AppService(database)
        self.document = MethodDocument()
        self.rendering = MethodRenderer()
        self.printer_backend = printers

    def get_settings(self) -> dict[str, Any]:
        raw = self.app_service.get_settings()["printing"]
        if raw.get("default_printer") == "system":
            raw["default_printer"] = VIRTUAL_PDF_PRINTER
        return MethodPrintSettings.model_validate(raw).model_dump(mode="json")

    def save_settings(self, settings: MethodPrintSettings, actor_user_id: int) -> dict[str, Any]:
        self.document._validate_geometry(PrintSettings(**settings.model_dump(mode="json")))
        names = {item["name"] for item in self.printer_backend.printers()}
        if settings.default_printer not in names:
            raise MethodDomainError(
                "printer_not_found",
                "选择的打印机不存在",
                fields=["default_printer"],
            )
        result = self.app_service.update_settings(
            SettingsPatch(printing=settings.model_dump(mode="json")), actor_user_id
        )["printing"]
        with self.database.write() as db:
            self._audit(db, actor_user_id, "method.print.settings", None, {"settings": result})
        return result

    def _snapshot(self, method_id: int, version: int | None) -> dict[str, Any]:
        with self.database.read() as db:
            snapshot = self.methods.bind_snapshots(db).for_print(method_id, version)
            return {
                "method": {key: getattr(snapshot.method, key) for key in ("id", "name", "description", "work_type", "status")},
                "version": snapshot.print_version(),
            }

    def prepare(self, method_id: int, version: int | None, settings: MethodPrintSettings | None = None) -> dict[str, Any]:
        applied = settings or MethodPrintSettings.model_validate(self.get_settings())
        internal_settings = PrintSettings(**applied.model_dump(mode="json"))
        self.document._validate_geometry(internal_settings)
        snapshot = self._snapshot(method_id, version)
        rows = self.document._document_rows(snapshot)
        layout = self.document._paginate(rows, internal_settings)
        return {"snapshot": snapshot, "rows": rows, "settings": applied.model_dump(mode="json"), **layout}

    def _audit(self, db, actor_user_id: int | None, action: str, method_id: int | None, details: dict[str, Any]) -> None:
        actor = self.methods._valid_actor(db, actor_user_id)
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'method_print', ?, ?, ?)",
            (actor, action, method_id, _json(details), utc_now()),
        )

    def preview(self, method_id: int, version: int | None, settings: MethodPrintSettings | None, actor_user_id: int) -> tuple[str, dict[str, Any]]:
        document = self.prepare(method_id, version, settings)
        with self.database.write() as db:
            self._audit(db, actor_user_id, "method.preview", method_id, {"version": document["snapshot"]["version"]["version"], "page_count": document["page_count"]})
        return self.rendering.render_html(document), document

    def pdf(self, method_id: int, version: int | None, settings: MethodPrintSettings | None, actor_user_id: int) -> tuple[bytes, dict[str, Any]]:
        document = self.prepare(method_id, version, settings)
        result = self.rendering.render_pdf(document)
        with self.database.write() as db:
            self._audit(db, actor_user_id, "method.pdf.export", method_id, {"version": document["snapshot"]["version"]["version"], "page_count": document["page_count"], "bytes": len(result)})
        return result, document

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .")
        return cleaned[:80] or "method"

    def print_method(self, method_id: int, version: int | None, settings: MethodPrintSettings | None, printer_name: str | None, actor_user_id: int) -> dict[str, Any]:
        document = self.prepare(method_id, version, settings)
        applied = document["settings"]
        printer = printer_name or applied["default_printer"]
        available = {item["name"]: item for item in self.printer_backend.printers()}
        if printer not in available:
            raise MethodDomainError("printer_not_found", "选择的打印机不存在", fields=["printer_name"])
        pdf_bytes = self.rendering.render_pdf(document)
        job_id = uuid.uuid4().hex
        created_at = utc_now()
        version_number = int(document["snapshot"]["version"]["version"])
        job_dir = self.database.path.parent / "print-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        pdf_path = job_dir / "method-parameters.pdf"
        input_path = job_dir / "render-input.json"
        input_snapshot = {
            "method": document["snapshot"],
            "settings": applied,
            "printer_name": printer,
            "page_count": document["page_count"],
            "field_count": document["field_count"],
        }
        pdf_path.write_bytes(pdf_bytes)
        input_path.write_text(json.dumps(input_snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        with self.database.write() as db:
            db.execute(
                "INSERT INTO method_print_jobs(id, method_id, method_version, printer_name, status, settings_json, input_json, pdf_path, page_count, field_count, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'rendered', ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, method_id, version_number, printer, _json(applied), _json(input_snapshot), str(pdf_path), document["page_count"], document["field_count"], self.methods._valid_actor(db, actor_user_id), created_at, created_at),
            )
        try:
            if printer == VIRTUAL_PDF_PRINTER:
                output_dir = self.database.path.parent / "prints"
                output_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                output_path = output_dir / f"{self._safe_name(document['snapshot']['method']['name'])}-v{version_number}-{stamp}-{job_id[:8]}.pdf"
                shutil.copyfile(pdf_path, output_path)
                status = "completed"
            else:
                self.printer_backend.dispatch_pdf(pdf_path, printer)
                output_path = None
                status = "queued"
            with self.database.write() as db:
                db.execute(
                    "UPDATE method_print_jobs SET status=?, output_path=?, updated_at=? WHERE id=?",
                    (status, str(output_path) if output_path else None, utc_now(), job_id),
                )
                self._audit(db, actor_user_id, "method.print", method_id, {"job_id": job_id, "version": version_number, "printer": printer, "status": status})
            return self.job(job_id)
        except Exception as exc:
            error_code = "print_dispatch_failed"
            with self.database.write() as db:
                db.execute(
                    "UPDATE method_print_jobs SET status='failed', error_code=?, error_message=?, updated_at=? WHERE id=?",
                    (error_code, str(exc), utc_now(), job_id),
                )
                self._audit(db, actor_user_id, "method.print", method_id, {"job_id": job_id, "version": version_number, "printer": printer, "status": "failed", "error_code": error_code})
            raise MethodDomainError(
                error_code,
                "打印调度失败，已保留渲染输入和 PDF",
                details={"job_id": job_id, "input_path": str(input_path), "pdf_path": str(pdf_path), "reason": str(exc)},
                status_code=502,
            ) from exc

    def job(self, job_id: str) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT * FROM method_print_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise MethodDomainError("print_job_not_found", "打印任务不存在", status_code=404)
            return dict(row)

    def jobs(self, method_id: int, limit: int = 50) -> list[dict[str, Any]]:
        self._snapshot(method_id, None)
        with self.database.read() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM method_print_jobs WHERE method_id=? ORDER BY created_at DESC LIMIT ?",
                    (method_id, limit),
                ).fetchall()
            ]

    @staticmethod
    def _validate_geometry(settings: MethodPrintSettings) -> None:
        MethodDocument._validate_geometry(PrintSettings(**settings.model_dump(mode="json")))

    _row = staticmethod(MethodDocument._row)

    def _document_rows(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        return self.document._document_rows(snapshot)

    @staticmethod
    def _paper(settings: MethodPrintSettings) -> tuple[float, float]:
        return MethodDocument._paper(PrintSettings(**settings.model_dump(mode="json")))

    def _paginate(self, rows: list[dict[str, str]], settings: MethodPrintSettings) -> dict[str, Any]:
        return self.document._paginate(rows, PrintSettings(**settings.model_dump(mode="json")))

    _html_lines = staticmethod(MethodRenderer._html_lines)

    def render_html(self, document: dict[str, Any]) -> str:
        return self.rendering.render_html(document)

    def render_pdf(self, document: dict[str, Any]) -> bytes:
        return self.rendering.render_pdf(document)

    def printers(self) -> list[dict[str, Any]]:
        return self.printer_backend.printers()


