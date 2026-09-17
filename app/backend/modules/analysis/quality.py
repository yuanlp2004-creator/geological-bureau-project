"""重复测量质控及快照事务。"""

from __future__ import annotations

import re
import sqlite3
from typing import Any
from ...db import Database, utc_now
from .errors import AnalysisError
from .serialization import _json, _sha
from .algorithms import repeat_statistics
from .repository import AnalysisRepository


class QualityService:
    def __init__(self, database: Database, repository: AnalysisRepository):
        self.database = database
        self.repository = repository

    @staticmethod
    def _standard_index(name: str) -> int | None:
        match = re.fullmatch(r"S([0-9]+)", name.strip(), flags=re.IGNORECASE)
        if match is None:
            return None
        number = int(match.group(1))
        return number - 1 if 1 <= number <= 50 else None

    def _qc_groups(self, db: sqlite3.Connection, run_id: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
        conditions = payload.get("conditions", {})
        latest: dict[int, sqlite3.Row] = {}
        accepted: set[tuple[int, str]] = set()
        for decision in db.execute("SELECT * FROM analysis_qc_decisions WHERE run_id=? ORDER BY id", (run_id,)).fetchall():
            if decision["line_result_id"] is None:
                if decision["action"] == "accept":
                    accepted.add((int(decision["acquisition_task_id"]), str(decision["line_id"])))
            else:
                latest[int(decision["line_result_id"])] = decision
        rows = db.execute(
            "SELECT lr.id AS line_result_id, lr.line_id, lr.element, lr.wavelength_nm, lr.quantitative_signal, lr.result_sha256 AS source_sha256, "
            "ars.sample_name, ars.position AS sample_position, s.repeat_index, s.sample_kind, s.task_id AS acquisition_task_id "
            "FROM analysis_line_results lr JOIN analysis_run_samples ars ON ars.run_id=lr.run_id AND ars.position=lr.sample_position "
            "JOIN acquisition_samples s ON s.id=ars.acquisition_sample_id "
            "WHERE lr.run_id=? AND lr.line_type='analysis' ORDER BY s.task_id, lr.line_position, s.repeat_index",
            (run_id,),
        ).fetchall()
        grouped: dict[tuple[int, str], list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault((int(row["acquisition_task_id"]), str(row["line_id"])), []).append(row)
        groups: list[dict[str, Any]] = []
        for (task_id, line_id), members in grouped.items():
            member_payload: list[dict[str, Any]] = []
            included_values: list[float] = []
            for row in members:
                decision = latest.get(int(row["line_result_id"]))
                included = True if decision is None else bool(decision["after_included"])
                value = float(row["quantitative_signal"])
                if included:
                    included_values.append(value)
                member_payload.append({
                    "line_result_id": int(row["line_result_id"]), "sample_position": int(row["sample_position"]),
                    "repeat_index": int(row["repeat_index"]), "value": value, "included": included,
                    "source_sha256": row["source_sha256"], "last_decision_id": int(decision["id"]) if decision else None,
                })
            stats = repeat_statistics(included_values)
            warnings: list[dict[str, Any]] = []
            if stats["effective_count"] == 0:
                warnings.append({"code": "analysis_qc_no_effective_repeat", "message": "全部重复已剔除，无法形成有效均值"})
            elif stats["effective_count"] == 1 and len(members) > 1:
                warnings.append({"code": "analysis_qc_single_effective_repeat", "message": "仅剩一个有效重复，标准差和 RSD 为零"})
            if stats["id"] is not None and stats["id"] > float(conditions.get("maximum_id_deviation", 5.0)):
                warnings.append({"code": "analysis_qc_id_exceeded", "message": "重复测量 ID 超过方法阈值", "actual": stats["id"], "threshold": float(conditions.get("maximum_id_deviation", 5.0))})
            if bool(conditions.get("rsd_enabled", True)) and stats["rsd"] is not None and stats["rsd"] > float(conditions.get("rsd_threshold", 5.0)):
                warnings.append({"code": "analysis_qc_rsd_exceeded", "message": "重复测量 RSD 超过方法阈值", "actual": stats["rsd"], "threshold": float(conditions.get("rsd_threshold", 5.0))})
            first = members[0]
            sample_name = str(first["sample_name"])
            groups.append({
                "acquisition_task_id": task_id, "sample_name": sample_name, "sample_kind": first["sample_kind"],
                "standard_index": self._standard_index(sample_name), "line_id": line_id, "element": first["element"],
                "wavelength_nm": float(first["wavelength_nm"]), "repeat_count": len(members), "members": member_payload,
                "statistics": stats, "warnings": warnings, "warning_accepted": (task_id, line_id) in accepted,
            })
        return groups

    def _write_qc_snapshot(self, db: sqlite3.Connection, run_id: int, payload: dict[str, Any], actor_user_id: int | None) -> int:
        groups = self._qc_groups(db, run_id, payload)
        sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM analysis_qc_snapshots WHERE run_id=?", (run_id,)).fetchone()[0])
        publishable = bool(groups) and all(group["statistics"]["effective_count"] > 0 for group in groups)
        snapshot = {"sequence": sequence, "groups": groups, "publishable": publishable}
        cursor = db.execute(
            "INSERT INTO analysis_qc_snapshots(run_id, sequence, groups_json, publishable, result_sha256, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, sequence, _json(groups), int(publishable), _sha(snapshot), self.repository._actor(db, actor_user_id), utc_now()),
        )
        return int(cursor.lastrowid)

    def build_quality(self, run_id: int, actor_user_id: int | None = None) -> dict[str, Any]:
        with self.database.write() as db:
            run, payload, _ = self.repository._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_qc_run_incomplete", "只有已完成的定量分析可以进入重复质控")
            snapshot_id = self._write_qc_snapshot(db, run_id, payload, actor_user_id)
            self.repository._audit(db, self.repository._actor(db, actor_user_id), "analysis.qc.recalculate", run_id, {"qc_snapshot_id": snapshot_id})
        return self.repository.run(run_id)

    def decide_quality(self, run_id: int, request: dict[str, Any], actor_user_id: int | None = None) -> dict[str, Any]:
        action = str(request.get("action"))
        task_id, line_id = int(request["acquisition_task_id"]), str(request["line_id"])
        line_result_id = request.get("line_result_id")
        reason = str(request.get("reason") or "").strip()
        with self.database.write() as db:
            run, payload, _ = self.repository._context(db, run_id)
            if run["status"] != "completed":
                raise AnalysisError("analysis_qc_run_incomplete", "只有已完成的定量分析可以进行重复质控")
            groups = self._qc_groups(db, run_id, payload)
            group = next((item for item in groups if item["acquisition_task_id"] == task_id and item["line_id"] == line_id), None)
            if group is None:
                raise AnalysisError("analysis_qc_group_not_found", "重复质控组不存在", status_code=404)
            before: bool | None = None
            after: bool | None = None
            if action == "accept":
                if line_result_id is not None:
                    raise AnalysisError("analysis_qc_accept_scope_invalid", "接受提示是组级操作，不能指定重复记录", status_code=422)
            else:
                member = next((item for item in group["members"] if item["line_result_id"] == line_result_id), None)
                if member is None:
                    raise AnalysisError("analysis_qc_member_not_found", "重复测量记录不存在", status_code=404)
                before = bool(member["included"])
                after = action == "restore"
                if action == "exclude" and not before:
                    raise AnalysisError("analysis_qc_already_excluded", "该重复已经被剔除")
                if action == "restore" and before:
                    raise AnalysisError("analysis_qc_already_included", "该重复当前已有效")
            cursor = db.execute(
                "INSERT INTO analysis_qc_decisions(run_id, acquisition_task_id, line_id, line_result_id, action, before_included, after_included, reason, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, task_id, line_id, line_result_id, action, None if before is None else int(before), None if after is None else int(after), reason, self.repository._actor(db, actor_user_id), utc_now()),
            )
            snapshot_id = self._write_qc_snapshot(db, run_id, payload, actor_user_id)
            self.repository._audit(db, self.repository._actor(db, actor_user_id), f"analysis.qc.{action}", run_id, {"decision_id": int(cursor.lastrowid), "qc_snapshot_id": snapshot_id, "acquisition_task_id": task_id, "line_id": line_id, "line_result_id": line_result_id, "reason": reason})
        return self.repository.run(run_id)

