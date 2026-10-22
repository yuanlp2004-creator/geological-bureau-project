"""Editable catalogue metadata is separate from immutable calibration coefficients."""
import sqlite3


def _migrate_v21(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS dispersion_calibration_metadata (calibration_version_id INTEGER PRIMARY KEY REFERENCES dispersion_calibration_versions(id) ON DELETE CASCADE, display_name TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)), updated_at TEXT NOT NULL)")
    # Acquisition owns these referential guards, avoiding a queue -> acquisition service cycle.
    connection.execute("CREATE TRIGGER IF NOT EXISTS acquisition_queue_item_delete_guard BEFORE DELETE ON sample_queue_items WHEN EXISTS(SELECT 1 FROM acquisition_tasks WHERE queue_item_id=OLD.id) OR EXISTS(SELECT 1 FROM acquisition_samples WHERE queue_item_id=OLD.id) BEGIN SELECT RAISE(ABORT,'queue item in use'); END")
    connection.execute("CREATE TRIGGER IF NOT EXISTS acquisition_queue_item_update_guard BEFORE UPDATE OF pre_name,repeats ON sample_queue_items WHEN (NEW.pre_name<>OLD.pre_name OR NEW.repeats<>OLD.repeats) AND (EXISTS(SELECT 1 FROM acquisition_tasks WHERE queue_item_id=OLD.id) OR EXISTS(SELECT 1 FROM acquisition_samples WHERE queue_item_id=OLD.id)) BEGIN SELECT RAISE(ABORT,'queue item in use'); END")
