"""Store the sample group selected for each analysis result and QC decision."""
import sqlite3


def _migrate_v31(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE analysis_qc_decisions ADD COLUMN sample_group_position INTEGER")
    connection.execute("""
        CREATE TABLE analysis_curve_results_numbered (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
            curve_snapshot_id INTEGER NOT NULL REFERENCES analysis_curve_snapshots(id),
            acquisition_task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id),
            sample_name TEXT NOT NULL,
            sample_kind TEXT NOT NULL,
            is_standard INTEGER NOT NULL CHECK(is_standard IN (0,1)),
            standard_value REAL,
            effective_count INTEGER NOT NULL CHECK(effective_count >= 0),
            intensity REAL NOT NULL,
            calculated_value REAL NOT NULL,
            result_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sample_group_position INTEGER
        )
    """)
    connection.execute("INSERT INTO analysis_curve_results_numbered SELECT *, NULL FROM analysis_curve_results")
    connection.execute("DROP TABLE analysis_curve_results")
    connection.execute("ALTER TABLE analysis_curve_results_numbered RENAME TO analysis_curve_results")
    connection.execute("""
        CREATE UNIQUE INDEX analysis_curve_results_by_task ON analysis_curve_results(curve_snapshot_id, acquisition_task_id)
        WHERE sample_group_position IS NULL
    """)
    connection.execute("""
        CREATE UNIQUE INDEX analysis_curve_results_by_sample ON analysis_curve_results(curve_snapshot_id, sample_group_position)
        WHERE sample_group_position IS NOT NULL
    """)
    connection.execute("""
        CREATE INDEX idx_analysis_curve_results_run ON analysis_curve_results(run_id, curve_snapshot_id, acquisition_task_id)
    """)
