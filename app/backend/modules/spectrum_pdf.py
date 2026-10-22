from __future__ import annotations
import hashlib
import io
from pathlib import Path
from typing import Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A3, LETTER, landscape, portrait
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


SPECTRUM_PDF_FONT = "GeoSpectrum-Spectrum-CJK"
_SPECTRUM_PDF_FONT_READY = False
_SPECTRUM_PDF_ACTIVE_FONT = SPECTRUM_PDF_FONT
_SPECTRUM_PDF_COLORS = ("#1c68b2", "#c75b39", "#27805d", "#8b5bb5", "#d18b22", "#247c8b", "#b54769", "#58677a")


def _spectrum_pdf_font() -> str:
    global _SPECTRUM_PDF_ACTIVE_FONT, _SPECTRUM_PDF_FONT_READY
    if _SPECTRUM_PDF_FONT_READY:
        return _SPECTRUM_PDF_ACTIVE_FONT
    for candidate in (
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ):
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(SPECTRUM_PDF_FONT, str(candidate), subfontIndex=0))
            _SPECTRUM_PDF_FONT_READY = True
            return SPECTRUM_PDF_FONT
        except Exception:
            continue
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _SPECTRUM_PDF_ACTIVE_FONT = "STSong-Light"
    _SPECTRUM_PDF_FONT_READY = True
    return _SPECTRUM_PDF_ACTIVE_FONT


def render_point_details_pdf(details: dict) -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    font = _spectrum_pdf_font()
    def header():
        pdf.setFont(font, 12)
        pdf.drawString(18 * mm, 280 * mm, "CCD 原始积分明细")
        pdf.setFont(font, 9)
        pdf.drawString(18 * mm, 271 * mm, f"{str(details['sample_name'])[:50]}  CCD {details['ccd_index'] + 1}  点 {details['point_index'] + 1}")
        pdf.drawString(18 * mm, 264 * mm, f"预激 {details['pre_excitation_seconds'] if details['pre_excitation_seconds'] is not None else '未记录'} 秒；燃烧 {details['burn_cycle_seconds']} 秒 × {details['burn_count']}；空白 {details['dark_cycle_seconds']} 秒 × {details['dark_count']}")
        pdf.drawString(18 * mm, 256 * mm, "阶段                 积分序号                 原始强度 ADC")
    header()
    y = 249 * mm
    for row in details["rows"]:
        if y < 20 * mm:
            pdf.showPage(); header(); y = 249 * mm
        pdf.drawString(18 * mm, y, f"{'燃烧' if row['phase'] == 'burn' else '空白'}                   {row['integration']}                          {row['value']}")
        y -= 6 * mm
    pdf.save()
    return output.getvalue()


