"""合同软件闭环：转角曝光原始帧、区间结果及管理样适配证据。"""

SQL = """
CREATE TABLE IF NOT EXISTS acquisition_management_tasks (
    task_id INTEGER PRIMARY KEY REFERENCES acquisition_tasks(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hardware_exposure_frames (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id),
    step_id INTEGER NOT NULL REFERENCES hardware_plan_steps(id),
    attempt INTEGER NOT NULL,
    frame_index INTEGER NOT NULL CHECK(frame_index >= 1),
    ccd_index INTEGER NOT NULL,
    points_blob BLOB NOT NULL,
    points_count INTEGER NOT NULL,
    points_sha256 TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    UNIQUE(step_id, attempt, frame_index, ccd_index)
);
CREATE TABLE IF NOT EXISTS hardware_exposure_results (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES hardware_tasks(id),
    step_id INTEGER NOT NULL REFERENCES hardware_plan_steps(id),
    attempt INTEGER NOT NULL,
    ccd_index INTEGER NOT NULL,
    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('averaged','full_interval')),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    points_count INTEGER NOT NULL,
    mean_blob BLOB NOT NULL,
    mean_sha256 TEXT NOT NULL,
    frames_blob BLOB,
    frames_sha256 TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(step_id, attempt, ccd_index)
);
CREATE TABLE IF NOT EXISTS analysis_control_adaptations (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES analysis_runs(id),
    line_id TEXT NOT NULL,
    qc_snapshot_id INTEGER NOT NULL REFERENCES analysis_qc_snapshots(id),
    adjustment_set_id INTEGER NOT NULL REFERENCES analysis_curve_adjustment_sets(id),
    snapshot_json TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

REQUIRED_COLUMNS = {
    'acquisition_management_tasks': {'task_id', 'created_at'},
    'hardware_exposure_frames': {'id', 'task_id', 'step_id', 'attempt', 'frame_index', 'ccd_index',
                                 'points_blob', 'points_count', 'points_sha256', 'captured_at'},
    'hardware_exposure_results': {'id', 'task_id', 'step_id', 'attempt', 'ccd_index', 'storage_mode',
                                  'start_frame', 'end_frame', 'points_count', 'mean_blob',
                                  'mean_sha256', 'frames_blob', 'frames_sha256', 'created_at'},
    'analysis_control_adaptations': {'id', 'run_id', 'line_id', 'qc_snapshot_id', 'adjustment_set_id',
                                     'snapshot_json', 'snapshot_sha256', 'created_at'},
}
REQUIRED_TRIGGERS = []
for table in REQUIRED_COLUMNS:
    for action in ('update', 'delete'):
        name = f'{table}_immutable_{action}'
        REQUIRED_TRIGGERS.append(name)
        SQL += f"""
CREATE TRIGGER IF NOT EXISTS {name} BEFORE {action.upper()} ON {table}
BEGIN SELECT RAISE(ABORT, 'contract evidence is immutable'); END;
"""


from .sql import _execute_sql_script


def _migrate_v23(connection) -> None:
    _execute_sql_script(connection, SQL)
