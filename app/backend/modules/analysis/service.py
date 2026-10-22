"""分析运行流程与对外应用服务；显式组合质控、曲线和打印服务。"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any
from ...db import Database, utc_now
from ..methods import MethodService
from .errors import AnalysisError
from .serialization import _json, _sha
from .repository import AnalysisRepository
from .quality import QualityService
from .curves import CurveService
from .printing import CurvePrintingService
from .report_inputs import AnalysisReportReader
from .inputs import AnalysisInputs, calculation_profile


class AnalysisService:
    def __init__(self, database: Database, *, methods: MethodService):
        self.database = database
        self.methods = methods
        self.inputs = AnalysisInputs(methods)
        self.repository = AnalysisRepository(database, methods=methods)
        self.quality = QualityService(database, self.repository)
        self.curves = CurveService(database, self.repository)
        self.printing = CurvePrintingService(database, self.repository)

    def bind_report_inputs(self, connection: sqlite3.Connection) -> AnalysisReportReader:
        return AnalysisReportReader(connection, self.methods)

    def calibration_preview(self, run_id: int, sample_position: int) -> dict:
        from .daily_operations import preview_positions
        return preview_positions(self, run_id, sample_position)

    def save_calibration(self, run_id: int, sample_position: int, actor_user_id: int, *, mode: str = 'measured', scope: str = 'all') -> dict:
        preview = self.calibration_preview(run_id, sample_position)
        if mode not in {'measured', 'theoretical', 'stored'} or scope not in {'reference', 'all'}:
            raise AnalysisError('analysis_calibration_mode_invalid', '校正模式无效')
        if scope == 'reference':
            preview['positions'] = [row for row in preview['positions'] if row['line_type'] == 'baseline']
        if mode == 'measured' and not all(row['found'] for row in preview['positions']):
            raise AnalysisError('analysis_calibration_peak_missing', '存在未找到有效峰的谱线，不能保存校正')
        for row in preview['positions']:
            if mode != 'measured':
                row['measured_wavelength_nm'] = row[f'{mode}_wavelength_nm']
                row['found'] = True
        preview['source_key'] = _sha({'source_key': preview['source_key'], 'mode': mode, 'scope': scope})
        preview['mode'], preview['scope'] = mode, scope
        return self.methods.save_calibrated_positions(preview, actor_user_id)

    def time_series(self, run_id: int, sample_position: int, acquisition, include_mean: bool = True) -> dict:
        from .daily_operations import time_series
        return time_series(self, run_id, sample_position, acquisition, include_mean)

    def export_time_series(self, run_id: int, sample_position: int, acquisition, include_mean: bool, actor: int) -> tuple[bytes, str]:
        import csv
        import io
        import hashlib
        data = self.time_series(run_id, sample_position, acquisition, include_mean)
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        keys = ['sample_name', 'line_id', 'element', 'wavelength_nm', 'point', 'cycle', 'seconds', 'intensity', 'background']
        writer.writerow(['样品', '谱线', '元素', '波长(nm)', '固定峰点(1起)', '周期', '时间(s)', '归一化强度', '背景(仅首行)'])
        for row in data['rows']:
            writer.writerow([row[key] for key in keys])
        content = stream.getvalue().encode('utf-8-sig')
        digest = hashlib.sha256(content).hexdigest()
        with self.database.write() as db:
            self.repository._audit(db, actor, 'analysis.time_series.export', run_id,
                {'sample_position': sample_position, 'include_mean': include_mean, 'input_sha256': data['input_sha256'],
                 'content_sha256': digest, 'row_count': len(data['rows'])})
        return content, digest


    def import_legacy_sources(
        self, record_ids: list[int], method_version_id: int, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        from ..spectrum_migration import SpectrumMigrationService
        from ..acquisition_import import AcquisitionRecordImporter

        if not record_ids or len(record_ids) != len(set(record_ids)) or len(record_ids) > 1000:
            raise AnalysisError("analysis_legacy_selection_invalid", "请选择不重复的旧样品记录")
        with self.database.write() as db:
            method = self.methods.bind_snapshots(db).by_id(method_version_id, published_only=True)
            if method is None or calculation_profile(method.payload.get("conditions", {})) != "legacy_2_0_2":
                raise AnalysisError("analysis_legacy_method_required", "旧样品须显式选择已发布的 legacy_2_0_2 方法版本")
            geometry = self.methods.bind_geometry(db, method.payload.get("conditions", {}))
            from ..legacy_migration import LegacyMigrationError

            try:
                rows = [SpectrumMigrationService.source_record(db, identifier) for identifier in record_ids]
            except LegacyMigrationError as exc:
                raise AnalysisError(exc.code, str(exc), status_code=404) from exc
            rows.sort(key=lambda row: (row["source_sha256"], row["record_index"]))
            groups = []
            for row in rows:
                if row["format"] not in ("cdt", "cmt") or row["sample_no"] is None or row["sample_no"] <= 0:
                    raise AnalysisError(
                        "analysis_legacy_source_invalid", "仅支持已有正样号的 CDT/CMT 样品，空样和未命名记录需先核对"
                    )
                if not geometry.accepts_legacy_layout(json.loads(row["layout_json"])):
                    raise AnalysisError(
                        "analysis_legacy_geometry_mismatch",
                        "旧样品与所选方法的 CCD 布局或色散系数不一致，禁止隐式重采样",
                    )
                if (
                    groups
                    and groups[-1][-1]["source_sha256"] == row["source_sha256"]
                    and groups[-1][-1]["sample_no"] == row["sample_no"]
                ):
                    if (
                        groups[-1][-1]["sample_name"] != row["sample_name"]
                        or row["record_index"] != groups[-1][-1]["record_index"] + 1
                    ):
                        raise AnalysisError(
                            "analysis_legacy_repeat_ambiguous", "同一样号的名称或重复记录不连续，请选择完整重复组"
                        )
                    groups[-1].append(row)
                else:
                    groups.append([row])
            if any(len(group) > 10 for group in groups):
                raise AnalysisError("analysis_legacy_repeats_limit", "旧重复组超过当前支持的十次，不能截断")
            standards = {
                str(point.get("name") or "").strip().casefold()
                for line in method.payload.get("lines", [])
                for point in line.get("standard_points", [])
            }
            importer = AcquisitionRecordImporter().bind(db)
            samples = []
            name_mappings = []
            try:
                for group in groups:
                    original_name = str(group[0]["sample_name"]).strip()
                    analytical_name = original_name
                    if method.payload.get("conditions", {}).get("storage_profile") == "legacy_specdirect_202":
                        # uGlobal.IndexOfStdNames is zero based; legacy_migration._standard_blob
                        # names the corresponding method points S1, S2, ... . Keep source text intact.
                        index = re.fullmatch(r"[Ss]([0-9]+)", original_name)
                        if index:
                            analytical_name = f"S{int(index.group(1)) + 1}"
                            if analytical_name.casefold() not in standards:
                                raise ValueError("legacy standard index has no corresponding method point")
                        elif original_name[:1].casefold() == "s":
                            raise ValueError("legacy standard name needs an explicit index mapping")
                    kind = "standard" if analytical_name.casefold() in standards else "normal"
                    name_mappings.append(
                        {"source_name": original_name, "analysis_name": analytical_name, "sample_kind": kind}
                    )
                    samples.extend(
                        importer.import_legacy_group(
                            group,
                            method,
                            geometry.layout_id,
                            kind,
                            actor_user_id,
                            utc_now(),
                            analytical_name=analytical_name,
                        )
                    )
            except ValueError as exc:
                raise AnalysisError(
                    "analysis_legacy_data_invalid",
                    "旧样品数据不足或包含损坏帧，导入已回滚",
                    details={"reason": str(exc)},
                ) from exc
            self.repository._audit(
                db,
                actor_user_id,
                "analysis.legacy.import",
                None,
                {
                    "source_ids": record_ids,
                    "source_hashes": [row["source_sha256"] for row in rows],
                    "method_version_id": method_version_id,
                    "sample_ids": samples,
                    "name_mappings": name_mappings,
                },
            )
            return {
                "sample_ids": samples,
                "method_version_id": method_version_id,
                "calculation_profile": "legacy_2_0_2",
                "name_mappings": name_mappings,
            }

    def options(self) -> dict[str, Any]:
        # 已固化采集样品、旧谱来源和已发布方法分别经当前存储及公开入口读取。
        with self.database.read() as db:
            samples = [
                dict(row)
                for row in db.execute(
                    "SELECT s.id, s.sample_name, s.sample_kind, s.repeat_index, s.result_sha256 AS input_sha256,"
                    " t.id AS acquisition_task_id, t.name AS acquisition_task_name, t.method_version_id,"
                    " t.method_id, t.method_version FROM acquisition_samples s "
                    "JOIN acquisition_tasks t ON t.id=s.task_id "
                    "WHERE s.status='completed' AND s.finalized=1 AND t.method_version_id IS NOT NULL "
                    "AND NOT EXISTS(SELECT 1 FROM acquisition_sample_disposals d WHERE d.sample_id=s.id) "
                    "ORDER BY t.id DESC, s.repeat_index"
                ).fetchall()
            ]
            from ..spectrum_migration import SpectrumMigrationService

            legacy_sources = SpectrumMigrationService.source_records(db, ("cdt", "cmt"))
            snapshots = self.methods.bind_snapshots(db).published()
        methods = [
            {
                "method_version_id": item.version_id,
                "method_id": item.method.id,
                "version": item.version,
                "name": item.method.name,
                "calculation_profile": calculation_profile(item.payload.get("conditions", {})),
            }
            for item in snapshots
        ]
        return {
            "legacy_sources": legacy_sources,
            "profiles": ["legacy_2_0_2", "modern_v1"],
            "samples": samples,
            "method_versions": methods,
        }

    def create_run(self, payload: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        sample_ids = [int(value) for value in payload.get("acquisition_sample_ids") or []]
        if not sample_ids or len(sample_ids) != len(set(sample_ids)):
            raise AnalysisError("analysis_samples_invalid", "必须选择至少一个且不重复的采集样品", status_code=422)
        with self.database.write() as db:
            ordered, version, lines, profile, snapshot_samples, snapshot = self.inputs.prepare_run(db, payload, sample_ids)
            now = utc_now()
            cursor = db.execute(
                (
                    "INSERT INTO analysis_runs(name, method_id, method_version_id, method_version, "
                    "calculation_profile, slow_mode, intervention_timeout_seconds, "
                    "input_snapshot_json, input_sha256, created_by, created_at, updated_at) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    str(payload.get("name") or "S17 定量与曲线分析").strip(),
                    version.method.id,
                    version.version_id,
                    version.version,
                    profile,
                    int(bool(payload.get("slow_mode"))),
                    float(payload.get("intervention_timeout_seconds", 300)),
                    _json(snapshot),
                    _sha(snapshot),
                    self.repository._actor(db, actor_user_id),
                    now,
                    now,
                ),
            )
            run_id = int(cursor.lastrowid)
            for position, row in enumerate(ordered):
                input_hash = _sha(snapshot_samples[position])
                db.execute(
                    (
                        "INSERT INTO analysis_run_samples(run_id, position, acquisition_sample_id, "
                        "sample_name, input_sha256) VALUES (?, ?, ?, ?, ?)"
                    ),
                    (run_id, position, row["id"], row["sample_name"], input_hash),
                )
            self.repository._message(
                db,
                run_id,
                "info",
                "analysis.run.created",
                "分析运行已建立，输入和版本已锁定",
                {"sample_count": len(ordered), "line_count": len(lines), "profile": profile},
            )
            self.repository._audit(
                db,
                self.repository._actor(db, actor_user_id),
                "analysis.run.create",
                run_id,
                {
                    "input_sha256": _sha(snapshot),
                    "sample_ids": sample_ids,
                    "method_version_id": version.version_id,
                    "profile": profile,
                },
            )
        return self.repository.run(run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [
                int(row[0])
                for row in db.execute(
                    "SELECT id FROM analysis_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
                ).fetchall()
            ]
        return [self.repository.run(run_id) for run_id in ids]


    def _write_result(
        self, db: sqlite3.Connection, run_id: int, candidate: dict[str, Any], intervention_id: int | None = None
    ) -> None:
        stored = {
            key: value
            for key, value in candidate.items()
            if key not in {"spectrum_window", "window_start", "window_end", "intermediates"}
        }
        digest = _sha(stored | {"intermediates": candidate["intermediates"], "intervention_id": intervention_id})
        db.execute(
            (
                "INSERT INTO analysis_line_results(run_id, sample_position, line_position, "
                "line_id, line_type, element, wavelength_nm, ccd_index, expected_position, "
                "peak_position, peak_height, background, net_signal, gaussian_center, "
                "gaussian_peak_height, gaussian_sigma, gaussian_area, quantitative_signal, "
                "calculation_profile, intervention_id, intermediates_json, result_sha256, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?)"
            ),
            (
                run_id,
                candidate["sample_position"],
                candidate["line_position"],
                candidate["line_id"],
                candidate["line_type"],
                candidate["element"],
                candidate["wavelength_nm"],
                candidate["ccd_index"],
                candidate["expected_position"],
                candidate["peak_position"],
                candidate["peak_height"],
                candidate["background"],
                candidate["net_signal"],
                candidate["gaussian_center"],
                candidate["gaussian_peak_height"],
                candidate["gaussian_sigma"],
                candidate["gaussian_area"],
                candidate["quantitative_signal"],
                candidate["calculation_profile"],
                intervention_id,
                _json(candidate["intermediates"]),
                digest,
                utc_now(),
            ),
        )

    def _advance(self, db: sqlite3.Connection, run: sqlite3.Row, lines: list[dict[str, Any]]) -> None:
        sample_position = int(run["current_sample_position"])
        line_position = int(run["current_line_position"]) + 1
        sample_count = int(
            db.execute("SELECT COUNT(*) FROM analysis_run_samples WHERE run_id=?", (run["id"],)).fetchone()[0]
        )
        if line_position >= len(lines):
            rows = db.execute(
                (
                    "SELECT line_id, element, wavelength_nm, quantitative_signal, "
                    "calculation_profile FROM analysis_line_results WHERE run_id=? AND "
                    "sample_position=? AND line_type='analysis' ORDER BY line_position"
                ),
                (run["id"], sample_position),
            ).fetchall()
            matrix = [dict(row) for row in rows]
            db.execute(
                "UPDATE analysis_run_samples SET result_matrix_json=?, result_sha256=?, completed_at=? WHERE run_id=? AND position=?",
                (_json(matrix), _sha(matrix), utc_now(), run["id"], sample_position),
            )
            sample_position += 1
            line_position = 0
        if sample_position >= sample_count:
            matrices = [
                json.loads(row[0] or "[]")
                for row in db.execute(
                    "SELECT result_matrix_json FROM analysis_run_samples WHERE run_id=? ORDER BY position", (run["id"],)
                ).fetchall()
            ]
            result_hash = _sha(matrices)
            db.execute(
                (
                    "UPDATE analysis_runs SET status='completed', current_sample_position=?, "
                    "current_line_position=0, result_sha256=?, completed_at=?, updated_at=? WHERE "
                    "id=?"
                ),
                (sample_position, result_hash, utc_now(), utc_now(), run["id"]),
            )
            self.repository._message(
                db,
                run["id"],
                "success",
                "analysis.run.completed",
                "全部样品定量分析完成",
                {"result_sha256": result_hash},
            )
        else:
            db.execute(
                "UPDATE analysis_runs SET status='running', current_sample_position=?, current_line_position=?, updated_at=? WHERE id=?",
                (sample_position, line_position, utc_now(), run["id"]),
            )

    def start(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, _, _ = self.repository._context(db, run_id)
            if run["status"] != "draft":
                raise AnalysisError("analysis_state_invalid", "只有草稿分析运行可以开始")
            db.execute(
                "UPDATE analysis_runs SET status='running', started_at=?, updated_at=? WHERE id=?",
                (utc_now(), utc_now(), run_id),
            )
            self.repository._message(db, run_id, "info", "analysis.run.started", "分析运行已开始")
            self.repository._audit(
                db,
                self.repository._actor(db, actor_user_id),
                "analysis.run.start",
                run_id,
                {"input_sha256": run["input_sha256"]},
            )
        return self.repository.run(run_id)

    def step(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, lines = self.repository._context(db, run_id)
            pending = db.execute(
                "SELECT * FROM analysis_checkpoints WHERE run_id=? AND status='pending'", (run_id,)
            ).fetchone()
            if pending is not None:
                if datetime.fromisoformat(pending["deadline_at"]) <= datetime.now(timezone.utc):
                    db.execute(
                        "UPDATE analysis_checkpoints SET status='cancelled', resolved_at=? WHERE id=?",
                        (utc_now(), pending["id"]),
                    )
                    db.execute(
                        (
                            "UPDATE analysis_runs SET status='failed', "
                            "failure_code='analysis_intervention_timeout', failure_message='慢进人工干预超时', "
                            "failure_details_json=?, updated_at=? WHERE id=?"
                        ),
                        (_json({"checkpoint_id": pending["id"], "line_id": pending["line_id"]}), utc_now(), run_id),
                    )
                    self.repository._message(
                        db,
                        run_id,
                        "error",
                        "analysis_intervention_timeout",
                        "慢进人工干预超时",
                        {"checkpoint_id": pending["id"]},
                    )
                    self.repository._audit(
                        db,
                        self.repository._actor(db, actor_user_id),
                        "analysis.run.failed",
                        run_id,
                        {"code": "analysis_intervention_timeout", "checkpoint_id": pending["id"]},
                    )
                    return self.repository._run_dict(db, run_id)
                raise AnalysisError(
                    "analysis_intervention_pending",
                    "必须先处理当前慢进检查点",
                    details={"checkpoint_id": pending["id"]},
                )
            if run["status"] != "running":
                raise AnalysisError("analysis_state_invalid", "分析运行当前不能推进", details={"status": run["status"]})
            try:
                candidate = self.inputs.candidate(
                    db, run, payload, lines, int(run["current_sample_position"]), int(run["current_line_position"])
                )
                if run["slow_mode"]:
                    sequence = int(
                        db.execute(
                            "SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_checkpoints WHERE run_id=?", (run_id,)
                        ).fetchone()[0]
                    )
                    deadline = datetime.fromtimestamp(
                        datetime.now(timezone.utc).timestamp() + float(run["intervention_timeout_seconds"]),
                        timezone.utc,
                    ).isoformat(timespec="milliseconds")
                    db.execute(
                        (
                            "INSERT INTO analysis_checkpoints(run_id, sequence, sample_position, "
                            "line_position, line_id, status, automatic_position, window_start, window_end, "
                            "spectrum_window_json, candidate_json, deadline_at) VALUES (?, ?, ?, ?, ?, "
                            "'pending', ?, ?, ?, ?, ?, ?)"
                        ),
                        (
                            run_id,
                            sequence,
                            candidate["sample_position"],
                            candidate["line_position"],
                            candidate["line_id"],
                            candidate["peak_position"],
                            candidate["window_start"],
                            candidate["window_end"],
                            _json(candidate["spectrum_window"]),
                            _json(candidate),
                            deadline,
                        ),
                    )
                    db.execute("UPDATE analysis_runs SET status='paused', updated_at=? WHERE id=?", (utc_now(), run_id))
                    self.repository._message(
                        db,
                        run_id,
                        "info",
                        "analysis.checkpoint.pending",
                        "已暂停在逐谱线慢进检查点",
                        {"sequence": sequence, "line_id": candidate["line_id"]},
                    )
                else:
                    self._write_result(db, run_id, candidate)
                    self._advance(db, run, lines)
            except AnalysisError as exc:
                details = exc.details | {
                    "sample_position": run["current_sample_position"],
                    "line_position": run["current_line_position"],
                }
                db.execute(
                    (
                        "UPDATE analysis_runs SET status='failed', failure_code=?, failure_message=?, "
                        "failure_details_json=?, updated_at=? WHERE id=?"
                    ),
                    (exc.code, exc.message, _json(details), utc_now(), run_id),
                )
                self.repository._message(db, run_id, "error", exc.code, exc.message, details)
                self.repository._audit(
                    db,
                    self.repository._actor(db, actor_user_id),
                    "analysis.run.failed",
                    run_id,
                    {"code": exc.code, "details": details},
                )
        return self.repository.run(run_id)

    def intervene(
        self, run_id: int, action: str, adjusted_position: int | None, reason: str, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, lines = self.repository._context(db, run_id)
            checkpoint = db.execute(
                "SELECT * FROM analysis_checkpoints WHERE run_id=? AND status='pending'", (run_id,)
            ).fetchone()
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
                    raise AnalysisError(
                        "analysis_adjustment_reason_required", "接受人工定位必须填写调整位置和理由", status_code=422
                    )
                after = int(adjusted_position)
                candidate = self.inputs.candidate(
                    db,
                    run,
                    payload,
                    lines,
                    int(checkpoint["sample_position"]),
                    int(checkpoint["line_position"]),
                    forced_position=after,
                )
            now = utc_now()
            cursor = db.execute(
                (
                    "INSERT INTO analysis_interventions(run_id, checkpoint_id, action, "
                    "before_position, after_position, reason, actor_user_id, created_at) VALUES (?, "
                    "?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    run_id,
                    checkpoint["id"],
                    action,
                    before,
                    after,
                    reason.strip(),
                    self.repository._actor(db, actor_user_id),
                    now,
                ),
            )
            intervention_id = int(cursor.lastrowid)
            self._write_result(db, run_id, candidate, intervention_id)
            db.execute(
                "UPDATE analysis_checkpoints SET status=?, accepted_position=?, resolved_at=? WHERE id=?",
                ("accepted" if action == "accept" else "discarded", after, now, checkpoint["id"]),
            )
            self.repository._audit(
                db,
                self.repository._actor(db, actor_user_id),
                "analysis.intervention.accept" if action == "accept" else "analysis.intervention.discard",
                run_id,
                {
                    "checkpoint_id": checkpoint["id"],
                    "line_id": checkpoint["line_id"],
                    "before_position": before,
                    "after_position": after,
                    "reason": reason.strip(),
                },
            )
            self._advance(db, run, lines)
        return self.repository.run(run_id)

    def cancel(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, _, _ = self.repository._context(db, run_id)
            if run["status"] not in {"draft", "running", "paused"}:
                raise AnalysisError("analysis_state_invalid", "分析运行当前不能取消")
            db.execute(
                "UPDATE analysis_checkpoints SET status='cancelled', resolved_at=? WHERE run_id=? AND status='pending'",
                (utc_now(), run_id),
            )
            db.execute(
                "UPDATE analysis_runs SET status='cancelled', updated_at=?, completed_at=? WHERE id=?",
                (utc_now(), utc_now(), run_id),
            )
            self.repository._message(
                db, run_id, "warning", "analysis.run.cancelled", "分析运行已取消；未确认检查点未写入结果"
            )
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.run.cancel", run_id, {})
        return self.repository.run(run_id)

    def build_quality(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.quality.build_quality(run_id, actor_user_id)

    def decide_quality(self, run_id: int, request: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        return self.quality.decide_quality(run_id, request, actor_user_id)

    def curve_action(
        self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.curves.curve_action(run_id, line_id, request, actor_user_id)

    def fit_standard_curve(
        self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.curves.fit_standard_curve(run_id, line_id, request, actor_user_id)

    def curve_evaluators(
        self, snapshot_ids: list[int], method_version_id: int, calculation_profile: str
    ) -> dict[str, dict[str, Any]]:
        return self.curves.curve_evaluators(snapshot_ids, method_version_id, calculation_profile)

    def publish_standard_curve(
        self, run_id: int, line_id: str, curve_snapshot_id: int, reason: str, actor_user_id: int | None = None
    ) -> dict[str, Any]:
        return self.curves.publish_standard_curve(run_id, line_id, curve_snapshot_id, reason, actor_user_id)

    def merge_results(self, run_id: int, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        return self.curves.merge_results(run_id, reason, actor_user_id)

    def curve_preview(self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None = None) -> str:
        return self.printing.curve_preview(run_id, curve_snapshot_id, mode, actor_user_id)

    def print_curve(
        self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None = None
    ) -> tuple[bytes, dict[str, Any]]:
        return self.printing.print_curve(run_id, curve_snapshot_id, mode, actor_user_id)

    def run(self, run_id: int) -> dict[str, Any]:
        return self.repository.run(run_id)


    def measurement_results(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        from .measurement import measurement_results
        with self.database.read() as db:
            # 曲线、方法和质控在同一个读事务中读取，避免一次测量混用前后状态。
            db.execute("BEGIN")
            return measurement_results(db, self.methods, snapshot)

    def spectrum(self, run_id: int, sample_position: int, acquisition: Any, line_id: str | None = None) -> dict[str, Any]:
        import hashlib
        import struct
        from ..spectral_lines import exposure_interval
        from ..acquisition import AcquisitionError
        with self.database.read() as db:
            run, payload, lines = self.repository._context(db, run_id)
            locator = self.methods.bind_geometry(db, payload.get('conditions', {}))
            locations = []
            for line in lines:
                position = locator.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm']))
                if position is not None:
                    locations.append({'id': line['id'], 'element': line['element'],
                                      'wavelength_nm': line['wavelength_nm'],
                                      'ccd_index': position.ccd_index, 'point': position.point,
                                      'exposure_interval': exposure_interval(line, payload.get('conditions', {}))})
            selected_line = next((line for line in lines if str(line['id']) == line_id), None) if line_id else None
            if line_id and selected_line is None:
                raise AnalysisError('analysis_curve_line_not_found', '当前方法中不存在所选谱线', status_code=404)
            sample = db.execute('SELECT * FROM analysis_run_samples WHERE run_id=? AND position=?',
                                (run_id, sample_position)).fetchone()
            if sample is None:
                raise AnalysisError('analysis_sample_not_found', '运行中不存在该样品', status_code=404)
            fixed = json.loads(run['input_snapshot_json'])['samples'][sample_position]
        snapshot = acquisition.spectrum_snapshot(sample['acquisition_sample_id'])
        expected = {item['ccd_index']: item['mean_sha256'] for item in fixed['bands']}
        if {band['ccd_index'] for band in snapshot['bands']} != set(expected):
            raise AnalysisError('analysis_band_integrity_failed', '谱图 CCD 集合与分析输入不符')
        for band in snapshot['bands']:
            blob = struct.pack(f"<{len(band['mean_points'])}f", *band['mean_points'])
            if hashlib.sha256(blob).hexdigest() != expected.get(band['ccd_index']):
                raise AnalysisError('analysis_band_integrity_failed', '谱图与分析输入快照哈希不符')
        interval = exposure_interval(selected_line, payload.get('conditions', {})) if selected_line else None
        if interval is not None:
            try:
                views = acquisition.spectrum_interval(sample['acquisition_sample_id'], interval)
            except AcquisitionError as exc:
                raise AnalysisError(exc.code, exc.message, status_code=exc.status_code) from exc
            for band in snapshot['bands']:
                band['source_mean_sha256'] = band['mean_sha256']
                band['mean_points'] = views[band['ccd_index']]['points']
                band['mean_sha256'] = hashlib.sha256(struct.pack(f"<{len(band['mean_points'])}f", *band['mean_points'])).hexdigest()
        return {'run_id': run_id, 'sample_position': sample_position, 'sample_name': sample['sample_name'],
                'acquisition_sample_id': sample['acquisition_sample_id'], 'selected_line_id': line_id,
                'exposure_interval': interval, 'bands': snapshot['bands'], 'lines': locations}

    def record_observation_print(self, run_id: int, details: dict, actor_user_id: int) -> None:
        with self.database.write() as db:
            self.repository._context(db, run_id)
            self.repository._audit(db, actor_user_id, 'analysis.observation.print', run_id, details)

    def record_observation_export(self, run_id: int, details: dict, actor_user_id: int) -> None:
        with self.database.write() as db:
            self.repository._context(db, run_id)
            self.repository._audit(db, actor_user_id, 'analysis.observation.export', run_id, details)

    def intensity_output(self, run_id: int, options: dict, actor: int) -> dict:
        from .intensity_output import intensity_output
        return intensity_output(self,run_id,options,actor)
