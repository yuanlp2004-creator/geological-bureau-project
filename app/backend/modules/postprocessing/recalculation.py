"""历史结果和已采集样品的重算流程。"""

from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from dataclasses import dataclass, field
from typing import Any
from ..analysis.contracts import RecalculationAnalysis
from ..methods import MethodService
from ...db import Database, utc_now
from ..analysis import AnalysisError, evaluate_curve
from ..spectral_lines import canonical_lines
from ..spectral_lines import exposure_interval
from .errors import PostProcessingError
from .serialization import _json, _sha
from .repository import PostProcessingRepository
from .legacy_calculation import LegacyIntensity, recalculate_legacy


@dataclass(frozen=True)
class _RecalculationInputs:
    """本次重算固定使用的输入、方法快照和曲线，供各内部步骤共享。"""

    source_ids: list[str]
    method_version_id: int
    profile: str
    curve_ids: list[int]
    expected_measure_time: str | None
    fingerprint: str
    method_payload: dict[str, Any]
    evaluators: dict[str, dict[str, Any]]
    allow_older_method: bool = False
    method_modified_at: str | None = None


@dataclass
class _SampleAnalysis:
    """样品分析阶段的结果、阻断原因以及本次创建的任务标识。"""

    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    created_runs: list[int] = field(default_factory=list)


# 每个来源返回成功结果或阻断原因；两者均为空表示阻断已由分析阶段记录。
_SourceOutcome = tuple[dict[str, Any] | None, dict[str, Any] | None]


