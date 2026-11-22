"""Read-only concentration estimates for a single spectrum record."""

import json
import math
from functools import cache

from ..acquisition import AcquisitionError, AcquisitionService
from ..methods import MethodDomainError
from ..spectral_lines import exposure_interval
from .algorithms import MIN_SIGNAL, evaluate_curve
from .candidate import calculate_candidate
from .curves import fit_standard_points, published_line_curves
from .errors import AnalysisError
from .inputs import calculation_profile
from .rules import _base_curve_points, _operational_lines


def acquired_source(db, methods, version, sample_id):
    @cache
    def geometry():
        return methods.bind_geometry(db, version.payload["conditions"])

    def locate(line):
        location = AcquisitionService.line_location(db, sample_id, line["id"])
        if location:
            return location["turn_index"], location["ccd_index"], location["point_index"]
        position = geometry().locate(float(line.get("actual_wavelength_nm") or line["wavelength_nm"]))
        return (None, position.ccd_index, position.point) if position is not None else None

    def values_for(turn, ccd, interval):
        return AcquisitionService.interval_band(db, sample_id, ccd, interval, turn_index=turn)["points"]

    return locate, values_for


def calculate_preview(db, version, locate, values_for):
    conditions = version.payload["conditions"]
    profile = calculation_profile(conditions)
    lines = _operational_lines(version.payload)
    curves = published_line_curves(db, version.version_id, profile)
    values_for = cache(values_for)
    locations = {}
    offsets, prior = {}, {}
    indexed_lines = {str(line["id"]): (position, line) for position, line in enumerate(lines)}

    def candidate(line, position, interval, previous):
        identifier = str(line["id"])
        if identifier not in locations:
            locations[identifier] = locate(line)
        target = locations[identifier]
        if target is None:
            raise AnalysisError("analysis_line_outside_ccd", "谱线不在该谱图的 CCD 覆盖范围内")
        turn, ccd, expected = target
        values = values_for(turn, ccd, interval)
        if not values:
            raise AnalysisError("analysis_band_missing", "该谱图没有此谱线的有效积分强度")
        return calculate_candidate(line, lines, 0, position, ccd, expected, values, offsets, previous, profile, None)

    rows = []
    for position, line in enumerate(lines):
        identifier = str(line["id"])
        quantitative = line["line_type"] == "analysis"
        row = {"line_id": identifier, "element": line["element"], "wavelength_nm": line["wavelength_nm"],
               "concentration": None, "unit": line.get("unit") or conditions.get("analysis_unit", ""),
               "decimal_places": line.get("decimal_places", 2), "quantitative_signal": None,
               "curve_source": None, "curve_snapshot_id": None, "message": None}
        try:
            interval = exposure_interval(line, conditions)
            previous = prior
            internal_id = str(line.get("internal_standard_line_id")) if line.get("internal_standard_mode") == "line" else None
            if interval and quantitative and internal_id in indexed_lines:
                internal_position, internal = indexed_lines[internal_id]
                previous = {**prior, internal_id: candidate(internal, internal_position, interval, prior)}
            measured = candidate(line, position, interval, previous)
            prior[identifier] = measured
            offsets[identifier] = measured["peak_position"] - measured["corrected_expected_position"]
            if quantitative:
                if internal_id is not None and profile == "legacy_2_0_2":
                    internal_signal = previous[internal_id]["peak_height"]
                    if line.get("background_offset_points"):
                        internal_signal -= previous[internal_id]["background"]
                    if internal_signal <= MIN_SIGNAL:
                        raise AnalysisError("analysis_internal_standard_missing", "内标净强度不足，无法计算浓度")
                signal = row["quantitative_signal"] = measured["quantitative_signal"]
                if curve := curves.get(identifier):
                    fit, coordinate = json.loads(curve["fit_json"]), curve["coordinate_type"]
                    row.update(curve_source="published", curve_snapshot_id=curve["id"])
                else:
                    standards = line.get("standard_points") or []
                    stored = [point for point in standards if point.get("intensity_valid")]
                    points = _base_curve_points(line, [], stored)
                    coordinate = line.get("coordinate_type", "normal")
                    fit = fit_standard_points(points, line.get("fit_mode", "linear"), coordinate, profile)
                    row["curve_source"] = "method_standards"
                value = evaluate_curve(fit, signal, coordinate)
                if not math.isfinite(value):
                    raise AnalysisError("analysis_curve_result_invalid", "拟合结果超出可显示范围")
                row["concentration"] = value
                x = math.log(signal) if coordinate == "logarithmic" else signal
                bounds = fit.get("x") or []
                if bounds and (x < min(bounds) - 1e-6 or x > max(bounds) + 1e-6):
                    row["message"] = "强度超出标准曲线范围"
        except (AnalysisError, AcquisitionError, MethodDomainError) as exc:
            row["message"] = ("缺少可用标准曲线，且有效的强度–浓度标准点不足"
                              if exc.code == "analysis_curve_points_insufficient" else exc.message)
        except ArithmeticError:
            row["message"] = "拟合结果超出可显示范围"
        if quantitative:
            rows.append(row)
    return {"method_name": version.method.name, "method_version": version.version,
            "calculation_profile": profile, "rows": rows}
