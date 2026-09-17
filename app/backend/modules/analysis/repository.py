"""分析模块共享查询、结果装配与事务内写入辅助；不创建独立写事务。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from ...db import Database, utc_now
from ..methods import MethodService
from ..spectral_lines import canonical_lines
from .errors import AnalysisError
from .serialization import _json


class AnalysisRepository:
    def __init__(self, database: Database, *, methods: MethodService):
        self.database = database
        self.methods = methods

    @staticmethod
    def _actor(db: sqlite3.Connection, actor_user_id: int | None) -> int | None:
        if actor_user_id is None:
            return None
        return actor_user_id if db.execute("SELECT 1 FROM users WHERE id=?", (actor_user_id,)).fetchone() else None

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: int | None, action: str, run_id: int, details: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json, created_at) VALUES (?, ?, 'analysis', ?, ?, ?)",
            (actor, action, run_id, _json(details), utc_now()),
        )

    @staticmethod
    def _message(db: sqlite3.Connection, run_id: int, level: str, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO analysis_messages(run_id, level, code, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, level, code, message, _json(details or {}), utc_now()))

    @staticmethod
    def _operational_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
        lines = [line for line in canonical_lines(payload.get("lines"), payload.get("conditions", {})) if line.get("enabled")]
        return [line for line in lines if line.get("line_type") == "baseline"] + [line for line in lines if line.get("line_type") in {"positioning", "internal_standard"}] + [line for line in lines if line.get("line_type") == "analysis"]

    def _context(self, db: sqlite3.Connection, run_id: int) -> tuple[sqlite3.Row, dict[str, Any], list[dict[str, Any]]]:
        run = db.execute("SELECT * FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise AnalysisError("analysis_run_not_found", "分析运行不存在", status_code=404)
        version = self.methods.bind_snapshots(db).by_id(run["method_version_id"])
        if version is None:
            raise AnalysisError("analysis_method_version_not_found", "分析运行引用的方法版本不存在")
        payload = version.payload
        return run, payload, self._operational_lines(payload)

    @staticmethod
    def _analysis_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [line for line in canonical_lines(payload.get("lines"), payload.get("conditions", {})) if line.get("enabled") and line.get("line_type") == "analysis"]

    @staticmethod
    def _latest_qc(db: sqlite3.Connection, run_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM analysis_qc_snapshots WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        if row is None:
            raise AnalysisError("analysis_qc_missing", "请先计算重复测量质控")
        return row

    def _base_curve_points(self, line: dict[str, Any], qc: sqlite3.Row) -> list[dict[str, Any]]:
        groups = json.loads(qc["groups_json"])
        by_name: dict[str, dict[str, Any]] = {}
        for group in groups:
            if group["line_id"] == str(line.get("id")) and group.get("sample_kind") == "standard":
                by_name[str(group.get("sample_name") or "").strip().casefold()] = group
        points: list[dict[str, Any]] = []
        for index, standard in enumerate(line.get("standard_points") or []):
            name = str(standard.get("name") or f"S{index + 1}").strip()
            group = by_name.get(name.casefold())
            mean = group["statistics"]["mean"] if group else None
            points.append({
                "point_index": index, "name": name, "standard_value": float(standard["value"]),
                "original_intensity": mean, "adjusted_intensity": mean,
                "original_active": bool(standard.get("active", True)), "active": bool(standard.get("active", True)),
                "qc_group": {"acquisition_task_id": group["acquisition_task_id"], "effective_count": group["statistics"]["effective_count"]} if group else None,
            })
        return points

    def _curve_workspace(self, db: sqlite3.Connection, run_id: int, line: dict[str, Any], qc: sqlite3.Row) -> dict[str, Any]:
        latest = db.execute("SELECT * FROM analysis_curve_adjustment_sets WHERE run_id=? AND line_id=? AND qc_snapshot_id=? ORDER BY sequence DESC LIMIT 1", (run_id, str(line["id"]), qc["id"])).fetchone()
        if latest is None:
            return {"fit_mode": line.get("fit_mode", "linear"), "coordinate_type": line.get("coordinate_type", "normal"), "points": self._base_curve_points(line, qc), "adjustment_set_id": None, "sequence": 0}
        return {"fit_mode": latest["fit_mode"], "coordinate_type": latest["coordinate_type"], "points": json.loads(latest["points_json"]), "adjustment_set_id": int(latest["id"]), "sequence": int(latest["sequence"])}

    @staticmethod
    def _curve_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for field in ("points_json", "fit_json", "diagnostics_json", "chart_json"):
            item[field.removesuffix("_json")] = json.loads(item.pop(field))
        item["publishable"] = bool(item["publishable"])
        return item

    def _run_dict(self, db: sqlite3.Connection, run_id: int) -> dict[str, Any]:
        row = db.execute("SELECT * FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise AnalysisError("analysis_run_not_found", "分析运行不存在", status_code=404)
        method = self.methods.bind_snapshots(db).identity(row["method_id"])
        if method is None:
            raise AnalysisError("analysis_run_not_found", "分析运行不存在", status_code=404)
        result = dict(row)
        result["method_name"] = method.name
        result["slow_mode"] = bool(result["slow_mode"])
        for field in ("input_snapshot_json", "failure_details_json"):
            result[field.removesuffix("_json")] = json.loads(result.pop(field) or ("{}" if field == "failure_details_json" else "{}"))
        samples: list[dict[str, Any]] = []
        for sample in db.execute("SELECT * FROM analysis_run_samples WHERE run_id=? ORDER BY position", (run_id,)).fetchall():
            item = dict(sample)
            item["result_matrix"] = json.loads(item.pop("result_matrix_json") or "[]")
            samples.append(item)
        result["samples"] = samples
        result["line_results"] = []
        for line in db.execute("SELECT * FROM analysis_line_results WHERE run_id=? ORDER BY sample_position, line_position", (run_id,)).fetchall():
            item = dict(line)
            item["intermediates"] = json.loads(item.pop("intermediates_json"))
            result["line_results"].append(item)
        checkpoint = db.execute("SELECT * FROM analysis_checkpoints WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)).fetchone()
        result["checkpoint"] = None
        if checkpoint is not None:
            item = dict(checkpoint)
            item["spectrum_window"] = json.loads(item.pop("spectrum_window_json"))
            item["candidate"] = json.loads(item.pop("candidate_json"))
            result["checkpoint"] = item
        result["interventions"] = [dict(item) for item in db.execute("SELECT * FROM analysis_interventions WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        result["messages"] = [{**dict(item), "details": json.loads(item["details_json"]), **{"details_json": None}} for item in db.execute("SELECT * FROM analysis_messages WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        for message in result["messages"]:
            message.pop("details_json", None)
        decisions = [dict(item) for item in db.execute("SELECT * FROM analysis_qc_decisions WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        qc_rows = db.execute("SELECT * FROM analysis_qc_snapshots WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        qc_snapshots = []
        for snapshot in qc_rows:
            item = dict(snapshot); item["groups"] = json.loads(item.pop("groups_json")); item["publishable"] = bool(item["publishable"]); qc_snapshots.append(item)
        result["quality"] = {"latest_snapshot": qc_snapshots[-1] if qc_snapshots else None, "snapshot_history": [{key: item[key] for key in ("id", "sequence", "publishable", "result_sha256", "created_at")} for item in qc_snapshots], "decisions": decisions}
        version = self.methods.bind_snapshots(db).by_id(row["method_version_id"])
        payload = version.payload if version else {}
        latest_qc_row = qc_rows[-1] if qc_rows else None
        active = {str(item["line_id"]): int(item["curve_snapshot_id"]) for item in db.execute("SELECT * FROM analysis_active_curves WHERE run_id=?", (run_id,)).fetchall()}
        curve_lines: list[dict[str, Any]] = []
        for line in self._analysis_lines(payload):
            line_id = str(line["id"])
            snapshots = [self._curve_row(item) for item in db.execute("SELECT * FROM analysis_curve_snapshots WHERE run_id=? AND line_id=? ORDER BY sequence", (run_id, line_id)).fetchall()]
            workspace = self._curve_workspace(db, run_id, line, latest_qc_row) if latest_qc_row is not None else {"fit_mode": line.get("fit_mode", "linear"), "coordinate_type": line.get("coordinate_type", "normal"), "points": [], "adjustment_set_id": None, "sequence": 0}
            curve_lines.append({
                "line_id": line_id, "element": line.get("element", ""), "wavelength_nm": float(line.get("wavelength_nm", 0)),
                "unit": line.get("unit", ""), "workspace": workspace, "snapshots": snapshots,
                "active_curve_snapshot_id": active.get(line_id),
            })
        actions: list[dict[str, Any]] = []
        for action in db.execute("SELECT * FROM analysis_curve_actions WHERE run_id=? ORDER BY id", (run_id,)).fetchall():
            item = dict(action); item["before"] = json.loads(item.pop("before_json")); item["after"] = json.loads(item.pop("after_json")); actions.append(item)
        curve_results = [dict(item) | {"is_standard": bool(item["is_standard"])} for item in db.execute("SELECT * FROM analysis_curve_results WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        merges: list[dict[str, Any]] = []
        for merge in db.execute("SELECT * FROM analysis_result_merges WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall():
            item = dict(merge); item["curve_snapshot_ids"] = json.loads(item.pop("curve_snapshot_ids_json")); item["results"] = json.loads(item.pop("results_json")); merges.append(item)
        print_jobs = [dict(item) for item in db.execute("SELECT id, run_id, curve_snapshot_id, mode, request_json, content_sha256, byte_length, actor_user_id, created_at FROM analysis_curve_print_jobs WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        for item in print_jobs:
            item["request"] = json.loads(item.pop("request_json"))
        result["curves"] = {"lines": curve_lines, "actions": actions, "results": curve_results, "merges": merges, "print_jobs": print_jobs}
        return result

    def run(self, run_id: int) -> dict[str, Any]:
        with self.database.read() as db:
            return self._run_dict(db, run_id)