class RecalculationService:
    def __init__(
        self,
        database: Database,
        repository: PostProcessingRepository,
        *,
        analysis: RecalculationAnalysis,
        methods: MethodService,
    ):
        self.database = database
        self.methods = methods
        self.repository = repository
        self.analysis = analysis

    @staticmethod
    def _method_lines(method_payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            line
            for line in canonical_lines(method_payload.get("lines"), method_payload.get("conditions", {}))
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
            raise PostProcessingError(
                "postprocessing_result_not_recalculable", "只有保存 Peak/Back 的 PDT 强度结果可以精确重算"
            )
        if calculation_profile != "legacy_2_0_2":
            raise PostProcessingError(
                "postprocessing_result_profile_invalid", "旧 PDT 不含 modern_v1 所需峰面积，只能使用 legacy_2_0_2 重算"
            )
        payload = json.loads(row["payload_json"] or "{}")
        source_lines = list(payload.get("lines") or [])
        band_count = int(payload.get("band_count") or 0)
        line_count = int(payload.get("line_count") or len(source_lines))
        raw = bytes(row["matrix_blob"] or b"")
        if band_count <= 0 or line_count != len(source_lines) or len(raw) != line_count * band_count * 8:
            raise PostProcessingError(
                "postprocessing_result_matrix_invalid",
                "PDT 强度矩阵与元数据不一致",
                status_code=409,
                details={
                    "line_count": line_count,
                    "band_count": band_count,
                    "expected_bytes": line_count * band_count * 8,
                    "actual_bytes": len(raw),
                },
            )
        values = list(struct.iter_unpack("<ff", raw))
        matrix = [values[index * band_count : (index + 1) * band_count] for index in range(line_count)]
        method_lines = self._method_lines(method_payload)
        conditions = method_payload.get('conditions', {})
        from ..spectral_lines import method_exposure_mode
        method_mode = method_exposure_mode(conditions, method_lines) == 'line_interval'
        segments = payload.get('exposure_segments') or []
        source_mode = payload.get('header') == 0x0A73 or bool(segments)
        if method_mode != source_mode:
            raise PostProcessingError('postprocessing_pdt_mode_mismatch', 'PDT 曝光区间模式与方法不一致')
        mapped = []
        for line in method_lines:
            interval = exposure_interval(line, conditions) or (1, int(conditions.get('frame_count', 1)))
            line['_exposure_interval'] = list(interval) if method_mode else None
            intervals = [interval]
            if method_mode and line.get('line_type') == 'internal_standard':
                for analysis in method_lines:
                    if str(analysis.get('internal_standard_line_id')) == str(line['id']):
                        candidate = exposure_interval(analysis, conditions) or (1, int(conditions.get('frame_count', 1)))
                        if candidate not in intervals:
                            intervals.append(candidate)
            mapped.extend((line, candidate) for candidate in intervals)
        if len(mapped) != line_count or (method_mode and len(segments) != line_count):
            raise PostProcessingError('postprocessing_pdt_line_count_mismatch', 'PDT 谱线数量与方法映射不一致')
        for index, (line, interval) in enumerate(mapped):
            source_line = source_lines[index]
            if source_mode:
                source_line['_exposure_interval'] = [segments[index]['left'], segments[index]['right']]
            if (str(source_line.get('element') or '') != str(line.get('element') or '')
                or struct.pack('<f', float(source_line.get('wavelength_nm') or 0)) != struct.pack('<f', float(line.get('wavelength_nm') or 0))
                or (source_mode and source_line['_exposure_interval'] != list(interval))):
                raise PostProcessingError('postprocessing_pdt_line_mismatch', 'PDT 元素、波长或曝光区间与方法不一致', details={'line_index': index})
        source = LegacyIntensity(
            row["source_sha256"], source_lines, list(payload.get("sample_rows") or []), matrix, band_count
        )
        return recalculate_legacy(source, method_lines, evaluators, calculation_profile)

    def recalculate(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        source_ids = list(dict.fromkeys(str(value) for value in payload.get("source_record_ids") or []))
        if not source_ids:
            raise PostProcessingError("postprocessing_selection_empty", "至少选择一个重算源")
        method_version_id = int(payload.get("method_version_id"))
        profile = str(payload.get("calculation_profile") or "legacy_2_0_2")
        curve_ids = [int(value) for value in payload.get("curve_snapshot_ids") or []]
        expected_measure_time = payload.get("expected_measure_time")
        fingerprint = _sha(
            {
                "source_record_ids": source_ids,
                "method_version_id": method_version_id,
                "calculation_profile": profile,
                "curve_snapshot_ids": curve_ids,
                "expected_measure_time": expected_measure_time,
                'allow_older_method': bool(payload.get('allow_older_method')),
            }
        )
        with self.database.read() as db:
            existing = db.execute(
                "SELECT * FROM postprocessing_recalculation_runs WHERE input_sha256=?", (fingerprint,)
            ).fetchone()
            method = self.methods.bind_snapshots(db).by_id(method_version_id, published_only=True)
        if existing is not None:
            return self.repository._recalc_dict(existing)
        if method is None:
            raise PostProcessingError("postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404)
        try:
            evaluators = self.analysis.curve_evaluators(curve_ids, method_version_id, profile)
        except AnalysisError as exc:
            raise PostProcessingError(exc.code, exc.message, details=exc.details, status_code=exc.status_code) from exc
        inputs = _RecalculationInputs(
            source_ids=source_ids,
            method_version_id=method_version_id,
            profile=profile,
            curve_ids=curve_ids,
            expected_measure_time=expected_measure_time,
            fingerprint=fingerprint,
            method_payload=method.payload,
            evaluators=evaluators,
            allow_older_method=bool(payload.get('allow_older_method')),
            method_modified_at=method.payload.get('legacy_migration', {}).get('modified_at'),
        )
        analysis = self._analyse_samples(inputs, actor_user_id)
        # 分析任务已独立提交并不可变；本事务只装配批次，保留并审计已提交运行。
        with self.database.write() as db:
            existing = db.execute(
                "SELECT * FROM postprocessing_recalculation_runs WHERE input_sha256=?", (fingerprint,)
            ).fetchone()
            if existing is not None:
                if analysis.created_runs:
                    db.execute(
                        (
                            "INSERT INTO audit_events(actor_user_id,action,target_type,details_json,created_a"
                            "t) VALUES (?,'postprocessing.recalculate.retained','postprocessing',?,?)"
                        ),
                        (
                            actor_user_id,
                            _json(
                                {
                                    "retained_analysis_run_ids": analysis.created_runs,
                                    "existing_batch_id": existing["id"],
                                    "reason": "concurrent_duplicate",
                                }
                            ),
                            utc_now(),
                        ),
                    )
                return self.repository._recalc_dict(existing)
            method = self.methods.bind_snapshots(db).by_id(method_version_id, published_only=True)
            if method is None:
                raise PostProcessingError(
                    "postprocessing_method_not_found", "目标方法版本不存在或未发布", status_code=404
                )
            result, blocked = self._collect_source_results(db, inputs, method.method.id, analysis)
            if blocked:
                result["discarded_sources"] = [item["id"] for item in result["sources"]]
                result["sources"] = []
                result["retained_analysis_run_ids"] = analysis.created_runs
            return self._save_batch(db, inputs, result, blocked, actor_user_id)

    def _analyse_samples(self, inputs: _RecalculationInputs, actor_user_id: int | None) -> _SampleAnalysis:
        """顺序执行样品分析，记录已创建任务和阻断原因，沿用分析服务的提交行为。"""
        outcome = _SampleAnalysis()
        sample_sources = [
            identifier for identifier in inputs.source_ids if self.repository._split(identifier)[0] == "sample"
        ]
        for sample_source in sample_sources:
            try:
                analysis_run = self.analysis.create_run(
                    {
                        "name": "S18 精确版本重算",
                        "acquisition_sample_ids": [int(self.repository._split(sample_source)[1])],
                        "method_version_id": inputs.method_version_id,
                        "calculation_profile": inputs.profile,
                    },
                    actor_user_id,
                )
                outcome.created_runs.append(int(analysis_run["id"]))
                analysis_run = self.analysis.start(int(analysis_run["id"]), actor_user_id)
                while analysis_run.get("status") == "running":
                    analysis_run = self.analysis.step(int(analysis_run["id"]), actor_user_id)
                if analysis_run.get("status") != "completed":
                    outcome.blocked.append(
                        {
                            "id": sample_source,
                            "code": "analysis_run_not_completed",
                            "analysis_run_id": analysis_run.get("id"),
                            "status": analysis_run.get("status"),
                        }
                    )
                else:
                    lines, diagnostics = self._calculate_sample_lines(analysis_run, sample_source, inputs)
                    if not lines:
                        outcome.blocked.append(
                            {
                                "id": sample_source,
                                "code": "postprocessing_recalculation_no_lines",
                                "analysis_run_id": analysis_run.get("id"),
                                "diagnostics": diagnostics,
                            }
                        )
                    else:
                        outcome.results[sample_source] = {
                            "analysis_run_id": analysis_run.get("id"),
                            "status": "partial" if diagnostics else "recalculated",
                            "lines": lines,
                            "diagnostics": diagnostics,
                        }
            except AnalysisError as exc:
                outcome.blocked.append(
                    {"id": sample_source, "code": exc.code, "message": exc.message, "details": exc.details}
                )
        return outcome

    @staticmethod
    def _calculate_sample_lines(
        analysis_run: dict[str, Any],
        sample_source: str,
        inputs: _RecalculationInputs,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """只对分析谱线应用确切曲线，返回结果与缺失曲线诊断，不访问数据库。"""
        diagnostics: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []
        sample_names = {int(item["position"]): str(item["sample_name"]) for item in analysis_run.get("samples", [])}
        for item in analysis_run.get("line_results", []):
            if item.get("line_type") != "analysis":
                continue
            evaluator = inputs.evaluators.get(str(item.get("line_id")))
            if evaluator is None:
                diagnostics.append({"line_id": item.get("line_id"), "code": "curve_snapshot_missing"})
                continue
            value = evaluate_curve(evaluator["fit"], float(item["quantitative_signal"]), evaluator["coordinate_type"])
            lines.append(
                {
                    "sample_index": int(item["sample_position"]),
                    "sample_name": sample_names.get(int(item["sample_position"]), sample_source),
                    "repeat_index": 1,
                    "line_id": item["line_id"],
                    "element": item["element"],
                    "wavelength_nm": item["wavelength_nm"],
                    "quantitative_signal": item["quantitative_signal"],
                    "calculated_value": value,
                    "unit": next((line.get("unit", "") for line in inputs.method_payload.get("lines", [])
                                  if str(line.get("id")) == str(item["line_id"])), ""),
                    "curve_snapshot_id": evaluator["curve_snapshot_id"],
                    "calculation_profile": inputs.profile,
                }
            )
        return lines, diagnostics

    def _collect_source_results(
        self,
        db: sqlite3.Connection,
        inputs: _RecalculationInputs,
        method_id: int,
        analysis: _SampleAnalysis,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """按输入顺序装配三类来源；不同来源分别保留自己的检查和错误规则。"""
        result: dict[str, Any] = {
            "sources": [],
            "method_version_id": inputs.method_version_id,
            "calculation_profile": inputs.profile,
            "curve_snapshot_ids": inputs.curve_ids,
        }
        blocked: list[dict[str, Any]] = []
        for source_id in inputs.source_ids:
            kind, value = self.repository._split(source_id)
            if not value.isdigit() and kind != "recalc":
                raise PostProcessingError("postprocessing_record_invalid", "源记录 ID 无效")
            if kind == "result":
                source, issue = self._legacy_source(db, source_id, value, inputs, method_id)
            elif kind == "sample":
                source, issue = self._sample_source(db, source_id, value, inputs, analysis)
            elif kind == "recalc":
                source, issue = self._previous_source(db, source_id, value, inputs)
            else:
                raise PostProcessingError("postprocessing_source_kind_invalid", "重算源必须是 result、sample 或 recalc")
            if source is not None:
                result["sources"].append(source)
            if issue is not None:
                blocked.append(issue)
        blocked.extend(item for item in analysis.blocked if item not in blocked)
        return result, blocked

    def _legacy_source(
        self,
        db: sqlite3.Connection,
        source_id: str,
        value: str,
        inputs: _RecalculationInputs,
        method_id: int,
    ) -> _SourceOutcome:
        """读取并检查旧结果，复用已有 PDT 解码与旧算法计算。"""
        row = db.execute("SELECT * FROM result_matrices WHERE id=?", (int(value),)).fetchone()
        if row is None:
            raise PostProcessingError("postprocessing_result_not_found", "结果矩阵不存在", status_code=404)
        payload_json = json.loads(row["payload_json"] or "{}")
        legacy_target = payload_json.get("method_target_id")
        legacy_id = payload_json.get('method_legacy_id')
        if legacy_id is None and legacy_target is None:
            return None, {'id': source_id, 'code': 'postprocessing_method_identity_missing', 'message': 'PDT 没有可核对的方法标识'}
        target_legacy_id = inputs.method_payload.get('legacy_migration', {}).get('legacy_method_id')
        if legacy_id is not None and (target_legacy_id is None or str(legacy_id) != str(target_legacy_id)):
            return None, {'id': source_id, 'code': 'method_legacy_id_mismatch', 'source_method_legacy_id': legacy_id}
        if legacy_target is not None and str(legacy_target) != str(method_id):
            return None, {"id": source_id, "code": "method_version_mismatch", "source_method_target_id": legacy_target}
        modified = inputs.method_modified_at
        if isinstance(modified, dict):
            modified = modified.get('value')
        if modified and payload_json.get('measure_time') and not inputs.allow_older_method:
            from datetime import datetime, timezone
            try:
                source_time, modified_time = datetime.fromisoformat(payload_json['measure_time']), datetime.fromisoformat(str(modified))
                source_time = source_time.astimezone(timezone.utc) if source_time.tzinfo else source_time.replace(tzinfo=timezone.utc)
                modified_time = modified_time.astimezone(timezone.utc) if modified_time.tzinfo else modified_time.replace(tzinfo=timezone.utc)
                if source_time < modified_time:
                    return None, {'id': source_id, 'code': 'postprocessing_older_pdt_confirmation_required', 'message': 'PDT 早于方法修改时间，请明确确认后重算', 'method_modified_at': modified}
            except ValueError:
                return None, {'id': source_id, 'code': 'postprocessing_method_time_invalid', 'message': '方法修改时间无法核对'}
        if (
            inputs.expected_measure_time
            and payload_json.get("measure_time")
            and str(payload_json["measure_time"]) != str(inputs.expected_measure_time)
        ):
            return None, {
                "id": source_id,
                "code": "measure_time_mismatch",
                "source_measure_time": payload_json["measure_time"],
                "expected_measure_time": inputs.expected_measure_time,
            }
        try:
            recalculated = self._recalculate_legacy_result(
                row, inputs.method_payload, inputs.evaluators, inputs.profile
            )
        except PostProcessingError as exc:
            return None, {"id": source_id, "code": exc.code, "message": exc.message, "details": exc.details}
        return {"id": source_id, **recalculated}, None

    def _sample_source(
        self,
        db: sqlite3.Connection,
        source_id: str,
        value: str,
        inputs: _RecalculationInputs,
        analysis: _SampleAnalysis,
    ) -> _SourceOutcome:
        """检查已固化样品的版本和时间，再接入前面完成的分析结果。"""
        sample = db.execute(
            (
                "SELECT s.id, s.result_sha256, t.method_version_id, "
                "json_extract(t.simulator_json, '$.measure_time') AS measure_time FROM "
                "acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id=? "
                "AND s.finalized=1"
            ),
            (int(value),),
        ).fetchone()
        if sample is None:
            raise PostProcessingError("postprocessing_sample_not_found", "转换样品不存在或尚未固化", status_code=404)
        if int(sample["method_version_id"] or 0) != inputs.method_version_id:
            return None, {
                "id": source_id,
                "code": "method_version_mismatch",
                "sample_method_version_id": sample["method_version_id"],
            }
        if (
            inputs.expected_measure_time
            and sample["measure_time"]
            and str(sample["measure_time"]) != str(inputs.expected_measure_time)
        ):
            return None, {
                "id": source_id,
                "code": "measure_time_mismatch",
                "source_measure_time": sample["measure_time"],
                "expected_measure_time": inputs.expected_measure_time,
            }
        if int(sample["method_version_id"] or 0) != inputs.method_version_id:
            return None, {
                "id": source_id,
                "code": "method_version_mismatch",
                "sample_method_version_id": sample["method_version_id"],
            }
        elif source_id in analysis.results:
            return {"id": source_id, "source_sha256": sample["result_sha256"], **analysis.results[source_id]}, None
        else:
            matching_block = next((item for item in analysis.blocked if item.get("id") == source_id), None)
            if matching_block is None:
                return None, {"id": source_id, "code": "analysis_run_not_completed"}
        return None, None

    @staticmethod
    def _previous_source(
        db: sqlite3.Connection,
        source_id: str,
        value: str,
        inputs: _RecalculationInputs,
    ) -> _SourceOutcome:
        """已有重算批次仅在方法、算法和曲线版本全部相同时复用。"""
        row = db.execute(
            (
                "SELECT result_json, result_sha256, method_version_id, calculation_profile, "
                "curve_snapshot_ids_json FROM postprocessing_recalculation_runs WHERE id=?"
            ),
            (value,),
        ).fetchone()
        if row is None:
            raise PostProcessingError("postprocessing_recalc_not_found", "重算批次不存在", status_code=404)
        if (
            int(row["method_version_id"]) != inputs.method_version_id
            or str(row["calculation_profile"]) != inputs.profile
            or json.loads(row["curve_snapshot_ids_json"]) != inputs.curve_ids
        ):
            return None, {"id": source_id, "code": "recalculation_version_mismatch"}
        else:
            previous = json.loads(row["result_json"])
            return {
                "id": source_id,
                "source_sha256": row["result_sha256"],
                "status": "recalculated",
                "lines": [line for source in previous.get("sources", []) for line in source.get("lines", [])],
            }, None

    @staticmethod
    def _save_batch(
        db: sqlite3.Connection,
        inputs: _RecalculationInputs,
        result: dict[str, Any],
        blocked: list[dict[str, Any]],
        actor_user_id: int | None,
    ) -> dict[str, Any]:
        """在调用方事务中写入批次结果及审计，不自行提交。"""
        status = "blocked" if blocked else "completed"
        result["blocked"] = blocked
        digest = _sha(result)
        run_id = f"s18-recalc-{uuid.uuid4().hex}"
        report = {
            "source_count": len(inputs.source_ids),
            "completed_count": len(result["sources"]),
            "blocked_count": len(blocked),
            "atomic_rollback": bool(blocked),
            "analysis_committed_separately": True,
            "retained_analysis_run_ids": result.get("retained_analysis_run_ids", []),
            "idempotent_input_sha256": inputs.fingerprint,
            'allow_older_method': inputs.allow_older_method,
            'method_modified_at': inputs.method_modified_at,
        }
        first_block = blocked[0] if blocked else None
        db.execute(
            (
                "INSERT INTO postprocessing_recalculation_runs(id,input_sha256,status,source_reco"
                "rd_ids_json,source_hashes_json,method_version_id,calculation_profile,curve_snaps"
                "hot_ids_json,result_json,report_json,result_sha256,created_by,created_at,complet"
                "ed_at,error_code,error_message) VALUES (?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                run_id,
                inputs.fingerprint,
                status,
                _json(inputs.source_ids),
                _json([item.get("source_sha256") for item in result["sources"]]),
                inputs.method_version_id,
                inputs.profile,
                _json(inputs.curve_ids),
                _json(result),
                _json(report),
                digest,
                actor_user_id,
                utc_now(),
                utc_now(),
                first_block.get("code") if first_block else None,
                first_block.get("message", "重算批次因输入或版本校验失败而回滚") if first_block else None,
            ),
        )
        db.execute(
            (
                "INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json"
                ",created_at) VALUES (?, 'postprocessing.recalculate', 'postprocessing', NULL, "
                "?, ?)"
            ),
            (actor_user_id, _json(report | {"run_id": run_id}), utc_now()),
        )
        return {"id": run_id, "status": status, "input_sha256": inputs.fingerprint, "result": result, "report": report}
