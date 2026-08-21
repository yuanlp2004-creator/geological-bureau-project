from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
import sqlite3
import struct
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..db import Database, utc_now
from .methods import MethodService
from .spectral_lines import canonical_lines


MIN_SIGNAL = 1e-5
FIT_MODES = {"linear": 1, "quadratic": 2, "cubic": 3, "spline": 3}
COORDINATE_TYPES = {"normal", "logarithmic"}
_CURVE_FONT = "GeoSpectrum-Curve-CJK"
_CURVE_FONT_READY = False


class AnalysisError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _legacy_floor(value: float) -> float:
    minimum = _float32(MIN_SIGNAL)
    return minimum if value < minimum else _float32(value)


def repeat_statistics(values: list[float]) -> dict[str, Any]:
    """Legacy-compatible repeat statistics used by the S17 QC workflow."""

    numbers = [float(value) for value in values]
    if any(not math.isfinite(value) for value in numbers):
        raise AnalysisError("analysis_qc_value_invalid", "重复测量值必须是有限数字", status_code=422)
    count = len(numbers)
    if count == 0:
        return {"effective_count": 0, "mean": None, "minimum": None, "maximum": None, "range": None, "stddev": None, "rsd": None, "id": None}
    minimum, maximum = min(numbers), max(numbers)
    mean = sum(numbers) / count
    stddev = 0.0 if count == 1 else math.sqrt(sum((value - mean) ** 2 for value in numbers) / (count - 1))
    rsd = 0.0 if stddev == 0 else min(999.0, abs(100.0 * stddev / mean)) if mean != 0 else 999.0
    identity = 0.0
    if minimum <= 0:
        identity = 999.0 if maximum > minimum else 0.0
    elif maximum > minimum:
        identity = 21.7147 * math.log(maximum / minimum)
    return {
        "effective_count": count,
        "mean": mean,
        "minimum": minimum,
        "maximum": maximum,
        "range": maximum - minimum,
        "stddev": stddev,
        "rsd": rsd,
        "id": identity,
    }


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [list(matrix[row]) + [float(vector[row])] for row in range(size)]
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = max(1e-14, scale * 1e-12)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= tolerance:
            raise AnalysisError("analysis_curve_ill_conditioned", "标准点矩阵病态，无法稳定拟合", details={"pivot": column})
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [value - factor * pivot_value for value, pivot_value in zip(augmented[row], augmented[column], strict=True)]
    return [augmented[row][-1] for row in range(size)]


def fit_curve(x_values: list[float], y_values: list[float], mode: str, coordinate_type: str = "normal") -> dict[str, Any]:
    if mode not in FIT_MODES:
        raise AnalysisError("analysis_curve_fit_mode_invalid", "拟合方式无效", status_code=422)
    if coordinate_type not in COORDINATE_TYPES:
        raise AnalysisError("analysis_curve_coordinate_invalid", "坐标方式无效", status_code=422)
    if len(x_values) != len(y_values):
        raise AnalysisError("analysis_curve_shape_invalid", "标准点强度与含量数量不一致", status_code=422)
    minimum_count = 4
    if len(x_values) < minimum_count:
        raise AnalysisError("analysis_curve_points_insufficient", f"{mode} 拟合至少需要 {minimum_count} 个有效标准点", details={"minimum": minimum_count, "actual": len(x_values)})
    pairs = [(float(x), float(y)) for x, y in zip(x_values, y_values, strict=True)]
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in pairs):
        raise AnalysisError("analysis_curve_value_invalid", "标准点必须是有限数字", status_code=422)
    if coordinate_type == "logarithmic":
        if any(x <= 0 or y <= 0 for x, y in pairs):
            raise AnalysisError("analysis_curve_log_nonpositive", "对数坐标要求强度和含量均大于零")
        pairs = [(math.log(x), math.log(y)) for x, y in pairs]
    pairs.sort(key=lambda item: item[0])
    if any(math.isclose(pairs[index][0], pairs[index - 1][0], rel_tol=0.0, abs_tol=1e-12) for index in range(1, len(pairs))):
        raise AnalysisError("analysis_curve_duplicate_x", "标准点存在重复强度，无法拟合")
    xs, ys = map(list, zip(*pairs, strict=True))
    if mode != "spline":
        degree = FIT_MODES[mode]
        matrix = [[sum(x ** (row + column) for x in xs) for column in range(degree + 1)] for row in range(degree + 1)]
        vector = [sum(y * (x ** row) for x, y in zip(xs, ys, strict=True)) for row in range(degree + 1)]
        coefficients = [_float32(value) for value in _solve_linear(matrix, vector)]
        coefficients += [0.0] * (4 - len(coefficients))
        return {"kind": "polynomial", "coefficients": coefficients, "x": xs, "y": ys}

    count = len(xs)
    h = [xs[index + 1] - xs[index] for index in range(count - 1)]
    if any(value <= 1e-12 for value in h):
        raise AnalysisError("analysis_curve_duplicate_x", "标准点存在重复强度，无法拟合")
    if count == 2:
        second = [0.0, 0.0]
    else:
        matrix = [[0.0] * (count - 2) for _ in range(count - 2)]
        vector = [0.0] * (count - 2)
        for row in range(count - 2):
            index = row + 1
            if row > 0:
                matrix[row][row - 1] = h[index - 1]
            matrix[row][row] = 2.0 * (h[index - 1] + h[index])
            if row < count - 3:
                matrix[row][row + 1] = h[index]
            vector[row] = 6.0 * ((ys[index + 1] - ys[index]) / h[index] - (ys[index] - ys[index - 1]) / h[index - 1])
        second = [0.0, *(_float32(value) for value in _solve_linear(matrix, vector)), 0.0]
    slopes = [_float32((second[index + 1] - second[index]) / h[index]) for index in range(count - 1)]
    dy = [_float32((ys[index + 1] - ys[index]) / h[index]) for index in range(count - 1)]
    return {"kind": "spline", "x": xs, "y": ys, "second_derivatives": second, "segment_slopes": slopes, "dy": dy}


def evaluate_curve(fit: dict[str, Any], x_value: float, coordinate_type: str = "normal") -> float:
    x = float(x_value)
    if coordinate_type == "logarithmic":
        if x <= 0:
            raise AnalysisError("analysis_curve_log_nonpositive", "对数坐标不能计算非正强度")
        x = math.log(x)
    if fit["kind"] == "polynomial":
        c0, c1, c2, c3 = (float(value) for value in fit["coefficients"])
        result = x * (x * (x * c3 + c2) + c1) + c0
    else:
        xs = [float(value) for value in fit["x"]]
        ys = [float(value) for value in fit["y"]]
        second = [float(value) for value in fit["second_derivatives"]]
        index = 0
        while index < len(xs) - 2 and x > xs[index + 1]:
            index += 1
        h = x - xs[index]
        span = xs[index + 1] - xs[index]
        dy = (ys[index + 1] - ys[index]) / span
        slope = (second[index + 1] - second[index]) / span
        result = ys[index] + h * (dy + (x - xs[index + 1]) * (second[index + 1] + 2.0 * second[index] + h * slope) / 6.0)
    if coordinate_type == "logarithmic":
        result = math.exp(result)
    if not math.isfinite(result):
        raise AnalysisError("analysis_curve_result_invalid", "拟合结果不是有限数字")
    return result


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


def legacy_gaussian(values: list[float]) -> dict[str, float | int | bool | None]:
    """Direct, testable port of SpecDirect 2.0.2 TGaussCur.Cal."""

    size = len(values)
    invalid = {"ok": False, "size": size, "center": 0.0, "peak_height": 0.0, "sigma": None, "area": None}
    if size < 3 or size > 9 or size % 2 == 0:
        return invalid
    if size == 3:
        calculated_size, multiplier = 7, 3
    elif size == 5:
        calculated_size, multiplier = 9, 2
    else:
        calculated_size, multiplier = size, 1
    pace = 1.0 / multiplier
    xs: list[float] = []
    weights: list[float] = []
    ys: list[float] = []
    for index in range(calculated_size):
        x = index * pace
        source_index = index // multiplier
        weight = float(values[source_index])
        remainder = index % multiplier
        if remainder:
            weight += (float(values[source_index + 1]) - weight) * remainder * pace
        if weight <= 0 or not math.isfinite(weight):
            return invalid
        xs.append(x)
        weights.append(weight)
        ys.append(math.log(weight))
    buf = [0.0] * 8
    for x, weight, y in zip(xs, weights, ys, strict=True):
        weighted_power = weight
        for power in range(5):
            if power < 3:
                buf[power + 5] += weighted_power * y
            buf[power] += weighted_power
            weighted_power *= x
    mean_x = buf[1] / buf[0]
    mean_x2 = buf[2] / buf[0]
    buf[5] /= buf[0]
    buf[6] -= buf[1] * buf[5]
    buf[7] -= buf[2] * buf[5]
    buf[4] -= buf[2] * mean_x2
    buf[3] -= buf[1] * mean_x2
    buf[1] = buf[2] - buf[1] * mean_x
    determinant = buf[1] * buf[4] - buf[3] * buf[3]
    if abs(determinant) < 1e-100:
        return invalid
    a2 = (buf[1] * buf[7] - buf[3] * buf[6]) / determinant
    a1 = (buf[4] * buf[6] - buf[3] * buf[7]) / determinant
    a0 = buf[5] - a1 * mean_x - a2 * mean_x2
    if a2 >= 0:
        return invalid
    sigma = math.sqrt(-0.5 / a2)
    center = -0.5 * a1 / a2
    peak = math.exp(a0 + 0.5 * center * a1)
    return {
        "ok": True,
        "size": size,
        "center": center,
        "peak_height": peak,
        "sigma": sigma,
        "area": peak * sigma * math.sqrt(2.0 * math.pi),
    }


