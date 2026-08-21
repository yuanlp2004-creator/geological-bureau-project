from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from ..db import Database, utc_now
from .method_printing import MethodPrintService, VIRTUAL_PDF_PRINTER


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _xml(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


class ReportError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status_code, self.details = code, message, status_code, details or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ReportService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("schema_json", "filter_json", "source_run_ids_json", "model_json", "report_json"):
            if key in item:
                item[key.removesuffix("_json")] = json.loads(item.pop(key) or ("{}" if key in {"schema_json", "filter_json", "model_json", "report_json"} else "[]"))
        for key in ("enabled",):
            if key in item:
                item[key] = bool(item[key])
        return item

    def templates(self) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._row_dict(row) for row in db.execute("SELECT * FROM report_templates WHERE enabled=1 ORDER BY name").fetchall()]

    def _template(self, db: Any, key: str) -> Any:
        row = db.execute("SELECT * FROM report_templates WHERE key=? AND enabled=1", (key,)).fetchone()
        if row is None:
            raise ReportError("report_template_not_found", "报告模板不存在", 404, {"template_key": key})
        return row

    def _build_model(self, db: Any, run_ids: list[int], arrangement: str, filters: dict[str, Any]) -> dict[str, Any]:
        if arrangement not in {"standard", "exchange"}:
            raise ReportError("report_arrangement_invalid", "报告排列必须为 standard 或 exchange")
        if not run_ids or len(run_ids) != len(set(run_ids)):
            raise ReportError("report_runs_invalid", "至少选择一个且不重复的分析运行")
        rows: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []
        sample_filter = str(filters.get("sample_name") or "").strip().lower()
        element_filter = str(filters.get("element") or "").strip().lower()
        for run_id in run_ids:
            run = db.execute("SELECT r.*, m.name AS method_name FROM analysis_runs r JOIN methods m ON m.id=r.method_id WHERE r.id=?", (run_id,)).fetchone()
            if run is None:
                raise ReportError("report_analysis_run_not_found", "分析运行不存在", 404, {"run_id": run_id})
            if run["status"] != "completed":
                raise ReportError("report_analysis_run_not_completed", "只能为已完成的分析运行建立报告", 409, {"run_id": run_id, "status": run["status"]})
            run_item = {"id": int(run["id"]), "name": run["name"], "status": run["status"], "method_name": run["method_name"], "method_version": int(run["method_version"]), "method_version_id": int(run["method_version_id"]), "calculation_profile": run["calculation_profile"], "result_sha256": run["result_sha256"]}
            runs.append(run_item)
            samples = db.execute("SELECT position, sample_name, result_sha256 FROM analysis_run_samples WHERE run_id=? ORDER BY position", (run_id,)).fetchall()
            qc = db.execute("SELECT publishable FROM analysis_qc_snapshots WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
            qc_status = "通过" if qc and bool(qc["publishable"]) else ("未通过" if qc else "未质控")
            merge = db.execute("SELECT * FROM analysis_result_merges WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
            if merge is None:
                raise ReportError("report_final_results_missing", "分析运行尚未保存最终曲线合并结果", 409, {"run_id": run_id})
            revision = db.execute("SELECT payload_json FROM method_versions WHERE id=?", (run["method_version_id"],)).fetchone()
            method_payload = json.loads(revision["payload_json"] or "{}") if revision else {}
            units = {str(item.get("id")): str(item.get("unit") or "") for item in method_payload.get("lines", []) if isinstance(item, dict)}
            merged_results = json.loads(merge["results_json"] or "[]")
            for sample in merged_results:
                sample_name = str(sample.get("sample_name") or f"样品 {sample.get('acquisition_task_id', '')}")
                if sample_filter and sample_filter not in str(sample_name).lower():
                    continue
                for value in sample.get("values", []):
                    if element_filter and element_filter not in str(value.get("element") or "").lower():
                        continue
                    line_id = str(value.get("line_id") or "")
                    rows.append({
                        "report_number": "", "sample_name": sample_name, "element": value.get("element"),
                        "wavelength_nm": float(value.get("wavelength_nm") or 0.0), "calculated_value": float(value["value"]),
                        "unit": units.get(line_id, ""), "curve_snapshot_id": int(value["curve_snapshot_id"]),
                        "calculation_profile": run["calculation_profile"], "qc_status": qc_status,
                        "analysis_run_id": int(run_id), "line_id": line_id, "merge_snapshot_id": int(merge["id"]),
                    })
        if not rows:
            raise ReportError("report_rows_empty", "筛选后没有可报告的分析结果")
        if arrangement == "standard":
            rows.sort(key=lambda item: (str(item["sample_name"]), str(item["element"]), float(item["wavelength_nm"])))
            columns = ["report_number", "sample_name", "element", "wavelength_nm", "calculated_value", "unit", "curve_snapshot_id", "calculation_profile", "qc_status"]
        else:
            rows.sort(key=lambda item: (str(item["element"]), float(item["wavelength_nm"]), str(item["sample_name"])))
            # Exchange arrangement changes the visible field order as well as row ordering.
            columns = ["report_number", "element", "wavelength_nm", "sample_name", "calculated_value", "unit", "curve_snapshot_id", "calculation_profile", "qc_status"]
        return {"columns": columns, "rows": rows, "runs": runs, "arrangement": arrangement, "filters": filters}

    def create(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        run_ids = [int(value) for value in payload.get("analysis_run_ids") or []]
        template_key = str(payload.get("template_key") or "analysis-standard")
        arrangement = str(payload.get("arrangement") or "standard")
        filters = payload.get("filters") or {}
        report_id = 0
        with self.database.write() as db:
            template = self._template(db, template_key)
            model = self._build_model(db, run_ids, arrangement, filters)
            requested = str(payload.get("report_number") or "").strip()
            if not requested:
                requested = f"RPT-{utc_now()[:10].replace('-', '')}-{int(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]) + 1:03d}"
            current = db.execute("SELECT COALESCE(MAX(version), 0) FROM reports WHERE report_number=?", (requested,)).fetchone()[0]
            version = int(current) + 1
            model["report_number"] = requested
            for row in model["rows"]:
                row["report_number"] = requested
            digest = _sha({"template": template["key"], "version": int(template["version"]), "model": model})
            now = utc_now()
            cursor = db.execute("INSERT INTO reports(report_number,version,template_id,source_run_ids_json,filter_json,arrangement,model_json,model_sha256,status,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?, 'draft',?,?,?)", (requested, version, template["id"], _json(run_ids), _json(filters), arrangement, _json(model), digest, actor_user_id, now, now))
            report_id = int(cursor.lastrowid)
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'report.create', 'report', ?, ?, ?)", (actor_user_id, report_id, _json({"report_number": requested, "version": version, "model_sha256": digest, "run_ids": run_ids}), now))
        return self.get(report_id)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [self._report_dict(row, include_model=False) for row in db.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)).fetchall()]

    @staticmethod
    def _report_dict(row: Any, include_model: bool = True) -> dict[str, Any]:
        item = dict(row)
        for key in ("source_run_ids_json", "filter_json"):
            item[key.removesuffix("_json")] = json.loads(item.pop(key) or ("[]" if key.startswith("source") else "{}"))
        if include_model:
            item["model"] = json.loads(item.pop("model_json") or "{}")
        else:
            item.pop("model_json", None)
        item["status"] = item["status"]
        return item

    def get(self, report_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            row = db.execute("SELECT r.*, t.key AS template_key, t.name AS template_name, t.version AS template_version FROM reports r JOIN report_templates t ON t.id=r.template_id WHERE r.id=?", (report_id,)).fetchone()
            if row is None:
                raise ReportError("report_not_found", "报告不存在", 404)
            return self._report_dict(row)

    def confirm(self, report_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            row = db.execute("SELECT status, model_sha256 FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise ReportError("report_not_found", "报告不存在", 404)
            if row["status"] == "draft":
                db.execute("UPDATE reports SET status='confirmed', updated_at=? WHERE id=?", (utc_now(), report_id))
                db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'report.confirm', 'report', ?, ?, ?)", (actor_user_id, report_id, _json({"model_sha256": row["model_sha256"]}), utc_now()))
            elif row["status"] not in {"confirmed", "published"}:
                raise ReportError("report_state_invalid", "报告当前状态不能确认", 409, {"status": row["status"]})
        return self.get(report_id)

    @staticmethod
    def _headers(model: dict[str, Any]) -> list[str]:
        labels = {
            "report_number": "报告编号",
            "sample_name": "样品名称",
            "element": "元素",
            "wavelength_nm": "波长 (nm)",
            "calculated_value": "分析结果",
            "unit": "单位",
            "curve_snapshot_id": "曲线快照",
            "calculation_profile": "计算档案",
            "qc_status": "质控状态",
        }
        return [labels[key] for key in model["columns"]]

    def _table(self, model: dict[str, Any]) -> list[list[Any]]:
        keys = model["columns"]
        return [self._headers(model)] + [[row.get(key) for key in keys] for row in model["rows"]]

    @staticmethod
    def _encode_table(table: list[list[Any]], fmt: str) -> tuple[bytes, str, str]:
        if fmt in {"txt", "csv"}:
            stream = io.StringIO(newline="")
            csv.writer(stream, delimiter="\t" if fmt == "txt" else ",", lineterminator="\n").writerows(table)
            return ("\ufeff" + stream.getvalue()).encode("utf-8"), ("text/plain; charset=utf-8" if fmt == "txt" else "text/csv; charset=utf-8"), (".txt" if fmt == "txt" else ".csv")
        parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<?mso-application progid="Excel.Sheet"?>', '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Report"><Table>']
        for row in table:
            parts.append("<Row>" + "".join(f'<Cell><Data ss:Type="{"Number" if isinstance(value, (int, float)) and not isinstance(value, bool) else "String"}">{_xml(value)}</Data></Cell>' for value in row) + "</Row>")
        parts.append("</Table></Worksheet></Workbook>")
        return "".join(parts).encode("utf-8"), "application/vnd.ms-excel", ".xls"

    def _pdf(self, report: dict[str, Any]) -> tuple[bytes, int]:
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=landscape(A4), pageCompression=1, invariant=1)
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light")); font = "STSong-Light"
        except Exception:
            font = "Helvetica"
        width, height = landscape(A4)
        rows = self._table(report["model"])
        page_count = 0
        data_rows = rows[1:]
        rows_per_page = 20
        for offset in range(0, len(data_rows), rows_per_page):
            page_count += 1
            pdf.setFont(font, 15); pdf.drawString(18 * mm, height - 18 * mm, f"分析报告 {report['report_number']} v{report['version']}")
            pdf.setFont(font, 8); pdf.setFillColor(colors.HexColor("#5b6b75")); pdf.drawString(18 * mm, height - 25 * mm, f"排列: {report['arrangement']} · 模板: {report.get('template_name', '分析结果报告')} · 方法/计算档案见表")
            y = height - 36 * mm; col_widths = [27, 26, 15, 20, 22, 14, 18, 28, 20]
            page_rows = [rows[0], *data_rows[offset:offset + rows_per_page]]
            for row_index, row in enumerate(page_rows):
                x = 18 * mm
                pdf.setFillColor(colors.HexColor("#eaf1f3") if row_index == 0 else colors.white); pdf.rect(x, y - 4 * mm, sum(col_widths) * mm, 7 * mm, fill=1, stroke=0)
                pdf.setFillColor(colors.HexColor("#20333f")); pdf.setFont(font, 7)
                for value, cell_width in zip(row, col_widths):
                    pdf.drawString(x + 1.5 * mm, y - 1.5 * mm, str(value if value is not None else "")[:22]); x += cell_width * mm
                y -= 7 * mm
            pdf.setFillColor(colors.HexColor("#7a8992")); pdf.drawString(18 * mm, 10 * mm, f"GeoSpectrum · SHA-256 {report['model_sha256']}")
            pdf.showPage()
        pdf.save()
        return output.getvalue(), page_count

    @staticmethod
    def _atomic(directory: Path, name: str, content: bytes, extension: str, strategy: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        safe = Path(name).name or "report"
        if not safe.lower().endswith(extension): safe += extension
        target = directory / safe
        if target.exists():
            if strategy == "error": raise ReportError("report_export_exists", "目标文件已存在", 409, {"path": str(target)})
            if strategy == "suffix":
                stem = target.stem; index = 2
                while (directory / f"{stem} ({index}){extension}").exists(): index += 1
                target = directory / f"{stem} ({index}){extension}"
        handle, tmp = tempfile.mkstemp(prefix=".report-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, target)
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
        return target

    def export(self, report_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        report = self.get(report_id)
        if report["status"] not in {"confirmed", "published"}:
            raise ReportError("report_not_confirmed", "请先预览并确认报告，再执行导出或打印", 409, {"status": report["status"]})
        fmt = str(payload.get("format") or "pdf")
        if fmt not in {"txt", "csv", "excel", "pdf", "print"}: raise ReportError("report_format_invalid", "报告格式无效")
        directory = Path(str(payload.get("output_directory") or "")).expanduser()
        if fmt != "print" and not str(directory): raise ReportError("report_output_directory_required", "必须提供输出目录")
        strategy = str(payload.get("same_name_strategy") or "suffix")
        if strategy not in {"suffix", "error", "overwrite"}: raise ReportError("report_same_name_strategy_invalid", "同名策略无效")
        if fmt in {"pdf", "print"}:
            content, pages = self._pdf(report); media, extension = "application/pdf", ".pdf"
        else:
            content, media, extension = self._encode_table(self._table(report["model"]), fmt); pages = 0
        path = None
        export_id = f"report-export-{uuid.uuid4().hex}"
        print_metadata: dict[str, Any] = {}
        if fmt != "print":
            path = self._atomic(directory, str(payload.get("filename") or f"{report['report_number']}-v{report['version']}"), content, extension, strategy)
        else:
            printer = str(payload.get("printer_name") or VIRTUAL_PDF_PRINTER)
            available = {item["name"]: item for item in MethodPrintService(self.database).printers()}
            if printer not in available:
                raise ReportError("printer_not_found", "选择的打印机不存在", 422, {"printer_name": printer})
            job_dir = self.database.path.parent / "print-jobs" / export_id
            job_dir.mkdir(parents=True, exist_ok=False)
            rendered = job_dir / "analysis-report.pdf"
            rendered.write_bytes(content)
            try:
                if printer == VIRTUAL_PDF_PRINTER:
                    output_dir = self.database.path.parent / "prints"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    path = output_dir / f"{report['report_number']}-v{report['version']}-{export_id[-8:]}.pdf"
                    shutil.copyfile(rendered, path)
                    dispatch_status = "completed"
                else:
                    MethodPrintService._dispatch_system_print(rendered, printer)
                    path = rendered
                    dispatch_status = "queued"
            except Exception as exc:
                now = utc_now()
                digest = hashlib.sha256(content).hexdigest()
                with self.database.write() as db:
                    db.execute("INSERT INTO report_exports(id,report_id,format,status,output_directory,requested_name,actual_path,same_name_strategy,content_sha256,byte_length,page_count,report_json,error_code,error_message,created_by,created_at,completed_at) VALUES (?,?,?,'failed',NULL,?,?,?, ?,?,?,?, ?,?,?,?,?)", (export_id, report_id, fmt, printer, str(rendered), strategy, digest, len(content), pages, _json({"printer_name": printer, "model_sha256": report["model_sha256"]}), "print_dispatch_failed", str(exc), actor_user_id, now, now))
                    db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'report.print', 'report', ?, ?, ?)", (actor_user_id, report_id, _json({"export_id": export_id, "printer_name": printer, "status": "failed", "error_code": "print_dispatch_failed"}), now))
                raise ReportError("print_dispatch_failed", "打印调度失败，已保留渲染输入和 PDF", 500, {"printer_name": printer, "pdf_path": str(rendered)}) from exc
            print_metadata = {"printer_name": printer, "dispatch_status": dispatch_status, "rendered_pdf_path": str(rendered)}
        digest = hashlib.sha256(content).hexdigest(); now = utc_now()
        with self.database.write() as db:
            db.execute("INSERT INTO report_exports(id,report_id,format,status,output_directory,requested_name,actual_path,same_name_strategy,content_sha256,byte_length,page_count,report_json,created_by,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (export_id, report_id, fmt, "completed", str(directory) if fmt != "print" else None, str(payload.get("filename") or payload.get("printer_name") or ""), str(path) if path else None, strategy, digest, len(content), pages, _json({"media_type": media, "columns": report["model"]["columns"], "row_count": len(report["model"]["rows"]), "arrangement": report["arrangement"], "model_sha256": report["model_sha256"], **print_metadata}), actor_user_id, now, now))
            action = "report.print" if fmt == "print" else "report.export"
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, ?, 'report', ?, ?, ?)", (actor_user_id, action, report_id, _json({"export_id": export_id, "format": fmt, "sha256": digest, "path": str(path) if path else None, "page_count": pages, **print_metadata}), now))
        return {"id": export_id, "report_id": report_id, "format": fmt, "status": "completed", "path": str(path) if path else None, "content_sha256": digest, "byte_length": len(content), "page_count": pages, "media_type": media, **print_metadata}

    def printers(self) -> list[dict[str, Any]]:
        return MethodPrintService(self.database).printers()

    def preview(self, report_id: int, actor_user_id: int | None = None) -> str:
        report = self.get(report_id)
        with self.database.write() as db:
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'report.preview', 'report', ?, ?, ?)", (actor_user_id, report_id, _json({"model_sha256": report["model_sha256"]}), utc_now()))
        table = self._table(report["model"])
        head = "".join(f"<th>{html.escape(str(value))}</th>" for value in table[0])
        body = "".join("<tr>" + "".join(f"<td>{html.escape(str(value if value is not None else ''))}</td>" for value in row) + "</tr>" for row in table[1:])
        return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{html.escape(report['report_number'])}</title><style>@page{{size:A4 landscape;margin:12mm}}body{{font-family:'Microsoft YaHei',sans-serif;color:#263d4d;margin:24px}}h1{{font-size:22px;border-bottom:2px solid #2b7d87;padding-bottom:10px}}small{{color:#71818d}}table{{width:100%;border-collapse:collapse;margin-top:16px}}th,td{{border-bottom:1px solid #dfe7eb;padding:7px;text-align:left;font-size:12px}}th{{background:#eaf1f3}}@media print{{body{{margin:0}}}}</style></head><body><h1>分析报告 {html.escape(report['report_number'])} v{report['version']}</h1><small>模板 {html.escape(str(report.get('template_name', '分析结果报告')))} · 排列 {html.escape(report['arrangement'])} · SHA-256 {report['model_sha256']}</small><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></body></html>"

    def exports(self, report_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute("SELECT * FROM report_exports WHERE report_id=? ORDER BY created_at DESC LIMIT ?", (report_id, max(1, min(int(limit), 200)))).fetchall()
            return [self._row_dict(row) for row in rows]
