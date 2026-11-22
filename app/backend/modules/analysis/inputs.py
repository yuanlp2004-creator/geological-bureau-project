from __future__ import annotations
from .candidate import calculate_candidate
import hashlib
import json
import sqlite3
import struct
from typing import Any
from ..methods import MethodService, MethodDomainError
from ..spectral_lines import canonical_lines, exposure_interval
from .errors import AnalysisError


def calculation_profile(conditions: dict[str, Any]) -> str:
    explicit = conditions.get("calculation_profile")
    if explicit in {"legacy_2_0_2", "modern_v1"}:
        return str(explicit)
    return "legacy_2_0_2" if conditions.get("storage_profile") == "legacy_specdirect_202" else "modern_v1"


class AnalysisInputs:
    def __init__(self, methods: MethodService):
        self.methods = methods

    def candidate(
        self,
        db: sqlite3.Connection,
        run: sqlite3.Row,
        payload: dict[str, Any],
        lines: list[dict[str, Any]],
        sample_position: int,
        line_position: int,
        forced_position: int | None = None,
    ) -> dict[str, Any]:
        sample = db.execute(
            "SELECT * FROM analysis_run_samples WHERE run_id=? AND position=?", (run["id"], sample_position)
        ).fetchone()
        if sample is None:
            raise AnalysisError("analysis_checkpoint_invalid", "分析样品检查点不存在")
        line = lines[line_position]
        conditions = payload.get("conditions", {})
        try:
            geometry = self.methods.bind_geometry(db, conditions)
        except MethodDomainError as exc:
            if exc.code != "method_geometry_missing":
                raise
            raise AnalysisError(
                "analysis_geometry_missing", "方法引用的 CCD 布局或色散校准不存在", details={"line_id": line.get("id")}
            ) from exc
        from ..acquisition import AcquisitionService, AcquisitionError
        location = AcquisitionService.line_location(db, sample['acquisition_sample_id'], line['id'])
        detected = geometry.locate(float(line.get("actual_wavelength_nm") or line["wavelength_nm"])) if not location else None
        if detected is None and location is None:
            raise AnalysisError(
                "analysis_line_outside_ccd",
                "谱线不在当前 CCD 覆盖范围内",
                details={"line_id": line.get("id"), "wavelength_nm": line.get("wavelength_nm")},
            )
        ccd_index, expected_float = (location['ccd_index'], location['point_index']) if location else detected[:2]
        band = next((band for band in AcquisitionService.band_metadata(db, sample['acquisition_sample_id'])
                     if band['ccd_index'] == ccd_index and (not location or band.get('turn_index') == location['turn_index'])), None)
        if band is None:
            raise AnalysisError(
                "analysis_band_missing",
                "谱线对应的 CCD 谱带不存在",
                details={
                    "sample_id": sample["acquisition_sample_id"],
                    "line_id": line.get("id"),
                    "ccd_index": ccd_index,
                },
            )
        interval = exposure_interval(line, conditions)
        try:
            values = AcquisitionService.interval_band(db, sample['acquisition_sample_id'], ccd_index, interval,
                turn_index=location['turn_index'] if location else None)['points']
        except AcquisitionError as exc:
            raise AnalysisError(exc.code, exc.message, details=exc.details) from exc
        offsets: dict[str, int] = {}
        prior_results: dict[str, dict[str, Any]] = {}
        for row in db.execute(
            (
                "SELECT line_id, peak_position, peak_height, background, expected_position, intermediates_json, net_signal, quantitative_signal FROM "
                "analysis_line_results WHERE run_id=? AND sample_position=?"
            ),
            (run["id"], sample_position),
        ).fetchall():
            prior_results[str(row["line_id"])] = dict(row)
            intermediates = json.loads(row["intermediates_json"] or "{}")
            corrected_expected = int(
                intermediates.get("corrected_expected_position", round(float(row["expected_position"])))
            )
            offsets[str(row["line_id"])] = int(row["peak_position"] - corrected_expected)
        if interval is not None and line.get('internal_standard_mode') == 'line':
            internal = next((item for item in lines if item['id'] == line['internal_standard_line_id']), None)
            if internal is not None:
                internal_location = AcquisitionService.line_location(db, sample['acquisition_sample_id'], internal['id'])
                detected_internal = geometry.locate(float(internal.get('actual_wavelength_nm') or internal['wavelength_nm']))
                if internal_location is None and detected_internal is None:
                    raise AnalysisError('analysis_internal_standard_missing', '内标线超出 CCD')
                internal_ccd = internal_location['ccd_index'] if internal_location else detected_internal.ccd_index
                internal_point = internal_location['point_index'] if internal_location else detected_internal.point
                try:
                    internal_values = AcquisitionService.interval_band(db, sample['acquisition_sample_id'], internal_ccd, interval,
                        turn_index=internal_location['turn_index'] if internal_location else None)['points']
                except AcquisitionError as exc:
                    raise AnalysisError(exc.code, exc.message, details=exc.details) from exc
                prior_results[str(internal['id'])] = calculate_candidate(internal, lines, sample_position, line_position,
                    internal_ccd, internal_point, internal_values, offsets, prior_results, run['calculation_profile'], None)
        candidate = calculate_candidate(line, lines, sample_position, line_position, ccd_index, expected_float, values, offsets, prior_results, run["calculation_profile"], forced_position)
        candidate['intermediates']['exposure_interval'] = interval
        if location:
            candidate['intermediates'].update(turn_index=location['turn_index'], angle_deg=location['angle_deg'])
        if interval and line.get('internal_standard_mode') == 'line':
            candidate['intermediates']['interval_internal_standard'] = prior_results[str(line['internal_standard_line_id'])]
        return candidate

    def prepare_run(self, db: sqlite3.Connection, payload: dict[str, Any], sample_ids: list[int]):
        placeholders = ",".join("?" for _ in sample_ids)
        rows = db.execute(
            (
                f"SELECT s.*, t.method_id, t.method_version_id, t.method_version FROM acquisition_samples s "
                f"JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id IN ({placeholders})"
            ),
            sample_ids,
        ).fetchall()
        by_id = {int(row["id"]): row for row in rows}
        if len(by_id) != len(sample_ids):
            raise AnalysisError("analysis_sample_not_found", "一个或多个采集样品不存在", status_code=404)
        if db.execute(f"SELECT 1 FROM acquisition_sample_disposals WHERE sample_id IN ({placeholders})", sample_ids).fetchone():
            raise AnalysisError("analysis_sample_discarded", "已删除的异常样品不能用于新分析", status_code=409)
        # 数据库 IN 查询不保证顺序，必须按用户选择恢复样品顺序，再锁定同一已发布方法版本。
        ordered = [by_id[value] for value in sample_ids]
        names = payload.get('sample_names')
        numbering = payload.get("sample_numbering")
        if numbering is not None and names is not None:
            raise AnalysisError("analysis_sample_numbering_conflict", "样号表与逐条编号不能同时提交", status_code=422)
        if names is not None:
            if len(names) != len(ordered) or any(not isinstance(name, str) or len(name.strip()) > 20 for name in names):
                raise AnalysisError('analysis_sample_names_invalid', '样品编号必须逐条对应记录，且不能超过20个字符', status_code=422)
            names = [name.strip() for name in names]
            grouped_names = {}
            for row, name in zip(ordered, names):
                if row['task_id'] in grouped_names and grouped_names[row['task_id']] != name:
                    raise AnalysisError('analysis_repeat_names_mismatch', '同一样品的重复记录必须使用相同编号', status_code=422)
                grouped_names[row['task_id']] = name
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
        version = self.methods.bind_snapshots(db).by_id(selected_version_id, published_only=True)
        if version is None:
            raise AnalysisError("analysis_method_version_not_found", "已发布方法版本不存在", status_code=404)
        method_payload = version.payload
        lines = [
            line
            for line in canonical_lines(method_payload.get("lines"), method_payload.get("conditions", {}))
            if line.get("enabled")
        ]
        if not any(line.get("line_type") == "analysis" for line in lines):
            raise AnalysisError("analysis_lines_missing", "方法版本没有已启用的分析线")
        profile = payload.get("calculation_profile") or calculation_profile(method_payload.get("conditions", {}))
        if profile not in {"legacy_2_0_2", "modern_v1"}:
            raise AnalysisError("analysis_profile_invalid", "计算档案无效", status_code=422)
        numbered_samples = []
        if numbering is not None:
            standards = {str(point.get("name") or f"S{index + 1}").strip().casefold()
                         for line in lines for index, point in enumerate(line.get("standard_points") or [])}
            used_standards = set()
            entries = []
            offset = 0
            for group_position, entry in enumerate(numbering):
                name, repeats = entry["name"].strip(), entry["repeats"]
                if len(name) > 20 or not isinstance(repeats, int) or not 0 <= repeats <= 10 or bool(name) != bool(repeats):
                    raise AnalysisError("analysis_sample_numbering_invalid", "空样占一条谱带，有效样号须填写重复次数", status_code=422)
                end = offset + max(repeats, 1)
                if end > len(ordered):
                    raise AnalysisError("analysis_sample_numbering_capacity", "样号占用谱带超过当前批次的谱带限制", status_code=422)
                folded_name = name.casefold()
                kind = "standard" if folded_name in standards else "normal"
                if kind == "standard":
                    if folded_name in used_standards:
                        raise AnalysisError("analysis_standard_number_duplicate", f"同名标准样号 {name} 已存在", status_code=422)
                    used_standards.add(folded_name)
                for repeat, row in enumerate(ordered[offset:end] if name else []):
                    numbered_samples.append((row, name, group_position, repeat, kind))
                entries.append({"name": name, "repeats": repeats})
                offset = end
            if not numbered_samples:
                raise AnalysisError("analysis_sample_names_required", "请先录入至少一个有效样号", status_code=422)
            ordered = [item[0] for item in numbered_samples]
        snapshot_samples: list[dict[str, Any]] = []
        for position, row in enumerate(ordered):
            from ..acquisition import AcquisitionService
            band_rows = AcquisitionService.band_metadata(db, row['id'])
            if not band_rows:
                raise AnalysisError(
                    "analysis_sample_bands_missing", "采集样品没有固化谱带", details={"sample_id": row["id"]}
                )
            snapshot_samples.append(
                {
                    "id": row["id"],
                    "name": names[position] if names is not None else row["sample_name"],
                    "result_sha256": row["result_sha256"],
                    "bands": [dict(item) for item in band_rows],
                }
            )
            if numbered_samples:
                _, name, group_position, repeat, kind = numbered_samples[position]
                snapshot_samples[-1].update(name=name, sample_group_position=group_position,
                                            numbered_repeat_index=repeat, numbered_kind=kind)
        # 快照保存方法内容哈希与每条谱带哈希，后续可核对本次分析实际使用的输入。
        snapshot = {
            "method_version_id": version.version_id,
            "method_content_sha256": version.content_sha256,
            "profile": profile,
            "samples": snapshot_samples,
        }
        if numbering is not None:
            snapshot["sample_numbering"] = {"source_sample_ids": sample_ids, "entries": entries}
        return ordered, version, lines, profile, snapshot_samples, snapshot
