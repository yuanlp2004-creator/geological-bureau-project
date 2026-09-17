from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import struct
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..db import Database


SPECTRUM_PDF_FONT = "GeoSpectrum-Spectrum-CJK"
_SPECTRUM_PDF_FONT_READY = False
_SPECTRUM_PDF_ACTIVE_FONT = SPECTRUM_PDF_FONT
_SPECTRUM_PDF_COLORS = ("#1c68b2", "#c75b39", "#27805d", "#8b5bb5", "#d18b22", "#247c8b", "#b54769", "#58677a")


def _spectrum_pdf_font() -> str:
    global _SPECTRUM_PDF_ACTIVE_FONT, _SPECTRUM_PDF_FONT_READY
    if _SPECTRUM_PDF_FONT_READY:
        return _SPECTRUM_PDF_ACTIVE_FONT
    for candidate in (Path("C:/Windows/Fonts/simhei.ttf"), Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")):
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


class SpectrumViewerError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 404, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _finite(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _wave(step: float, coefficients: list[float]) -> float | None:
    if len(coefficients) < 3:
        return None
    a, b, c = (float(item) for item in coefficients[:3])
    if not all(math.isfinite(item) for item in (a, b, c)) or a == 0 or b == 0 or c == 0:
        return None
    discriminant = b * b - 4.0 * a * (c - step)
    if discriminant < 0:
        return None
    return _finite((math.sqrt(discriminant) - b) / (2.0 * a))


class SpectrumViewerService:
    """Read-side query service for published S08/S09 spectrum records.

    The service never rewrites migration tables or recalculates analysis values.
    It exposes complete stored points for the selected CCD/line and loads raw
    acquisition frames only when explicitly requested by the viewer.
    """

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _record_id(kind: str, identifier: int) -> str:
        return f"{kind}:{identifier}"

    def list(self, *, kind: str = "all", limit: int = 100, angle_deg: float | None = None) -> list[dict[str, Any]]:
        if kind not in {"all", "raw", "result"}:
            raise SpectrumViewerError("spectrum_kind_invalid", "kind must be all, raw, or result", status_code=422)
        limit = max(1, min(int(limit), 200))
        records: list[dict[str, Any]] = []
        with self.database.read() as db:
            if kind in {"all", "raw"}:
                rows = db.execute(
                    "SELECT id, source_sha256, record_index, format, sample_no, sample_name, band_name, "
                    "long_name, measure_time, frame_count, ccd_count, points_per_ccd, mean_blob IS NOT NULL AS has_mean, "
                    "burn_adcs_blob IS NOT NULL AS has_burn, dark_adcs_blob IS NOT NULL AS has_dark, details_json "
                    "FROM spectrum_bands ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                for row in rows:
                    details = _json(row["details_json"], {})
                    record_angle = _finite(details.get("angle_deg"))
                    if angle_deg is not None and (record_angle is None or abs(record_angle - angle_deg) > 1e-6):
                        continue
                    records.append(
                        {
                            "id": self._record_id("raw", int(row["id"])),
                            "kind": "raw",
                            "source_sha256": row["source_sha256"],
                            "record_index": int(row["record_index"]),
                            "format": row["format"],
                            "sample_no": row["sample_no"],
                            "sample_name": row["sample_name"],
                            "band_name": row["band_name"] or row["long_name"],
                            "measure_time": row["measure_time"],
                            "angle_deg": record_angle,
                            "frame_count": int(row["frame_count"]),
                            "ccd_count": int(row["ccd_count"]),
                            "points_per_ccd": int(row["points_per_ccd"]),
                            "available": {"mean": bool(row["has_mean"]), "burn": bool(row["has_burn"]), "dark": bool(row["has_dark"])},
                        }
                    )
            if kind in {"all", "result"}:
                rows = db.execute(
                    "SELECT id, source_sha256, record_index, format, payload_json "
                    "FROM result_matrices ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                for row in rows:
                    payload = _json(row["payload_json"], {})
                    records.append(
                        {
                            "id": self._record_id("result", int(row["id"])),
                            "kind": "result",
                            "source_sha256": row["source_sha256"],
                            "record_index": int(row["record_index"]),
                            "format": row["format"],
                            "sample_name": (payload.get("sample_names") or [None])[0],
                            "sample_names": payload.get("sample_names") or [],
                            "band_name": None,
                            "measure_time": payload.get("measure_time"),
                            "line_count": int(payload.get("line_count") or 0),
                            "band_count": int(payload.get("band_count") or 0),
                            "sample_count": int(payload.get("sample_count") or 0),
                            "matrix_kind": payload.get("matrix_kind"),
                            "method_match_status": payload.get("method_match_status"),
                        }
                    )
        records.sort(key=lambda item: (item["kind"], -int(item["record_index"])), reverse=True)
        return records[:limit]

    def get(
        self,
        record_id: str,
        *,
        ccd: int = 0,
        line: int = 0,
        detail: str = "summary",
        phase: str = "burn",
        frame: int = 0,
        exposure_start: int | None = None,
        exposure_end: int | None = None,
    ) -> dict[str, Any]:
        try:
            kind, identifier_text = record_id.split(":", 1)
            identifier = int(identifier_text)
        except (ValueError, AttributeError):
            raise SpectrumViewerError("spectrum_record_invalid", "record id must be raw:<id> or result:<id>", status_code=422) from None
        if kind not in {"raw", "result"} or identifier <= 0:
            raise SpectrumViewerError("spectrum_record_invalid", "record id must be raw:<id> or result:<id>", status_code=422)
        if detail not in {"summary", "frame"}:
            raise SpectrumViewerError("spectrum_detail_invalid", "detail must be summary or frame", status_code=422)
        with self.database.read() as db:
            if kind == "raw":
                row = db.execute("SELECT * FROM spectrum_bands WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    raise SpectrumViewerError("spectrum_record_not_found", "Spectrum record was not found")
                return self._raw(row, ccd=ccd, detail=detail, phase=phase, frame=frame, exposure_start=exposure_start, exposure_end=exposure_end)
            row = db.execute("SELECT * FROM result_matrices WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise SpectrumViewerError("spectrum_record_not_found", "Result matrix was not found")
            return self._result(row, line=line)

    @staticmethod
    def _raw(
        row: Any,
        *,
        ccd: int,
        detail: str,
        phase: str,
        frame: int,
        exposure_start: int | None,
        exposure_end: int | None,
    ) -> dict[str, Any]:
        layout = _json(row["layout_json"], {})
        ignition = _json(row["ignition_json"], {})
        indices = [int(item) for item in layout.get("ccd_indices", [])]
        points_per_ccd = int(row["points_per_ccd"])
        ccd_count = int(row["ccd_count"])
        if not 0 <= ccd < ccd_count:
            raise SpectrumViewerError("spectrum_ccd_invalid", "CCD selection is outside the installed CCD range", status_code=422, details={"ccd_count": ccd_count})
        gaps = [float(item) for item in layout.get("gap_points", [])]
        coefficients = [float(item) for item in layout.get("ws_cof", [])]
        physical_index = indices[ccd] if ccd < len(indices) else ccd
        left_step = physical_index * points_per_ccd + sum(gaps[:physical_index])
        mean_blob = bytes(row["mean_blob"] or b"")
        expected_mean = ccd_count * points_per_ccd
        if mean_blob and len(mean_blob) != expected_mean * 4:
            raise SpectrumViewerError("spectrum_mean_shape_invalid", "Stored mean data does not match its CCD layout", status_code=500)
        mean_values: tuple[float, ...] = struct.unpack(f"<{expected_mean}f", mean_blob) if mean_blob else ()

        def points(values: list[float] | tuple[float, ...], *, include_adc: bool = False) -> list[dict[str, Any]]:
            result = []
            for point_index, value in enumerate(values):
                step = left_step + point_index
                item: dict[str, Any] = {
                    "point_index": point_index,
                    "step": step,
                    "wavelength_nm": _wave(step, coefficients),
                    "value": float(value),
                }
                if include_adc:
                    item["adc"] = int(value)
                result.append(item)
            return result

        selected = list(mean_values[ccd * points_per_ccd:(ccd + 1) * points_per_ccd]) if mean_values else []
        exposure_segment = None
        if exposure_start is not None or exposure_end is not None:
            if exposure_start is None or exposure_end is None:
                raise SpectrumViewerError("spectrum_exposure_invalid", "exposure_start and exposure_end must be provided together", status_code=422)
            burn_count = int(ignition.get("burn_count") or 0)
            if not 1 <= exposure_start <= exposure_end <= burn_count:
                raise SpectrumViewerError("spectrum_exposure_invalid", "Exposure interval is outside the stored burn frames", status_code=422, details={"burn_count": burn_count})
            burn_blob = bytes(row["burn_adcs_blob"] or b"")
            if len(burn_blob) != burn_count * expected_mean * 2:
                raise SpectrumViewerError("spectrum_frame_shape_invalid", "Stored raw frames do not match their layout", status_code=500)
            totals = [0.0] * points_per_ccd
            for exposure_index in range(exposure_start - 1, exposure_end):
                offset = (exposure_index * expected_mean + ccd * points_per_ccd) * 2
                values = struct.unpack_from(f"<{points_per_ccd}H", burn_blob, offset)
                for point_index, value in enumerate(values):
                    totals[point_index] += value
            divisor = exposure_end - exposure_start + 1
            selected = [value / divisor for value in totals]
            exposure_segment = {"start": exposure_start, "end": exposure_end, "count": divisor}
        details = _json(row["details_json"], {})
        result: dict[str, Any] = {
            "id": f"raw:{int(row['id'])}",
            "kind": "raw",
            "format": row["format"],
            "source_sha256": row["source_sha256"],
            "record_index": int(row["record_index"]),
            "sample_name": row["sample_name"],
            "sample_no": row["sample_no"],
            "band_name": row["band_name"] or row["long_name"],
            "measure_time": row["measure_time"],
            "reference_step": row["real_ref_step"],
            "angle_deg": _finite(details.get("angle_deg")),
            "exposure_segment": exposure_segment,
            "layout": {**layout, "ccd_indices": indices, "ccd_count": ccd_count, "points_per_ccd": points_per_ccd},
            "ignition": ignition,
            "bad_frame_indices": _json(row["bad_frame_indices_json"], []),
            "ccd": {"position": ccd, "index": physical_index, "points": points(selected)},
            "frame_detail": None,
        }
        if detail == "frame":
            if phase not in {"burn", "dark"}:
                raise SpectrumViewerError("spectrum_phase_invalid", "phase must be burn or dark", status_code=422)
            blob = bytes((row["burn_adcs_blob"] if phase == "burn" else row["dark_adcs_blob"]) or b"")
            count = int(ignition.get(f"{phase}_count") or 0)
            expected = count * expected_mean * 2
            if count <= 0 or not blob:
                raise SpectrumViewerError("spectrum_frame_unavailable", "The requested raw frame is not stored", status_code=404)
            if len(blob) != expected:
                raise SpectrumViewerError("spectrum_frame_shape_invalid", "Stored raw frames do not match their layout", status_code=500)
            if not 0 <= frame < count:
                raise SpectrumViewerError("spectrum_frame_invalid", "Frame selection is outside the available range", status_code=422, details={"frame_count": count})
            offset = (frame * expected_mean + ccd * points_per_ccd) * 2
            values = struct.unpack_from(f"<{points_per_ccd}H", blob, offset)
            result["frame_detail"] = {"phase": phase, "index": frame, "frame_count": count, "ccd": {"position": ccd, "index": physical_index, "points": points(list(values), include_adc=True)}}
        return result

    def export_csv(
        self,
        record_id: str,
        *,
        ccd: int = 0,
        line: int = 0,
        detail: str = "summary",
        phase: str = "burn",
        frame: int = 0,
        exposure_start: int | None = None,
        exposure_end: int | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        reference_shift: float = 0.0,
    ) -> tuple[bytes, str, int]:
        if (x_min is None) != (x_max is None) or (x_min is not None and x_max is not None and x_min > x_max):
            raise SpectrumViewerError("spectrum_visible_range_invalid", "x_min and x_max must form an ordered visible range", status_code=422)
        record = self.get(
            record_id,
            ccd=ccd,
            line=line,
            detail=detail,
            phase=phase,
            frame=frame,
            exposure_start=exposure_start,
            exposure_end=exposure_end,
        )
        if record["kind"] == "raw":
            source_points = (record.get("frame_detail") or {}).get("ccd", {}).get("points") or record["ccd"]["points"]
        else:
            source_points = record["line"]["points"]
        rows: list[dict[str, Any]] = []
        for point in source_points:
            x = point.get("wavelength_nm")
            if x is None:
                x = point.get("step", point.get("x", point["point_index"]))
            x = float(x) + (reference_shift if record["kind"] == "raw" else 0.0)
            if x_min is not None and x_max is not None and not x_min <= x <= x_max:
                continue
            rows.append({**point, "x": x})
        fieldnames = ["point_index", "x", "wavelength_nm", "step", "value", "adc", "peak", "back", "sample_index", "repeat_index", "sample_name"]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        content = ("\ufeff" + stream.getvalue()).encode("utf-8")
        return content, hashlib.sha256(content).hexdigest(), len(rows)

    def render_visible_pdf(
        self,
        record_id: str,
        *,
        selected_record_ids: list[str],
        ccd: int,
        line: int,
        mode: str,
        reference_shift: float,
        visible_x_min: float,
        visible_x_max: float,
        visible_y_min: float,
        visible_y_max: float,
        frame_phase: str = "burn",
        frame_index: int = 0,
        exposure_start: int | None = None,
        exposure_end: int | None = None,
        priority_record_id: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        if visible_x_min > visible_x_max or visible_y_min > visible_y_max:
            raise SpectrumViewerError("spectrum_visible_range_invalid", "Visible ranges must be ordered", status_code=422)
        if mode not in {"mean", "peak", "back", "value", "frame"}:
            raise SpectrumViewerError("spectrum_print_mode_invalid", "Print mode is not supported", status_code=422)
        if (exposure_start is None) != (exposure_end is None):
            raise SpectrumViewerError("spectrum_exposure_invalid", "Exposure interval must include both endpoints", status_code=422)

        ordered_ids = list(dict.fromkeys([record_id, *selected_record_ids]))[:8]
        curves: list[dict[str, Any]] = []
        for index, item_id in enumerate(ordered_ids):
            is_active = item_id == record_id
            detail = "frame" if is_active and mode == "frame" else "summary"
            item_exposure_start = exposure_start if detail == "summary" else None
            item_exposure_end = exposure_end if detail == "summary" else None
            try:
                record = self.get(
                    item_id,
                    ccd=ccd,
                    line=line,
                    detail=detail,
                    phase=frame_phase,
                    frame=frame_index,
                    exposure_start=item_exposure_start,
                    exposure_end=item_exposure_end,
                )
            except SpectrumViewerError as exc:
                if exc.code != "spectrum_ccd_invalid":
                    raise
                first = self.get(item_id, ccd=0, line=line, detail="summary", exposure_start=item_exposure_start, exposure_end=item_exposure_end)
                clipped_ccd = max(0, min(ccd, int(first.get("layout", {}).get("ccd_count") or 1) - 1))
                record = self.get(item_id, ccd=clipped_ccd, line=line, detail=detail, phase=frame_phase, frame=frame_index, exposure_start=item_exposure_start, exposure_end=item_exposure_end)

            if record["kind"] == "raw":
                source = (record.get("frame_detail") or {}).get("ccd", {}).get("points") or record["ccd"]["points"]
                label = record.get("sample_name") or record.get("band_name") or item_id
            else:
                source = record["line"]["points"]
                label = record["line"].get("element") or (record.get("sample_names") or [item_id])[0]
            points: list[tuple[float, float]] = []
            for point_index, point in enumerate(source):
                x = point.get("wavelength_nm")
                if x is None:
                    x = point.get("step", point.get("x", point_index))
                x = float(x) + (reference_shift if record["kind"] == "raw" else 0.0)
                if mode == "peak":
                    y = point.get("peak")
                elif mode == "back":
                    y = point.get("back")
                else:
                    y = point.get("value", point.get("peak", point.get("adc")))
                if y is not None and math.isfinite(x) and math.isfinite(float(y)):
                    points.append((x, float(y)))
            curves.append({"id": item_id, "label": str(label), "points": points, "color": _SPECTRUM_PDF_COLORS[index % len(_SPECTRUM_PDF_COLORS)], "priority": (priority_record_id or record_id) == item_id})

        width, height = landscape(A4)
        left, right = 18 * mm, width - 15 * mm
        bottom, top = 33 * mm, height - 45 * mm
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
        pdf.drawString(left, height - 25 * mm, f"记录 {record_id}  ·  模式 {mode}  ·  CCD {ccd + 1}  ·  谱线 {line + 1}")
        pdf.drawString(left, height - 30 * mm, f"可见范围 X {visible_x_min:.6g}–{visible_x_max:.6g}  ·  Y {visible_y_min:.6g}–{visible_y_max:.6g}  ·  参考校正 {reference_shift:.6g}")

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
            if started:
                pdf.setStrokeColor(colors.HexColor(curve["color"]))
                pdf.setLineWidth(1.6 if curve["priority"] else 0.8)
                pdf.drawPath(path, stroke=1, fill=0)
        pdf.restoreState()

        legend_x, legend_y = left, 21 * mm
        pdf.setFont(font, 8)
        for curve in curves:
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
        pdf.drawRightString(right, 10 * mm, f"曲线 {len(curves)} · 可见点 {visible_points}")
        pdf.showPage()
        pdf.save()
        content = output.getvalue()
        return content, {"curve_count": len(curves), "visible_point_count": visible_points, "sha256": hashlib.sha256(content).hexdigest()}

    @staticmethod
    def _result(row: Any, *, line: int) -> dict[str, Any]:
        payload = _json(row["payload_json"], {})
        line_count = int(payload.get("line_count") or 0)
        band_count = int(payload.get("band_count") or 0)
        if not 0 <= line < line_count:
            raise SpectrumViewerError("spectrum_line_invalid", "Line selection is outside the result matrix", status_code=422, details={"line_count": line_count})
        sample_rows = payload.get("sample_rows") or []
        lines = payload.get("lines") or []
        matrix = bytes(row["matrix_blob"] or b"")
        kind = payload.get("matrix_kind")
        expected = line_count * band_count * (8 if kind == "peak_back" else 4)
        if len(matrix) != expected:
            raise SpectrumViewerError("result_matrix_shape_invalid", "Stored result matrix does not match its metadata", status_code=500)
        points: list[dict[str, Any]] = []
        metadata = lines[line] if line < len(lines) else {"index": line}
        if kind == "peak_back":
            for point_index in range(band_count):
                peak, back = struct.unpack_from("<ff", matrix, (line * band_count + point_index) * 8)
                sample = sample_rows[point_index] if point_index < len(sample_rows) else {}
                points.append({"point_index": point_index, "x": point_index, "sample_index": sample.get("sample_index"), "repeat_index": sample.get("repeat_index"), "sample_name": sample.get("name"), "peak": float(peak), "back": float(back)})
        else:
            for point_index in range(band_count):
                (value,) = struct.unpack_from("<f", matrix, (line * band_count + point_index) * 4)
                sample = sample_rows[point_index] if point_index < len(sample_rows) else {}
                points.append({"point_index": point_index, "x": point_index, "sample_index": sample.get("sample_index"), "repeat_index": sample.get("repeat_index"), "sample_name": sample.get("name"), "value": float(value)})
        return {
            "id": f"result:{int(row['id'])}",
            "kind": "result",
            "format": row["format"],
            "source_sha256": row["source_sha256"],
            "record_index": int(row["record_index"]),
            "measure_time": payload.get("measure_time"),
            "sample_names": payload.get("sample_names") or [],
            "sample_reps": payload.get("sample_reps") or [],
            "sample_rows": sample_rows,
            "line_count": line_count,
            "band_count": band_count,
            "matrix_kind": kind,
            "matrix_order": payload.get("matrix_order"),
            "exposure_segments": payload.get("exposure_segments") or [],
            "line": {**metadata, "index": line, "points": points},
        }
