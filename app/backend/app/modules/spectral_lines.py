from __future__ import annotations

import json
import math
import sqlite3
import uuid
from copy import deepcopy
from typing import Any

from ..db import Database, utc_now
from ..schemas import SpectralLineInput
from .methods import MethodDomainError, MethodService, _json


REFERENCE_BASELINE_ID = "reference-baseline"
MAX_LINE_COUNT = 300
MIN_WAVELENGTH_NM = 160.0
MAX_WAVELENGTH_NM = 800.0
DUPLICATE_WAVELENGTH_TOLERANCE_NM = 0.01
MAX_ACTUAL_WAVELENGTH_OFFSET_NM = 0.3
ELEMENT_MAX_GB18030_BYTES = 4
MIN_STANDARD_POINTS = 4
MAX_STANDARD_POINTS = 50
STANDARD_VALUE_TOLERANCE = 9.5e-7
ELEMENT_SYMBOLS = (
    "Ag", "Al", "Ar", "As", "Au", "B", "Ba", "Be", "Bi", "Br", "C", "Ca", "Cd",
    "Ce", "Cl", "Co", "Cr", "Cs", "Cu", "Dy", "Er", "Eu", "Fe", "Ga", "Gd", "Ge",
    "H", "He", "Hf", "Hg", "Ho", "I", "In", "Ir", "K", "Kr", "La", "Li", "Lu", "Mg",
    "Mn", "Mo", "N", "Na", "Nb", "Nd", "Ne", "Ni", "O", "Os", "P", "Pb", "Pd", "Po",
    "Pr", "Pt", "Pu", "Ra", "Rb", "Re", "Rh", "Rn", "Ru", "S", "Sb", "Sc", "Se", "Si",
    "Sm", "Sn", "Sr", "Ta", "Tb", "Tc", "Te", "Th", "Ti", "Tl", "Tm", "U", "V", "W",
    "Xe", "Y", "Yb", "Zn", "Zr",
)


def reference_baseline(conditions: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": REFERENCE_BASELINE_ID,
        "order": 0,
        "line_type": "baseline",
        "element": "基线",
        "wavelength_nm": conditions.get("reference_wavelength_nm", 253.65),
        "actual_wavelength_nm": conditions.get("actual_reference_wavelength_nm", 253.65),
        "enabled": True,
        "critical_band": False,
        "priority": 0,
        "background_line_id": None,
        "alignment_line_id": None,
        "internal_standard_mode": "none",
        "internal_standard_line_id": None,
        "scan_width_points": conditions.get("reference_width_points", 21),
        "background_offset_points": 0,
        "peak_mode": "maximum",
        "peak_width_points": 1,
        "fit_mode": "linear",
        "coordinate_type": "linear",
        "unit": conditions.get("analysis_unit", "ug/g"),
        "value_kind": "content",
        "decimal_places": 2,
        "lower_peak": 300,
        "minimum_peak_ratio": 1.5,
        "valid_range_min": 0.0,
        "valid_range_max": 9_999_999.0,
        "over_limit_tolerance_percent": 0.0,
        "standard_points": [],
        "reference_baseline": True,
    }


def canonical_lines(lines: Any, conditions: dict[str, Any]) -> list[dict[str, Any]]:
    result = [deepcopy(item) for item in lines] if isinstance(lines, list) else []
    baselines = [item for item in result if isinstance(item, dict) and item.get("line_type") == "baseline"]
    if not baselines:
        result.insert(0, reference_baseline(conditions))
        baselines = [result[0]]
    primary = baselines[0]
    primary.update(
        {
            "id": primary.get("id") or REFERENCE_BASELINE_ID,
            "order": 0,
            "element": "基线",
            "wavelength_nm": conditions.get("reference_wavelength_nm", 253.65),
            "actual_wavelength_nm": conditions.get("actual_reference_wavelength_nm", 253.65),
            "scan_width_points": conditions.get("reference_width_points", 21),
            "unit": conditions.get("analysis_unit", "ug/g"),
            "enabled": True,
            "reference_baseline": True,
        }
    )
    others = [item for item in result if item is not primary]
    others.sort(key=lambda item: (item.get("order", 10_000) if isinstance(item, dict) else 10_000))
    for order, item in enumerate(others, start=1):
        if isinstance(item, dict):
            item["order"] = order
            item["reference_baseline"] = False
    return [primary, *others]


