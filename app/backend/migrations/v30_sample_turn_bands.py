"""Add angle-qualified bands without rewriting historical spectra or turn evidence."""
import sqlite3


def _migrate_v30(connection: sqlite3.Connection) -> None:
    connection.execute('''CREATE TABLE acquisition_turn_bands (
        id INTEGER PRIMARY KEY, sample_id INTEGER NOT NULL REFERENCES acquisition_samples(id),
        turn_index INTEGER NOT NULL, angle_deg REAL NOT NULL, ccd_index INTEGER NOT NULL,
        storage_mode TEXT NOT NULL, points_count INTEGER NOT NULL,
        burn_frame_count INTEGER NOT NULL, dark_frame_count INTEGER NOT NULL,
        mean_blob BLOB NOT NULL, mean_sha256 TEXT NOT NULL,
        burn_frames_blob BLOB, burn_sha256 TEXT, dark_frames_blob BLOB, dark_sha256 TEXT,
        created_at TEXT NOT NULL, UNIQUE(sample_id,turn_index,ccd_index))''')
    for action in ('UPDATE', 'DELETE'):
        connection.execute(f'''CREATE TRIGGER acquisition_turn_bands_no_{action.lower()}
            BEFORE {action} ON acquisition_turn_bands
            BEGIN SELECT RAISE(ABORT,'sample turn bands are immutable'); END''')
