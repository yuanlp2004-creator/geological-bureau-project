"""分析运行流程与对外应用服务；显式组合质控、曲线和打印服务。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from datetime import datetime, timezone
from typing import Any
from ...db import Database, utc_now
from ..methods import MethodService
from ..spectral_lines import canonical_lines
from .errors import AnalysisError
from .serialization import _json, _sha
from .algorithms import _float32, _legacy_floor, legacy_gaussian, _bounded_range, _search_peak, MIN_SIGNAL
from .repository import AnalysisRepository
from .quality import QualityService
from .curves import CurveService
from .printing import CurvePrintingService


class AnalysisService:
    def __init__(self, database: Database, *, methods: MethodService):
        self.database = database
        self.methods = methods
        self.repository = AnalysisRepository(database, methods=methods)
        self.quality = QualityService(database, self.repository)
        self.curves = CurveService(database, self.repository)
        self.printing = CurvePrintingService(database, self.repository)

    @staticmethod
    def _profile(conditions: dict[str, Any]) -> str:
        explicit = conditions.get("calculation_profile")
        if explicit in {"legacy_2_0_2", "modern_v1"}:
            return str(explicit)
        return "legacy_2_0_2" if conditions.get("storage_profile") == "legacy_specdirect_202" else "modern_v1"

    def options(self) -> dict[str, Any]:
        with self.database.read() as db:
            samples = [dict(row) for row in db.execute(
                "SELECT s.id, s.sample_name, s.sample_kind, s.repeat_index, s.result_sha256 AS input_sha256, t.id AS acquisition_task_id, t.name AS acquisition_task_name, t.method_version_id, t.method_id, t.method_version "
                "FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.status='completed' AND s.finalized=1 AND t.method_version_id IS NOT NULL ORDER BY t.id DESC, s.repeat_index"
            ).fetchall()]
            snapshots = self.methods.bind_snapshots(db).published()
        methods = [{"method_version_id": item.version_id, "method_id": item.method.id,
                    "version": item.version, "name": item.method.name,
                    "calculation_profile": self._profile(item.payload.get("conditions", {}))}
                   for item in snapshots]
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
            version = self.methods.bind_snapshots(db).by_id(selected_version_id, published_only=True)
            if version is None:
                raise AnalysisError("analysis_method_version_not_found", "已发布方法版本不存在", status_code=404)
            method_payload = version.payload
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
            snapshot = {"method_version_id": version.version_id, "method_content_sha256": version.content_sha256, "profile": profile, "samples": snapshot_samples}
            now = utc_now()
            cursor = db.execute(
                "INSERT INTO analysis_runs(name, method_id, method_version_id, method_version, calculation_profile, slow_mode, intervention_timeout_seconds, input_snapshot_json, input_sha256, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(payload.get("name") or "S17 定量与曲线分析").strip(), version.method.id, version.version_id, version.version, profile, int(bool(payload.get("slow_mode"))), float(payload.get("intervention_timeout_seconds", 300)), _json(snapshot), _sha(snapshot), self.repository._actor(db, actor_user_id), now, now),
            )
            run_id = int(cursor.lastrowid)
            for position, row in enumerate(ordered):
                input_hash = _sha(snapshot_samples[position])
                db.execute("INSERT INTO analysis_run_samples(run_id, position, acquisition_sample_id, sample_name, input_sha256) VALUES (?, ?, ?, ?, ?)", (run_id, position, row["id"], row["sample_name"], input_hash))
            self.repository._message(db, run_id, "info", "analysis.run.created", "分析运行已建立，输入和版本已锁定", {"sample_count": len(ordered), "line_count": len(lines), "profile": profile})
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.run.create", run_id, {"input_sha256": _sha(snapshot), "sample_ids": sample_ids, "method_version_id": version.version_id, "profile": profile})
        return self.repository.run(run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.read() as db:
            ids = [int(row[0]) for row in db.execute("SELECT id FROM analysis_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()]
        return [self.repository.run(run_id) for run_id in ids]

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
            self.repository._message(db, run["id"], "success", "analysis.run.completed", "全部样品定量分析完成", {"result_sha256": result_hash})
        else:
            db.execute("UPDATE analysis_runs SET status='running', current_sample_position=?, current_line_position=?, updated_at=? WHERE id=?", (sample_position, line_position, utc_now(), run["id"]))

    def start(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, _, _ = self.repository._context(db, run_id)
            if run["status"] != "draft":
                raise AnalysisError("analysis_state_invalid", "只有草稿分析运行可以开始")
            db.execute("UPDATE analysis_runs SET status='running', started_at=?, updated_at=? WHERE id=?", (utc_now(), utc_now(), run_id))
            self.repository._message(db, run_id, "info", "analysis.run.started", "分析运行已开始")
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.run.start", run_id, {"input_sha256": run["input_sha256"]})
        return self.repository.run(run_id)

    def step(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, lines = self.repository._context(db, run_id)
            pending = db.execute("SELECT * FROM analysis_checkpoints WHERE run_id=? AND status='pending'", (run_id,)).fetchone()
            if pending is not None:
                if datetime.fromisoformat(pending["deadline_at"]) <= datetime.now(timezone.utc):
                    db.execute("UPDATE analysis_checkpoints SET status='cancelled', resolved_at=? WHERE id=?", (utc_now(), pending["id"]))
                    db.execute("UPDATE analysis_runs SET status='failed', failure_code='analysis_intervention_timeout', failure_message='慢进人工干预超时', failure_details_json=?, updated_at=? WHERE id=?", (_json({"checkpoint_id": pending["id"], "line_id": pending["line_id"]}), utc_now(), run_id))
                    self.repository._message(db, run_id, "error", "analysis_intervention_timeout", "慢进人工干预超时", {"checkpoint_id": pending["id"]})
                    self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.run.failed", run_id, {"code": "analysis_intervention_timeout", "checkpoint_id": pending["id"]})
                    return self.repository._run_dict(db, run_id)
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
                    self.repository._message(db, run_id, "info", "analysis.checkpoint.pending", "已暂停在逐谱线慢进检查点", {"sequence": sequence, "line_id": candidate["line_id"]})
                else:
                    self._write_result(db, run_id, candidate)
                    self._advance(db, run, lines)
            except AnalysisError as exc:
                details = exc.details | {"sample_position": run["current_sample_position"], "line_position": run["current_line_position"]}
                db.execute("UPDATE analysis_runs SET status='failed', failure_code=?, failure_message=?, failure_details_json=?, updated_at=? WHERE id=?", (exc.code, exc.message, _json(details), utc_now(), run_id))
                self.repository._message(db, run_id, "error", exc.code, exc.message, details)
                self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.run.failed", run_id, {"code": exc.code, "details": details})
        return self.repository.run(run_id)

    def intervene(self, run_id: int, action: str, adjusted_position: int | None, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, lines = self.repository._context(db, run_id)
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
            cursor = db.execute("INSERT INTO analysis_interventions(run_id, checkpoint_id, action, before_position, after_position, reason, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (run_id, checkpoint["id"], action, before, after, reason.strip(), self.repository._actor(db, actor_user_id), now))
            intervention_id = int(cursor.lastrowid)
            self._write_result(db, run_id, candidate, intervention_id)
            db.execute("UPDATE analysis_checkpoints SET status=?, accepted_position=?, resolved_at=? WHERE id=?", ("accepted" if action == "accept" else "discarded", after, now, checkpoint["id"]))
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.intervention.accept" if action == "accept" else "analysis.intervention.discard", run_id, {"checkpoint_id": checkpoint["id"], "line_id": checkpoint["line_id"], "before_position": before, "after_position": after, "reason": reason.strip()})
            self._advance(db, run, lines)
        return self.repository.run(run_id)

    def cancel(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, _, _ = self.repository._context(db, run_id)
            if run["status"] not in {"draft", "running", "paused"}:
                raise AnalysisError("analysis_state_invalid", "分析运行当前不能取消")
            db.execute("UPDATE analysis_checkpoints SET status='cancelled', resolved_at=? WHERE run_id=? AND status='pending'", (utc_now(), run_id))
            db.execute("UPDATE analysis_runs SET status='cancelled', updated_at=?, completed_at=? WHERE id=?", (utc_now(), utc_now(), run_id))
            self.repository._message(db, run_id, "warning", "analysis.run.cancelled", "分析运行已取消；未确认检查点未写入结果")
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.run.cancel", run_id, {})
        return self.repository.run(run_id)

    def build_quality(self, run_id: int, actor_user_id: int | None=None) -> dict[str, Any]:
        return self.quality.build_quality(run_id, actor_user_id)

    def decide_quality(self, run_id: int, request: dict[str, Any], actor_user_id: int | None=None) -> dict[str, Any]:
        return self.quality.decide_quality(run_id, request, actor_user_id)

    def curve_action(self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None=None) -> dict[str, Any]:
        return self.curves.curve_action(run_id, line_id, request, actor_user_id)

    def fit_standard_curve(self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None=None) -> dict[str, Any]:
        return self.curves.fit_standard_curve(run_id, line_id, request, actor_user_id)

    def curve_evaluators(self, snapshot_ids: list[int], method_version_id: int, calculation_profile: str) -> dict[str, dict[str, Any]]:
        return self.curves.curve_evaluators(snapshot_ids, method_version_id, calculation_profile)

    def publish_standard_curve(self, run_id: int, line_id: str, curve_snapshot_id: int, reason: str, actor_user_id: int | None=None) -> dict[str, Any]:
        return self.curves.publish_standard_curve(run_id, line_id, curve_snapshot_id, reason, actor_user_id)

    def merge_results(self, run_id: int, reason: str, actor_user_id: int | None=None) -> dict[str, Any]:
        return self.curves.merge_results(run_id, reason, actor_user_id)

    def curve_preview(self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None=None) -> str:
        return self.printing.curve_preview(run_id, curve_snapshot_id, mode, actor_user_id)

    def print_curve(self, run_id: int, curve_snapshot_id: int, mode: str, actor_user_id: int | None=None) -> tuple[bytes, dict[str, Any]]:
        return self.printing.print_curve(run_id, curve_snapshot_id, mode, actor_user_id)

    def run(self, run_id: int) -> dict[str, Any]:
        return self.repository.run(run_id)

