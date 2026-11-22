"""Retain capture history when a task is removed from the workbench."""
import sqlite3


def _migrate_v32(connection: sqlite3.Connection) -> None:
    for table in ("acquisition_tasks", "dispersion_tasks"):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "discarded_at" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN discarded_at TEXT")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS acquisition_disposals_prepared_guard
        BEFORE INSERT ON acquisition_sample_disposals
        WHEN EXISTS(SELECT 1 FROM postprocessing_prepared_targets t, json_each(t.records_json) r
            WHERE json_extract(r.value, '$.id')=NEW.sample_id)
        BEGIN SELECT RAISE(ABORT, 'sample used in prepared collection'); END""")
