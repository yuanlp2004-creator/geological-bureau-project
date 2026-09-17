"""标准曲线调整、拟合、发布及结果合并事务。"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any
from ...db import Database, utc_now
from .errors import AnalysisError
from .serialization import _json, _sha
from .algorithms import fit_curve, evaluate_curve, FIT_MODES, COORDINATE_TYPES
from .repository import AnalysisRepository


class CurveService:
    def __init__(self, database: Database, repository: AnalysisRepository):
        self.database = database
        self.repository = repository

    def _save_workspace(self, db: sqlite3.Connection, run_id: int, line_id: str, qc_id: int, workspace: dict[str, Any], actor_user_id: int | None) -> int:
        sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_curve_adjustment_sets WHERE run_id=? AND line_id=?", (run_id, line_id)).fetchone()[0])
        stored = {"fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "points": workspace["points"]}
        cursor = db.execute(
            "INSERT INTO analysis_curve_adjustment_sets(run_id, line_id, qc_snapshot_id, sequence, fit_mode, coordinate_type, points_json, workspace_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, line_id, qc_id, sequence, workspace["fit_mode"], workspace["coordinate_type"], _json(workspace["points"]), _sha(stored), self.repository._actor(db, actor_user_id), utc_now()),
        )
        return int(cursor.lastrowid)

    def curve_action(self, run_id: int, line_id: str, request: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        action, reason = str(request["action"]), str(request.get("reason") or "").strip()
        with self.database.write() as db:
            run, payload, _ = self.repository._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_curve_run_incomplete", "只有已完成的分析可以调整标准曲线")
            line = next((item for item in self.repository._analysis_lines(payload) if str(item["id"]) == line_id), None)
            if line is None:
                raise AnalysisError("analysis_curve_line_not_found", "分析线不存在", status_code=404)
            qc = self.repository._latest_qc(db, run_id)
            workspace = self.repository._curve_workspace(db, run_id, line, qc)
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
                (run_id, line_id, qc["id"], action, index, _json(before), _json(after), reason, self.repository._actor(db, actor_user_id), utc_now()),
            )
            self.repository._audit(db, self.repository._actor(db, actor_user_id), f"analysis.curve.{action}", run_id, {"line_id": line_id, "action_id": int(cursor.lastrowid), "adjustment_set_id": adjustment_id, "qc_snapshot_id": int(qc["id"]), "reason": reason})
        return self.repository.run(run_id)

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
            run, payload, _ = self.repository._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_curve_run_incomplete", "只有已完成的分析可以拟合标准曲线")
            line = next((item for item in self.repository._analysis_lines(payload) if str(item["id"]) == line_id), None)
            if line is None:
                raise AnalysisError("analysis_curve_line_not_found", "分析线不存在", status_code=404)
            qc = self.repository._latest_qc(db, run_id)
            workspace = self.repository._curve_workspace(db, run_id, line, qc)
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
                (run_id, line_id, qc["id"], adjustment_id, sequence, workspace["fit_mode"], workspace["coordinate_type"], _json(workspace["points"]), _json(fit), _json(diagnostics), _json(chart), int(bool(qc["publishable"])), _sha(snapshot), self.repository._actor(db, actor_user_id), utc_now()),
            )
            snapshot_id = int(cursor.lastrowid)
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.curve.fit", run_id, {"line_id": line_id, "curve_snapshot_id": snapshot_id, "fit_mode": workspace["fit_mode"], "coordinate_type": workspace["coordinate_type"], "qc_snapshot_id": int(qc["id"]), "reason": request.get("reason")})
        return self.repository.run(run_id)

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
            run, payload, _ = self.repository._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_curve_run_incomplete", "只有已完成的分析可以发布标准曲线")
            curve = db.execute("SELECT * FROM analysis_curve_snapshots WHERE id=? AND run_id=? AND line_id=?", (curve_snapshot_id, run_id, line_id)).fetchone()
            if curve is None:
                raise AnalysisError("analysis_curve_snapshot_not_found", "曲线快照不存在", status_code=404)
            latest_qc = self.repository._latest_qc(db, run_id)
            if int(curve["qc_snapshot_id"]) != int(latest_qc["id"]):
                raise AnalysisError("analysis_curve_qc_stale", "质控决定已变化，请基于最新质控重新拟合")
            if not curve["publishable"] or not latest_qc["publishable"]:
                raise AnalysisError("analysis_curve_not_publishable", "当前质控或拟合结果不可发布")
            fit, coordinate_type = json.loads(curve["fit_json"]), str(curve["coordinate_type"])
            groups = [item for item in json.loads(latest_qc["groups_json"]) if item["line_id"] == line_id]
            if not groups or any(item["statistics"]["effective_count"] <= 0 for item in groups):
                raise AnalysisError("analysis_curve_effective_repeats_insufficient", "存在没有有效重复的样品，不能发布曲线")
            line = next((item for item in self.repository._analysis_lines(payload) if str(item["id"]) == line_id), None)
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
                (run_id, line_id, curve_snapshot_id, self.repository._actor(db, actor_user_id), utc_now()),
            )
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.curve.publish", run_id, {"line_id": line_id, "curve_snapshot_id": curve_snapshot_id, "result_sha256": curve["result_sha256"], "reason": reason})
        return self.repository.run(run_id)

    def merge_results(self, run_id: int, reason: str, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, _ = self.repository._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_merge_run_incomplete", "只有已完成的分析可以合并结果")
            lines = self.repository._analysis_lines(payload)
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
                (run_id, sequence, _json(curve_ids), _json(merged_samples), _sha(snapshot), self.repository._actor(db, actor_user_id), utc_now()),
            )
            merge_id = int(cursor.lastrowid)
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.results.merge", run_id, {"merge_id": merge_id, "curve_snapshot_ids": curve_ids, "sample_count": len(merged_samples), "reason": reason})
        return self.repository.run(run_id)