def _bounded_range(center: int, width: int, point_count: int) -> tuple[int, int, bool]:
    if width <= 0 or width > point_count:
        raise AnalysisError("analysis_window_invalid", "谱线计算窗口超出 CCD 点数", details={"center": center, "width": width, "point_count": point_count})
    left = center - width // 2
    adjusted = False
    if left < 0:
        left = 0
        adjusted = True
    right = left + width - 1
    if right >= point_count:
        right = point_count - 1
        left = right - width + 1
        adjusted = True
    return left, right, adjusted


def _search_peak(values: list[float], center: int, width: int, *, checked: bool, lower_peak: float, minimum_ratio: float, maximum: bool = False) -> dict[str, Any]:
    left, right, adjusted = _bounded_range(center, width, len(values))
    window = values[left:right + 1]
    minimum = min(window)
    if maximum:
        peak = max(window)
        position = left + window.index(peak)
        found = True
    else:
        position = max(left, min(right, center))
        peak = float(values[position])
        found = False
        candidate_peak = 0.0
        for index in range(left + 1, right):
            current = float(values[index])
            if current > values[index - 1] and current > values[index + 1] and candidate_peak < current:
                candidate_peak = current
                position = index
                found = True
        if found and checked and not (candidate_peak > lower_peak and candidate_peak > minimum * minimum_ratio):
            found = False
            position = max(left, min(right, center))
        peak = float(values[position])
    return {"position": position, "peak": peak, "minimum": float(minimum), "found": found, "window_start": left, "window_end": right, "boundary_adjusted": adjusted}


