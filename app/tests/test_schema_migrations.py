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

from backend.db import Database
from backend import db as database_module
from backend.migrations import MIGRATIONS, SCHEMA_VERSION
from backend.upgrade import prepare_database_upgrade


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


def test_s11_s17_ordered_upgrade_converts_dispersion_frames_atomically(tmp_path: Path) -> None:
    path = tmp_path / "legacy-v10.sqlite3"
    points = [1, 2, 3, 65535]
    _legacy_v10_database(path, json.dumps(points))

    Database(path).initialize()

    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")] == list(range(10, 21))
        assert all(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() for name in ("postprocessing_conversion_runs", "postprocessing_recalculation_runs", "postprocessing_exports", "report_templates", "reports", "report_exports", "maintenance_backups", "maintenance_operations", "help_topics"))
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
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE dispersion_task_frames SET points_count=3 WHERE id=1")


def test_s11_s17_upgrade_failure_rolls_back_schema_and_history(tmp_path: Path) -> None:
    path = tmp_path / "broken-v10.sqlite3"
    _legacy_v10_database(path, "not-json")

    with pytest.raises(sqlite3.IntegrityError, match="cannot be migrated"):
        Database(path).initialize()

    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(10,)]
        columns = {row[1] for row in db.execute("PRAGMA table_info(dispersion_task_frames)")}
        assert "points_json" in columns and "points_blob" not in columns
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_profiles'").fetchone() is None


@pytest.mark.parametrize("version", range(10, 21))
def test_resume_each_recorded_version_preserves_data_and_history(tmp_path, monkeypatch, version):
    # Synthetic checkpoints of the supported baseline, not archived release databases.
    path = tmp_path / f"checkpoint-v{version}.sqlite3"
    with monkeypatch.context() as patch:
        patch.setattr(database_module, "MIGRATIONS", tuple(step for step in MIGRATIONS if step[0] <= version))
        patch.setattr(database_module, "SCHEMA_VERSION", version)
        patch.setattr(database_module, "utc_now", lambda: "checkpoint-time")
        Database(path).initialize()
    with Database(path).write() as connection:
        connection.execute("INSERT INTO methods(id,name,description,work_type,status,created_at,updated_at) VALUES (1,'preserved','内容','spectral','active','then','then')")
        connection.execute("INSERT INTO method_versions(method_id,version,state,payload_json,created_at) VALUES (1,1,'draft','{\"preserve\":true}','then')")
    with Database(path).read() as connection:
        methods = [tuple(row) for row in connection.execute("SELECT * FROM methods")]
        revisions = [tuple(row) for row in connection.execute("SELECT * FROM method_versions")]
        history = [tuple(row) for row in connection.execute("SELECT * FROM schema_migrations ORDER BY version")]
    called = []

    def tracked(step_version, migration):
        def run(connection):
            called.append(step_version)
            migration(connection)
        return run

    monkeypatch.setattr(database_module, "MIGRATIONS", tuple((v, key, tracked(v, fn)) for v, key, fn in MIGRATIONS))
    Database(path).initialize()
    assert called == list(range(version + 1, SCHEMA_VERSION + 1))
    Database(path).initialize()
    assert called == list(range(version + 1, SCHEMA_VERSION + 1))
    with Database(path).read() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM methods")] == methods
        assert [tuple(row) for row in connection.execute("SELECT * FROM method_versions")] == revisions
        after = [tuple(row) for row in connection.execute("SELECT * FROM schema_migrations ORDER BY version")]
        assert after[:len(history)] == history
        assert [row[0] for row in after] == list(range(10, 21))
        assert connection.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0] == "20"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_late_migration_failure_rolls_back_all_prior_steps(tmp_path, monkeypatch):
    path = tmp_path / "late-failure.sqlite3"
    _legacy_v10_database(path, "[1,2,65535]")
    with sqlite3.connect(path) as connection:
        before = list(connection.iterdump())

    def fail(connection):
        connection.execute("CREATE TABLE should_rollback(value TEXT)")
        raise sqlite3.IntegrityError("injected v20 failure")

    with monkeypatch.context() as patch:
        patch.setattr(database_module, "MIGRATIONS", MIGRATIONS[:-1] + ((20, "maintenance", fail),))
        with pytest.raises(sqlite3.IntegrityError, match="injected v20 failure"):
            Database(path).initialize()
    with sqlite3.connect(path) as connection:
        assert list(connection.iterdump()) == before
    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 20
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_staged_conversion_keeps_original_bytes(tmp_path):
    path = tmp_path / "geospectrum.sqlite3"
    _legacy_v10_database(path, "invalid-json")
    before = path.read_bytes()
    with pytest.raises(sqlite3.IntegrityError, match="cannot be migrated"):
        prepare_database_upgrade(path)
    assert path.read_bytes() == before
