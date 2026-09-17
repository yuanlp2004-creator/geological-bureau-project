"""历史结果和已采集样品的重算流程。"""

from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from typing import Any
from ..analysis.contracts import RecalculationAnalysis
from ..methods import MethodService
from ...db import Database, utc_now
from ..analysis import AnalysisError, evaluate_curve
from ..spectral_lines import canonical_lines
from .errors import PostProcessingError
from .serialization import _json, _sha
from .repository import PostProcessingRepository
from .legacy_calculation import LegacyIntensity, recalculate_legacy



class RecalculationService:
    def __init__(self, database: Database, repository: PostProcessingRepository, *, analysis: RecalculationAnalysis, methods: MethodService):
        self.database = database
        self.methods = methods
        self.repository = repository
        self.analysis = analysis

    @staticmethod
    def _method_lines(method_payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            line for line in canonical_lines(method_payload.get("lines"), method_payload.get("conditions", {}))
            if line.get("enabled")
        ]

    def _recalculate_legacy_result(
        self,
        row: sqlite3.Row,
        method_payload: dict[str, Any],
        evaluators: dict[str, dict[str, Any]],
        calculation_profile: str,
    ) -> dict[str, Any]:
        if row["format"] != "pdt":
            raise PostProcessingError("postprocessing_result_not_recalculable", "只有保存 Peak/Back 的 PDT 强度结果可以精确重算")
        if calculation_profile != "legacy_2_0_2":
            raise PostProcessingError("postprocessing_result_profile_invalid", "旧 PDT 不含 modern_v1 所需峰面积，只能使用 legacy_2_0_2 重算")
        payload = json.loads(row["payload_json"] or "{}")
        source_lines = list(payload.get("lines") or [])
        band_count = int(payload.get("band_count") or 0)
        line_count = int(payload.get("line_count") or len(source_lines))
        raw = bytes(row["matrix_blob"] or b"")
        if band_count <= 0 or line_count != len(source_lines) or len(raw) != line_count * band_count * 8:
            raise PostProcessingError(
                "postprocessing_result_matrix_invalid", "PDT 强度矩阵与元数据不一致", status_code=409,
                details={"line_count": line_count, "band_count": band_count, "expected_bytes": line_count * band_count * 8, "actual_bytes": len(raw)},
            )
        values = list(struct.iter_unpack("<ff", raw))
        matrix = [values[index * band_count:(index + 1) * band_count] for index in range(line_count)]
        method_lines = self._method_lines(method_payload)
        source = LegacyIntensity(row["source_sha256"], source_lines, list(payload.get("sample_rows") or []), matrix, band_count)
        return recalculate_legacy(source, method_lines, evaluators, calculation_profile)

    def recalculate(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        source_ids = list(dict.fromkeys(str(value) for value in payload.get("source_record_ids") or []))
        if not source_ids:
            raise PostProcessingError("postprocessing_selection_empty", "至少选择一个重算源")
        method_version_id = int(payload.get("method_version_id"))
        profile = str(payload.get("calculation_profile") or "legacy_2_0_2")
        curve_ids = [int(value) for value in payload.get("curve_snapshot_ids") or []]
        expected_measure_time = payload.get("expected_measure_time")
        fingerprint = _sha({"source_record_ids": source_ids, "method_version_id": method_version_id, "calculation_profile": profile, "curve_snapshot_ids": curve_ids, "expected_measure_time": expected_measure_time})
        with self.database.read() as db:
            existing = db.execute("SELECT * FROM postprocessing_recalculation_runs WHERE input_sha256=?", (fingerprint,)).fetchone()
            method = self.methods.bind_snapshots(db).by_id(method_version_id, published_only=True)
        if existing is not None:
            return self.repository._recalc_dict(existing)
        if method is None:
            raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
        try:
            evaluators = self.analysis.curve_evaluators(curve_ids, method_version_id, profile)
        except AnalysisError as exc:
            raise PostProcessingError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        method_payload = method.payload
        analysis_results: dict[str, dict[str, Any]] = {}
        analysis_blocked: list[dict[str, Any]] = []
        created_analysis_runs: list[int] = []
        sample_sources = [identifier for identifier in source_ids if self.repository._split(identifier)[0] == "sample"]
        for sample_source in sample_sources:
            try:
                analysis_run = self.analysis.create_run({"name": "S18 精确版本重算", "acquisition_sample_ids": [int(self.repository._split(sample_source)[1])], "method_version_id": method_version_id, "calculation_profile": profile}, actor_user_id)
                created_analysis_runs.append(int(analysis_run["id"]))
                analysis_run = self.analysis.start(int(analysis_run["id"]), actor_user_id)
                while analysis_run.get("status") == "running":
                    analysis_run = self.analysis.step(int(analysis_run["id"]), actor_user_id)
                if analysis_run.get("status") != "completed":
                    analysis_blocked.append({"id": sample_source, "code": "analysis_run_not_completed", "analysis_run_id": analysis_run.get("id"), "status": analysis_run.get("status")})
                else:
                    diagnostics: list[dict[str, Any]] = []
                    lines: list[dict[str, Any]] = []
                    sample_names = {int(item["position"]): str(item["sample_name"]) for item in analysis_run.get("samples", [])}
                    for item in analysis_run.get("line_results", []):
                        if item.get("line_type") != "analysis":
                            continue
                        evaluator = evaluators.get(str(item.get("line_id")))
                        if evaluator is None:
                            diagnostics.append({"line_id": item.get("line_id"), "code": "curve_snapshot_missing"})
                            continue
                        value = evaluate_curve(evaluator["fit"], float(item["quantitative_signal"]), evaluator["coordinate_type"])
                        lines.append({
                            "sample_index": int(item["sample_position"]), "sample_name": sample_names.get(int(item["sample_position"]), sample_source),
                            "repeat_index": 1, "line_id": item["line_id"], "element": item["element"], "wavelength_nm": item["wavelength_nm"],
                            "quantitative_signal": item["quantitative_signal"], "calculated_value": value,
                            "curve_snapshot_id": evaluator["curve_snapshot_id"], "calculation_profile": profile,
                        })
                    if not lines:
                        analysis_blocked.append({"id": sample_source, "code": "postprocessing_recalculation_no_lines", "analysis_run_id": analysis_run.get("id"), "diagnostics": diagnostics})
                    else:
                        analysis_results[sample_source] = {"analysis_run_id": analysis_run.get("id"), "status": "partial" if diagnostics else "recalculated", "lines": lines, "diagnostics": diagnostics}
            except AnalysisError as exc:
                analysis_blocked.append({"id": sample_source, "code": exc.code, "message": exc.message, "details": exc.details})
        with self.database.write() as db:
            existing = db.execute("SELECT * FROM postprocessing_recalculation_runs WHERE input_sha256=?", (fingerprint,)).fetchone()
            if existing is not None:
                if created_analysis_runs:
                    db.executemany("DELETE FROM analysis_runs WHERE id=?", [(created_id,) for created_id in created_analysis_runs])
                return self.repository._recalc_dict(existing)
            method = self.methods.bind_snapshots(db).by_id(method_version_id, published_only=True)
            if method is None:
                raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
            result: dict[str, Any] = {"sources": [], "method_version_id": method_version_id, "calculation_profile": profile, "curve_snapshot_ids": curve_ids}
            blocked: list[dict[str, Any]] = []
            for source_id in source_ids:
                kind, value = self.repository._split(source_id)
                if not value.isdigit() and kind != "recalc":
                    raise PostProcessingError("postprocessing_record_invalid", "源记录 ID 无效")
                if kind == "result":
                    row = db.execute("SELECT * FROM result_matrices WHERE id=?", (int(value),)).fetchone()
                    if row is None:
                        raise PostProcessingError("postprocessing_result_not_found", "结果矩阵不存在", status_code=404)
                    payload_json = json.loads(row["payload_json"] or "{}")
                    legacy_target = payload_json.get("method_target_id")
                    if legacy_target is not None and str(legacy_target) != str(method.method.id):
                        blocked.append({"id": source_id, "code": "method_version_mismatch", "source_method_target_id": legacy_target})
                        continue
                    if expected_measure_time and payload_json.get("measure_time") and str(payload_json["measure_time"]) != str(expected_measure_time):
                        blocked.append({"id": source_id, "code": "measure_time_mismatch", "source_measure_time": payload_json["measure_time"], "expected_measure_time": expected_measure_time})
                        continue
                    try:
                        recalculated = self._recalculate_legacy_result(row, method_payload, evaluators, profile)
                    except PostProcessingError as exc:
                        blocked.append({"id": source_id, "code": exc.code, "message": exc.message, "details": exc.details})
                        continue
                    result["sources"].append({"id": source_id, **recalculated})
                elif kind == "sample":
                    sample = db.execute("SELECT s.id, s.result_sha256, t.method_version_id, json_extract(t.simulator_json, '$.measure_time') AS measure_time FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id=? AND s.finalized=1", (int(value),)).fetchone()
                    if sample is None:
                        raise PostProcessingError("postprocessing_sample_not_found", "转换样品不存在或尚未固化", status_code=404)
                    if int(sample["method_version_id"] or 0) != method_version_id:
                        blocked.append({"id": source_id, "code": "method_version_mismatch", "sample_method_version_id": sample["method_version_id"]})
                        continue
                    if expected_measure_time and sample["measure_time"] and str(sample["measure_time"]) != str(expected_measure_time):
                        blocked.append({"id": source_id, "code": "measure_time_mismatch", "source_measure_time": sample["measure_time"], "expected_measure_time": expected_measure_time})
                        continue
                    if int(sample["method_version_id"] or 0) != method_version_id:
                        blocked.append({"id": source_id, "code": "method_version_mismatch", "sample_method_version_id": sample["method_version_id"]})
                    elif source_id in analysis_results:
                        result["sources"].append({"id": source_id, "source_sha256": sample["result_sha256"], **analysis_results[source_id]})
                    else:
                        matching_block = next((item for item in analysis_blocked if item.get("id") == source_id), None)
                        if matching_block is None:
                            blocked.append({"id": source_id, "code": "analysis_run_not_completed"})
                elif kind == "recalc":
                    row = db.execute("SELECT result_json, result_sha256, method_version_id, calculation_profile, curve_snapshot_ids_json FROM postprocessing_recalculation_runs WHERE id=?", (value,)).fetchone()
                    if row is None:
                        raise PostProcessingError("postprocessing_recalc_not_found", "重算批次不存在", status_code=404)
                    if int(row["method_version_id"]) != method_version_id or str(row["calculation_profile"]) != profile or json.loads(row["curve_snapshot_ids_json"]) != curve_ids:
                        blocked.append({"id": source_id, "code": "recalculation_version_mismatch"})
                    else:
                        previous = json.loads(row["result_json"])
                        result["sources"].append({"id": source_id, "source_sha256": row["result_sha256"], "status": "recalculated", "lines": [line for source in previous.get("sources", []) for line in source.get("lines", [])]})
                else:
                    raise PostProcessingError("postprocessing_source_kind_invalid", "重算源必须是 result、sample 或 recalc")
            blocked.extend(item for item in analysis_blocked if item not in blocked)
            if blocked:
                result["discarded_sources"] = [item["id"] for item in result["sources"]]
                result["sources"] = []
                if created_analysis_runs:
                    db.executemany("DELETE FROM analysis_runs WHERE id=?", [(run_id,) for run_id in created_analysis_runs])
            status = "blocked" if blocked else "completed"
            result["blocked"] = blocked
            digest = _sha(result)
            run_id = f"s18-recalc-{uuid.uuid4().hex}"
            report = {"source_count": len(source_ids), "completed_count": len(result["sources"]), "blocked_count": len(blocked), "atomic_rollback": bool(blocked), "idempotent_input_sha256": fingerprint}
            first_block = blocked[0] if blocked else None
            db.execute("INSERT INTO postprocessing_recalculation_runs(id,input_sha256,status,source_record_ids_json,source_hashes_json,method_version_id,calculation_profile,curve_snapshot_ids_json,result_json,report_json,result_sha256,created_by,created_at,completed_at,error_code,error_message) VALUES (?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, fingerprint, status, _json(source_ids), _json([item.get("source_sha256") for item in result["sources"]]), method_version_id, profile, _json(curve_ids), _json(result), _json(report), digest, actor_user_id, utc_now(), utc_now(), first_block.get("code") if first_block else None, first_block.get("message", "重算批次因输入或版本校验失败而回滚") if first_block else None))
            db.execute("INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) VALUES (?, 'postprocessing.recalculate', 'postprocessing', NULL, ?, ?)", (actor_user_id, _json(report | {"run_id": run_id}), utc_now()))
            return {"id": run_id, "status": status, "input_sha256": fingerprint, "result": result, "report": report}