def render_spectrum_pdf(curves, record_id, mode, ccd, line, reference_shift, visible_x_min, visible_x_max, visible_y_min, visible_y_max,
    *, layers=None, print_scale='fit_long', paper='A4', physical_width_mm=None) -> tuple[bytes, dict[str, Any]]:
    layers = layers if layers is not None else ['curve']
    width, height = (portrait if print_scale == 'fit_short' else landscape)({'A4': A4, 'A3': A3, 'Letter': LETTER}[paper])
    left, right = 18 * mm, width - 15 * mm
    bottom, top = 33 * mm, height - 45 * mm
    if physical_width_mm is not None:
        if physical_width_mm * mm > right - left:
            raise ValueError(f'十倍 CCD 需要 {physical_width_mm:.2f} mm，超过当前纸张可用宽度；请选择更大纸型或缩小当前图像范围')
        left = (width - physical_width_mm * mm) / 2
        right = left + physical_width_mm * mm
    grayscale_top = top
    if 'grayscale' in layers:
        top -= 25.4 * mm + 8 * mm
    plot_width, plot_height = right - left, top - bottom
    x_span = max(visible_x_max - visible_x_min, 1e-12)
    y_span = max(visible_y_max - visible_y_min, 1e-12)
    font = _spectrum_pdf_font()
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setTitle("GeoSpectrum - 当前可见谱图")
    pdf.setAuthor("GeoSpectrum")
    pdf.setFillColor(colors.HexColor("#245f9f"))
    pdf.setFont(font, 16)
    pdf.drawString(left, height - 18 * mm, "GeoSpectrum 谱图打印")
    pdf.setFillColor(colors.HexColor("#60758a"))
    pdf.setFont(font, 8.5)
    pdf.drawString(
        left, height - 25 * mm, f"记录 {record_id}  ·  模式 {mode}  ·  CCD {ccd + 1}  ·  谱线 {line + 1}"
    )
    pdf.drawString(
        left,
        height - 30 * mm,
        (
            f"可见范围 X {visible_x_min:.6g}–{visible_x_max:.6g}  ·  Y {visible_y_min:.6g}"
            f"–{visible_y_max:.6g}  ·  参考校正 {reference_shift:.6g}"
        ),
    )

    if 'curve' in layers:
        pdf.setFillColor(colors.HexColor("#fbfcfe"))
        pdf.rect(left, bottom, plot_width, plot_height, stroke=0, fill=1)
        pdf.setStrokeColor(colors.HexColor("#dce5ed"))
        pdf.setLineWidth(0.5)
        for step in range(6):
            ratio = step / 5
            grid_x = left + ratio * plot_width
            grid_y = bottom + ratio * plot_height
            pdf.line(grid_x, bottom, grid_x, top)
            pdf.line(left, grid_y, right, grid_y)
            pdf.setFillColor(colors.HexColor("#718599"))
            pdf.setFont("Helvetica", 7)
            pdf.drawCentredString(grid_x, bottom - 10, f"{visible_x_min + ratio * x_span:.4g}")
            pdf.drawRightString(left - 5, grid_y - 2, f"{visible_y_min + ratio * y_span:.4g}")
        pdf.setStrokeColor(colors.HexColor("#8195a8"))
        pdf.rect(left, bottom, plot_width, plot_height, stroke=1, fill=0)

    clip = pdf.beginPath()
    clip.rect(left, bottom, plot_width, plot_height)
    pdf.saveState()
    pdf.clipPath(clip, stroke=0, fill=0)
    visible_points = 0
    for curve in curves:
        path = pdf.beginPath()
        started = False
        for x, y in curve["points"]:
            if not visible_x_min <= x <= visible_x_max:
                continue
            px = left + ((x - visible_x_min) / x_span) * plot_width
            py = bottom + ((y - visible_y_min) / y_span) * plot_height
            if not started:
                path.moveTo(px, py)
                started = True
            else:
                path.lineTo(px, py)
            visible_points += 1
        if started and 'curve' in layers:
            pdf.setStrokeColor(colors.HexColor(curve["color"]))
            pdf.setLineWidth(1.6 if curve["priority"] else 0.8)
            pdf.drawPath(path, stroke=1, fill=0)
    pdf.restoreState()

    grayscale_max = None
    if 'grayscale' in layers:
        chosen = next((curve for curve in curves if curve['priority']), curves[0])
        values = [(x, y) for x, y in chosen['points'] if visible_x_min <= x <= visible_x_max]
        grayscale_max = max(5000, chosen.get('grayscale_max', max((y for _, y in chosen['points']), default=0)))
        pdf.saveState()
        strip = pdf.beginPath(); strip.rect(left, grayscale_top - 25.4 * mm, plot_width, 25.4 * mm)
        pdf.clipPath(strip, stroke=0, fill=0)
        for index, (x, value) in enumerate(values):
            next_x = values[index + 1][0] if index + 1 < len(values) else visible_x_max
            start = left + ((x - visible_x_min) / x_span) * plot_width
            end = left + ((next_x - visible_x_min) / x_span) * plot_width
            pdf.setFillGray(max(0, min(1, (255 - round(value * 255 / grayscale_max)) / 255)))
            pdf.rect(start, grayscale_top - 25.4 * mm, max(end - start, 0.1), 25.4 * mm, stroke=0, fill=1)
        pdf.restoreState()
        pdf.setFont(font, 7); pdf.setFillColor(colors.HexColor('#536a7f'))
        pdf.drawString(left, grayscale_top + 3 * mm, f"灰度谱带 · {chosen['label']}")

    legend_x, legend_y = left, 21 * mm
    pdf.setFont(font, 8)
    for curve in (curves if 'curve' in layers else []):
        pdf.setFillColor(colors.HexColor(curve["color"]))
        pdf.rect(legend_x, legend_y - 2, 9, 3, stroke=0, fill=1)
        pdf.setFillColor(colors.HexColor("#536a7f"))
        label = ("优先 · " if curve["priority"] else "") + curve["label"]
        pdf.drawString(legend_x + 13, legend_y - 4, label[:28])
        legend_x += min(150, 30 + len(label) * 7)
        if legend_x > right - 120:
            legend_x, legend_y = left, legend_y - 11
    pdf.setFillColor(colors.HexColor("#8494a3"))
    pdf.setFont(font, 7)
    pdf.drawRightString(right, 10 * mm, f"峰形 {len(curves) if 'curve' in layers else 0} · 灰度 {1 if 'grayscale' in layers else 0} · 可见点 {visible_points}")
    pdf.showPage()
    pdf.save()
    content = output.getvalue()
    return content, {
        "curve_count": len(curves),
        "visible_point_count": visible_points,
        "grayscale_max": grayscale_max,
        "sha256": hashlib.sha256(content).hexdigest(),
    }