def _issue(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


def detect_wavelength(
    method_service: MethodService,
    db: sqlite3.Connection,
    conditions: dict[str, Any],
    wavelength_nm: Any,
    actual_wavelength_nm: Any = None,
    scan_width_points: Any = 9,
) -> dict[str, Any]:
    if isinstance(wavelength_nm, bool) or not isinstance(wavelength_nm, (int, float)) or not math.isfinite(float(wavelength_nm)):
        return {"detectable": False, "reason_code": "wavelength_required", "message": "波长必须是有限数字"}
    theoretical = float(wavelength_nm)
    actual = theoretical if actual_wavelength_nm is None else actual_wavelength_nm
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(float(actual)):
        return {"detectable": False, "reason_code": "actual_wavelength_required", "message": "实际波长必须是有限数字"}
    measured = float(actual)
    if theoretical < MIN_WAVELENGTH_NM or theoretical > MAX_WAVELENGTH_NM:
        return {
            "detectable": False,
            "reason_code": "wavelength_out_of_global_range",
            "message": "理论波长必须在 160–800 nm 范围内",
        }
    if abs(measured - theoretical) > MAX_ACTUAL_WAVELENGTH_OFFSET_NM:
        return {
            "detectable": False,
            "reason_code": "actual_wavelength_offset_too_large",
            "message": "实际波长与理论值偏差不能大于 0.3 nm",
        }
    layout = method_service._layout(db, conditions.get("ccd_layout_id", "default"))
    if layout is None:
        return {"detectable": False, "reason_code": "ccd_layout_not_found", "message": "未找到 CCD 布局"}
    dispersion = method_service._dispersion(
        db, conditions.get("dispersion_calibration_id", "default")
    )
    if dispersion is None:
        return {"detectable": False, "reason_code": "dispersion_not_found", "message": "未找到色散引用"}
    if int(dispersion["ccd_layout_id"]) != int(layout["id"]):
        return {"detectable": False, "reason_code": "dispersion_layout_mismatch", "message": "色散引用与 CCD 布局不匹配"}
    position = method_service._reference_position(measured, layout, dispersion)
    if position is None:
        return {
            "detectable": False,
            "reason_code": "wavelength_not_on_ccd",
            "message": "波长不在当前 CCD/色散覆盖范围内",
        }
    ccd_index, point_index, safe = position
    selected = conditions.get("selected_ccds", [])
    if ccd_index not in selected:
        return {
            "detectable": False,
            "reason_code": "ccd_not_selected",
            "message": f"波长位于 CCD{ccd_index + 1}，但该 CCD 未启用",
            "ccd_index": ccd_index,
            "point_index": round(point_index, 3),
        }
    if not safe:
        return {
            "detectable": False,
            "reason_code": "wavelength_outside_safe_boundary",
            "message": "波长超出 CCD 安全边界",
            "ccd_index": ccd_index,
            "point_index": round(point_index, 3),
        }
    if isinstance(scan_width_points, bool) or not isinstance(scan_width_points, int):
        return {"detectable": False, "reason_code": "scan_width_invalid", "message": "扫描宽度必须是整数"}
    frame_index = ccd_index // int(layout["ccds_per_frame"])
    exposures = conditions.get("angle_exposures", [])
    angle = exposures[frame_index].get("angle_deg") if isinstance(exposures, list) and frame_index < len(exposures) and isinstance(exposures[frame_index], dict) else None
    return {
        "detectable": True,
        "reason_code": "detectable",
        "message": "谱线位于可检测范围",
        "ccd_index": ccd_index,
        "ccd_label": f"CCD {ccd_index + 1}",
        "point_index": round(point_index, 3),
        "frame_index": frame_index,
        "angle_slot": frame_index + 1,
        "angle_deg": angle,
    }


def validate_spectral_lines(
    method_service: MethodService,
    db: sqlite3.Connection,
    conditions: dict[str, Any],
    lines: Any,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(lines, list):
        return [_issue("lines", "line_collection_invalid", "谱线集合必须是数组")]
    if len(lines) > MAX_LINE_COUNT:
        errors.append(_issue("lines", "line_limit_exceeded", "每个方法最多保存 300 条谱线"))
    baselines = [item for item in lines if isinstance(item, dict) and item.get("line_type") == "baseline"]
    if len(baselines) != 1:
        errors.append(_issue("lines", "reference_baseline_count", "方法必须且只能有一条参考基线"))

    ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    nonbaseline_waves: list[tuple[int, float]] = []
    valid_types = {"baseline", "analysis", "internal_standard", "alignment"}
    valid_peak_modes = {"maximum", "gaussian"}
    valid_fit_modes = {"linear", "quadratic", "cubic", "spline"}
    valid_coords = {"linear", "logarithmic"}
    valid_units = {"ug/g", "mg/g", "%"}

    def number(prefix: str, line: dict[str, Any], field: str, minimum: float | None = None, maximum: float | None = None, *, integer: bool = False) -> float | None:
        value = line.get(field)
        path = f"{prefix}.{field}"
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append(_issue(path, "number_required", "必须是有限数字"))
            return None
        result = float(value)
        if integer and not result.is_integer():
            errors.append(_issue(path, "integer_required", "必须是整数"))
        if minimum is not None and result < minimum:
            errors.append(_issue(path, "below_minimum", f"不能小于 {minimum:g}"))
        if maximum is not None and result > maximum:
            errors.append(_issue(path, "above_maximum", f"不能大于 {maximum:g}"))
        return result

    for index, line in enumerate(lines):
        prefix = f"lines.{index}"
        if not isinstance(line, dict):
            errors.append(_issue(prefix, "line_invalid", "谱线必须是对象"))
            continue
        line_id = line.get("id")
        if not isinstance(line_id, str) or not line_id:
            errors.append(_issue(f"{prefix}.id", "line_id_required", "谱线 ID 不能为空"))
        elif line_id in ids:
            errors.append(_issue(f"{prefix}.id", "line_id_duplicate", "谱线 ID 不能重复"))
        else:
            ids.append(line_id)
            by_id[line_id] = line
        line_type = line.get("line_type")
        if line_type not in valid_types:
            errors.append(_issue(f"{prefix}.line_type", "line_type_invalid", "谱线类型无效"))
        element = line.get("element")
        if not isinstance(element, str) or not element.strip():
            errors.append(_issue(f"{prefix}.element", "element_required", "元素符号不能为空"))
        else:
            try:
                element_bytes = len(element.strip().encode("gb18030"))
            except UnicodeEncodeError:
                element_bytes = ELEMENT_MAX_GB18030_BYTES + 1
            if element_bytes > ELEMENT_MAX_GB18030_BYTES:
                errors.append(_issue(f"{prefix}.element", "element_too_long", "元素符号不能超过 4 个 GB18030 字节"))
        wave = number(prefix, line, "wavelength_nm", MIN_WAVELENGTH_NM, MAX_WAVELENGTH_NM)
        actual = number(prefix, line, "actual_wavelength_nm", MIN_WAVELENGTH_NM, MAX_WAVELENGTH_NM)
        if wave is not None and actual is not None and abs(actual - wave) > MAX_ACTUAL_WAVELENGTH_OFFSET_NM:
            errors.append(_issue(f"{prefix}.actual_wavelength_nm", "actual_wavelength_offset_too_large", "实际波长与理论值偏差不能大于 0.3 nm"))
        if wave is not None and line_type != "baseline":
            nonbaseline_waves.append((index, wave))
        detection = detect_wavelength(
            method_service, db, conditions, wave, actual, line.get("scan_width_points")
        ) if wave is not None and actual is not None else None
        if detection is not None and not detection["detectable"]:
            errors.append(_issue(f"{prefix}.wavelength_nm", detection["reason_code"], detection["message"]))

        if not isinstance(line.get("enabled"), bool):
            errors.append(_issue(f"{prefix}.enabled", "boolean_required", "启用状态必须是布尔值"))
        if not isinstance(line.get("critical_band"), bool):
            errors.append(_issue(f"{prefix}.critical_band", "boolean_required", "关键波段标记必须是布尔值"))
        number(prefix, line, "priority", 0, 100, integer=True)
        width_limits = (11, 50) if line_type == "baseline" else (5, 31)
        scan_width = number(prefix, line, "scan_width_points", *width_limits, integer=True)
        number(prefix, line, "background_offset_points", -100, 100, integer=True)
        peak_mode = line.get("peak_mode")
        peak_width = number(prefix, line, "peak_width_points", 1, 9, integer=True)
        if peak_mode not in valid_peak_modes:
            errors.append(_issue(f"{prefix}.peak_mode", "peak_mode_invalid", "峰值方式无效"))
        elif peak_mode == "maximum" and peak_width is not None and int(peak_width) != 1:
            errors.append(_issue(f"{prefix}.peak_width_points", "maximum_peak_width", "最大值模式只能使用 1 个计算点"))
        elif peak_mode == "gaussian" and peak_width is not None:
            if int(peak_width) < 3 or int(peak_width) > 9 or int(peak_width) % 2 == 0:
                errors.append(_issue(f"{prefix}.peak_width_points", "gaussian_points_invalid", "高斯计算点数必须是 3–9 的奇数"))
            if scan_width is not None and peak_width > scan_width:
                errors.append(_issue(f"{prefix}.peak_width_points", "peak_width_exceeds_scan", "计算点数不能大于扫描宽度"))
        if line.get("fit_mode") not in valid_fit_modes:
            errors.append(_issue(f"{prefix}.fit_mode", "fit_mode_invalid", "拟合方式无效"))
        if line.get("coordinate_type") not in valid_coords:
            errors.append(_issue(f"{prefix}.coordinate_type", "coordinate_type_invalid", "拟合坐标无效"))
        if line.get("unit") not in valid_units:
            errors.append(_issue(f"{prefix}.unit", "unit_invalid", "单位只能是 ug/g、mg/g 或 %"))
        if line.get("value_kind") not in {"content", "concentration"}:
            errors.append(_issue(f"{prefix}.value_kind", "value_kind_invalid", "数值类型只能是含量或浓度"))
        number(prefix, line, "decimal_places", 0, 6, integer=True)
        number(prefix, line, "lower_peak", 100, 600, integer=True)
        number(prefix, line, "minimum_peak_ratio", 1.1, 2.5)
        minimum = number(prefix, line, "valid_range_min", 0, 9_999_999)
        maximum = number(prefix, line, "valid_range_max", 0, 9_999_999)
        if minimum is not None and maximum is not None and maximum <= minimum:
            errors.append(_issue(f"{prefix}.valid_range_max", "valid_range_order", "有效范围上限必须大于下限"))
        number(prefix, line, "over_limit_tolerance_percent", 0, 100)

        points = line.get("standard_points")
        if line_type == "analysis":
            if not isinstance(points, list) or not MIN_STANDARD_POINTS <= len(points) <= MAX_STANDARD_POINTS:
                errors.append(_issue(f"{prefix}.standard_points", "standard_point_count", "分析线必须配置 4–50 个标准点"))
            else:
                point_values: list[float] = []
                for point_index, point in enumerate(points):
                    point_path = f"{prefix}.standard_points.{point_index}.value"
                    value = point.get("value") if isinstance(point, dict) else None
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 9.9e-7 <= float(value) <= 9_999_999:
                        errors.append(_issue(point_path, "standard_value_invalid", "标准点必须在 0.00000099–9999999 范围内"))
                        continue
                    numeric = float(value)
                    if any(abs(numeric - existing) <= STANDARD_VALUE_TOLERANCE for existing in point_values):
                        errors.append(_issue(point_path, "standard_value_duplicate", "标准点数值不能重复"))
                    point_values.append(numeric)
        elif isinstance(points, list) and points:
            errors.append(_issue(f"{prefix}.standard_points", "standard_points_not_allowed", "只有分析线可以配置标准点"))

    for left_index, left_wave in nonbaseline_waves:
        for right_index, right_wave in nonbaseline_waves:
            if right_index <= left_index:
                continue
            if abs(left_wave - right_wave) <= DUPLICATE_WAVELENGTH_TOLERANCE_NM:
                errors.append(_issue(f"lines.{right_index}.wavelength_nm", "line_wavelength_duplicate", "±0.01 nm 内已存在近似谱线"))

    graph: dict[str, list[str]] = {}
    for index, line in enumerate(lines):
        if not isinstance(line, dict) or not isinstance(line.get("id"), str):
            continue
        prefix = f"lines.{index}"
        line_id = line["id"]
        refs = {
            "background_line_id": "baseline",
            "alignment_line_id": ("alignment", "internal_standard"),
            "internal_standard_line_id": "internal_standard",
        }
        graph[line_id] = []
        for field, expected in refs.items():
            reference = line.get(field)
            if reference is None:
                continue
            graph[line_id].append(reference)
            target = by_id.get(reference)
            if reference == line_id:
                errors.append(_issue(f"{prefix}.{field}", "line_self_reference", "谱线不能引用自身"))
            elif target is None:
                errors.append(_issue(f"{prefix}.{field}", "line_reference_not_found", "引用的谱线不存在"))
            else:
                expected_types = {expected} if isinstance(expected, str) else set(expected)
                if target.get("line_type") not in expected_types:
                    errors.append(_issue(f"{prefix}.{field}", "line_reference_type", "引用的谱线类型不匹配"))
                if not target.get("enabled", False):
                    errors.append(_issue(f"{prefix}.{field}", "line_reference_disabled", "不能引用已停用谱线"))
        mode = line.get("internal_standard_mode")
        if line.get("line_type") == "analysis":
            if mode not in {"none", "background", "line"}:
                errors.append(_issue(f"{prefix}.internal_standard_mode", "internal_standard_mode_invalid", "内标方式无效"))
            elif mode == "background" and line.get("background_line_id") is None:
                errors.append(_issue(f"{prefix}.background_line_id", "background_reference_required", "背景内标必须引用参考基线"))
            elif mode == "line" and line.get("internal_standard_line_id") is None:
                errors.append(_issue(f"{prefix}.internal_standard_line_id", "internal_standard_required", "普通内标必须引用内标线"))
        elif mode != "none" or line.get("internal_standard_line_id") is not None:
            errors.append(_issue(f"{prefix}.internal_standard_mode", "internal_standard_not_allowed", "只有分析线可以配置内标"))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for target in graph.get(node, []):
            if target in graph and visit(target):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(visit(node) for node in graph):
        errors.append(_issue("lines", "line_reference_cycle", "谱线引用不能形成循环"))
    return errors


class SpectralLineService:
    def __init__(self, database: Database):
        self.database = database
        self.methods = MethodService(database)

    def options(self) -> dict[str, Any]:
        return {
            "element_symbols": list(ELEMENT_SYMBOLS),
            "line_types": [
                {"value": "baseline", "label": "参考基线"},
                {"value": "analysis", "label": "分析线"},
                {"value": "internal_standard", "label": "内标线"},
                {"value": "alignment", "label": "定位线"},
            ],
            "internal_standard_modes": [
                {"value": "none", "label": "无内标"},
                {"value": "background", "label": "背景内标"},
                {"value": "line", "label": "普通内标线"},
            ],
            "peak_modes": [{"value": "maximum", "label": "最大值"}, {"value": "gaussian", "label": "高斯曲线"}],
            "fit_modes": [
                {"value": "linear", "label": "直线函数"},
                {"value": "quadratic", "label": "二次曲线"},
                {"value": "cubic", "label": "三次曲线"},
                {"value": "spline", "label": "样条函数"},
            ],
            "coordinate_types": [{"value": "linear", "label": "普通坐标"}, {"value": "logarithmic", "label": "对数坐标"}],
            "limits": {
                "wavelength_nm": [160, 800],
                "duplicate_tolerance_nm": 0.01,
                "actual_offset_nm": 0.3,
                "line_count": 300,
                "scan_width_points": [5, 31],
                "gaussian_points": [3, 9],
                "standard_points": [4, 50],
                "decimal_places": [0, 6],
            },
        }

    @staticmethod
    def _method_row(db: sqlite3.Connection, method_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM methods WHERE id=? AND status <> 'deleted'", (method_id,)).fetchone()
        if row is None:
            raise MethodDomainError("method_not_found", "方法不存在", status_code=404)
        return row

    def _payload(self, db: sqlite3.Connection, method_id: int) -> tuple[sqlite3.Row, dict[str, Any]]:
        row = self._method_row(db, method_id)
        latest = self.methods._latest_row(db, method_id)
        if latest is None:
            raise MethodDomainError("method_version_not_found", "方法版本不存在", status_code=404)
        payload = json.loads(latest["payload_json"])
        conditions = payload.get("conditions", {})
        payload["lines"] = canonical_lines(payload.get("lines"), conditions)
        return row, payload

    def _audit(self, db: sqlite3.Connection, actor_user_id: int | None, action: str, method_id: int, line_id: str | None, details: dict[str, Any]) -> None:
        actor = self.methods._valid_actor(db, actor_user_id)
        payload = {"method_id": method_id, "line_id": line_id, **details}
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'spectral_line', ?, ?, ?)",
            (actor, action, method_id, _json(payload), utc_now()),
        )

    def _commit(self, db: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any], actor_user_id: int, action: str, line_id: str | None, details: dict[str, Any]) -> dict[str, Any]:
        conditions = payload.get("conditions", {})
        payload["lines"] = canonical_lines(payload.get("lines"), conditions)
        line_errors = validate_spectral_lines(self.methods, db, conditions, payload["lines"])
        if line_errors:
            raise MethodDomainError(
                "invalid_spectral_line",
                "谱线未通过校验",
                fields=sorted({item["field"] for item in line_errors}),
                details={"validation_errors": line_errors},
            )
        now = utc_now()
        version, method_errors = self.methods._insert_payload_draft(
            db, int(row["id"]), payload, actor_user_id, now
        )
        db.execute("UPDATE methods SET updated_at=? WHERE id=?", (now, row["id"]))
        self._audit(db, actor_user_id, action, int(row["id"]), line_id, {"version": version, "validation_issue_count": len(method_errors), **details})
        updated = db.execute("SELECT * FROM methods WHERE id=?", (row["id"],)).fetchone()
        state = db.execute("SELECT current_method_id FROM method_runtime_state WHERE id=1").fetchone()
        return self.methods._method_dict(db, updated, current_id=state[0] if state else None)

    def list(self, method_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            _, payload = self._payload(db, method_id)
            conditions = payload.get("conditions", {})
            latest = self.methods._latest_row(db, method_id)
            lines = []
            for line in payload["lines"]:
                item = deepcopy(line)
                item["detectability"] = detect_wavelength(
                    self.methods,
                    db,
                    conditions,
                    item.get("wavelength_nm"),
                    item.get("actual_wavelength_nm"),
                    item.get("scan_width_points"),
                )
                lines.append(item)
            return {"method_id": method_id, "version": latest["version"], "state": latest["state"], "lines": lines}

    def detect(self, method_id: int, wavelength_nm: float, actual_wavelength_nm: float | None, scan_width_points: int) -> dict[str, Any]:
        with self.database.read() as db:
            _, payload = self._payload(db, method_id)
            return detect_wavelength(self.methods, db, payload.get("conditions", {}), wavelength_nm, actual_wavelength_nm, scan_width_points)

    def create(self, method_id: int, value: SpectralLineInput, actor_user_id: int) -> dict[str, Any]:
        if value.line_type == "baseline":
            raise MethodDomainError("reference_baseline_exists", "参考基线由方法条件维护，不能重复新增", fields=["line_type"])
        with self.database.write() as db:
            row, payload = self._payload(db, method_id)
            lines = payload["lines"]
            if len(lines) >= MAX_LINE_COUNT:
                raise MethodDomainError("line_limit_exceeded", "每个方法最多保存 300 条谱线", fields=["lines"])
            line = value.model_dump(mode="json")
            line["id"] = uuid.uuid4().hex
            line["order"] = len(lines)
            if line["actual_wavelength_nm"] is None:
                line["actual_wavelength_nm"] = line["wavelength_nm"]
            line["reference_baseline"] = False
            payload["lines"] = [*lines, line]
            return self._commit(db, row, payload, actor_user_id, "spectral_line.create", line["id"], {"line_type": line["line_type"], "wavelength_nm": line["wavelength_nm"]})

    def update(self, method_id: int, line_id: str, value: SpectralLineInput, actor_user_id: int) -> dict[str, Any]:
        if line_id == REFERENCE_BASELINE_ID or value.line_type == "baseline":
            raise MethodDomainError("reference_baseline_readonly", "参考基线请在方法条件中维护", fields=["line_type"], status_code=409)
        with self.database.write() as db:
            row, payload = self._payload(db, method_id)
            index = next((index for index, line in enumerate(payload["lines"]) if line.get("id") == line_id), None)
            if index is None:
                raise MethodDomainError("spectral_line_not_found", "谱线不存在", status_code=404)
            previous = payload["lines"][index]
            replacement = value.model_dump(mode="json")
            replacement.update({"id": line_id, "order": previous["order"], "reference_baseline": False})
            if replacement["actual_wavelength_nm"] is None:
                replacement["actual_wavelength_nm"] = replacement["wavelength_nm"]
            payload["lines"][index] = replacement
            action = "spectral_line.toggle" if previous.get("enabled") != replacement.get("enabled") else "spectral_line.update"
            return self._commit(db, row, payload, actor_user_id, action, line_id, {"enabled": replacement["enabled"], "wavelength_nm": replacement["wavelength_nm"]})

    def delete(self, method_id: int, line_id: str, actor_user_id: int) -> dict[str, Any]:
        if line_id == REFERENCE_BASELINE_ID:
            raise MethodDomainError("reference_baseline_readonly", "参考基线不能删除", status_code=409)
        with self.database.write() as db:
            row, payload = self._payload(db, method_id)
            target = next((line for line in payload["lines"] if line.get("id") == line_id), None)
            if target is None:
                raise MethodDomainError("spectral_line_not_found", "谱线不存在", status_code=404)
            dependent_ids = [
                line.get("id")
                for line in payload["lines"]
                if line.get("background_line_id") == line_id
                or line.get("alignment_line_id") == line_id
                or line.get("internal_standard_line_id") == line_id
            ]
            if dependent_ids:
                raise MethodDomainError("spectral_line_in_use", "谱线仍被其他谱线引用，不能删除", fields=["line_id"], details={"dependent_line_ids": dependent_ids}, status_code=409)
            payload["lines"] = [line for line in payload["lines"] if line.get("id") != line_id]
            return self._commit(db, row, payload, actor_user_id, "spectral_line.delete", line_id, {"wavelength_nm": target.get("wavelength_nm")})

    def reorder(self, method_id: int, line_ids: list[str], actor_user_id: int) -> dict[str, Any]:
        with self.database.write() as db:
            row, payload = self._payload(db, method_id)
            movable = [line for line in payload["lines"] if line.get("line_type") != "baseline"]
            expected = [line["id"] for line in movable]
            if len(line_ids) != len(set(line_ids)) or set(line_ids) != set(expected):
                raise MethodDomainError("line_reorder_mismatch", "排序列表必须包含全部非基线谱线且不能重复", fields=["line_ids"])
            by_id = {line["id"]: line for line in movable}
            baseline = next(line for line in payload["lines"] if line.get("line_type") == "baseline")
            ordered = [by_id[line_id] for line_id in line_ids]
            for order, line in enumerate(ordered, start=1):
                line["order"] = order
            payload["lines"] = [baseline, *ordered]
            return self._commit(db, row, payload, actor_user_id, "spectral_line.reorder", None, {"line_ids": line_ids})
