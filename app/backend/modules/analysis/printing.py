"""不可变曲线快照的预览、PDF 和打印记录。"""

from __future__ import annotations

import hashlib
import html
import io
from typing import Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from ...db import Database, utc_now
from .errors import AnalysisError
from .serialization import _json
from .repository import AnalysisRepository


_CURVE_FONT = "GeoSpectrum-Curve-CJK"

_CURVE_FONT_READY = False


def _curve_font() -> str:
    global _CURVE_FONT_READY
    if _CURVE_FONT_READY:
        return _CURVE_FONT
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        try:
            pdfmetrics.registerFont(TTFont(_CURVE_FONT, path))
            _CURVE_FONT_READY = True
            return _CURVE_FONT
        except (OSError, ValueError):
            continue
    return "Helvetica"


class CurvePrintingService:
    def __init__(self, database: Database, repository: AnalysisRepository):
        self.database = database
        self.repository = repository

    @staticmethod
    def _curve_preview_html(curve: dict[str, Any], mode: str) -> str:
        title = f"{curve['line_id']} · {curve['fit_mode']} / {curve['coordinate_type']}"
        diagnostics = curve["diagnostics"]
        if mode == "text":
            rows = "".join(
                f"<tr><td>{int(item['point_index']) + 1}</td><td>{html.escape(str(item['name']))}</td><td>{float(item['original_intensity']):.8g}</td><td>{float(item['adjusted_intensity']):.8g}</td><td>{float(item['standard_value']):.8g}</td><td>{float(item['calculated_value']):.8g}</td><td>{float(item['residual']):.5g}</td></tr>"
                for item in diagnostics["points"]
            )
            content = f"<table><thead><tr><th>#</th><th>标准点</th><th>原始强度</th><th>修正强度</th><th>标准值</th><th>计算值</th><th>残差</th></tr></thead><tbody>{rows}</tbody></table>"
        else:
            chart = curve["chart"]
            points = diagnostics["points"]
            all_x = [float(item["intensity"]) for item in chart] + [float(item["adjusted_intensity"]) for item in points]
            all_y = [float(item["value"]) for item in chart] + [float(item["standard_value"]) for item in points]
            min_x, max_x = min(all_x), max(all_x); min_y, max_y = min(all_y), max(all_y)
            span_x, span_y = max(max_x - min_x, 1e-12), max(max_y - min_y, 1e-12)
            polyline = " ".join(f"{40 + 820 * (float(item['intensity']) - min_x) / span_x:.2f},{300 - 260 * (float(item['value']) - min_y) / span_y:.2f}" for item in chart)
            circles = "".join(f"<circle cx='{40 + 820 * (float(item['adjusted_intensity']) - min_x) / span_x:.2f}' cy='{300 - 260 * (float(item['standard_value']) - min_y) / span_y:.2f}' r='5'/>" for item in points)
            content = f"<svg viewBox='0 0 900 340' role='img' aria-label='标准曲线'><rect x='40' y='40' width='820' height='260'/><polyline points='{polyline}'/>{circles}</svg>"
        return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>@page{{size:A4 landscape;margin:14mm}}*{{box-sizing:border-box}}body{{font-family:'Microsoft YaHei',sans-serif;color:#263d4d;margin:22px}}header{{border-bottom:2px solid #2b7d87;margin-bottom:18px;padding-bottom:10px}}h1{{font-size:22px;margin:0 0 5px}}small{{color:#71818d}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #dfe7eb;padding:8px;text-align:right}}th:nth-child(2),td:nth-child(2){{text-align:left}}svg{{width:100%;height:auto;background:#f8fafb}}svg rect{{fill:#fff;stroke:#9fb2bd}}polyline{{fill:none;stroke:#267d88;stroke-width:2.4}}circle{{fill:#ed8c4a;stroke:#fff;stroke-width:2}}footer{{margin-top:14px;color:#768590}}@media print{{body{{margin:0}}}}</style></head><body><header><h1>{html.escape(title)}</h1><small>曲线快照 #{curve['id']} · SHA-256 {curve['result_sha256']}</small></header>{content}<footer>相关系数 {diagnostics.get('correlation') if diagnostics.get('correlation') is not None else '—'} · RMSE {diagnostics['rmse']:.8g}</footer></body></html>"""

    def _curve_pdf(self, curve: dict[str, Any], mode: str) -> bytes:
        font = _curve_font()
        output = io.BytesIO()
        width, height = landscape(A4)
        pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1, invariant=1)
        pdf.setTitle(f"GeoSpectrum 标准曲线 {curve['line_id']}")
        pdf.setFont(font, 16); pdf.setFillColor(colors.HexColor("#245f69")); pdf.drawString(18 * mm, height - 18 * mm, "GeoSpectrum 标准曲线")
        pdf.setFont(font, 9); pdf.setFillColor(colors.HexColor("#637986")); pdf.drawString(18 * mm, height - 25 * mm, f"{curve['line_id']}  ·  {curve['fit_mode']} / {curve['coordinate_type']}  ·  快照 #{curve['id']}")
        if mode == "text":
            y = height - 38 * mm
            headers = ("#", "标准点", "原始强度", "修正强度", "标准值", "计算值", "残差")
            xs = (18, 31, 68, 105, 142, 177, 212)
            pdf.setFont(font, 8.5); pdf.setFillColor(colors.HexColor("#405969"))
            for x, label in zip(xs, headers, strict=True): pdf.drawString(x * mm, y, label)
            y -= 6 * mm
            for item in curve["diagnostics"]["points"]:
                values = (str(int(item["point_index"]) + 1), str(item["name"]), f"{item['original_intensity']:.8g}", f"{item['adjusted_intensity']:.8g}", f"{item['standard_value']:.8g}", f"{item['calculated_value']:.8g}", f"{item['residual']:.5g}")
                for x, value in zip(xs, values, strict=True): pdf.drawString(x * mm, y, value)
                y -= 6 * mm
        else:
            chart, points = curve["chart"], curve["diagnostics"]["points"]
            all_x = [float(item["intensity"]) for item in chart] + [float(item["adjusted_intensity"]) for item in points]
            all_y = [float(item["value"]) for item in chart] + [float(item["standard_value"]) for item in points]
            min_x, max_x, min_y, max_y = min(all_x), max(all_x), min(all_y), max(all_y)
            span_x, span_y = max(max_x - min_x, 1e-12), max(max_y - min_y, 1e-12)
            left, bottom, plot_width, plot_height = 24 * mm, 27 * mm, width - 44 * mm, height - 70 * mm
            pdf.setStrokeColor(colors.HexColor("#cad6dc")); pdf.rect(left, bottom, plot_width, plot_height)
            path = pdf.beginPath()
            for index, item in enumerate(chart):
                x = left + (float(item["intensity"]) - min_x) / span_x * plot_width; y = bottom + (float(item["value"]) - min_y) / span_y * plot_height
                path.moveTo(x, y) if index == 0 else path.lineTo(x, y)
            pdf.setStrokeColor(colors.HexColor("#267d88")); pdf.setLineWidth(1.4); pdf.drawPath(path, stroke=1)
            pdf.setFillColor(colors.HexColor("#ed8c4a"))
            for item in points:
                x = left + (float(item["adjusted_intensity"]) - min_x) / span_x * plot_width; y = bottom + (float(item["standard_value"]) - min_y) / span_y * plot_height
                pdf.circle(x, y, 2.2, stroke=0, fill=1)
        pdf.setFont(font, 7); pdf.setFillColor(colors.HexColor("#7e8e98")); pdf.drawString(18 * mm, 10 * mm, f"SHA-256 {curve['result_sha256']}")
        pdf.showPage(); pdf.save()
        return output.getvalue()

    def curve_preview(self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None = None) -> str:
        if mode not in {"image", "text"}:
            raise AnalysisError("analysis_curve_print_mode_invalid", "打印模式必须是 image 或 text", status_code=422)
        with self.database.write() as db:
            row = db.execute("SELECT * FROM analysis_curve_snapshots WHERE id=? AND run_id=?", (curve_snapshot_id, run_id)).fetchone()
            if row is None:
                raise AnalysisError("analysis_curve_snapshot_not_found", "曲线快照不存在", status_code=404)
            curve = self.repository._curve_row(row)
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.curve.preview", run_id, {"curve_snapshot_id": curve_snapshot_id, "mode": mode, "result_sha256": row["result_sha256"]})
        return self._curve_preview_html(curve, mode)

    def print_curve(self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None = None) -> tuple[bytes, dict[str, Any]]:
        if mode not in {"image", "text"}:
            raise AnalysisError("analysis_curve_print_mode_invalid", "打印模式必须是 image 或 text", status_code=422)
        with self.database.write() as db:
            row = db.execute("SELECT * FROM analysis_curve_snapshots WHERE id=? AND run_id=?", (curve_snapshot_id, run_id)).fetchone()
            if row is None:
                raise AnalysisError("analysis_curve_snapshot_not_found", "曲线快照不存在", status_code=404)
            content = self._curve_pdf(self.repository._curve_row(row), mode)
            digest = hashlib.sha256(content).hexdigest()
            cursor = db.execute(
                "INSERT INTO analysis_curve_print_jobs(run_id, curve_snapshot_id, mode, request_json, content_blob, content_sha256, byte_length, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, curve_snapshot_id, mode, _json({"mode": mode, "curve_result_sha256": row["result_sha256"]}), content, digest, len(content), self.repository._actor(db, actor_user_id), utc_now()),
            )
            job_id = int(cursor.lastrowid)
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.curve.print", run_id, {"print_job_id": job_id, "curve_snapshot_id": curve_snapshot_id, "mode": mode, "content_sha256": digest, "byte_length": len(content)})
        return content, {"job_id": job_id, "sha256": digest, "byte_length": len(content)}

