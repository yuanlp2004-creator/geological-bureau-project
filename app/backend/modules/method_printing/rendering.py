"""方法文档的 HTML/PDF 渲染与字体注册。"""

from __future__ import annotations

import html
import io
from pathlib import Path
from typing import Any
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from .settings import PrintSettings


FONT_NAME = "GeoSpectrum-CJK"


FONT_BOLD = "GeoSpectrum-CJK-Bold"


_FONT_READY = False


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


class MethodRenderer:

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
        settings = PrintSettings(**document["settings"])
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

