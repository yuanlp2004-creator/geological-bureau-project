"""报告所需的分析事实快照；读取绑定事务，报告准入与格式规则仍归报告。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..methods import MethodService


@dataclass(frozen=True)
class ReportResultSnapshot:
    quality: dict[str, Any] | None
    merge_id: int | None
    curve_ids: list[int]
    active_curve_ids: list[int]
    curves: list[dict[str, Any] | None]
    _results_json: str

    def rows(self) -> list[dict[str, Any]]:
        # Preserve decoding after the caller has checked result validity.
        return json.loads(self._results_json or "[]")


class AnalysisReportReader:
    def __init__(self, connection: sqlite3.Connection, methods: MethodService):
        self._connection = connection
        self._methods = methods.bind_snapshots(connection)

    def run(self, run_id: int) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        method = self._methods.identity(row["method_id"])
        if method is None:
            return None
        return {
            **{key: row[key] for key in (
                "id", "name", "status", "method_version", "method_version_id", "calculation_profile", "result_sha256", "created_at", "completed_at"
            )},
            "method_name": method.name,
        }

    def latest_results(self, run_id: int) -> ReportResultSnapshot:
        db = self._connection
        qc = db.execute(
            "SELECT id, publishable FROM analysis_qc_snapshots WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        quality = dict(qc) if qc is not None else None
        merge = db.execute(
            "SELECT * FROM analysis_result_merges WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)
        ).fetchone()
        if merge is None:
            return ReportResultSnapshot(quality, None, [], [], [], "[]")
        curve_ids = json.loads(merge["curve_snapshot_ids_json"])
        active_ids = [
            row[0] for row in db.execute("SELECT curve_snapshot_id FROM analysis_active_curves WHERE run_id=?", (run_id,))
        ]
        curves = []
        for identifier in curve_ids:
            row = db.execute(
                "SELECT run_id, qc_snapshot_id FROM analysis_curve_snapshots WHERE id=?", (identifier,)
            ).fetchone()
            curves.append(dict(row) if row is not None else None)
        return ReportResultSnapshot(quality, int(merge["id"]), curve_ids, active_ids, curves, merge["results_json"])

    def method_payload(self, version_id: int) -> dict[str, Any]:
        snapshot = self._methods.by_id(version_id)
        return snapshot.payload if snapshot is not None else {}
