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
        detected = geometry.locate(float(line.get("actual_wavelength_nm") or line["wavelength_nm"]))
        if detected is None:
            raise AnalysisError(
                "analysis_line_outside_ccd",
                "谱线不在当前 CCD 覆盖范围内",
                details={"line_id": line.get("id"), "wavelength_nm": line.get("wavelength_nm")},
            )
        ccd_index, expected_float, _ = detected
        band = db.execute(
            "SELECT * FROM acquisition_sample_bands WHERE sample_id=? AND ccd_index=?",
            (sample["acquisition_sample_id"], ccd_index),
        ).fetchone()
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
        count = int(band["points_count"])
        blob = bytes(band["mean_blob"])
        if len(blob) != count * 4 or hashlib.sha256(blob).hexdigest() != band["mean_sha256"]:
            raise AnalysisError(
                "analysis_band_integrity_failed",
                "谱带形状或 SHA-256 校验失败",
                details={"sample_id": sample["acquisition_sample_id"], "ccd_index": ccd_index},
            )
        from ..acquisition import AcquisitionService, AcquisitionError
        interval = exposure_interval(line, conditions)
        try:
            values = AcquisitionService.interval_band(db, sample['acquisition_sample_id'], ccd_index, interval)['points']
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
                location = geometry.locate(float(internal.get('actual_wavelength_nm') or internal['wavelength_nm']))
                if location is None:
                    raise AnalysisError('analysis_internal_standard_missing', '内标线超出 CCD')
                try:
                    internal_values = AcquisitionService.interval_band(db, sample['acquisition_sample_id'], location.ccd_index, interval)['points']
                except AcquisitionError as exc:
                    raise AnalysisError(exc.code, exc.message, details=exc.details) from exc
                prior_results[str(internal['id'])] = calculate_candidate(internal, lines, sample_position, line_position,
                    location.ccd_index, location.point, internal_values, offsets, prior_results, run['calculation_profile'], None)
        candidate = calculate_candidate(line, lines, sample_position, line_position, ccd_index, expected_float, values, offsets, prior_results, run["calculation_profile"], forced_position)
        candidate['intermediates']['exposure_interval'] = interval
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
        snapshot_samples: list[dict[str, Any]] = []
        for row in ordered:
            band_rows = db.execute(
                "SELECT ccd_index, points_count, mean_sha256 FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index",
                (row["id"],),
            ).fetchall()
            if not band_rows:
                raise AnalysisError(
                    "analysis_sample_bands_missing", "采集样品没有固化谱带", details={"sample_id": row["id"]}
                )
            snapshot_samples.append(
                {
                    "id": row["id"],
                    "name": row["sample_name"],
                    "result_sha256": row["result_sha256"],
                    "bands": [dict(item) for item in band_rows],
                }
            )
        # 快照保存方法内容哈希与每条谱带哈希，后续可核对本次分析实际使用的输入。
        snapshot = {
            "method_version_id": version.version_id,
            "method_content_sha256": version.content_sha256,
            "profile": profile,
            "samples": snapshot_samples,
        }
        return ordered, version, lines, profile, snapshot_samples, snapshot
