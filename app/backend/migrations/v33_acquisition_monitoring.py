"""Add acquisition monitoring state, immutable decisions, and single-angle attempt isolation."""
import sqlite3


def _migrate_v33(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS acquisition_monitoring_state (
            task_id INTEGER PRIMARY KEY REFERENCES acquisition_tasks(id),
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS acquisition_monitoring_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id),
            repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
            turn_index INTEGER NOT NULL DEFAULT 0 CHECK(turn_index >= 0),
            attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
            frame_index INTEGER NOT NULL DEFAULT 0 CHECK(frame_index >= 0),
            anomaly_kinds_json TEXT NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('accept','warn','correct','retry','manual','stop')),
            correction_offset REAL,
            observed_json TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            actor_user_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_acquisition_monitoring_decisions_task
            ON acquisition_monitoring_decisions(task_id, repeat_index, turn_index, attempt)""",
        """CREATE TRIGGER IF NOT EXISTS acquisition_monitoring_decisions_immutable_update
            BEFORE UPDATE ON acquisition_monitoring_decisions
            BEGIN SELECT RAISE(ABORT, 'acquisition monitoring decisions are immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS acquisition_monitoring_decisions_immutable_delete
            BEFORE DELETE ON acquisition_monitoring_decisions
            BEGIN SELECT RAISE(ABORT, 'acquisition monitoring decisions are immutable'); END""",
        """CREATE TABLE IF NOT EXISTS acquisition_attempt_frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES acquisition_tasks(id),
            sample_id INTEGER NOT NULL REFERENCES acquisition_samples(id),
            repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
            attempt INTEGER NOT NULL CHECK(attempt >= 0),
            phase TEXT NOT NULL CHECK(phase IN ('burn','dark')),
            frame_index INTEGER NOT NULL CHECK(frame_index >= 0),
            ccd_index INTEGER NOT NULL CHECK(ccd_index >= 0),
            points_blob BLOB,
            points_count INTEGER NOT NULL DEFAULT 0 CHECK(points_count >= 0),
            dtype TEXT NOT NULL DEFAULT 'uint16' CHECK(dtype = 'uint16'),
            endianness TEXT NOT NULL DEFAULT 'little' CHECK(endianness = 'little'),
            points_sha256 TEXT,
            raw_transfer_sha256 TEXT,
            raw_byte_length INTEGER NOT NULL DEFAULT 0 CHECK(raw_byte_length >= 0),
            headers_json TEXT NOT NULL DEFAULT '[]',
            virtual_time_ms REAL NOT NULL DEFAULT 0,
            peak_value REAL,
            peak_position INTEGER,
            integral_value REAL,
            monitoring_json TEXT NOT NULL DEFAULT '{}',
            damaged INTEGER NOT NULL DEFAULT 0 CHECK(damaged IN (0,1)),
            damage_code TEXT,
            damage_message TEXT,
            accepted INTEGER NOT NULL DEFAULT 0 CHECK(accepted IN (0,1)),
            captured_at TEXT NOT NULL,
            CHECK(accepted=0 OR (damaged=0 AND points_count>0 AND points_blob IS NOT NULL)),
            UNIQUE(task_id, repeat_index, attempt, phase, frame_index, ccd_index)
        )""",
        """CREATE INDEX IF NOT EXISTS idx_acquisition_attempt_frames_task
            ON acquisition_attempt_frames(task_id, repeat_index, attempt)""",
        """CREATE TRIGGER IF NOT EXISTS acquisition_attempt_frames_immutable
            BEFORE UPDATE OF task_id, sample_id, repeat_index, attempt, phase, frame_index,
                ccd_index, points_blob, points_count, dtype, endianness, points_sha256,
                raw_transfer_sha256, raw_byte_length, headers_json, virtual_time_ms,
                peak_value, peak_position, integral_value, monitoring_json, damaged,
                damage_code, damage_message, captured_at
            ON acquisition_attempt_frames
            BEGIN SELECT RAISE(ABORT, 'acquisition attempt evidence is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS acquisition_attempt_frames_no_delete
            BEFORE DELETE ON acquisition_attempt_frames
            BEGIN SELECT RAISE(ABORT, 'acquisition attempt evidence is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS acquisition_attempt_accept_monotonic
            BEFORE UPDATE OF accepted ON acquisition_attempt_frames
            WHEN OLD.accepted=1 AND NEW.accepted=0
            BEGIN SELECT RAISE(ABORT, 'confirmed attempt evidence cannot be withdrawn'); END""",
    )
    for statement in statements:
        connection.execute(statement)
