from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import sys
import zlib
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from backend.app.db import Database


def _legacy_v10_database(path: Path, points_json: str) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_migrations(version, applied_at) VALUES (10, 'legacy');
            CREATE TABLE dispersion_task_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                phase TEXT NOT NULL,
                frame_index INTEGER NOT NULL,
                ccd_index INTEGER NOT NULL,
                points_json TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                headers_json TEXT NOT NULL DEFAULT '[]',
                byte_length INTEGER NOT NULL,
                captured_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO dispersion_task_frames(task_id, phase, frame_index, ccd_index, points_json, sha256, headers_json, byte_length, captured_at) VALUES (1, 'burn', 0, 0, ?, 'raw-transfer', '[0,0,0]', 24579, 'legacy')",
            (points_json,),
        )


def test_s11_s16_ordered_upgrade_converts_dispersion_frames_atomically(tmp_path: Path) -> None:
    path = tmp_path / "legacy-v10.sqlite3"
    points = [1, 2, 3, 65535]
    _legacy_v10_database(path, json.dumps(points))

    Database(path).initialize()

    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")] == list(range(10, 17))
        columns = {row[1] for row in db.execute("PRAGMA table_info(dispersion_task_frames)")}
        assert {"points_blob", "points_count", "dtype", "endianness", "compression", "points_sha256", "raw_transfer_sha256", "raw_byte_length"}.issubset(columns)
        assert {"points_json", "sha256", "byte_length"}.isdisjoint(columns)
        frame = db.execute("SELECT * FROM dispersion_task_frames WHERE id=1").fetchone()
        expected_blob = struct.pack("<4H", *points)
        assert zlib.decompress(bytes(frame["points_blob"])) == expected_blob
        assert frame["compression"] == "zlib"
        assert frame["points_sha256"] == hashlib.sha256(expected_blob).hexdigest()
        assert frame["raw_transfer_sha256"] == "raw-transfer"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE dispersion_task_frames SET points_count=3 WHERE id=1")


def test_s11_s16_upgrade_failure_rolls_back_schema_and_history(tmp_path: Path) -> None:
    path = tmp_path / "broken-v10.sqlite3"
    _legacy_v10_database(path, "not-json")

    with pytest.raises(sqlite3.IntegrityError, match="cannot be migrated"):
        Database(path).initialize()

    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(10,)]
        columns = {row[1] for row in db.execute("PRAGMA table_info(dispersion_task_frames)")}
        assert "points_json" in columns and "points_blob" not in columns
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_profiles'").fetchone() is None
