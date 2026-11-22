"""摄谱即时测量计算；复用正式候选与曲线公式，仅返回当前读快照。"""

from __future__ import annotations
import json
from typing import Any

from .algorithms import evaluate_curve
from .candidate import calculate_candidate
from .curves import published_line_curves
from .errors import AnalysisError
from .inputs import calculation_profile
from .rules import _operational_lines
from ..methods import MethodDomainError
from ..spectral_lines import exposure_interval
from ..acquisition import AcquisitionService, AcquisitionError


# 使用采集公共快照计算当前强度与绑定方法版本的已发布曲线浓度。
def measurement_results(db, methods, snapshot: dict[str, Any]) -> dict[str, Any]:
    result = {"task_id": snapshot["task_id"], "method_version_id": snapshot["method_version_id"],
              "rows": [], "message": "等待有效燃烧帧", "provisional": True}
    # 即时测量沿用采集绑定的已发布方法版本；没有方法时只返回等待或原始谱图提示。
    version = methods.bind_snapshots(db).by_id(snapshot["method_version_id"], published_only=True)
    if version is None:
        result["message"] = "未绑定已发布方法，当前只显示原始 CCD 谱图"
        return result
    payload = version.payload
    profile = calculation_profile(payload.get("conditions", {}))
    result["calculation_profile"] = profile
    lines = _operational_lines(payload)
    try:
        geometry = methods.bind_geometry(db, payload.get("conditions", {}))
    except MethodDomainError as exc:
        result["message"] = exc.message
        return result
    # 浓度只使用同方法版本、同算法档案且匹配最新质控的已发布曲线。
    curves = published_line_curves(db, version.version_id, profile)
    for position, sample in enumerate(snapshot["samples"]):
        bands = {(band.get('turn_index', 0), band['ccd_index']): band for band in sample['bands']}
        # 每个重复独立维护基准偏移和内标结果；不能沿用另一个样品的修正值。
        offsets, prior = {}, {}
        for line_position, line in enumerate(lines):
            row = {"sample_id": sample["id"], "sample_name": sample["name"], "repeat_index": sample["repeat_index"],
                   "line_id": str(line["id"]), "element": line.get("element", ""), "wavelength_nm": line["wavelength_nm"],
                   "complete": sample["complete"], "concentration": None, "curve_snapshot_id": None,
                   "unit": line.get("unit") or payload.get("conditions", {}).get("analysis_unit", ""),
                   "decimal_places": line.get("decimal_places", 2)}
            try:
                location = AcquisitionService.line_location(db, sample['id'], line['id'])
                detected = geometry.locate(float(line.get("actual_wavelength_nm") or line["wavelength_nm"])) if not location else None
                if detected is None and location is None:
                    raise AnalysisError("analysis_line_outside_ccd", "谱线超出检测范围")
                ccd, expected = (location['ccd_index'], location['point_index']) if location else detected[:2]
                band = bands.get((location['turn_index'] if location else 0, ccd))
                if band is None:
                    raise AnalysisError("analysis_band_missing", "等待该 CCD 的有效燃烧帧")
                # 复用正式分析的寻峰、扣背景和内标公式；这里的当前帧结果不写入正式分析表。
                interval = exposure_interval(line, payload.get('conditions', {}))
                points = AcquisitionService.interval_band(db, sample['id'], ccd, interval,
                    turn_index=location['turn_index'] if location else None)['points'] if interval else band['points']
                line_prior = prior.copy()
                internal = next((item for item in lines if str(item['id']) == str(line.get('internal_standard_line_id'))), None)
                if interval and internal:
                    internal_location = AcquisitionService.line_location(db, sample['id'], internal['id'])
                    located = geometry.locate(float(internal.get('actual_wavelength_nm') or internal['wavelength_nm'])) if not internal_location else None
                    if located is None and internal_location is None:
                        raise AnalysisError('analysis_internal_standard_missing', '内标线超出 CCD 范围')
                    internal_ccd, internal_point = (internal_location['ccd_index'], internal_location['point_index']) if internal_location else located[:2]
                    values = AcquisitionService.interval_band(db, sample['id'], internal_ccd, interval,
                        turn_index=internal_location['turn_index'] if internal_location else None)['points']
                    line_prior[str(internal['id'])] = calculate_candidate(internal, lines, position, lines.index(internal),
                        internal_ccd, internal_point, values, offsets, prior, profile, None)
                candidate = calculate_candidate(line, lines, position, line_position, ccd, expected,
                                                points, offsets, line_prior, profile, None)
                # 先保存所有操作谱线的候选，后面的分析线才能引用已算内标及定位偏移。
                prior[str(line["id"])] = candidate
                offsets[str(line["id"])] = candidate["peak_position"] - candidate["corrected_expected_position"]
                row.update({key: candidate[key] for key in ("peak_position", "peak_height", "background", "net_signal", "quantitative_signal")})
                row.update({"burn_count": band["burn_count"], "dark_count": band["dark_count"], "message": "未发布对应标准曲线"})
                curve = curves.get(str(line["id"]))
                if curve:
                    row["concentration"] = evaluate_curve(json.loads(curve["fit_json"]), candidate["quantitative_signal"], curve["coordinate_type"])
                    row["curve_snapshot_id"] = curve["id"]
                    row["message"] = "当前测量" if sample["complete"] else "采集中，暗帧与区间尚未完成"
            except (AnalysisError, AcquisitionError) as exc:
                row["message"] = exc.message
            # 定位线和内标线参与计算，但页面只展示分析线；单线失败以行消息呈现。
            if line.get("line_type") == "analysis":
                result["rows"].append(row)
    if result["rows"]:
        result["message"] = "即时结果用于观察，正式结果需完成分析与质控"
    return result
