from __future__ import annotations
from .rendering import render_html
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import base64
import json
import shutil
import uuid
from ...file_exports import publish_export
from pathlib import Path
from typing import Any
from ...db import Database, utc_now
from ...services import AppService
from ...printing import SystemPrinters, VIRTUAL_PDF_PRINTER, PrintCancelled
from ..analysis import AnalysisService
from .rendering import _encode_table, _pdf, _table
from .values import ReportError, _json, _sha


def _display_analysis_value(value: float, places: int) -> str:
    number = Decimal(str(value))
    rounded = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return format(number, ".5E") if number and not rounded else format(rounded, "f")


class ReportService:
    def __init__(self, database: Database, *, printers: SystemPrinters, analysis: AnalysisService, results=None):
        self.database = database
        self.printer_backend = printers
        self.analysis = analysis
        self.results = results

    def legacy_sources(self) -> list[dict[str, Any]]:
        return self.results.report_sources() if self.results else []

    def _legacy_model(self, db, identifiers, arrangement, filters, unit):
        from ..result_migration import ResultMigrationError
        if not self.results or not identifiers or len(set(identifiers)) != len(identifiers):
            raise ReportError('report_dat_selection_invalid', '请选择不重复的 DAT 结果记录')
        unit = str(unit or '').strip()
        if arrangement not in {'standard', 'exchange'}:
            raise ReportError('report_arrangement_invalid', '报告排列无效')
        try:
            sources = self.results.report_inputs(db, identifiers)
        except ResultMigrationError as exc:
            raise ReportError(exc.code, exc.message, exc.status_code, exc.details) from exc
        rows = []
        for source in sources:
            payload = source['payload']
            for line_index, line in enumerate(payload['lines']):
                for index, sample in enumerate(payload['sample_rows']):
                    name, element = str(sample.get('name') or ''), str(line.get('element') or '')
                    if str(filters.get('sample_name') or '').lower() not in name.lower() or str(filters.get('element') or '').lower() not in element.lower():
                        continue
                    value = source['values'][line_index * payload['band_count'] + index]
                    digits = max(0, min(9, int(line.get('digits') or 0)))
                    rows.append({'sample_name': name, 'element': element, 'wavelength_nm': None,
                                 'calculated_value': value, 'display_value': format(Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP), 'f'),
                                 'decimal_places': digits, 'unit': unit, 'curve_snapshot_id': None,
                                 'calculation_profile': '旧 DAT 导入值', 'qc_status': '旧文件未提供',
                                 'legacy_result_id': source['id'], 'source_sha256': source['source_sha256']})
                    rows[-1]['sample_index']=index
        if not rows:
            raise ReportError('report_rows_empty', '筛选后没有可报告的 DAT 结果')
        order = ('sample_name', 'element') if arrangement == 'standard' else ('element', 'sample_name')
        rows.sort(key=lambda row: tuple(row[key] for key in order))
        return {'columns': ['report_number', *order, 'wavelength_nm', 'calculated_value', 'unit', 'curve_snapshot_id', 'calculation_profile', 'qc_status'],
                'rows': rows, 'runs': [], 'arrangement': arrangement, 'filters': filters, 'source_kind': 'legacy_dat',
                'analysis_times': [source['payload'].get('measure_time') for source in sources],
                'legacy_sources': [{key: source[key] for key in ('id', 'source_sha256', 'matrix_sha256')} for source in sources],
                'provenance_note': ('旧 DAT 不含方法、波长、单位和质控记录；'
                                    + ('单位由用户指定' if unit else '原文件未记录单位')
                                    + '，数值沿用原文件。')}


    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("schema_json", "filter_json", "source_run_ids_json", "model_json", "report_json"):
            if key in item:
                item[key.removesuffix("_json")] = json.loads(
                    item.pop(key)
                    or ("{}" if key in {"schema_json", "filter_json", "model_json", "report_json"} else "[]")
                )
        for key in ("enabled",):
            if key in item:
                item[key] = bool(item[key])
        return item

    def templates(self) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [
                self._row_dict(row)
                for row in db.execute("SELECT * FROM report_templates WHERE enabled=1 ORDER BY name").fetchall()
            ]

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
        inputs = self.analysis.bind_report_inputs(db)
        for run_id in run_ids:
            run = inputs.run(run_id)
            if run is None:
                raise ReportError("report_analysis_run_not_found", "分析运行不存在", 404, {"run_id": run_id})
            if run["status"] != "completed":
                raise ReportError(
                    "report_analysis_run_not_completed",
                    "只能为已完成的分析运行建立报告",
                    409,
                    {"run_id": run_id, "status": run["status"]},
                )
            run_item = {
                "id": int(run["id"]),
                "name": run["name"],
                "status": run["status"],
                "method_name": run["method_name"],
                "method_version": int(run["method_version"]),
                "method_version_id": int(run["method_version_id"]),
                "calculation_profile": run["calculation_profile"],
                "result_sha256": run["result_sha256"],
                'completed_at':run.get('completed_at') or run.get('created_at'),
            }
            runs.append(run_item)
            snapshot = inputs.latest_results(run_id)
            qc = snapshot.quality
            qc_status = "通过" if qc and bool(qc["publishable"]) else ("未通过" if qc else "未质控")
            if snapshot.merge_id is None:
                raise ReportError(
                    "report_final_results_missing", "分析运行尚未保存最终曲线合并结果", 409, {"run_id": run_id}
                )
            curve_ids = snapshot.curve_ids
            active_ids = snapshot.active_curve_ids
            curves = snapshot.curves
            if (
                not qc
                or not qc["publishable"]
                or not curves
                or set(curve_ids) != set(active_ids)
                or any(
                    curve is None or curve["run_id"] != run_id or curve["qc_snapshot_id"] != qc["id"]
                    for curve in curves
                )
            ):
                raise ReportError(
                    "report_results_stale",
                    "质控或已发布曲线已变化，请重新拟合、发布并合并结果后建立新报告",
                    409,
                    {"run_id": run_id},
                )
            run_item.update(
                qc_snapshot_id=int(qc["id"]), merge_snapshot_id=snapshot.merge_id, curve_snapshot_ids=curve_ids
            )
            method_payload = inputs.method_payload(run["method_version_id"])
            units = {
                str(item.get("id")): str(item.get("unit") or "")
                for item in method_payload.get("lines", [])
                if isinstance(item, dict)
            }
            decimal_places = {
                str(item.get("id")): int(item.get("decimal_places", 2)) for item in method_payload.get("lines", [])
            }
            merged_results = snapshot.rows()
            for sample in merged_results:
                sample_name = str(sample.get("sample_name") or f"样品 {sample.get('acquisition_task_id', '')}")
                if sample_filter and sample_filter not in str(sample_name).lower():
                    continue
                for value in sample.get("values", []):
                    if element_filter and element_filter not in str(value.get("element") or "").lower():
                        continue
                    line_id = str(value.get("line_id") or "")
                    rows.append(
                        {
                            "report_number": "",
                            "sample_name": sample_name,
                            'sample_id':sample.get('acquisition_task_id',sample_name),
                            "element": value.get("element"),
                            "wavelength_nm": float(value.get("wavelength_nm") or 0.0),
                            "calculated_value": float(value["value"]),
                            "decimal_places": decimal_places.get(line_id, 2),
                            "display_value": _display_analysis_value(value["value"], decimal_places.get(line_id, 2)),
                            "unit": units.get(line_id, ""),
                            "curve_snapshot_id": int(value["curve_snapshot_id"]),
                            "calculation_profile": run["calculation_profile"],
                            "qc_status": qc_status,
                            "analysis_run_id": int(run_id),
                            "line_id": line_id,
                            "merge_snapshot_id": snapshot.merge_id,
                            "qc_snapshot_id": int(qc["id"]),
                        }
                    )
        if not rows:
            raise ReportError("report_rows_empty", "筛选后没有可报告的分析结果")
        if arrangement == "standard":
            rows.sort(key=lambda item: (str(item["sample_name"]), str(item["element"]), float(item["wavelength_nm"])))
            columns = [
                "report_number",
                "sample_name",
                "element",
                "wavelength_nm",
                "calculated_value",
                "unit",
                "curve_snapshot_id",
                "calculation_profile",
                "qc_status",
            ]
        else:
            rows.sort(key=lambda item: (str(item["element"]), float(item["wavelength_nm"]), str(item["sample_name"])))
            # Exchange arrangement changes the visible field order as well as row ordering.
            columns = [
                "report_number",
                "element",
                "wavelength_nm",
                "sample_name",
                "calculated_value",
                "unit",
                "curve_snapshot_id",
                "calculation_profile",
                "qc_status",
            ]
        return {"columns": columns, "rows": rows, "runs": runs, "arrangement": arrangement, "filters": filters,
                'analysis_times':[run.get('completed_at') or run.get('created_at') for run in runs]}

    def create(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        run_ids = [int(value) for value in payload.get("analysis_run_ids") or []]
        template_key = str(payload.get("template_key") or "analysis-standard")
        arrangement = str(payload.get("arrangement") or "standard")
        filters = payload.get("filters") or {}
        report_id = 0
        with self.database.write() as db:
            template = self._template(db, template_key)
            legacy_ids = [int(value) for value in payload.get('legacy_result_ids') or []]
            if bool(run_ids) == bool(legacy_ids):
                raise ReportError('report_source_invalid', '请选择分析运行或旧 DAT 其中一种来源')
            model = self._legacy_model(db, legacy_ids, arrangement, filters, payload.get('legacy_unit')) if legacy_ids else self._build_model(db, run_ids, arrangement, filters)
            model['table_layout'] = payload.get('table_layout','legacy_matrix')
            requested = str(payload.get("report_number") or "").strip()
            if not requested:
                requested = f"RPT-{utc_now()[:10].replace('-', '')}-{int(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]) + 1:03d}"
            current = db.execute(
                "SELECT COALESCE(MAX(version), 0) FROM reports WHERE report_number=?", (requested,)
            ).fetchone()[0]
            version = int(current) + 1
            model["report_number"] = requested
            for row in model["rows"]:
                row["report_number"] = requested
            digest = _sha({"template": template["key"], "version": int(template["version"]), "model": model})
            now = utc_now()
            cursor = db.execute(
                (
                    "INSERT INTO reports(report_number,version,template_id,source_run_ids_json,filter"
                    "_json,arrangement,model_json,model_sha256,status,created_by,created_at,updated_a"
                    "t) VALUES (?,?,?,?,?,?,?,?, 'draft',?,?,?)"
                ),
                (
                    requested,
                    version,
                    template["id"],
                    _json(run_ids),
                    _json(filters),
                    arrangement,
                    _json(model),
                    digest,
                    actor_user_id,
                    now,
                    now,
                ),
            )
            report_id = int(cursor.lastrowid)
            db.execute(
                (
                    "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                    ",created_at) VALUES (?, 'report.create', 'report', ?, ?, ?)"
                ),
                (
                    actor_user_id,
                    report_id,
                    _json({"report_number": requested, "version": version, "model_sha256": digest, "run_ids": run_ids, 'legacy_result_ids': legacy_ids}),
                    now,
                ),
            )
        return self.get(report_id)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            return [
                self._report_dict(row, include_model=False)
                for row in db.execute(
                    "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),)
                ).fetchall()
            ]

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
            row = db.execute(
                (
                    "SELECT r.*, t.key AS template_key, t.name AS template_name, t.version AS "
                    "template_version FROM reports r JOIN report_templates t ON t.id=r.template_id "
                    "WHERE r.id=?"
                ),
                (report_id,),
            ).fetchone()
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
                db.execute(
                    (
                        "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                        ",created_at) VALUES (?, 'report.confirm', 'report', ?, ?, ?)"
                    ),
                    (actor_user_id, report_id, _json({"model_sha256": row["model_sha256"]}), utc_now()),
                )
            elif row["status"] not in {"confirmed", "published"}:
                raise ReportError("report_state_invalid", "报告当前状态不能确认", 409, {"status": row["status"]})
        return self.get(report_id)

    @staticmethod
    def _atomic(directory: Path, name: str, content: bytes, extension: str, strategy: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        safe = Path(name).name or "report"
        if not safe.lower().endswith(extension):
            safe += extension
        try:
            return publish_export(directory, safe, content, extension, strategy)
        except FileExistsError as exc:
            raise ReportError(
                "report_export_exists", "目标文件已存在", status_code=409, details={"path": str(directory / safe)}
            ) from exc

    def export(self, report_id: int, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        report = self.get(report_id)
        if report["status"] not in {"confirmed", "published"}:
            raise ReportError(
                "report_not_confirmed", "请先预览并确认报告，再执行导出或打印", 409, {"status": report["status"]}
            )
        fmt = str(payload.get("format") or "pdf")
        if fmt not in {"txt", "csv", "excel", "pdf", "print"}:
            raise ReportError("report_format_invalid", "报告格式无效")
        output_directory = str(payload.get("output_directory") or "")
        download = bool(payload.get('download')) and fmt != 'print'
        if fmt != "print" and not download and not output_directory.strip():
            raise ReportError("report_output_directory_required", "必须提供输出目录")
        directory = Path(output_directory).expanduser()
        strategy = str(payload.get("same_name_strategy") or "suffix")
        if strategy not in {"suffix", "error", "overwrite"}:
            raise ReportError("report_same_name_strategy_invalid", "同名策略无效")
        report['printing'] = AppService(self.database).get_settings()['printing']
        report['printed_at'] = utc_now()
        if fmt in {"pdf", "print"}:
            content, pages = _pdf(report)
            media, extension = "application/pdf", ".pdf"
        else:
            content, media, extension = _encode_table(_table(report["model"]), fmt)
            pages = 0
        path = None
        export_id = f"report-export-{uuid.uuid4().hex}"
        if download:
            digest = hashlib.sha256(content).hexdigest()
            with self.database.write() as db:
                db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'report.export.prepare', 'report', ?, ?, ?)",
                           (actor_user_id, report_id, _json({'format': fmt, 'sha256': digest, 'byte_length': len(content)}), utc_now()))
            return {'id': export_id, 'report_id': report_id, 'format': fmt, 'status': 'prepared', 'path': None,
                    'content_sha256': digest, 'byte_length': len(content), 'page_count': pages, 'media_type': media,
                    'filename': f"{report['report_number']}-v{report['version']}{extension}", 'content_base64': base64.b64encode(content).decode()}
        print_metadata: dict[str, Any] = {}
        if fmt != "print" and not download:
            path = self._atomic(
                directory,
                str(payload.get("filename") or f"{report['report_number']}-v{report['version']}"),
                content,
                extension,
                strategy,
            )
        elif fmt == 'print':
            printer = str(payload.get("printer_name") or report["printing"].get("default_printer") or "system")
            if printer in {"system", VIRTUAL_PDF_PRINTER}:
                printer = self.printer_backend.default_printer()
            available = {item["name"]: item for item in self.printer_backend.printers()}
            if printer not in available:
                raise ReportError("printer_not_found", "选择的打印机不存在", 422, {"printer_name": printer})
            job_dir = self.database.path.parent / "print-jobs" / export_id
            job_dir.mkdir(parents=True, exist_ok=False)
            rendered = job_dir / "analysis-report.pdf"
            rendered.write_bytes(content)
            try:
                self.printer_backend.dispatch_pdf(rendered, printer, report['printing'])
                path = rendered
                dispatch_status = "queued"
            except Exception as exc:
                error_code = "print_cancelled" if isinstance(exc, PrintCancelled) else "print_dispatch_failed"
                now = utc_now()
                digest = hashlib.sha256(content).hexdigest()
                with self.database.write() as db:
                    db.execute(
                        (
                            "INSERT INTO report_exports(id,report_id,format,status,output_directory,requested"
                            "_name,actual_path,same_name_strategy,content_sha256,byte_length,page_count,repor"
                            "t_json,error_code,error_message,created_by,created_at,completed_at) VALUES "
                            "(?,?,?,'failed',NULL,?,?,?, ?,?,?,?, ?,?,?,?,?)"
                        ),
                        (
                            export_id,
                            report_id,
                            fmt,
                            printer,
                            str(rendered),
                            strategy,
                            digest,
                            len(content),
                            pages,
                            _json({"printer_name": printer, "model_sha256": report["model_sha256"]}),
                            error_code,
                            str(exc),
                            actor_user_id,
                            now,
                            now,
                        ),
                    )
                    db.execute(
                        (
                            "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                            ",created_at) VALUES (?, 'report.print', 'report', ?, ?, ?)"
                        ),
                        (
                            actor_user_id,
                            report_id,
                            _json(
                                {
                                    "export_id": export_id,
                                    "printer_name": printer,
                                    "status": "failed",
                                    "error_code": error_code,
                                }
                            ),
                            now,
                        ),
                    )
                raise ReportError(
                    error_code,
                    "已取消 Windows 打印" if isinstance(exc, PrintCancelled) else "打印调度失败，已保留渲染输入和 PDF",
                    409 if isinstance(exc, PrintCancelled) else 500,
                    {"printer_name": printer, "pdf_path": str(rendered)},
                ) from exc
            print_metadata = {
                "printer_name": printer,
                "dispatch_status": dispatch_status,
                "rendered_pdf_path": str(rendered),
            }
        digest = hashlib.sha256(content).hexdigest()
        now = utc_now()
        with self.database.write() as db:
            db.execute(
                (
                    "INSERT INTO report_exports(id,report_id,format,status,output_directory,requested"
                    "_name,actual_path,same_name_strategy,content_sha256,byte_length,page_count,repor"
                    "t_json,created_by,created_at,completed_at) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    export_id,
                    report_id,
                    fmt,
                    "completed",
                    str(directory) if fmt != "print" else None,
                    str(payload.get("filename") or payload.get("printer_name") or ""),
                    str(path) if path else None,
                    strategy,
                    digest,
                    len(content),
                    pages,
                    _json(
                        {
                            "media_type": media,
                            "columns": report["model"]["columns"],
                            "row_count": len(report["model"]["rows"]),
                            "arrangement": report["arrangement"],
                            "model_sha256": report["model_sha256"],
                            **print_metadata,
                        }
                    ),
                    actor_user_id,
                    now,
                    now,
                ),
            )
            action = "report.print" if fmt == "print" else "report.export"
            db.execute(
                (
                    "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                    ",created_at) VALUES (?, ?, 'report', ?, ?, ?)"
                ),
                (
                    actor_user_id,
                    action,
                    report_id,
                    _json(
                        {
                            "export_id": export_id,
                            "format": fmt,
                            "sha256": digest,
                            "path": str(path) if path else None,
                            "page_count": pages,
                            **print_metadata,
                        }
                    ),
                    now,
                ),
            )
        return {
            "id": export_id,
            "report_id": report_id,
            "format": fmt,
            "status": "completed",
            "path": str(path) if path else None,
            "content_sha256": digest,
            "byte_length": len(content),
            "page_count": pages,
            "media_type": media,
            **print_metadata,
        }

    def printers(self) -> list[dict[str, Any]]:
        return self.printer_backend.printers()

    def preview(self, report_id: int, actor_user_id: int | None = None) -> str:
        report = self.get(report_id)
        report['printing'] = AppService(self.database).get_settings()['printing']
        report['printed_at'] = utc_now()
        with self.database.write() as db:
            db.execute(
                (
                    "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                    ",created_at) VALUES (?, 'report.preview', 'report', ?, ?, ?)"
                ),
                (actor_user_id, report_id, _json({"model_sha256": report["model_sha256"]}), utc_now()),
            )
        return render_html(report)

    def exports(self, report_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            rows = db.execute(
                "SELECT * FROM report_exports WHERE report_id=? ORDER BY created_at DESC LIMIT ?",
                (report_id, max(1, min(int(limit), 200))),
            ).fetchall()
            return [self._row_dict(row) for row in rows]