class AnalysisService:
    def __init__(self, database: Database):
        self.database = database
        self.methods = MethodService(database)

    @staticmethod
    def _profile(conditions: dict[str, Any]) -> str:
        explicit = conditions.get("calculation_profile")
        if explicit in {"legacy_2_0_2", "modern_v1"}:
            return str(explicit)
        return "legacy_2_0_2" if conditions.get("storage_profile") == "legacy_specdirect_202" else "modern_v1"

    @staticmethod
    def _actor(db: sqlite3.Connection, actor_user_id: int | None) -> int | None:
        if actor_user_id is None:
            return None
        return actor_user_id if db.execute("SELECT 1 FROM users WHERE id=?", (actor_user_id,)).fetchone() else None

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: int | None, action: str, run_id: int, details: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'analysis', ?, ?, ?)",
            (actor, action, run_id, _json(details), utc_now()),
        )

    @staticmethod
    def _message(db: sqlite3.Connection, run_id: int, level: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO analysis_messages(run_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, level, code, message, _json(details or {}), utc_now()))

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            samples = [dict(row) for row in db.execute(
                "SELECT s.id, s.sample_name, s.sample_kind, s.repeat_index, s.result_sha256 AS input_sha256, t.id AS acquisition_task_id, t.name AS acquisition_task_name, t.method_version_id, t.method_id, t.method_version "
                "FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.status='completed' AND s.finalized=1 AND t.method_version_id IS NOT NULL ORDER BY t.id DESC, s.repeat_index"
            ).fetchall()]
            methods = [dict(row) for row in db.execute("SELECT v.id AS method_version_id, v.method_id, v.version, m.name, v.payload_json FROM method_versions v JOIN methods m ON m.id=v.method_id WHERE v.state='published' ORDER BY m.name, v.version DESC").fetchall()]
        for item in methods:
            payload = json.loads(item.pop("payload_json"))
            item["calculation_profile"] = self._profile(payload.get("conditions", {}))
        return {"profiles": ["legacy_2_0_2", "modern_v1"], "samples": samples, "method_versions": methods}

    def create_run(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        sample_ids = [int(value) for value in payload.get("acquisition_sample_ids") or []]
        if not sample_ids or len(sample_ids) != len(set(sample_ids)):
            raise AnalysisError("analysis_samples_invalid", "必须选择至少一个且不重复的采集样品", status_code=422)
        with self.database.write() as db:
            placeholders = ",".join("?" for _ in sample_ids)
            rows = db.execute(
                f"SELECT s.*, t.method_id, t.method_version_id, t.method_version FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id IN ({placeholders})",
                sample_ids,
            ).fetchall()
            by_id = {int(row["id"]): row for row in rows}
            if len(by_id) != len(sample_ids):
                raise AnalysisError("analysis_sample_not_found", "一个或多个采集样品不存在", status_code=404)
            ordered = [by_id[value] for value in sample_ids]
            if any(row["status"] != "completed" or not row["finalized"] for row in ordered):
                raise AnalysisError("analysis_sample_not_finalized", "只能分析已完成且已固化的采集样品")
            method_version_ids = {row["method_version_id"] for row in ordered}
            selected_version_id = payload.get("method_version_id")
            if selected_version_id is None:
                if len(method_version_ids) != 1 or None in method_version_ids:
                    raise AnalysisError("analysis_method_mismatch", "所选样品未引用同一方法版本")
                selected_version_id = next(iter(method_version_ids))
            if any(int(row["method_version_id"] or 0) != int(selected_version_id) for row in ordered):
                raise AnalysisError("analysis_method_mismatch", "所选样品与分析方法版本不一致")
            version = db.execute("SELECT * FROM method_versions WHERE id=? AND state='published'", (selected_version_id,)).fetchone()
            if version is None:
                raise AnalysisError("analysis_method_version_not_found", "已发布方法版本不存在", status_code=404)
            method = db.execute("SELECT * FROM methods WHERE id=?", (version["method_id"],)).fetchone()
            method_payload = json.loads(version["payload_json"])
            lines = [line for line in canonical_lines(method_payload.get("lines"), method_payload.get("conditions", {})) if line.get("enabled")]
            if not any(line.get("line_type") == "analysis" for line in lines):
                raise AnalysisError("analysis_lines_missing", "方法版本没有已启用的分析线")
            profile = payload.get("calculation_profile") or self._profile(method_payload.get("conditions", {}))
            if profile not in {"legacy_2_0_2", "modern_v1"}:
                raise AnalysisError("analysis_profile_invalid", "计算档案无效", status_code=422)
            snapshot_samples: list[dict[str, Any]] = []
            for row in ordered:
                band_rows = db.execute("SELECT ccd_index, points_count, mean_sha256 FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index", (row["id"],)).fetchall()
                if not band_rows:
                    raise AnalysisError("analysis_sample_bands_missing", "采集样品没有固化谱带", details={"sample_id": row["id"]})
                snapshot_samples.append({"id": row["id"], "name": row["sample_name"], "result_sha256": row["result_sha256"], "bands": [dict(item) for item in band_rows]})
            snapshot = {"method_version_id": version["id"], "method_content_sha256": hashlib.sha256(version["payload_json"].encode("utf-8")).hexdigest(), "profile": profile, "samples": snapshot_samples}
            now = utc_now()
            cursor = db.execute(
                "INSERT INTO analysis_runs(name, method_id, method_version_id, method_version, calculation_profile, slow_mode, intervention_timeout_seconds, input_snapshot_json, input_sha256, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(payload.get("name") or "S17 定量与曲线分析").strip(), method["id"], version["id"], version["version"], profile, int(bool(payload.get("slow_mode"))), float(payload.get("intervention_timeout_seconds", 300)), _json(snapshot), _sha(snapshot), self._actor(db, actor_user_id), now, now),
            )
            run_id = int(cursor.lastrowid)
            for position, row in enumerate(ordered):
                input_hash = _sha(snapshot_samples[position])
                db.execute("INSERT INTO analysis_run_samples(run_id, position, acquisition_sample_id, sample_name, input_sha256) VALUES (?, ?, ?, ?, ?)", (run_id, position, row["id"], row["sample_name"], input_hash))
            self._message(db, run_id, "info", "analysis.run.created", "分析运行已建立，输入和版本已锁定", {"sample_count": len(ordered), "line_count": len(lines), "profile": profile})
            self._audit(db, self._actor(db, actor_user_id), "analysis.run.create", run_id, {"input_sha256": _sha(snapshot), "sample_ids": sample_ids, "method_version_id": version["id"], "profile": profile})
        return self.run(run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [int(row[0]) for row in db.execute("SELECT id FROM analysis_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()]
        return [self.run(run_id) for run_id in ids]

    @staticmethod
    def _operational_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
        lines = [line for line in canonical_lines(payload.get("lines"), payload.get("conditions", {})) if line.get("enabled")]
        return [line for line in lines if line.get("line_type") == "baseline"] + [line for line in lines if line.get("line_type") in {"positioning", "internal_standard"}] + [line for line in lines if line.get("line_type") == "analysis"]

    def _context(self, db: sqlite3.Connection, run_id: int) -> tuple[sqlite3.Row, dict[str, Any], list[dict[str, Any]]]:
        run = db.execute("SELECT * FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise AnalysisError("analysis_run_not_found", "分析运行不存在", status_code=404)
        version = db.execute("SELECT payload_json FROM method_versions WHERE id=?", (run["method_version_id"],)).fetchone()
        if version is None:
            raise AnalysisError("analysis_method_version_not_found", "分析运行引用的方法版本不存在")
        payload = json.loads(version["payload_json"])
        return run, payload, self._operational_lines(payload)

    def _line_candidate(self, db: sqlite3.Connection, run: sqlite3.Row, payload: dict[str, Any], lines: list[dict[str, Any]], sample_position: int, line_position: int, forced_position: int | None = None) -> dict[str, Any]:
        sample = db.execute("SELECT * FROM analysis_run_samples WHERE run_id=? AND position=?", (run["id"], sample_position)).fetchone()
        if sample is None:
            raise AnalysisError("analysis_checkpoint_invalid", "分析样品检查点不存在")
        line = lines[line_position]
        conditions = payload.get("conditions", {})
        layout = self.methods._layout(db, conditions.get("ccd_layout_id", "default"))
        dispersion = self.methods._dispersion(db, conditions.get("dispersion_calibration_id", "default"))
        if layout is None or dispersion is None:
            raise AnalysisError("analysis_geometry_missing", "方法引用的 CCD 布局或色散校准不存在", details={"line_id": line.get("id")})
        detected = self.methods._reference_position(float(line.get("actual_wavelength_nm") or line["wavelength_nm"]), layout, dispersion)
        if detected is None:
            raise AnalysisError("analysis_line_outside_ccd", "谱线不在当前 CCD 覆盖范围内", details={"line_id": line.get("id"), "wavelength_nm": line.get("wavelength_nm")})
        ccd_index, expected_float, _ = detected
        band = db.execute("SELECT * FROM acquisition_sample_bands WHERE sample_id=? AND ccd_index=?", (sample["acquisition_sample_id"], ccd_index)).fetchone()
        if band is None:
            raise AnalysisError("analysis_band_missing", "谱线对应的 CCD 谱带不存在", details={"sample_id": sample["acquisition_sample_id"], "line_id": line.get("id"), "ccd_index": ccd_index})
        count = int(band["points_count"])
        blob = bytes(band["mean_blob"])
        if len(blob) != count * 4 or hashlib.sha256(blob).hexdigest() != band["mean_sha256"]:
            raise AnalysisError("analysis_band_integrity_failed", "谱带形状或 SHA-256 校验失败", details={"sample_id": sample["acquisition_sample_id"], "ccd_index": ccd_index})
        values = list(struct.unpack(f"<{count}f", blob))
        offsets: dict[str, int] = {}
        for row in db.execute("SELECT line_id, peak_position, expected_position, intermediates_json FROM analysis_line_results WHERE run_id=? AND sample_position=?", (run["id"], sample_position)).fetchall():
            intermediates = json.loads(row["intermediates_json"] or "{}")
            corrected_expected = int(intermediates.get("corrected_expected_position", round(float(row["expected_position"]))))
            offsets[str(row["line_id"])] = int(row["peak_position"] - corrected_expected)
        reference = next((item for item in lines if item.get("line_type") == "baseline"), None)
        correction = offsets.get(str(reference.get("id")), 0) if reference else 0
        alignment_id = line.get("alignment_line_id")
        if alignment_id:
            correction += offsets.get(str(alignment_id), 0)
        expected = int(round(expected_float)) + correction
        maximum = line.get("line_type") == "baseline"
        checked = line.get("line_type") not in {"baseline", "positioning"}
        search = _search_peak(values, expected, int(line.get("scan_width_points", 9)), checked=checked, lower_peak=float(line.get("lower_peak", 300)), minimum_ratio=float(line.get("minimum_peak_ratio", 1.5)), maximum=maximum)
        peak_position = int(forced_position if forced_position is not None else search["position"])
        if not 0 <= peak_position < count:
            raise AnalysisError("analysis_adjustment_outside_ccd", "人工定位点超出 CCD 范围", details={"position": peak_position, "point_count": count})
        if forced_position is not None:
            allowed_left, allowed_right, _ = _bounded_range(expected, int(line.get("scan_width_points", 9)), count)
            if not allowed_left <= peak_position <= allowed_right:
                raise AnalysisError("analysis_adjustment_outside_window", "人工定位点必须位于谱线扫描窗口内", details={"position": peak_position, "window_start": allowed_left, "window_end": allowed_right})
        peak_height = float(values[peak_position])
        gaussian: dict[str, Any] | None = None
        if line.get("peak_mode") == "gaussian":
            left, right, gaussian_adjusted = _bounded_range(peak_position, int(line.get("peak_width_points", 3)), count)
            gaussian = legacy_gaussian(values[left:right + 1])
            if not gaussian["ok"]:
                raise AnalysisError("analysis_gaussian_fit_failed", "高斯峰拟合失败", details={"line_id": line.get("id"), "sample_position": sample_position, "values": values[left:right + 1], "window_start": left, "window_end": right})
            gaussian = {**gaussian, "center": float(gaussian["center"]) + left, "boundary_adjusted": gaussian_adjusted}
            peak_height = float(gaussian["peak_height"])
        background = 0.0
        background_adjusted = False
        if int(line.get("background_offset_points", 0)):
            background_center = peak_position + int(line["background_offset_points"])
            left, right, background_adjusted = _bounded_range(background_center, 7, count)
            background = min(float(value) for value in values[left:right + 1])
        legacy_profile = run["calculation_profile"] == "legacy_2_0_2"
        stored_peak_height = _float32(peak_height) if legacy_profile else peak_height
        stored_background = _float32(background) if legacy_profile else background
        if int(line.get("background_offset_points", 0)):
            net = stored_peak_height / stored_background if line.get("line_type") == "analysis" and line.get("internal_standard_mode") == "background" and stored_background != 0 else stored_peak_height - stored_background
        else:
            net = stored_peak_height
        net = _legacy_floor(net) if legacy_profile else max(MIN_SIGNAL, net)
        quantitative = net
        if line.get("line_type") == "analysis" and line.get("internal_standard_mode") == "line":
            internal_id = str(line.get("internal_standard_line_id"))
            internal = db.execute("SELECT net_signal FROM analysis_line_results WHERE run_id=? AND sample_position=? AND line_id=?", (run["id"], sample_position, internal_id)).fetchone()
            if internal is None or float(internal["net_signal"]) <= 0:
                raise AnalysisError("analysis_internal_standard_missing", "普通内标线尚未产生有效结果", details={"line_id": line.get("id"), "internal_standard_line_id": internal_id})
            quantitative = _legacy_floor(net / float(internal["net_signal"])) if legacy_profile else max(MIN_SIGNAL, net / float(internal["net_signal"]))
        if run["calculation_profile"] == "modern_v1" and gaussian is not None:
            quantitative = float(gaussian["area"])
            if line.get("internal_standard_mode") == "background":
                quantitative = max(MIN_SIGNAL, quantitative / background) if background > 0 else MIN_SIGNAL
            elif line.get("internal_standard_mode") == "line":
                internal_id = str(line.get("internal_standard_line_id"))
                internal = db.execute("SELECT quantitative_signal FROM analysis_line_results WHERE run_id=? AND sample_position=? AND line_id=?", (run["id"], sample_position, internal_id)).fetchone()
                if internal is None or float(internal["quantitative_signal"]) <= 0:
                    raise AnalysisError("analysis_internal_standard_missing", "普通内标线尚未产生有效面积结果", details={"line_id": line.get("id"), "internal_standard_line_id": internal_id})
                quantitative = max(MIN_SIGNAL, quantitative / float(internal["quantitative_signal"]))
        window_left, window_right, _ = _bounded_range(peak_position, min(31, count), count)
        return {
            "sample_position": sample_position, "line_position": line_position, "line_id": str(line.get("id")), "line_type": line.get("line_type"), "element": line.get("element", ""), "wavelength_nm": float(line.get("wavelength_nm")), "ccd_index": ccd_index,
            "expected_position": float(expected_float), "corrected_expected_position": expected, "peak_position": peak_position,
            "peak_height": stored_peak_height,
            "background": stored_background, "net_signal": net,
            "gaussian_center": gaussian.get("center") if gaussian else None, "gaussian_peak_height": gaussian.get("peak_height") if gaussian else None,
            "gaussian_sigma": gaussian.get("sigma") if gaussian else None, "gaussian_area": gaussian.get("area") if gaussian else None,
            "quantitative_signal": quantitative, "calculation_profile": run["calculation_profile"],
            "intermediates": {"search": search, "reference_correction_points": correction, "corrected_expected_position": expected, "background_boundary_adjusted": background_adjusted, "gaussian": gaussian},
            "spectrum_window": [{"point_index": index, "value": float(values[index])} for index in range(window_left, window_right + 1)],
            "window_start": window_left, "window_end": window_right,
        }

    def _write_result(self, db: sqlite3.Connection, run_id: int, candidate: dict[str, Any], intervention_id: int | None = None) -> None:
        stored = {key: value for key, value in candidate.items() if key not in {"spectrum_window", "window_start", "window_end", "intermediates"}}
        digest = _sha(stored | {"intermediates": candidate["intermediates"], "intervention_id": intervention_id})
        db.execute(
            "INSERT INTO analysis_line_results(run_id, sample_position, line_position, line_id, line_type, element, wavelength_nm, ccd_index, expected_position, peak_position, peak_height, background, net_signal, gaussian_center, gaussian_peak_height, gaussian_sigma, gaussian_area, quantitative_signal, calculation_profile, intervention_id, intermediates_json, result_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, candidate["sample_position"], candidate["line_position"], candidate["line_id"], candidate["line_type"], candidate["element"], candidate["wavelength_nm"], candidate["ccd_index"], candidate["expected_position"], candidate["peak_position"], candidate["peak_height"], candidate["background"], candidate["net_signal"], candidate["gaussian_center"], candidate["gaussian_peak_height"], candidate["gaussian_sigma"], candidate["gaussian_area"], candidate["quantitative_signal"], candidate["calculation_profile"], intervention_id, _json(candidate["intermediates"]), digest, utc_now()),
        )

    def _advance(self, db: sqlite3.Connection, run: sqlite3.Row, lines: list[dict[str, Any]]) -> None:
        sample_position = int(run["current_sample_position"])
        line_position = int(run["current_line_position"]) + 1
        sample_count = int(db.execute("SELECT COUNT(*) FROM analysis_run_samples WHERE run_id=?", (run["id"],)).fetchone()[0])
        if line_position >= len(lines):
            rows = db.execute("SELECT line_id, element, wavelength_nm, quantitative_signal, calculation_profile FROM analysis_line_results WHERE run_id=? AND sample_position=? AND line_type='analysis' ORDER BY line_position", (run["id"], sample_position)).fetchall()
            matrix = [dict(row) for row in rows]
            db.execute("UPDATE analysis_run_samples SET result_matrix_json=?, result_sha256=?, completed_at=? WHERE run_id=? AND position=?", (_json(matrix), _sha(matrix), utc_now(), run["id"], sample_position))
            sample_position += 1
            line_position = 0
        if sample_position >= sample_count:
            matrices = [json.loads(row[0] or "[]") for row in db.execute("SELECT result_matrix_json FROM analysis_run_samples WHERE run_id=? ORDER BY position", (run["id"],)).fetchall()]
            result_hash = _sha(matrices)
            db.execute("UPDATE analysis_runs SET status='completed', current_sample_position=?, current_line_position=0, result_sha256=?, completed_at=?, updated_at=? WHERE id=?", (sample_position, result_hash, utc_now(), utc_now(), run["id"]))
            self._message(db, run["id"], "success", "analysis.run.completed", "全部样品定量分析完成", {"result_sha256": result_hash})
        else:
            db.execute("UPDATE analysis_runs SET status='running', current_sample_position=?, current_line_position=?, updated_at=? WHERE id=?", (sample_position, line_position, utc_now(), run["id"]))

    def start(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, _, _ = self._context(db, run_id)
            if run["status"] != "draft":
                raise AnalysisError("analysis_state_invalid", "只有草稿分析运行可以开始")
            db.execute("UPDATE analysis_runs SET status='running', started_at=?, updated_at=? WHERE id=?", (utc_now(), utc_now(), run_id))
            self._message(db, run_id, "info", "analysis.run.started", "分析运行已开始")
            self._audit(db, self._actor(db, actor_user_id), "analysis.run.start", run_id, {"input_sha256": run["input_sha256"]})
        return self.run(run_id)

    def step(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, lines = self._context(db, run_id)
            pending = db.execute("SELECT * FROM analysis_checkpoints WHERE run_id=? AND status='pending'", (run_id,)).fetchone()
            if pending is not None:
                if datetime.fromisoformat(pending["deadline_at"]) <= datetime.now(timezone.utc):
                    db.execute("UPDATE analysis_checkpoints SET status='cancelled', resolved_at=? WHERE id=?", (utc_now(), pending["id"]))
                    db.execute("UPDATE analysis_runs SET status='failed', failure_code='analysis_intervention_timeout', failure_message='慢进人工干预超时', failure_details_json=?, updated_at=? WHERE id=?", (_json({"checkpoint_id": pending["id"], "line_id": pending["line_id"]}), utc_now(), run_id))
                    self._message(db, run_id, "error", "analysis_intervention_timeout", "慢进人工干预超时", {"checkpoint_id": pending["id"]})
                    self._audit(db, self._actor(db, actor_user_id), "analysis.run.failed", run_id, {"code": "analysis_intervention_timeout", "checkpoint_id": pending["id"]})
                    return self._run_dict(db, run_id)
                raise AnalysisError("analysis_intervention_pending", "必须先处理当前慢进检查点", details={"checkpoint_id": pending["id"]})
            if run["status"] != "running":
                raise AnalysisError("analysis_state_invalid", "分析运行当前不能推进", details={"status": run["status"]})
            try:
                candidate = self._line_candidate(db, run, payload, lines, int(run["current_sample_position"]), int(run["current_line_position"]))
                if run["slow_mode"]:
                    sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_checkpoints WHERE run_id=?", (run_id,)).fetchone()[0])
                    deadline = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + float(run["intervention_timeout_seconds"]), timezone.utc).isoformat(timespec="milliseconds")
                    db.execute("INSERT INTO analysis_checkpoints(run_id, sequence, sample_position, line_position, line_id, status, automatic_position, window_start, window_end, spectrum_window_json, candidate_json, deadline_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)", (run_id, sequence, candidate["sample_position"], candidate["line_position"], candidate["line_id"], candidate["peak_position"], candidate["window_start"], candidate["window_end"], _json(candidate["spectrum_window"]), _json(candidate), deadline))
                    db.execute("UPDATE analysis_runs SET status='paused', updated_at=? WHERE id=?", (utc_now(), run_id))
                    self._message(db, run_id, "info", "analysis.checkpoint.pending", "已暂停在逐谱线慢进检查点", {"sequence": sequence, "line_id": candidate["line_id"]})
                else:
                    self._write_result(db, run_id, candidate)
                    self._advance(db, run, lines)
            except AnalysisError as exc:
                details = exc.details | {"sample_position": run["current_sample_position"], "line_position": run["current_line_position"]}
                db.execute("UPDATE analysis_runs SET status='failed', failure_code=?, failure_message=?, failure_details_json=?, updated_at=? WHERE id=?", (exc.code, exc.message, _json(details), utc_now(), run_id))
                self._message(db, run_id, "error", exc.code, exc.message, details)
                self._audit(db, self._actor(db, actor_user_id), "analysis.run.failed", run_id, {"code": exc.code, "details": details})
        return self.run(run_id)

    def intervene(self, run_id: int, action: str, adjusted_position: int | None, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, lines = self._context(db, run_id)
            checkpoint = db.execute("SELECT * FROM analysis_checkpoints WHERE run_id=? AND status='pending'", (run_id,)).fetchone()
            if run["status"] != "paused" or checkpoint is None:
                raise AnalysisError("analysis_checkpoint_missing", "没有待处理的慢进检查点")
            if datetime.fromisoformat(checkpoint["deadline_at"]) <= datetime.now(timezone.utc):
                raise AnalysisError("analysis_intervention_timeout", "慢进人工干预已超时")
            if action not in {"accept", "discard"}:
                raise AnalysisError("analysis_intervention_invalid", "干预动作无效", status_code=422)
            before = int(checkpoint["automatic_position"])
            after = before
            candidate = json.loads(checkpoint["candidate_json"])
            if action == "accept":
                if adjusted_position is None or not reason.strip():
                    raise AnalysisError("analysis_adjustment_reason_required", "接受人工定位必须填写调整位置和理由", status_code=422)
                after = int(adjusted_position)
                candidate = self._line_candidate(db, run, payload, lines, int(checkpoint["sample_position"]), int(checkpoint["line_position"]), forced_position=after)
            now = utc_now()
            cursor = db.execute("INSERT INTO analysis_interventions(run_id, checkpoint_id, action, before_position, after_position, reason, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (run_id, checkpoint["id"], action, before, after, reason.strip(), self._actor(db, actor_user_id), now))
            intervention_id = int(cursor.lastrowid)
            self._write_result(db, run_id, candidate, intervention_id)
            db.execute("UPDATE analysis_checkpoints SET status=?, accepted_position=?, resolved_at=? WHERE id=?", ("accepted" if action == "accept" else "discarded", after, now, checkpoint["id"]))
            self._audit(db, self._actor(db, actor_user_id), "analysis.intervention.accept" if action == "accept" else "analysis.intervention.discard", run_id, {"checkpoint_id": checkpoint["id"], "line_id": checkpoint["line_id"], "before_position": before, "after_position": after, "reason": reason.strip()})
            self._advance(db, run, lines)
        return self.run(run_id)

    def cancel(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, _, _ = self._context(db, run_id)
            if run["status"] not in {"draft", "running", "paused"}:
                raise AnalysisError("analysis_state_invalid", "分析运行当前不能取消")
            db.execute("UPDATE analysis_checkpoints SET status='cancelled', resolved_at=? WHERE run_id=? AND status='pending'", (utc_now(), run_id))
            db.execute("UPDATE analysis_runs SET status='cancelled', updated_at=?, completed_at=? WHERE id=?", (utc_now(), utc_now(), run_id))
            self._message(db, run_id, "warning", "analysis.run.cancelled", "分析运行已取消；未确认检查点未写入结果")
            self._audit(db, self._actor(db, actor_user_id), "analysis.run.cancel", run_id, {})
        return self.run(run_id)

    @staticmethod
    def _standard_index(name: str) -> int | None:
        match = re.fullmatch(r"S([0-9]+)", name.strip(), flags=re.IGNORECASE)
        if match is None:
            return None
        number = int(match.group(1))
        return number - 1 if 1 <= number <= 50 else None

    @staticmethod
    def _analysis_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [line for line in canonical_lines(payload.get("lines"), payload.get("conditions", {})) if line.get("enabled") and line.get("line_type") == "analysis"]

    def _qc_groups(self, db: sqlite3.Connection, run_id: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
        conditions = payload.get("conditions", {})
        latest: dict[int, sqlite3.Row] = {}
        accepted: set[tuple[int, str]] = set()
        for decision in db.execute("SELECT * FROM analysis_qc_decisions WHERE run_id=? ORDER BY id", (run_id,)).fetchall():
            if decision["line_result_id"] is None:
                if decision["action"] == "accept":
                    accepted.add((int(decision["acquisition_task_id"]), str(decision["line_id"])))
            else:
                latest[int(decision["line_result_id"])] = decision
        rows = db.execute(
            "SELECT lr.id AS line_result_id, lr.line_id, lr.element, lr.wavelength_nm, lr.quantitative_signal, lr.result_sha256 AS source_sha256, "
            "ars.sample_name, ars.position AS sample_position, s.repeat_index, s.sample_kind, s.task_id AS acquisition_task_id "
            "FROM analysis_line_results lr JOIN analysis_run_samples ars ON ars.run_id=lr.run_id AND ars.position=lr.sample_position "
            "JOIN acquisition_samples s ON s.id=ars.acquisition_sample_id "
            "WHERE lr.run_id=? AND lr.line_type='analysis' ORDER BY s.task_id, lr.line_position, s.repeat_index",
            (run_id,),
        ).fetchall()
        grouped: dict[tuple[int, str], list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault((int(row["acquisition_task_id"]), str(row["line_id"])), []).append(row)
        groups: list[dict[str, Any]] = []
        for (task_id, line_id), members in grouped.items():
            member_payload: list[dict[str, Any]] = []
            included_values: list[float] = []
            for row in members:
                decision = latest.get(int(row["line_result_id"]))
                included = True if decision is None else bool(decision["after_included"])
                value = float(row["quantitative_signal"])
                if included:
                    included_values.append(value)
                member_payload.append({
                    "line_result_id": int(row["line_result_id"]), "sample_position": int(row["sample_position"]),
                    "repeat_index": int(row["repeat_index"]), "value": value, "included": included,
                    "source_sha256": row["source_sha256"], "last_decision_id": int(decision["id"]) if decision else None,
                })
            stats = repeat_statistics(included_values)
            warnings: list[dict[str, Any]] = []
            if stats["effective_count"] == 0:
                warnings.append({"code": "analysis_qc_no_effective_repeat", "message": "全部重复已剔除，无法形成有效均值"})
            elif stats["effective_count"] == 1 and len(members) > 1:
                warnings.append({"code": "analysis_qc_single_effective_repeat", "message": "仅剩一个有效重复，标准差和 RSD 为零"})
            if stats["id"] is not None and stats["id"] > float(conditions.get("maximum_id_deviation", 5.0)):
                warnings.append({"code": "analysis_qc_id_exceeded", "message": "重复测量 ID 超过方法阈值", "actual": stats["id"], "threshold": float(conditions.get("maximum_id_deviation", 5.0))})
            if bool(conditions.get("rsd_enabled", True)) and stats["rsd"] is not None and stats["rsd"] > float(conditions.get("rsd_threshold", 5.0)):
                warnings.append({"code": "analysis_qc_rsd_exceeded", "message": "重复测量 RSD 超过方法阈值", "actual": stats["rsd"], "threshold": float(conditions.get("rsd_threshold", 5.0))})
            first = members[0]
            sample_name = str(first["sample_name"])
            groups.append({
                "acquisition_task_id": task_id, "sample_name": sample_name, "sample_kind": first["sample_kind"],
                "standard_index": self._standard_index(sample_name), "line_id": line_id, "element": first["element"],
                "wavelength_nm": float(first["wavelength_nm"]), "repeat_count": len(members), "members": member_payload,
                "statistics": stats, "warnings": warnings, "warning_accepted": (task_id, line_id) in accepted,
            })
        return groups

    def _write_qc_snapshot(self, db: sqlite3.Connection, run_id: int, payload: dict[str, Any], actor_user_id: int | None) -> int:
        groups = self._qc_groups(db, run_id, payload)
        sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_qc_snapshots WHERE run_id=?", (run_id,)).fetchone()[0])
        publishable = bool(groups) and all(group["statistics"]["effective_count"] > 0 for group in groups)
        snapshot = {"sequence": sequence, "groups": groups, "publishable": publishable}
        cursor = db.execute(
            "INSERT INTO analysis_qc_snapshots(run_id, sequence, groups_json, publishable, result_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, sequence, _json(groups), int(publishable), _sha(snapshot), self._actor(db, actor_user_id), utc_now()),
        )
        return int(cursor.lastrowid)

    def build_quality(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, _ = self._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_qc_run_incomplete", "只有已完成的定量分析可以进入重复质控")
            snapshot_id = self._write_qc_snapshot(db, run_id, payload, actor_user_id)
            self._audit(db, self._actor(db, actor_user_id), "analysis.qc.recalculate", run_id, {"qc_snapshot_id": snapshot_id})
        return self.run(run_id)

    def decide_quality(self, run_id: int, request: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        action = str(request.get("action"))
        task_id, line_id = int(request["acquisition_task_id"]), str(request["line_id"])
        line_result_id = request.get("line_result_id")
        reason = str(request.get("reason") or "").strip()
        with self.database.write() as db:
            run, payload, _ = self._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_qc_run_incomplete", "只有已完成的定量分析可以进行重复质控")
            groups = self._qc_groups(db, run_id, payload)
            group = next((item for item in groups if item["acquisition_task_id"] == task_id and item["line_id"] == line_id), None)
            if group is None:
                raise AnalysisError("analysis_qc_group_not_found", "重复质控组不存在", status_code=404)
            before: bool | None = None
            after: bool | None = None
            if action == "accept":
                if line_result_id is not None:
                    raise AnalysisError("analysis_qc_accept_scope_invalid", "接受提示是组级操作，不能指定重复记录", status_code=422)
            else:
                member = next((item for item in group["members"] if item["line_result_id"] == line_result_id), None)
                if member is None:
                    raise AnalysisError("analysis_qc_member_not_found", "重复测量记录不存在", status_code=404)
                before = bool(member["included"])
                after = action == "restore"
                if action == "exclude" and not before:
                    raise AnalysisError("analysis_qc_already_excluded", "该重复已经被剔除")
                if action == "restore" and before:
                    raise AnalysisError("analysis_qc_already_included", "该重复当前已有效")
            cursor = db.execute(
                "INSERT INTO analysis_qc_decisions(run_id, acquisition_task_id, line_id, line_result_id, action, before_included, after_included, reason, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, task_id, line_id, line_result_id, action, None if before is None else int(before), None if after is None else int(after), reason, self._actor(db, actor_user_id), utc_now()),
            )
            snapshot_id = self._write_qc_snapshot(db, run_id, payload, actor_user_id)
            self._audit(db, self._actor(db, actor_user_id), f"analysis.qc.{action}", run_id, {"decision_id": int(cursor.lastrowid), "qc_snapshot_id": snapshot_id, "acquisition_task_id": task_id, "line_id": line_id, "line_result_id": line_result_id, "reason": reason})
        return self.run(run_id)

    @staticmethod
    def _latest_qc(db: sqlite3.Connection, run_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM analysis_qc_snapshots WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        if row is None:
            raise AnalysisError("analysis_qc_missing", "请先计算重复测量质控")
        return row

    def _base_curve_points(self, line: dict[str, Any], qc: sqlite3.Row) -> list[dict[str, Any]]:
        groups = json.loads(qc["groups_json"])
        by_name: dict[str, dict[str, Any]] = {}
        for group in groups:
            if group["line_id"] == str(line.get("id")) and group.get("sample_kind") == "standard":
                by_name[str(group.get("sample_name") or "").strip().casefold()] = group
        points: list[dict[str, Any]] = []
        for index, standard in enumerate(line.get("standard_points") or []):
            name = str(standard.get("name") or f"S{index + 1}").strip()
            group = by_name.get(name.casefold())
            mean = group["statistics"]["mean"] if group else None
            points.append({
                "point_index": index, "name": name, "standard_value": float(standard["value"]),
                "original_intensity": mean, "adjusted_intensity": mean,
                "original_active": bool(standard.get("active", True)), "active": bool(standard.get("active", True)),
                "qc_group": {"acquisition_task_id": group["acquisition_task_id"], "effective_count": group["statistics"]["effective_count"]} if group else None,
            })
        return points

    def _curve_workspace(self, db: sqlite3.Connection, run_id: int, line: dict[str, Any], qc: sqlite3.Row) -> dict[str, Any]:
        latest = db.execute("SELECT * FROM analysis_curve_adjustment_sets WHERE run_id=? AND line_id=? AND qc_snapshot_id=? ORDER BY sequence DESC LIMIT 1", (run_id, str(line["id"]), qc["id"])).fetchone()
        if latest is None:
            return {"fit_mode": line.get("fit_mode", "linear"), "coordinate_type": line.get("coordinate_type", "normal"), "points": self._base_curve_points(line, qc), "adjustment_set_id": None, "sequence": 0}
        return {"fit_mode": latest["fit_mode"], "coordinate_type": latest["coordinate_type"], "points": json.loads(latest["points_json"]), "adjustment_set_id": int(latest["id"]), "sequence": int(latest["sequence"])}

    def _save_workspace(self, db: sqlite3.Connection, run_id: int, line_id: str, qc_id: int, workspace: dict[str, Any], actor_user_id: int | None) -> int:
        sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_curve_adjustment_sets WHERE run_id=? AND line_id=?", (run_id, line_id)).fetchone()[0])
        stored = {"fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "points": workspace["points"]}
        cursor = db.execute(
            "INSERT INTO analysis_curve_adjustment_sets(run_id, line_id, qc_snapshot_id, sequence, fit_mode, coordinate_type, points_json, workspace_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, line_id, qc_id, sequence, workspace["fit_mode"], workspace["coordinate_type"], _json(workspace["points"]), _sha(stored), self._actor(db, actor_user_id), utc_now()),
        )
        return int(cursor.lastrowid)

    def curve_action(self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        action, reason = str(request["action"]), str(request.get("reason") or "").strip()
        with self.database.write() as db:
            run, payload, _ = self._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_curve_run_incomplete", "只有已完成的分析可以调整标准曲线")
            line = next((item for item in self._analysis_lines(payload) if str(item["id"]) == line_id), None)
            if line is None:
                raise AnalysisError("analysis_curve_line_not_found", "分析线不存在", status_code=404)
            qc = self._latest_qc(db, run_id)
            workspace = self._curve_workspace(db, run_id, line, qc)
            before = {"fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "points": json.loads(_json(workspace["points"]))}
            index = request.get("point_index")
            point = None if index is None else next((item for item in workspace["points"] if item["point_index"] == int(index)), None)
            if action == "set_fit":
                if request.get("fit_mode") not in FIT_MODES:
                    raise AnalysisError("analysis_curve_fit_mode_invalid", "拟合方式无效", status_code=422)
                workspace["fit_mode"] = request["fit_mode"]
            elif action == "set_coordinate":
                if request.get("coordinate_type") not in COORDINATE_TYPES:
                    raise AnalysisError("analysis_curve_coordinate_invalid", "坐标方式无效", status_code=422)
                workspace["coordinate_type"] = request["coordinate_type"]
            elif action in {"set_active", "adjust", "restore"}:
                if point is None:
                    raise AnalysisError("analysis_curve_point_not_found", "标准点不存在", status_code=404)
                if action == "set_active":
                    if request.get("active") is None:
                        raise AnalysisError("analysis_curve_active_required", "必须提供标准点启用状态", status_code=422)
                    point["active"] = bool(request["active"])
                elif action == "adjust":
                    value = request.get("adjusted_intensity")
                    if value is None or not math.isfinite(float(value)):
                        raise AnalysisError("analysis_curve_adjustment_invalid", "修正强度必须是有限数字", status_code=422)
                    point["adjusted_intensity"] = float(value)
                else:
                    point["adjusted_intensity"] = point["original_intensity"]
            elif action == "restore_all":
                for item in workspace["points"]:
                    item["adjusted_intensity"] = item["original_intensity"]
                    item["active"] = item["original_active"]
            else:
                raise AnalysisError("analysis_curve_action_invalid", "曲线调整动作无效", status_code=422)
            after = {"fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "points": workspace["points"]}
            adjustment_id = self._save_workspace(db, run_id, line_id, int(qc["id"]), workspace, actor_user_id)
            cursor = db.execute(
                "INSERT INTO analysis_curve_actions(run_id, line_id, qc_snapshot_id, action, point_index, before_json, after_json, reason, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, line_id, qc["id"], action, index, _json(before), _json(after), reason, self._actor(db, actor_user_id), utc_now()),
            )
            self._audit(db, self._actor(db, actor_user_id), f"analysis.curve.{action}", run_id, {"line_id": line_id, "action_id": int(cursor.lastrowid), "adjustment_set_id": adjustment_id, "qc_snapshot_id": int(qc["id"]), "reason": reason})
        return self.run(run_id)

    @staticmethod
    def _fit_diagnostics(fit: dict[str, Any], points: list[dict[str, Any]], coordinate_type: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for point in points:
            calculated = evaluate_curve(fit, float(point["adjusted_intensity"]), coordinate_type)
            expected = float(point["standard_value"])
            rows.append({**point, "calculated_value": calculated, "residual": calculated - expected, "relative_error_percent": None if expected == 0 else 100.0 * (calculated - expected) / expected})
        expected_values = [float(item["standard_value"]) for item in rows]
        calculated_values = [float(item["calculated_value"]) for item in rows]
        mean_x, mean_y = sum(expected_values) / len(rows), sum(calculated_values) / len(rows)
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(expected_values, calculated_values, strict=True))
        denominator = math.sqrt(sum((x - mean_x) ** 2 for x in expected_values) * sum((y - mean_y) ** 2 for y in calculated_values))
        return {"points": rows, "correlation": None if denominator == 0 else numerator / denominator, "rmse": math.sqrt(sum(item["residual"] ** 2 for item in rows) / len(rows)), "maximum_absolute_error": max(abs(item["residual"]) for item in rows)}

    def fit_standard_curve(self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, _ = self._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_curve_run_incomplete", "只有已完成的分析可以拟合标准曲线")
            line = next((item for item in self._analysis_lines(payload) if str(item["id"]) == line_id), None)
            if line is None:
                raise AnalysisError("analysis_curve_line_not_found", "分析线不存在", status_code=404)
            qc = self._latest_qc(db, run_id)
            workspace = self._curve_workspace(db, run_id, line, qc)
            fit_mode = request.get("fit_mode") or workspace["fit_mode"]
            coordinate_type = request.get("coordinate_type") or workspace["coordinate_type"]
            if fit_mode != workspace["fit_mode"] or coordinate_type != workspace["coordinate_type"]:
                workspace["adjustment_set_id"] = None
            workspace["fit_mode"] = fit_mode
            workspace["coordinate_type"] = coordinate_type
            active = [item for item in workspace["points"] if item["active"] and item["adjusted_intensity"] is not None]
            fit = fit_curve([item["adjusted_intensity"] for item in active], [item["standard_value"] for item in active], workspace["fit_mode"], workspace["coordinate_type"])
            diagnostics = self._fit_diagnostics(fit, active, workspace["coordinate_type"])
            adjustment_id = workspace["adjustment_set_id"] or self._save_workspace(db, run_id, line_id, int(qc["id"]), workspace, actor_user_id)
            minimum_x, maximum_x = min(float(item["adjusted_intensity"]) for item in active), max(float(item["adjusted_intensity"]) for item in active)
            chart = [{"intensity": minimum_x + (maximum_x - minimum_x) * index / 120, "value": evaluate_curve(fit, minimum_x + (maximum_x - minimum_x) * index / 120, workspace["coordinate_type"])} for index in range(121)]
            sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_curve_snapshots WHERE run_id=? AND line_id=?", (run_id, line_id)).fetchone()[0])
            snapshot = {"run_id": run_id, "line_id": line_id, "qc_snapshot_id": int(qc["id"]), "adjustment_set_id": adjustment_id, "sequence": sequence, "fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "points": workspace["points"], "fit": fit, "diagnostics": diagnostics, "chart": chart, "publishable": bool(qc["publishable"])}
            cursor = db.execute(
                "INSERT INTO analysis_curve_snapshots(run_id, line_id, qc_snapshot_id, adjustment_set_id, sequence, fit_mode, coordinate_type, points_json, fit_json, diagnostics_json, chart_json, publishable, result_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, line_id, qc["id"], adjustment_id, sequence, workspace["fit_mode"], workspace["coordinate_type"], _json(workspace["points"]), _json(fit), _json(diagnostics), _json(chart), int(bool(qc["publishable"])), _sha(snapshot), self._actor(db, actor_user_id), utc_now()),
            )
            snapshot_id = int(cursor.lastrowid)
            self._audit(db, self._actor(db, actor_user_id), "analysis.curve.fit", run_id, {"line_id": line_id, "curve_snapshot_id": snapshot_id, "fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "qc_snapshot_id": int(qc["id"]), "reason": request.get("reason")})
        return self.run(run_id)

    @staticmethod
    def _curve_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for field in ("points_json", "fit_json", "diagnostics_json", "chart_json"):
            item[field.removesuffix("_json")] = json.loads(item.pop(field))
        item["publishable"] = bool(item["publishable"])
        return item

    def curve_evaluators(self, snapshot_ids: list[int], method_version_id: int, calculation_profile: str) -> dict[str, dict[str, Any]]:
        """Return immutable, version-checked curve evaluators for another application service."""

        requested = list(dict.fromkeys(int(value) for value in snapshot_ids))
        if not requested:
            raise AnalysisError("analysis_curve_selection_empty", "精确重算至少需要选择一个曲线快照")
        evaluators: dict[str, dict[str, Any]] = {}
        with self.database.read() as db:
            for snapshot_id in requested:
                row = db.execute(
                    "SELECT cs.*, ar.method_version_id, ar.calculation_profile "
                    "FROM analysis_curve_snapshots cs JOIN analysis_runs ar ON ar.id=cs.run_id WHERE cs.id=?",
                    (snapshot_id,),
                ).fetchone()
                if row is None:
                    raise AnalysisError("analysis_curve_snapshot_not_found", "曲线快照不存在", status_code=404, details={"curve_snapshot_id": snapshot_id})
                if int(row["method_version_id"]) != int(method_version_id):
                    raise AnalysisError(
                        "analysis_curve_method_mismatch",
                        "曲线快照与目标方法版本不一致",
                        details={"curve_snapshot_id": snapshot_id, "curve_method_version_id": int(row["method_version_id"]), "method_version_id": int(method_version_id)},
                    )
                if str(row["calculation_profile"]) != str(calculation_profile):
                    raise AnalysisError(
                        "analysis_curve_profile_mismatch",
                        "曲线快照与目标计算档案不一致",
                        details={"curve_snapshot_id": snapshot_id, "curve_profile": row["calculation_profile"], "calculation_profile": calculation_profile},
                    )
                if not bool(row["publishable"]):
                    raise AnalysisError("analysis_curve_not_publishable", "所选曲线快照不可发布", details={"curve_snapshot_id": snapshot_id})
                line_id = str(row["line_id"])
                if line_id in evaluators:
                    raise AnalysisError("analysis_curve_duplicate_line", "同一谱线只能选择一个曲线快照", details={"line_id": line_id})
                evaluators[line_id] = {
                    "curve_snapshot_id": snapshot_id,
                    "line_id": line_id,
                    "fit": json.loads(row["fit_json"]),
                    "coordinate_type": str(row["coordinate_type"]),
                    "result_sha256": str(row["result_sha256"]),
                }
        return evaluators

    def publish_standard_curve(self, run_id: int, line_id: str, curve_snapshot_id: int, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, _ = self._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_curve_run_incomplete", "只有已完成的分析可以发布标准曲线")
            curve = db.execute("SELECT * FROM analysis_curve_snapshots WHERE id=? AND run_id=? AND line_id=?", (curve_snapshot_id, run_id, line_id)).fetchone()
            if curve is None:
                raise AnalysisError("analysis_curve_snapshot_not_found", "曲线快照不存在", status_code=404)
            latest_qc = self._latest_qc(db, run_id)
            if int(curve["qc_snapshot_id"]) != int(latest_qc["id"]):
                raise AnalysisError("analysis_curve_qc_stale", "质控决定已变化，请基于最新质控重新拟合")
            if not curve["publishable"] or not latest_qc["publishable"]:
                raise AnalysisError("analysis_curve_not_publishable", "当前质控或拟合结果不可发布")
            fit, coordinate_type = json.loads(curve["fit_json"]), str(curve["coordinate_type"])
            groups = [item for item in json.loads(latest_qc["groups_json"]) if item["line_id"] == line_id]
            if not groups or any(item["statistics"]["effective_count"] <= 0 for item in groups):
                raise AnalysisError("analysis_curve_effective_repeats_insufficient", "存在没有有效重复的样品，不能发布曲线")
            line = next((item for item in self._analysis_lines(payload) if str(item["id"]) == line_id), None)
            if line is None:
                raise AnalysisError("analysis_curve_line_not_found", "分析线不存在", status_code=404)
            standards = line.get("standard_points") or []
            standard_values = {
                str(item.get("name") or f"S{index + 1}").strip().casefold(): float(item["value"])
                for index, item in enumerate(standards)
            }
            for group in groups:
                intensity = float(group["statistics"]["mean"])
                calculated = evaluate_curve(fit, intensity, coordinate_type)
                standard_value = standard_values.get(str(group["sample_name"]).strip().casefold()) if group["sample_kind"] == "standard" else None
                is_standard = standard_value is not None
                result = {"curve_snapshot_id": curve_snapshot_id, "acquisition_task_id": group["acquisition_task_id"], "sample_name": group["sample_name"], "sample_kind": group["sample_kind"], "is_standard": is_standard, "standard_value": standard_value, "effective_count": group["statistics"]["effective_count"], "intensity": intensity, "calculated_value": calculated}
                db.execute(
                    "INSERT OR IGNORE INTO analysis_curve_results(run_id, curve_snapshot_id, acquisition_task_id, sample_name, sample_kind, is_standard, standard_value, effective_count, intensity, calculated_value, result_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, curve_snapshot_id, group["acquisition_task_id"], group["sample_name"], group["sample_kind"], int(is_standard), standard_value, group["statistics"]["effective_count"], intensity, calculated, _sha(result), utc_now()),
                )
            db.execute(
                "INSERT INTO analysis_active_curves(run_id, line_id, curve_snapshot_id, updated_by, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(run_id,line_id) DO UPDATE SET curve_snapshot_id=excluded.curve_snapshot_id, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                (run_id, line_id, curve_snapshot_id, self._actor(db, actor_user_id), utc_now()),
            )
            self._audit(db, self._actor(db, actor_user_id), "analysis.curve.publish", run_id, {"line_id": line_id, "curve_snapshot_id": curve_snapshot_id, "result_sha256": curve["result_sha256"], "reason": reason})
        return self.run(run_id)

    def merge_results(self, run_id: int, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, _ = self._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_merge_run_incomplete", "只有已完成的分析可以合并结果")
            lines = self._analysis_lines(payload)
            active_rows = db.execute("SELECT ac.line_id, ac.curve_snapshot_id FROM analysis_active_curves ac WHERE ac.run_id=?", (run_id,)).fetchall()
            active = {str(row["line_id"]): int(row["curve_snapshot_id"]) for row in active_rows}
            missing = [str(line["id"]) for line in lines if str(line["id"]) not in active]
            if missing:
                raise AnalysisError("analysis_merge_curves_missing", "所有分析线必须先发布曲线", details={"line_ids": missing})
            candidates: dict[tuple[int, str], list[dict[str, Any]]] = {}
            sample_meta: dict[int, dict[str, Any]] = {}
            line_by_id = {str(line["id"]): line for line in lines}
            for line_id, snapshot_id in active.items():
                for row in db.execute("SELECT * FROM analysis_curve_results WHERE curve_snapshot_id=? AND is_standard=0 ORDER BY acquisition_task_id", (snapshot_id,)).fetchall():
                    task_id = int(row["acquisition_task_id"])
                    line = line_by_id[line_id]
                    sample_meta[task_id] = {"acquisition_task_id": task_id, "sample_name": row["sample_name"], "sample_kind": row["sample_kind"]}
                    candidates.setdefault((task_id, str(line["element"])), []).append({
                        "line_id": line_id, "wavelength_nm": float(line["wavelength_nm"]), "curve_snapshot_id": snapshot_id,
                        "value": float(row["calculated_value"]), "intensity": float(row["intensity"]),
                        "valid_range_min": float(line.get("valid_range_min", 0)), "valid_range_max": float(line.get("valid_range_max", 9_999_999)),
                        "line_order": int(line.get("order", 0)),
                    })
            merged_samples: list[dict[str, Any]] = []
            for task_id in sorted(sample_meta):
                values: list[dict[str, Any]] = []
                for (candidate_task, element), items in sorted(candidates.items(), key=lambda entry: (entry[0][0], min(item["line_order"] for item in entry[1]))):
                    if candidate_task != task_id:
                        continue
                    items.sort(key=lambda item: item["line_order"])
                    selected = next((item for item in items if item["valid_range_min"] <= item["value"] <= item["valid_range_max"]), items[-1])
                    values.append({"element": element, **{key: value for key, value in selected.items() if key != "line_order"}, "candidate_count": len(items)})
                merged_samples.append({**sample_meta[task_id], "values": values})
            curve_ids = [active[str(line["id"])] for line in lines]
            sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_result_merges WHERE run_id=?", (run_id,)).fetchone()[0])
            snapshot = {"sequence": sequence, "curve_snapshot_ids": curve_ids, "results": merged_samples}
            cursor = db.execute(
                "INSERT INTO analysis_result_merges(run_id, sequence, curve_snapshot_ids_json, results_json, result_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, sequence, _json(curve_ids), _json(merged_samples), _sha(snapshot), self._actor(db, actor_user_id), utc_now()),
            )
            merge_id = int(cursor.lastrowid)
            self._audit(db, self._actor(db, actor_user_id), "analysis.results.merge", run_id, {"merge_id": merge_id, "curve_snapshot_ids": curve_ids, "sample_count": len(merged_samples), "reason": reason})
        return self.run(run_id)

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
            curve = self._curve_row(row)
            self._audit(db, self._actor(db, actor_user_id), "analysis.curve.preview", run_id, {"curve_snapshot_id": curve_snapshot_id, "mode": mode, "result_sha256": row["result_sha256"]})
        return self._curve_preview_html(curve, mode)

    def print_curve(self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None = None) -> tuple[bytes, dict[str, Any]]:
        if mode not in {"image", "text"}:
            raise AnalysisError("analysis_curve_print_mode_invalid", "打印模式必须是 image 或 text", status_code=422)
        with self.database.write() as db:
            row = db.execute("SELECT * FROM analysis_curve_snapshots WHERE id=? AND run_id=?", (curve_snapshot_id, run_id)).fetchone()
            if row is None:
                raise AnalysisError("analysis_curve_snapshot_not_found", "曲线快照不存在", status_code=404)
            content = self._curve_pdf(self._curve_row(row), mode)
            digest = hashlib.sha256(content).hexdigest()
            cursor = db.execute(
                "INSERT INTO analysis_curve_print_jobs(run_id, curve_snapshot_id, mode, request_json, content_blob, content_sha256, byte_length, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, curve_snapshot_id, mode, _json({"mode": mode, "curve_result_sha256": row["result_sha256"]}), content, digest, len(content), self._actor(db, actor_user_id), utc_now()),
            )
            job_id = int(cursor.lastrowid)
            self._audit(db, self._actor(db, actor_user_id), "analysis.curve.print", run_id, {"print_job_id": job_id, "curve_snapshot_id": curve_snapshot_id, "mode": mode, "content_sha256": digest, "byte_length": len(content)})
        return content, {"job_id": job_id, "sha256": digest, "byte_length": len(content)}

    def _run_dict(self, db: sqlite3.Connection, run_id: int) -> dict[str, Any]:
        row = db.execute("SELECT r.*, m.name AS method_name FROM analysis_runs r JOIN methods m ON m.id=r.method_id WHERE r.id=?", (run_id,)).fetchone()
        if row is None:
            raise AnalysisError("analysis_run_not_found", "分析运行不存在", status_code=404)
        result = dict(row)
        result["slow_mode"] = bool(result["slow_mode"])
        for field in ("input_snapshot_json", "failure_details_json"):
            result[field.removesuffix("_json")] = json.loads(result.pop(field) or ("{}" if field == "failure_details_json" else "{}"))
        samples: list[dict[str, Any]] = []
        for sample in db.execute("SELECT * FROM analysis_run_samples WHERE run_id=? ORDER BY position", (run_id,)).fetchall():
            item = dict(sample)
            item["result_matrix"] = json.loads(item.pop("result_matrix_json") or "[]")
            samples.append(item)
        result["samples"] = samples
        result["line_results"] = []
        for line in db.execute("SELECT * FROM analysis_line_results WHERE run_id=? ORDER BY sample_position, line_position", (run_id,)).fetchall():
            item = dict(line)
            item["intermediates"] = json.loads(item.pop("intermediates_json"))
            result["line_results"].append(item)
        checkpoint = db.execute("SELECT * FROM analysis_checkpoints WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        result["checkpoint"] = None
        if checkpoint is not None:
            item = dict(checkpoint)
            item["spectrum_window"] = json.loads(item.pop("spectrum_window_json"))
            item["candidate"] = json.loads(item.pop("candidate_json"))
            result["checkpoint"] = item
        result["interventions"] = [dict(item) for item in db.execute("SELECT * FROM analysis_interventions WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        result["messages"] = [{**dict(item), "details": json.loads(item["details_json"]), **{"details_json": None}} for item in db.execute("SELECT * FROM analysis_messages WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        for message in result["messages"]:
            message.pop("details_json", None)
        decisions = [dict(item) for item in db.execute("SELECT * FROM analysis_qc_decisions WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        qc_rows = db.execute("SELECT * FROM analysis_qc_snapshots WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        qc_snapshots = []
        for snapshot in qc_rows:
            item = dict(snapshot); item["groups"] = json.loads(item.pop("groups_json")); item["publishable"] = bool(item["publishable"]); qc_snapshots.append(item)
        result["quality"] = {"latest_snapshot": qc_snapshots[-1] if qc_snapshots else None, "snapshot_history": [{key: item[key] for key in ("id", "sequence", "publishable", "result_sha256", "created_at")} for item in qc_snapshots], "decisions": decisions}
        version = db.execute("SELECT payload_json FROM method_versions WHERE id=?", (row["method_version_id"],)).fetchone()
        payload = json.loads(version["payload_json"]) if version else {}
        latest_qc_row = qc_rows[-1] if qc_rows else None
        active = {str(item["line_id"]): int(item["curve_snapshot_id"]) for item in db.execute("SELECT * FROM analysis_active_curves WHERE run_id=?", (run_id,)).fetchall()}
        curve_lines: list[dict[str, Any]] = []
        for line in self._analysis_lines(payload):
            line_id = str(line["id"])
            snapshots = [self._curve_row(item) for item in db.execute("SELECT * FROM analysis_curve_snapshots WHERE run_id=? AND line_id=? ORDER BY sequence", (run_id, line_id)).fetchall()]
            workspace = self._curve_workspace(db, run_id, line, latest_qc_row) if latest_qc_row is not None else {"fit_mode": line.get("fit_mode", "linear"), "coordinate_type": line.get("coordinate_type", "normal"), "points": [], "adjustment_set_id": None, "sequence": 0}
            curve_lines.append({
                "line_id": line_id, "element": line.get("element", ""), "wavelength_nm": float(line.get("wavelength_nm", 0)),
                "unit": line.get("unit", ""), "workspace": workspace, "snapshots": snapshots,
                "active_curve_snapshot_id": active.get(line_id),
            })
        actions: list[dict[str, Any]] = []
        for action in db.execute("SELECT * FROM analysis_curve_actions WHERE run_id=? ORDER BY id", (run_id,)).fetchall():
            item = dict(action); item["before"] = json.loads(item.pop("before_json")); item["after"] = json.loads(item.pop("after_json")); actions.append(item)
        curve_results = [dict(item) | {"is_standard": bool(item["is_standard"])} for item in db.execute("SELECT * FROM analysis_curve_results WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        merges: list[dict[str, Any]] = []
        for merge in db.execute("SELECT * FROM analysis_result_merges WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall():
            item = dict(merge); item["curve_snapshot_ids"] = json.loads(item.pop("curve_snapshot_ids_json")); item["results"] = json.loads(item.pop("results_json")); merges.append(item)
        print_jobs = [dict(item) for item in db.execute("SELECT id, run_id, curve_snapshot_id, mode, request_json, content_sha256, byte_length, actor_user_id, created_at FROM analysis_curve_print_jobs WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        for item in print_jobs:
            item["request"] = json.loads(item.pop("request_json"))
        result["curves"] = {"lines": curve_lines, "actions": actions, "results": curve_results, "merges": merges, "print_jobs": print_jobs}
        return result

    def run(self, run_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            return self._run_dict(db, run_id)
