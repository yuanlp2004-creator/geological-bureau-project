"""Acquisition owns turn execution and immutable attempt evidence."""
import sqlite3


def _migrate_v24(connection: sqlite3.Connection) -> None:
    statements = (
        '''CREATE TABLE acquisition_turn_tasks (
            task_id INTEGER PRIMARY KEY REFERENCES acquisition_tasks(id),
            config_json TEXT NOT NULL, runtime_json TEXT NOT NULL)''',
        '''CREATE TABLE acquisition_turn_frames (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id),
            repeat_index INTEGER NOT NULL, turn_index INTEGER NOT NULL, attempt INTEGER NOT NULL,
            phase TEXT NOT NULL CHECK(phase IN ('burn','dark')), frame_index INTEGER NOT NULL,
            ccd_index INTEGER NOT NULL, points_blob BLOB, points_count INTEGER NOT NULL,
            points_sha256 TEXT, metrics_json TEXT NOT NULL, event_json TEXT NOT NULL, damaged INTEGER NOT NULL CHECK(damaged IN (0,1)),
            accepted INTEGER NOT NULL CHECK(accepted IN (0,1)), captured_at TEXT NOT NULL,
            UNIQUE(task_id,repeat_index,turn_index,attempt,phase,frame_index,ccd_index))''',
        'CREATE INDEX acquisition_turn_frames_task ON acquisition_turn_frames(task_id,repeat_index,turn_index,attempt)',
        '''CREATE TRIGGER acquisition_turn_config_immutable BEFORE UPDATE OF config_json ON acquisition_turn_tasks
            BEGIN SELECT RAISE(ABORT,'acquisition turn configuration is immutable'); END''',
        '''CREATE TRIGGER acquisition_turn_frame_immutable BEFORE UPDATE OF task_id,repeat_index,turn_index,attempt,phase,frame_index,
            ccd_index,points_blob,points_count,points_sha256,metrics_json,event_json,damaged,captured_at ON acquisition_turn_frames
            BEGIN SELECT RAISE(ABORT,'acquisition turn evidence is immutable'); END''',
        '''CREATE TRIGGER acquisition_turn_frame_no_delete BEFORE DELETE ON acquisition_turn_frames
            BEGIN SELECT RAISE(ABORT,'acquisition turn evidence is immutable'); END''',
        '''CREATE TRIGGER acquisition_turn_config_no_delete BEFORE DELETE ON acquisition_turn_tasks
            BEGIN SELECT RAISE(ABORT,'acquisition turn configuration is immutable'); END''',
        '''CREATE TRIGGER acquisition_turn_accept_monotonic BEFORE UPDATE OF accepted ON acquisition_turn_frames WHEN OLD.accepted=1 AND NEW.accepted=0
            BEGIN SELECT RAISE(ABORT,'confirmed turn evidence cannot be withdrawn'); END''',
    )
    for statement in statements:
        connection.execute(statement)
