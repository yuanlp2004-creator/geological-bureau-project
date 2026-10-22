"""合同补充要求：新版样号长度及不可变异常样品删除记录。"""

SQL = """
CREATE TABLE IF NOT EXISTS sample_queue_options (
    queue_id INTEGER PRIMARY KEY REFERENCES sample_queues(id),
    name_length INTEGER NOT NULL CHECK(name_length IN (10,12,20))
);
CREATE TABLE IF NOT EXISTS acquisition_task_options (
    task_id INTEGER PRIMARY KEY REFERENCES acquisition_tasks(id),
    name_length INTEGER NOT NULL CHECK(name_length IN (10,12,20))
);
CREATE TABLE IF NOT EXISTS acquisition_sample_disposals (
    sample_id INTEGER PRIMARY KEY REFERENCES acquisition_samples(id),
    reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS acquisition_disposals_immutable_update
BEFORE UPDATE ON acquisition_sample_disposals
BEGIN SELECT RAISE(ABORT, 'sample disposal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS acquisition_disposals_immutable_delete
BEFORE DELETE ON acquisition_sample_disposals
BEGIN SELECT RAISE(ABORT, 'sample disposal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS acquisition_disposals_analysis_guard
BEFORE INSERT ON acquisition_sample_disposals
WHEN EXISTS(SELECT 1 FROM analysis_run_samples WHERE acquisition_sample_id=NEW.sample_id)
BEGIN SELECT RAISE(ABORT, 'sample already analyzed'); END;
CREATE TRIGGER IF NOT EXISTS analysis_disposed_sample_guard
BEFORE INSERT ON analysis_run_samples
WHEN EXISTS(SELECT 1 FROM acquisition_sample_disposals WHERE sample_id=NEW.acquisition_sample_id)
BEGIN SELECT RAISE(ABORT, 'sample discarded'); END;
"""

REQUIRED_COLUMNS = {
    "sample_queue_options": ["queue_id", "name_length"],
    "acquisition_task_options": ["task_id", "name_length"],
    "acquisition_sample_disposals": ["sample_id", "reason", "created_by", "created_at"],
}
REQUIRED_TRIGGERS = [
    "acquisition_disposals_immutable_update", "acquisition_disposals_immutable_delete",
    "acquisition_disposals_analysis_guard", "analysis_disposed_sample_guard",
]


from .sql import _execute_sql_script


def _migrate_v22(connection) -> None:
    _execute_sql_script(connection, SQL)
