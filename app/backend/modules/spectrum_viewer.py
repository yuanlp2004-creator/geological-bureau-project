from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import struct
from typing import Any


from ..db import Database
from .spectrum_pdf import render_spectrum_pdf, _SPECTRUM_PDF_COLORS


def point_details_text(details: dict, orientation: str) -> str:
    """Clipboard export uses the same verified raw values as the detail view and PDF."""
    header = f"{details['sample_name']}\tCCD{details['ccd_index'] + 1}\t点{details['point_index'] + 1}\t{details.get('wavelength_nm') or ''}"
    if orientation == 'vertical':
        return '\n'.join([header, '阶段\t积分序号\t原始强度 ADC',
            *[f"{'燃烧' if row['phase'] == 'burn' else '空白'}\t{row['integration']}\t{row['value']}" for row in details['rows']]])
    if orientation == 'horizontal':
        return '\t'.join([header,
            *[f"{'燃烧' if row['phase'] == 'burn' else '空白'}{row['integration']}\t{row['value']}" for row in details['rows']]])
    raise SpectrumViewerError('spectrum_copy_orientation_invalid', '复制方向无效', status_code=422)


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

    def list(
        self, *, kind: str = "all", limit: int = 100, angle_deg: float | None = None, offset: int = 0, query: str = ""
    ) -> list[dict[str, Any]]:
        if kind not in {"all", "raw", "result", "sample"}:
            raise SpectrumViewerError("spectrum_kind_invalid", "kind must be all, raw, or result", status_code=422)
        limit = max(1, min(int(limit), 200))
        records: list[dict[str, Any]] = []
        with self.database.read() as db:
            if kind in {"all", "raw"}:
                rows = db.execute(
                    "SELECT id, source_sha256, record_index, format, sample_no, sample_name, band_name, "
                    "long_name, measure_time, frame_count, ccd_count, points_per_ccd, mean_blob IS NOT NULL AS has_mean, "
                    "burn_adcs_blob IS NOT NULL AS has_burn, dark_adcs_blob IS NOT NULL AS has_dark, details_json "
                    "FROM spectrum_bands ORDER BY id DESC",
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
                            "available": {
                                "mean": bool(row["has_mean"]),
                                "burn": bool(row["has_burn"]),
                                "dark": bool(row["has_dark"]),
                            },
                        }
                    )
            if kind in {"all", "result"}:
                rows = db.execute(
                    "SELECT id, source_sha256, record_index, format, payload_json "
                    "FROM result_matrices ORDER BY id DESC",
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
        if kind in {"all", "sample"}:
            from .acquisition import AcquisitionService

            for sample in AcquisitionService(self.database).spectrum_records():
                records.append(
                    {
                        "id": f"sample:{sample['id']}",
                        "kind": "sample",
                        "format": "acquisition",
                        "source_sha256": sample["result_sha256"],
                        "record_index": sample["id"],
                        "sample_name": sample["sample_name"],
                        "band_name": None,
                        "measure_time": sample["completed_at"],
                        "angle_deg": None,
                        "frame_count": json.loads(sample["simulator_json"] or "{}").get(
                            "source_frame_count", sample["burn_frame_count"]
                        ),
                        "ccd_count": len(json.loads(sample["ccd_indices_json"])),
                        "points_per_ccd": sample["points_per_ccd"],
                        "available": {
                            "mean": True,
                            "burn": sample["storage_mode"] == "full_interval",
                            "dark": sample["storage_mode"] == "full_interval",
                        },
                    }
                )
        if angle_deg is not None:
            records = [
                record
                for record in records
                if record.get("angle_deg") is not None and abs(record["angle_deg"] - angle_deg) <= 1e-6
            ]
        if query.strip():
            term = query.strip().casefold()
            records = [
                record
                for record in records
                if term
                in " ".join(
                    str(record.get(field) or "")
                    for field in ("id", "sample_name", "sample_names", "band_name", "source_sha256")
                ).casefold()
            ]
        records.sort(key=lambda item: (-int(item["id"].split(":")[1]), item["kind"]))
        return records[max(0, offset) : max(0, offset) + limit]

    def _sample(
        self,
        identifier: int,
        *,
        ccd: int,
        detail: str,
        phase: str,
        frame: int,
        exposure_start: int | None,
        exposure_end: int | None,
    ) -> dict[str, Any]:
        from .acquisition import AcquisitionService, AcquisitionError

        try:
            snapshot = AcquisitionService(self.database).spectrum_snapshot(
                identifier, include_frames=detail == "frame" or exposure_start is not None or exposure_end is not None
            )
        except AcquisitionError as exc:
            raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc
        sample, bands = snapshot["sample"], snapshot["bands"]
        if not 0 <= ccd < len(bands):
            raise SpectrumViewerError("spectrum_ccd_invalid", "CCD 超出实际采集布局", status_code=422)
        band = bands[ccd]
        points = lambda values: [
            {"point_index": index, "step": index, "wavelength_nm": None, "value": value}
            for index, value in enumerate(values)
        ]
        values = band["mean_points"]
        frames = [
            row
            for row in snapshot["frames"]
            if row["ccd_index"] == band["ccd_index"] and row["phase"] == phase and row.get("points")
        ]
        frame_detail = None
        exposure = None
        if detail == "frame" or exposure_start is not None or exposure_end is not None:
            if not frames:
                raise SpectrumViewerError(
                    "spectrum_frames_unavailable", "该样品未保存此阶段的完整原始帧，仅可查看固化均值", status_code=409
                )
            if detail == "frame":
                if not 0 <= frame < len(frames):
                    raise SpectrumViewerError("spectrum_frame_invalid", "帧序号超出范围", status_code=422)
                frame_detail = {
                    "phase": phase,
                    "index": frame,
                    "frame_count": len(frames),
                    "ccd": {"position": ccd, "index": band["ccd_index"], "points": points(frames[frame]["points"])},
                }
            else:
                if (
                    exposure_start is None
                    or exposure_end is None
                    or not 1 <= exposure_start <= exposure_end <= len(frames)
                ):
                    raise SpectrumViewerError("spectrum_exposure_invalid", "曝光区间超出保存帧范围", status_code=422)
                chosen = frames[exposure_start - 1 : exposure_end]
                values = [sum(row["points"][i] for row in chosen) / len(chosen) for i in range(len(values))]
                exposure = {"start": exposure_start, "end": exposure_end, "count": len(chosen)}
        return {
            "id": f"sample:{identifier}",
            "kind": "sample",
            "format": "acquisition",
            "source_sha256": sample["result_sha256"],
            "record_index": identifier,
            "sample_name": sample["sample_name"],
            "measure_time": sample["completed_at"],
            "angle_deg": None,
            "coordinate_system": f"ccd_pixel:{band['ccd_index']}",
            "layout": {"ccd_count": len(bands), "ccd_indices": [item['ccd_index'] for item in bands],
                       "points_per_ccd": len(values), "point_width_um": snapshot['point_width_um']},
            "ignition": {
                "pre_burn": sample["pre_excitation_seconds"],
                "burn_cyc": sample["burn_cycle_seconds"],
                "dark_cyc": sample["dark_cycle_seconds"],
                "burn_count": json.loads(sample["simulator_json"] or "{}").get(
                    "source_frame_count", sample["burn_frame_count"]
                ),
                "dark_count": sample["dark_frame_count"],
            },
            "ccd": {"position": ccd, "index": band["ccd_index"], "points": points(values)},
            "frame_detail": frame_detail,
            "exposure_segment": exposure,
        }

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
            raise SpectrumViewerError(
                "spectrum_record_invalid", "record id must be raw:<id> or result:<id>", status_code=422
            ) from None
        if kind not in {"raw", "result", "sample"} or identifier <= 0:
            raise SpectrumViewerError(
                "spectrum_record_invalid", "record id must be raw:<id> or result:<id>", status_code=422
            )
        if detail not in {"summary", "frame"}:
            raise SpectrumViewerError("spectrum_detail_invalid", "detail must be summary or frame", status_code=422)
        if kind == "sample":
            return self._sample(
                identifier,
                ccd=ccd,
                detail=detail,
                phase=phase,
                frame=frame,
                exposure_start=exposure_start,
                exposure_end=exposure_end,
            )
        with self.database.read() as db:
            if kind == "raw":
                row = db.execute("SELECT * FROM spectrum_bands WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    raise SpectrumViewerError("spectrum_record_not_found", "Spectrum record was not found")
                return self._raw(
                    row,
                    ccd=ccd,
                    detail=detail,
                    phase=phase,
                    frame=frame,
                    exposure_start=exposure_start,
                    exposure_end=exposure_end,
                )
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
            raise SpectrumViewerError(
                "spectrum_ccd_invalid",
                "CCD selection is outside the installed CCD range",
                status_code=422,
                details={"ccd_count": ccd_count},
            )
        gaps = [float(item) for item in layout.get("gap_points", [])]
        coefficients = [float(item) for item in layout.get("ws_cof", [])]
        physical_index = indices[ccd] if ccd < len(indices) else ccd
        left_step = physical_index * points_per_ccd + sum(gaps[:physical_index])
        mean_blob = bytes(row["mean_blob"] or b"")
        expected_mean = ccd_count * points_per_ccd
        if mean_blob and len(mean_blob) != expected_mean * 4:
            raise SpectrumViewerError(
                "spectrum_mean_shape_invalid", "Stored mean data does not match its CCD layout", status_code=500
            )
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

        selected = list(mean_values[ccd * points_per_ccd : (ccd + 1) * points_per_ccd]) if mean_values else []
        exposure_segment = None
        if exposure_start is not None or exposure_end is not None:
            if exposure_start is None or exposure_end is None:
                raise SpectrumViewerError(
                    "spectrum_exposure_invalid",
                    "exposure_start and exposure_end must be provided together",
                    status_code=422,
                )
            burn_count = int(ignition.get("burn_count") or 0)
            if not 1 <= exposure_start <= exposure_end <= burn_count:
                raise SpectrumViewerError(
                    "spectrum_exposure_invalid",
                    "Exposure interval is outside the stored burn frames",
                    status_code=422,
                    details={"burn_count": burn_count},
                )
            burn_blob = bytes(row["burn_adcs_blob"] or b"")
            if len(burn_blob) != burn_count * expected_mean * 2:
                raise SpectrumViewerError(
                    "spectrum_frame_shape_invalid", "Stored raw frames do not match their layout", status_code=500
                )
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
                raise SpectrumViewerError(
                    "spectrum_frame_unavailable", "The requested raw frame is not stored", status_code=404
                )
            if len(blob) != expected:
                raise SpectrumViewerError(
                    "spectrum_frame_shape_invalid", "Stored raw frames do not match their layout", status_code=500
                )
            if not 0 <= frame < count:
                raise SpectrumViewerError(
                    "spectrum_frame_invalid",
                    "Frame selection is outside the available range",
                    status_code=422,
                    details={"frame_count": count},
                )
            offset = (frame * expected_mean + ccd * points_per_ccd) * 2
            values = struct.unpack_from(f"<{points_per_ccd}H", blob, offset)
            result["frame_detail"] = {
                "phase": phase,
                "index": frame,
                "frame_count": count,
                "ccd": {"position": ccd, "index": physical_index, "points": points(list(values), include_adc=True)},
            }
        return result

    def point_details(self, record_id: str, *, ccd: int, point: int) -> dict[str, Any]:
        """All raw burn/dark integrations at one zero-based point, without normalization."""
        record = self.get(record_id, ccd=ccd)
        if record["kind"] == "result":
            raise SpectrumViewerError("spectrum_raw_required", "结果矩阵不包含 CCD 原始积分值", status_code=422)
        point_values = record['ccd']['points']
        if not point_values and record['kind'] == 'raw':
            phase = 'burn' if int((record.get('ignition') or {}).get('burn_count') or 0) else 'dark'
            point_values = self.get(record_id, ccd=ccd, detail='frame', phase=phase, frame=0)['frame_detail']['ccd']['points']
        count = len(point_values)
        if not 0 <= point < count:
            raise SpectrumViewerError("spectrum_point_invalid", "点位超出当前 CCD", status_code=422)
        ignition = record.get("ignition") or {}
        rows = []
        if record["kind"] == "sample":
            from .acquisition import AcquisitionService, AcquisitionError
            try:
                snapshot = AcquisitionService(self.database).spectrum_snapshot(int(record_id.split(":")[1]), include_frames=True)
            except AcquisitionError as exc:
                raise SpectrumViewerError(exc.code, exc.message, status_code=exc.status_code) from exc
            physical_ccd = record["ccd"]["index"]
            for phase in ("burn", "dark"):
                frames = sorted((item for item in snapshot["frames"] if item["ccd_index"] == physical_ccd and item["phase"] == phase),
                                key=lambda item: item["frame_index"])
                expected = int(snapshot["sample"][f"{phase}_frame_count"])
                if [item["frame_index"] for item in frames] != list(range(expected)):
                    raise SpectrumViewerError("spectrum_frames_unavailable", "仅保存均值或分时帧不完整，不能生成原始明细", status_code=409)
                for frame in frames:
                    values = frame.get("points") or []
                    if frame.get("damaged") or len(values) != count or hashlib.sha256(struct.pack(f"<{len(values)}H", *values)).hexdigest() != frame["points_sha256"]:
                        raise SpectrumViewerError("spectrum_frame_integrity_failed", "原始帧损坏或 SHA-256 校验失败", status_code=409)
                    rows.append({"phase": phase, "integration": frame["frame_index"] + 1, "value": values[point]})
        else:
            # Decode the selected column directly; avoid constructing a whole CCD for every frame.
            with self.database.read() as db:
                raw = db.execute("SELECT * FROM spectrum_bands WHERE id=?", (int(record_id.split(":")[1]),)).fetchone()
                stride = int(raw["ccd_count"]) * int(raw["points_per_ccd"])
                for phase in ("burn", "dark"):
                    total = int(ignition.get(f"{phase}_count") or 0)
                    blob = bytes(raw[f"{phase}_adcs_blob"] or b"")
                    if len(blob) != total * stride * 2:
                        raise SpectrumViewerError("spectrum_frames_unavailable", "未保存完整原始分时数据", status_code=409)
                    expected_hash = raw[f'{phase}_sha256']
                    if expected_hash and hashlib.sha256(blob).hexdigest() != expected_hash:
                        raise SpectrumViewerError('spectrum_frame_integrity_failed', '旧谱图原始帧 SHA-256 校验失败', status_code=409)
                    for index in range(total):
                        value = struct.unpack_from("<H", blob, (index * stride + ccd * count + point) * 2)[0]
                        rows.append({"phase": phase, "integration": index + 1, "value": value})
        if not rows:
            raise SpectrumViewerError("spectrum_frames_unavailable", "该记录只有均值，没有原始积分明细", status_code=409)
        result = {"record_id": record_id, "sample_name": record.get("sample_name") or record.get("band_name") or record_id,
                  "ccd_index": record["ccd"]["index"], "point_index": point,
                  "wavelength_nm": point_values[point].get("wavelength_nm"),
                  "source_sha256": record["source_sha256"],
                  "pre_excitation_seconds": ignition.get("pre_burn"),
                  "burn_cycle_seconds": ignition.get("burn_cyc"), "dark_cycle_seconds": ignition.get("dark_cyc"),
                  "burn_count": sum(row["phase"] == "burn" for row in rows),
                  "dark_count": sum(row["phase"] == "dark" for row in rows), "rows": rows}
        result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
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
            raise SpectrumViewerError(
                "spectrum_visible_range_invalid", "x_min and x_max must form an ordered visible range", status_code=422
            )
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
        if record["kind"] in {"raw", "sample"}:
            source_points = (record.get("frame_detail") or {}).get("ccd", {}).get("points") or record["ccd"]["points"]
        else:
            source_points = record["line"]["points"]
        rows: list[dict[str, Any]] = []
        for point in source_points:
            x = point.get("wavelength_nm")
            if x is None:
                x = point.get("step", point.get("x", point["point_index"]))
            x = float(x) + (reference_shift if record["kind"] in {"raw", "sample"} else 0.0)
            if x_min is not None and x_max is not None and not x_min <= x <= x_max:
                continue
            rows.append({**point, "x": x})
        fieldnames = [
            "point_index",
            "x",
            "wavelength_nm",
            "step",
            "value",
            "adc",
            "peak",
            "back",
            "sample_index",
            "repeat_index",
            "sample_name",
        ]
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
        print_scope: str = 'visible',
        print_layers: list[str] | None = None,
        print_scale: str = 'fit_long',
        paper: str = 'A4',
    ) -> tuple[bytes, dict[str, Any]]:
        if visible_x_min > visible_x_max or visible_y_min > visible_y_max:
            raise SpectrumViewerError(
                "spectrum_visible_range_invalid", "Visible ranges must be ordered", status_code=422
            )
        if mode not in {"mean", "peak", "back", "value", "frame"}:
            raise SpectrumViewerError("spectrum_print_mode_invalid", "Print mode is not supported", status_code=422)
        if (exposure_start is None) != (exposure_end is None):
            raise SpectrumViewerError(
                "spectrum_exposure_invalid", "Exposure interval must include both endpoints", status_code=422
            )

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
                first = self.get(
                    item_id,
                    ccd=0,
                    line=line,
                    detail="summary",
                    exposure_start=item_exposure_start,
                    exposure_end=item_exposure_end,
                )
                clipped_ccd = max(0, min(ccd, int(first.get("layout", {}).get("ccd_count") or 1) - 1))
                record = self.get(
                    item_id,
                    ccd=clipped_ccd,
                    line=line,
                    detail=detail,
                    phase=frame_phase,
                    frame=frame_index,
                    exposure_start=item_exposure_start,
                    exposure_end=item_exposure_end,
                )

            coordinates = record.get(
                "coordinate_system", "legacy_wavelength" if record["kind"] == "raw" else "result_index"
            )
            if curves and coordinates != curves[0].get("coordinate_system"):
                raise SpectrumViewerError(
                    "spectrum_overlay_incompatible", "叠加来源的坐标和单位不可比，请分别查看", status_code=422
                )
            if record["kind"] in {"raw", "sample"}:
                source = (record.get("frame_detail") or {}).get("ccd", {}).get("points") or record["ccd"]["points"]
                label = record.get("sample_name") or record.get("band_name") or item_id
            else:
                source = record["line"]["points"]
                label = record["line"].get("element") or (record.get("sample_names") or [item_id])[0]
            points: list[tuple[float, float]] = []
            point_indices = []
            for point_index, point in enumerate(source):
                x = point.get("wavelength_nm")
                if x is None:
                    x = point.get("step", point.get("x", point_index))
                x = float(x) + (reference_shift if record["kind"] in {"raw", "sample"} else 0.0)
                if mode == "peak":
                    y = point.get("peak")
                elif mode == "back":
                    y = point.get("back")
                else:
                    y = point.get("value", point.get("peak", point.get("adc")))
                if y is not None and math.isfinite(x) and math.isfinite(float(y)):
                    points.append((x, float(y)))
                    point_indices.append(int(point.get('point_index', point_index)))
            curves.append(
                {
                    "coordinate_system": coordinates,
                    "id": item_id,
                    "label": str(label),
                    "points": points,
                    "color": _SPECTRUM_PDF_COLORS[index % len(_SPECTRUM_PDF_COLORS)],
                    "priority": (priority_record_id or record_id) == item_id,
                    "point_indices": point_indices,
                    # FmPrintCcd.PrintBlack scales against the whole CCD, with DefaultMaxAvg=5000.
                    "grayscale_max": max(5000.0, max((value for _, value in points), default=0.0)),
                    "point_width_um": record.get('layout', {}).get('point_width_um', record.get('layout', {}).get('point_width')),
                    "raw": record['kind'] in {'raw', 'sample'},
                }
            )
        layers = list(dict.fromkeys(print_layers if print_layers is not None else ['curve']))
        if not layers or set(layers) - {'curve', 'grayscale'}:
            raise SpectrumViewerError('spectrum_print_layers_invalid', '灰度谱带和峰形至少选择一项', status_code=422)
        if print_scope not in {'visible', 'ccd'} or print_scale not in {'fit_long', 'fit_short', 'ccd_10x'} or paper not in {'A4', 'A3', 'Letter'}:
            raise SpectrumViewerError('spectrum_print_options_invalid', '打印范围、比例或纸型无效', status_code=422)
        if ('grayscale' in layers or print_scale == 'ccd_10x' or print_scope == 'ccd') and any(not curve['raw'] for curve in curves):
            raise SpectrumViewerError('spectrum_raw_required', 'CCD 灰度和物理比例输出需要原始谱图', status_code=422)
        if print_scope == 'ccd':
            all_points = [point for curve in curves for point in curve['points']]
            if not all_points:
                raise SpectrumViewerError('spectrum_print_empty', '当前 CCD 没有可打印点', status_code=422)
            visible_x_min, visible_x_max = min(p[0] for p in all_points), max(p[0] for p in all_points)
            visible_y_min, visible_y_max = min(0, min(p[1] for p in all_points)), max(1, max(p[1] for p in all_points))
        physical_width_mm = None
        if print_scale == 'ccd_10x':
            widths = [float(curve.get('point_width_um') or 0) for curve in curves]
            if any(not math.isfinite(width) or width <= 0 for width in widths) or max(widths) - min(widths) > 1e-6:
                raise SpectrumViewerError('spectrum_point_width_unavailable', '未记录一致的 CCD 点宽，无法按十倍物理比例打印', status_code=422)
            for curve in curves:
                curve['points'] = [(index, value) for index, (x, value) in zip(curve['point_indices'], curve['points'], strict=True)
                                   if visible_x_min <= x <= visible_x_max]
            selected = [point for curve in curves for point in curve['points']]
            if not selected:
                raise SpectrumViewerError('spectrum_print_empty', '当前图像没有可打印点', status_code=422)
            visible_x_min, visible_x_max = min(p[0] for p in selected), max(p[0] for p in selected)
            # Old CalGraphicWidth counts inclusive CCD pixels, including both endpoints.
            physical_width_mm = (visible_x_max - visible_x_min + 1) * widths[0] * 10 / 1000
        try:
            content, metadata = render_spectrum_pdf(curves, record_id, mode, ccd, line, reference_shift,
                visible_x_min, visible_x_max, visible_y_min, visible_y_max,
                layers=layers, print_scale=print_scale, paper=paper, physical_width_mm=physical_width_mm)
        except ValueError as exc:
            raise SpectrumViewerError('spectrum_print_physical_size_exceeds_page', str(exc), status_code=422) from exc
        return content, {**metadata, 'print_scope': print_scope, 'print_layers': layers,
                         'print_scale': print_scale, 'paper': paper, 'physical_width_mm': physical_width_mm}

    @staticmethod
    def decode_result_matrix(row: Any, *, line: int) -> dict[str, Any]:
        payload = _json(row["payload_json"], {})
        line_count = int(payload.get("line_count") or 0)
        band_count = int(payload.get("band_count") or 0)
        if not 0 <= line < line_count:
            raise SpectrumViewerError(
                "spectrum_line_invalid",
                "Line selection is outside the result matrix",
                status_code=422,
                details={"line_count": line_count},
            )
        sample_rows = payload.get("sample_rows") or []
        lines = payload.get("lines") or []
        matrix = bytes(row["matrix_blob"] or b"")
        kind = payload.get("matrix_kind")
        expected = line_count * band_count * (8 if kind == "peak_back" else 4)
        if len(matrix) != expected:
            raise SpectrumViewerError(
                "result_matrix_shape_invalid", "Stored result matrix does not match its metadata", status_code=500
            )
        points: list[dict[str, Any]] = []
        metadata = lines[line] if line < len(lines) else {"index": line}
        if kind == "peak_back":
            for point_index in range(band_count):
                peak, back = struct.unpack_from("<ff", matrix, (line * band_count + point_index) * 8)
                sample = sample_rows[point_index] if point_index < len(sample_rows) else {}
                points.append(
                    {
                        "point_index": point_index,
                        "x": point_index,
                        "sample_index": sample.get("sample_index"),
                        "repeat_index": sample.get("repeat_index"),
                        "sample_name": sample.get("name"),
                        "peak": float(peak),
                        "back": float(back),
                    }
                )
        else:
            for point_index in range(band_count):
                (value,) = struct.unpack_from("<f", matrix, (line * band_count + point_index) * 4)
                sample = sample_rows[point_index] if point_index < len(sample_rows) else {}
                points.append(
                    {
                        "point_index": point_index,
                        "x": point_index,
                        "sample_index": sample.get("sample_index"),
                        "repeat_index": sample.get("repeat_index"),
                        "sample_name": sample.get("name"),
                        "value": float(value),
                    }
                )
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

    _result = decode_result_matrix
