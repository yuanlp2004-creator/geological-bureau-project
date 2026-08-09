from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..db import Database, utc_now
from ..schemas import MethodPrintSettings, SettingsPatch
from ..services import AppService
from .methods import MethodDomainError, MethodService, _json


PAPER_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "Letter": (215.9, 279.4),
}
VIRTUAL_PDF_PRINTER = "geospectrum-pdf"
FONT_NAME = "GeoSpectrum-CJK"
FONT_BOLD = "GeoSpectrum-CJK-Bold"
_FONT_READY = False

CONDITION_LABELS = (
    ("ccd_layout_id", "CCD 布局"),
    ("selected_ccds", "启用 CCD"),
    ("dispersion_calibration_id", "色散标定"),
    ("reference_wavelength_nm", "参考波长"),
    ("actual_reference_wavelength_nm", "实际参考波长"),
    ("reference_width_points", "参考线宽"),
    ("analysis_unit", "分析单位"),
    ("pre_excitation_seconds", "预激发时间"),
    ("sampling_period_seconds", "采样周期"),
    ("frame_count", "采集帧数"),
    ("dark_frame_count", "暗帧数"),
    ("sample_repeats", "样品重复次数"),
    ("standard_repeats", "标样重复次数"),
    ("control_repeats", "控制样重复次数"),
    ("standard_sample_name", "标准样品"),
    ("maximum_id_deviation", "最大 ID 偏差"),
    ("rsd_enabled", "RSD 检查"),
    ("rsd_threshold", "RSD 阈值"),
    ("calibration_threshold", "校准阈值"),
    ("qc_threshold", "质控阈值"),
    ("abnormal_threshold", "异常阈值"),
)

LINE_TYPE_LABELS = {
    "baseline": "参考基线",
    "analysis": "分析线",
    "internal_standard": "内标线",
    "alignment": "定位线",
}
PEAK_LABELS = {"maximum": "最大值", "gaussian": "高斯曲线"}
FIT_LABELS = {"linear": "直线", "quadratic": "二次", "cubic": "三次", "spline": "样条"}
INTERNAL_LABELS = {"none": "无内标", "background": "背景内标", "line": "普通内标线"}


def _display(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_display(item) for item in value)
    return str(value)


def _weighted_length(value: str) -> int:
    return sum(1 if ord(char) < 128 else 2 for char in value)


def _wrap(value: str, limit: int) -> list[str]:
    text = value or "-"
    result: list[str] = []
    current = ""
    units = 0
    for char in text:
        if char == "\n":
            result.append(current or " ")
            current, units = "", 0
            continue
        weight = 1 if ord(char) < 128 else 2
        if current and units + weight > limit:
            result.append(current)
            current, units = char, weight
        else:
            current += char
            units += weight
    if current or not result:
        result.append(current or " ")
    return result


def _register_font() -> tuple[str, str]:
    global _FONT_READY
    if _FONT_READY:
        return FONT_NAME, FONT_BOLD
    candidates = (
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    )
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(candidate), subfontIndex=0))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(candidate), subfontIndex=0))
            _FONT_READY = True
            return FONT_NAME, FONT_BOLD
        except Exception:
            continue
    # ReportLab's bundled CID font keeps Chinese output usable on systems
    # without a local CJK TrueType font.
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _FONT_READY = True
    return "STSong-Light", "STSong-Light"


