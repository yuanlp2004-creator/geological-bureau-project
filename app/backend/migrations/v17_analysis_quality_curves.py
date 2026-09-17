"""Existing v17 migration: analysis_quality_curves."""

import sqlite3

from .sql import _require_tables


def _migrate_v17(connection: sqlite3.Connection) -> None:
    _require_tables(
        connection,
        17,
        (
            "analysis_qc_decisions",
            "analysis_qc_snapshots",
            "analysis_curve_actions",
            "analysis_curve_adjustment_sets",
            "analysis_curve_snapshots",
            "analysis_active_curves",
            "analysis_curve_results",
            "analysis_result_merges",
            "analysis_curve_print_jobs",
        ),
    )