class MethodPrintService:
    def __init__(self, database: Database):
        self.database = database
        self.methods = MethodService(database)
        self.app_service = AppService(database)

    def get_settings(self) -> dict[str, Any]:
        raw = self.app_service.get_settings()["printing"]
        if raw.get("default_printer") == "system":
            raw["default_printer"] = VIRTUAL_PDF_PRINTER
        return MethodPrintSettings.model_validate(raw).model_dump(mode="json")

    @staticmethod
    def _validate_geometry(settings: MethodPrintSettings) -> None:
        width, height = PAPER_MM[settings.paper]
        if settings.orientation == "landscape":
            width, height = height, width
        if settings.margin_left_mm + settings.margin_right_mm > width - 80:
            raise MethodDomainError(
                "print_margin_width_invalid",
                "左右边距过大，可打印宽度不足",
                fields=["margin_left_mm", "margin_right_mm"],
            )
        if settings.margin_top_mm + settings.margin_bottom_mm > height - 100:
            raise MethodDomainError(
                "print_margin_height_invalid",
                "上下边距过大，可打印高度不足",
                fields=["margin_top_mm", "margin_bottom_mm"],
            )

    def save_settings(self, settings: MethodPrintSettings, actor_user_id: int) -> dict[str, Any]:
        self._validate_geometry(settings)
        names = {item["name"] for item in self.printers()}
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

    @staticmethod
    def _system_printers() -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        try:
            import win32print  # type: ignore[import-not-found]

            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            rows = win32print.EnumPrinters(flags)
            default = win32print.GetDefaultPrinter()
            return [
                {
                    "name": row[2],
                    "display_name": row[2],
                    "virtual": False,
                    "system": True,
                    "default": row[2] == default,
                }
                for row in rows
                if row[2]
            ]
        except Exception:
            pass
        script = (
            "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
            "Get-CimInstance Win32_Printer | Select-Object Name,Default | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=True,
            )
            payload = json.loads(completed.stdout.lstrip("\ufeff") or "[]")
            rows = payload if isinstance(payload, list) else [payload]
            return [
                {
                    "name": row["Name"],
                    "display_name": row["Name"],
                    "virtual": False,
                    "system": True,
                    "default": bool(row.get("Default")),
                }
                for row in rows
                if isinstance(row, dict) and row.get("Name")
            ]
        except Exception:
            return []

    def printers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": VIRTUAL_PDF_PRINTER,
                "display_name": "GeoSpectrum PDF（虚拟打印机）",
                "virtual": True,
                "system": False,
                "default": True,
            },
            *self._system_printers(),
        ]

    def _snapshot(self, method_id: int, version: int | None) -> dict[str, Any]:
        with self.database.read() as db:
            method = db.execute(
                "SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)
            ).fetchone()
            if method is None:
                raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
            if version is None:
                revision = self.methods._latest_row(db, method_id)
            else:
                revision = db.execute(
                    "SELECT * FROM method_versions WHERE method_id=? AND version=?",
                    (method_id, version),
                ).fetchone()
            if revision is None:
                raise MethodDomainError(
                    "method_version_not_found", "方法版本不存在", fields=["version"], status_code=404
                )
            revision_dict = self.methods._version_dict(revision)
            assert revision_dict is not None
            return {
                "method": {
                    "id": method["id"],
                    "name": method["name"],
                    "description": method["description"],
                    "work_type": method["work_type"],
                    "status": method["status"],
                },
                "version": revision_dict,
            }

    @staticmethod
    def _row(kind: str, label: str, value: str = "") -> dict[str, str]:
        return {"kind": kind, "label": label, "value": value}

    def _document_rows(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        method = snapshot["method"]
        version = snapshot["version"]
        conditions = version["conditions"]
        lines = version["lines"]
        rows = [
            self._row("section", "方法概要"),
            self._row("item", "方法名称", method["name"]),
            self._row("item", "版本", f"v{version['version']} / {version['state']}"),
            self._row("item", "工作类型", method["work_type"]),
            self._row("item", "说明", method["description"] or "-"),
            self._row("item", "内容 SHA-256", version["content_sha256"]),
            self._row("item", "版本创建时间", str(version["created_at"])),
            self._row("section", "方法条件"),
        ]
        suffixes = {
            "reference_wavelength_nm": " nm",
            "actual_reference_wavelength_nm": " nm",
            "reference_width_points": " 点",
            "pre_excitation_seconds": " s",
            "sampling_period_seconds": " s",
            "maximum_id_deviation": " %",
            "rsd_threshold": " %",
            "calibration_threshold": " %",
            "qc_threshold": " %",
            "abnormal_threshold": " %",
        }
        for key, label in CONDITION_LABELS:
            rows.append(self._row("item", label, _display(conditions.get(key)) + suffixes.get(key, "")))
        rows.append(self._row("section", "分角度曝光"))
        for index, exposure in enumerate(conditions.get("angle_exposures", []), start=1):
            rows.append(
                self._row(
                    "item",
                    f"角度 {index}",
                    f"{_display(exposure.get('angle_deg'))}° / {exposure.get('storage_mode')} / "
                    f"帧 {exposure.get('start_frame')}-{exposure.get('end_frame')}",
                )
            )
        by_id = {
            line.get("id"): f"{line.get('element')} {float(line.get('wavelength_nm', 0)):.4f} nm"
            for line in lines
        }
        rows.append(self._row("section", f"分析谱线（{len(lines)} 条）"))
        for index, line in enumerate(lines, start=1):
            references = []
            for label, key in (
                ("背景", "background_line_id"),
                ("定位", "alignment_line_id"),
                ("内标", "internal_standard_line_id"),
            ):
                if line.get(key):
                    references.append(f"{label}={by_id.get(line[key], line[key])}")
            value = (
                f"{LINE_TYPE_LABELS.get(line.get('line_type'), line.get('line_type'))}; "
                f"实际 {float(line.get('actual_wavelength_nm', line.get('wavelength_nm', 0))):.4f} nm; "
                f"启用={_display(line.get('enabled'))}; 关键={_display(line.get('critical_band'))}; "
                f"优先级={line.get('priority')}; 扫描={line.get('scan_width_points')}点; "
                f"背景偏移={line.get('background_offset_points')}点; "
                f"峰值={PEAK_LABELS.get(line.get('peak_mode'), line.get('peak_mode'))}/{line.get('peak_width_points')}点; "
                f"拟合={FIT_LABELS.get(line.get('fit_mode'), line.get('fit_mode'))}/{line.get('coordinate_type')}; "
                f"内标方式={INTERNAL_LABELS.get(line.get('internal_standard_mode'), line.get('internal_standard_mode'))}; "
                f"结果={line.get('value_kind')} {line.get('unit')} / {line.get('decimal_places')}位; "
                f"有效范围={line.get('valid_range_min')}-{line.get('valid_range_max')}; "
                f"超限容差={line.get('over_limit_tolerance_percent')}%"
            )
            if references:
                value += "; " + "; ".join(references)
            rows.append(
                self._row(
                    "item",
                    f"{index}. {line.get('element')} {float(line.get('wavelength_nm', 0)):.4f} nm",
                    value,
                )
            )
        standard_count = sum(len(line.get("standard_points", [])) for line in lines)
        rows.append(self._row("section", f"标准点（{standard_count} 个）"))
        for line in lines:
            for point_index, point in enumerate(line.get("standard_points", []), start=1):
                rows.append(
                    self._row(
                        "item",
                        f"{line.get('element')} / {point.get('name') or f'S{point_index}'}",
                        f"{point.get('value')} {line.get('unit')} / 启用={_display(point.get('active'))}",
                    )
                )
        issues = version.get("validation_errors", [])
        if issues:
            rows.append(self._row("section", f"草稿验证问题（{len(issues)} 项）"))
            for issue in issues:
                rows.append(self._row("item", issue.get("field", "-"), f"{issue.get('code')}: {issue.get('message')}"))
        return rows

    @staticmethod
    def _paper(settings: MethodPrintSettings) -> tuple[float, float]:
        width, height = PAPER_MM[settings.paper]
        return (height, width) if settings.orientation == "landscape" else (width, height)

    def _paginate(self, rows: list[dict[str, str]], settings: MethodPrintSettings) -> dict[str, Any]:
        width_mm, height_mm = self._paper(settings)
        usable_pt = (height_mm - settings.margin_top_mm - settings.margin_bottom_mm) * mm - 52
        line_height = settings.font_size_pt * (1.28 if settings.layout == "compact" else 1.48)
        capacity = max(12, int(usable_pt // line_height))
        value_limit = int((width_mm - settings.margin_left_mm - settings.margin_right_mm) * (0.46 if settings.layout == "compact" else 0.40))
        label_limit = max(18, int(value_limit * 0.42))
        value_limit = max(42, value_limit)
        prepared = []
        for row in rows:
            if row["kind"] == "section":
                prepared.append({**row, "label_lines": [row["label"]], "value_lines": [], "units": 2})
            else:
                labels = _wrap(row["label"], label_limit)
                values = _wrap(row["value"], value_limit)
                prepared.append({**row, "label_lines": labels, "value_lines": values, "units": max(len(labels), len(values)) + 1})
        pages: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        used = 0
        for index, row in enumerate(prepared):
            units = row["units"]
            if row["kind"] == "section" and current and used + units + (prepared[index + 1]["units"] if index + 1 < len(prepared) else 0) > capacity:
                pages.append(current)
                current, used = [], 0
            elif current and used + units > capacity:
                pages.append(current)
                current, used = [], 0
            current.append(row)
            used += units
        if current:
            pages.append(current)
        return {
            "pages": pages,
            "page_count": len(pages),
            "field_count": sum(1 for row in rows if row["kind"] == "item"),
            "line_height": line_height,
            "width_mm": width_mm,
            "height_mm": height_mm,
        }

    def prepare(self, method_id: int, version: int | None, settings: MethodPrintSettings | None = None) -> dict[str, Any]:
        applied = settings or MethodPrintSettings.model_validate(self.get_settings())
        self._validate_geometry(applied)
        snapshot = self._snapshot(method_id, version)
        rows = self._document_rows(snapshot)
        layout = self._paginate(rows, applied)
        return {"snapshot": snapshot, "rows": rows, "settings": applied.model_dump(mode="json"), **layout}

    @staticmethod
    def _html_lines(lines: list[str]) -> str:
        return "<br>".join(html.escape(line) for line in lines)

    def render_html(self, document: dict[str, Any]) -> str:
        settings = document["settings"]
        method = document["snapshot"]["method"]
        version = document["snapshot"]["version"]
        pages_html = []
        for page_index, rows in enumerate(document["pages"], start=1):
            body = []
            for row in rows:
                if row["kind"] == "section":
                    body.append(f'<div class="section-title">{html.escape(row["label"])}</div>')
                else:
                    body.append(
                        '<div class="preview-row">'
                        f'<div class="preview-label">{self._html_lines(row["label_lines"])}</div>'
                        f'<div class="preview-value">{self._html_lines(row["value_lines"])}</div>'
                        "</div>"
                    )
            pages_html.append(
                f'<article class="preview-page" data-page="{page_index}" style="width:{document["width_mm"]}mm;height:{document["height_mm"]}mm;padding:{settings["margin_top_mm"]}mm {settings["margin_right_mm"]}mm {settings["margin_bottom_mm"]}mm {settings["margin_left_mm"]}mm">'
                '<header><span>GEOSPECTRUM / METHOD PARAMETERS</span>'
                f'<strong>{html.escape(method["name"])}</strong><small>v{version["version"]} · {version["state"]}</small></header>'
                f'<main>{"".join(body)}</main>'
                f'<footer><span>SHA-256 {version["content_sha256"][:16]}</span><span>{page_index} / {document["page_count"]}</span></footer>'
                "</article>"
            )
        orientation = settings["orientation"]
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(method['name'])} - 方法参数预览</title>
<style>
@page {{ size: {settings['paper']} {orientation}; margin: 0; }}
* {{ box-sizing: border-box; }} body {{ margin:0; padding:18px; background:#e9eef3; color:#33495f; font-family:'Microsoft YaHei','Noto Sans CJK SC',sans-serif; font-size:{settings['font_size_pt']}pt; }}
.preview-page {{ position:relative; margin:0 auto 18px; overflow:hidden; background:white; box-shadow:0 8px 28px rgba(35,55,76,.14); page-break-after:always; }}
header {{ height:15mm; display:grid; grid-template-columns:1fr auto; align-items:end; padding-bottom:3mm; border-bottom:1px solid #aac1d8; }} header span {{ grid-column:1/-1; color:#2d73c8; font-size:7pt; letter-spacing:.12em; }} header strong {{ font-size:15pt; }} header small {{ color:#778a9c; }}
main {{ padding-top:3mm; }} .section-title {{ margin-top:2mm; padding:1.5mm 2mm; color:#245f9f; background:#eaf3fc; border-left:1.2mm solid #347bd1; font-weight:700; }}
.preview-row {{ display:grid; grid-template-columns:28% 72%; border-bottom:1px solid #e8edf2; page-break-inside:avoid; }} .preview-label,.preview-value {{ padding:1.2mm 2mm; line-height:1.42; }} .preview-label {{ color:#60758a; background:#f8fafc; font-weight:600; }}
footer {{ position:absolute; left:{settings['margin_left_mm']}mm; right:{settings['margin_right_mm']}mm; bottom:{max(3, settings['margin_bottom_mm']-6)}mm; display:flex; justify-content:space-between; padding-top:2mm; color:#8494a3; border-top:1px solid #dfe7ee; font-size:7pt; }}
@media print {{ body {{ padding:0; background:white; }} .preview-page {{ margin:0; box-shadow:none; }} }}
</style></head><body data-page-count="{document['page_count']}" data-field-count="{document['field_count']}">{''.join(pages_html)}</body></html>"""

    def render_pdf(self, document: dict[str, Any]) -> bytes:
        regular_font, bold_font = _register_font()
        settings = MethodPrintSettings.model_validate(document["settings"])
        width_mm, height_mm = document["width_mm"], document["height_mm"]
        page_size = (width_mm * mm, height_mm * mm)
        output = io.BytesIO()
        pdf = canvas.Canvas(output, pagesize=page_size, pageCompression=1)
        method = document["snapshot"]["method"]
        version = document["snapshot"]["version"]
        pdf.setTitle(f"{method['name']} - 方法参数")
        pdf.setAuthor("GeoSpectrum")
        pdf.setSubject(f"方法 {method['name']} v{version['version']}")
        left = settings.margin_left_mm * mm
        right = page_size[0] - settings.margin_right_mm * mm
        top = page_size[1] - settings.margin_top_mm * mm
        bottom = settings.margin_bottom_mm * mm
        label_width = (right - left) * 0.28
        line_height = document["line_height"]
        for page_index, rows in enumerate(document["pages"], start=1):
            pdf.setFillColor(colors.HexColor("#2d73c8"))
            pdf.setFont(bold_font, 7)
            pdf.drawString(left, top, "GEOSPECTRUM / METHOD PARAMETERS")
            pdf.setFillColor(colors.HexColor("#273f56"))
            pdf.setFont(bold_font, 15)
            pdf.drawString(left, top - 19, method["name"])
            pdf.setFont(regular_font, 8)
            state_text = f"v{version['version']} / {version['state']}"
            pdf.drawRightString(right, top - 17, state_text)
            pdf.setStrokeColor(colors.HexColor("#aac1d8"))
            pdf.line(left, top - 27, right, top - 27)
            y = top - 37
            alternate = False
            for row in rows:
                height = row["units"] * line_height
                if row["kind"] == "section":
                    pdf.setFillColor(colors.HexColor("#eaf3fc"))
                    pdf.rect(left, y - height + 2, right - left, height - 2, stroke=0, fill=1)
                    pdf.setFillColor(colors.HexColor("#347bd1"))
                    pdf.rect(left, y - height + 2, 4, height - 2, stroke=0, fill=1)
                    pdf.setFont(bold_font, settings.font_size_pt)
                    pdf.setFillColor(colors.HexColor("#245f9f"))
                    pdf.drawString(left + 8, y - line_height, row["label"])
                else:
                    if alternate:
                        pdf.setFillColor(colors.HexColor("#fafcfd"))
                        pdf.rect(left, y - height, right - left, height, stroke=0, fill=1)
                    pdf.setStrokeColor(colors.HexColor("#e5ebf0"))
                    pdf.line(left, y - height, right, y - height)
                    pdf.setFont(bold_font, settings.font_size_pt - 0.5)
                    pdf.setFillColor(colors.HexColor("#60758a"))
                    for line_index, text in enumerate(row["label_lines"]):
                        pdf.drawString(left + 6, y - line_height * (line_index + 1), text)
                    pdf.setFont(regular_font, settings.font_size_pt - 0.5)
                    pdf.setFillColor(colors.HexColor("#33495f"))
                    for line_index, text in enumerate(row["value_lines"]):
                        pdf.drawString(left + label_width + 6, y - line_height * (line_index + 1), text)
                    alternate = not alternate
                y -= height
            pdf.setStrokeColor(colors.HexColor("#dfe7ee"))
            pdf.line(left, bottom + 12, right, bottom + 12)
            pdf.setFillColor(colors.HexColor("#8091a1"))
            pdf.setFont(regular_font, 7)
            pdf.drawString(left, bottom + 2, f"SHA-256 {version['content_sha256'][:16]}")
            pdf.drawRightString(right, bottom + 2, f"{page_index} / {document['page_count']}")
            pdf.showPage()
        pdf.save()
        return output.getvalue()

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
        return self.render_html(document), document

    def pdf(self, method_id: int, version: int | None, settings: MethodPrintSettings | None, actor_user_id: int) -> tuple[bytes, dict[str, Any]]:
        document = self.prepare(method_id, version, settings)
        result = self.render_pdf(document)
        with self.database.write() as db:
            self._audit(db, actor_user_id, "method.pdf.export", method_id, {"version": document["snapshot"]["version"]["version"], "page_count": document["page_count"], "bytes": len(result)})
        return result, document

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .")
        return cleaned[:80] or "method"

    @staticmethod
    def _dispatch_system_print(pdf_path: Path, printer_name: str) -> None:
        if os.name != "nt":
            raise RuntimeError("当前系统不支持 Windows 打印调度")
        try:
            import win32api  # type: ignore[import-not-found]

            result = win32api.ShellExecute(0, "printto", str(pdf_path), f'"{printer_name}"', str(pdf_path.parent), 0)
            if result <= 32:
                raise RuntimeError(f"ShellExecute printto failed: {result}")
            return
        except ImportError as exc:
            raise RuntimeError("缺少 pywin32，无法调度系统打印机") from exc

    def print_method(self, method_id: int, version: int | None, settings: MethodPrintSettings | None, printer_name: str | None, actor_user_id: int) -> dict[str, Any]:
        document = self.prepare(method_id, version, settings)
        applied = document["settings"]
        printer = printer_name or applied["default_printer"]
        available = {item["name"]: item for item in self.printers()}
        if printer not in available:
            raise MethodDomainError("printer_not_found", "选择的打印机不存在", fields=["printer_name"])
        pdf_bytes = self.render_pdf(document)
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
                self._dispatch_system_print(pdf_path, printer)
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
