from __future__ import annotations

import os
from pathlib import Path

from backend.db import Database
from backend.modules.maintenance import MaintenanceService


def test_s20_backup_verify_restore_and_reclaim(tmp_path: Path) -> None:
    database = Database(tmp_path / "data" / "geospectrum.sqlite3")
    database.initialize()
    with database.write() as connection:
        connection.execute(
            (
                "INSERT INTO methods(name, description, work_type, status, created_at, "
                "updated_at) VALUES (?, '', 'spectral', 'active', ?, ?)"
            ),
            ("S20 fixture", "2026-01-01", "2026-01-01"),
        )
    service = MaintenanceService(database, tmp_path / "logs" / "runtime.jsonl")
    backup = service.backup(str(tmp_path / "backups"))
    assert backup["verification"]["integrity"] == "ok"
    assert service.verify_backup(backup["id"])["verification"]["integrity"] == "ok"
    assert service.restore_rehearsal(backup["id"])["status"] == "verified"
    assert service.reclaim()["snapshot"]["entity_counts"]["methods"] == 1
    topics = service.help_topics()
    assert len(topics) >= 18
    covered_routes = {route for topic in topics for route in topic["related_routes"]}
    assert {
        "/workspace",
        "/methods",
        "/migration",
        "/spectrum-migration",
        "/result-migration",
        "/spectra",
        "/postprocessing",
        "/samples",
        "/acquisition",
        "/dispersion",
        "/sample-acquisition",
        "/hardware-acquisition",
        "/mercury-calibration",
        "/analysis",
        "/reports",
        "/maintenance",
        "/help",
        "/settings",
        "/about",
        "/users",
        "/audit",
    } <= covered_routes


def test_relative_backup_directory_is_independent_of_working_directory(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "user-data" / "geospectrum.sqlite3")
    database.initialize()
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    service = MaintenanceService(database, database.path.parent / "logs" / "runtime.jsonl")
    backup = service.backup("backups")
    assert Path(backup["backup_path"]).parent == database.path.parent / "backups"
    assert Path(backup["backup_path"]).is_absolute()
    assert not (launch_dir / "backups").exists()
    monkeypatch.chdir(tmp_path)
    assert service.verify_backup(backup["id"])["verification"]["integrity"] == "ok"
    assert service.restore_rehearsal(backup["id"])["status"] == "verified"


def test_s20_log_temp_cleanup_and_error_code_topics(tmp_path: Path) -> None:
    database = Database(tmp_path / "data" / "geospectrum.sqlite3")
    database.initialize()
    runtime_log = tmp_path / "logs" / "runtime.jsonl"
    runtime_log.parent.mkdir(parents=True)
    old_log = runtime_log.with_name("runtime.jsonl.20240101")
    recent_log = runtime_log.with_name("runtime.jsonl.20260816")
    old_log.write_text("old", encoding="utf-8")
    recent_log.write_text("recent", encoding="utf-8")
    temp_root = database.path.parent / "tmp"
    temp_root.mkdir()
    old_temp = temp_root / "old.tmp"
    recent_temp = temp_root / "recent.tmp"
    old_temp.write_text("old", encoding="utf-8")
    recent_temp.write_text("recent", encoding="utf-8")
    os.utime(old_log, (1, 1))
    os.utime(old_temp, (1, 1))

    service = MaintenanceService(database, runtime_log)
    assert service.cleanup_logs(30)["removed"] == [str(old_log)]
    assert service.cleanup_temp(7)["removed"] == [str(old_temp)]
    assert recent_log.exists()
    assert recent_temp.exists()
    assert service.help_topic_for_error("ANALYSIS_CURVE_NOT_FOUND")["topic"]["slug"] == "analysis"
    assert service.help_topic_for_error("MAINTENANCE_PERMISSION")["topic"]["slug"] == "maintenance"
    assert service.help_topic_for_error("unknown_stable_code")["topic"]["slug"] == "errors"
    assert service.help_topics("REPORT_FINAL_RESULTS_MISSING")[0]["slug"] == "reports"


def test_manual_refreshes_existing_database_without_changing_method_records(tmp_path: Path) -> None:
    database = Database(tmp_path / "geospectrum.sqlite3")
    database.initialize()
    with database.write() as connection:
        connection.execute("UPDATE help_topics SET body='旧版简短说明' WHERE slug='methods'")
        # An existing installation contains the longer articles from the prior
        # manual. A refresh must merge them without leaving duplicate entries.
        connection.execute(
            "INSERT INTO help_topics(slug,title,section,keywords_json,body,related_routes_json,updated_at,enabled) "
            "VALUES ('quality','旧独立质控主题','核心流程','[]','旧重复说明','[]','2026-01-01',1) "
            "ON CONFLICT(slug) DO UPDATE SET enabled=1"
        )
        connection.execute(
            "INSERT INTO methods(name, description, work_type, status, created_at, updated_at) "
            "VALUES ('用户现有方法', '保留操作条件', 'spectral', 'active', '2026-01-01', '2026-01-01')"
        )
        before = [tuple(row) for row in connection.execute("SELECT * FROM methods ORDER BY id")]
        migrations = [tuple(row) for row in connection.execute("SELECT * FROM schema_migrations ORDER BY version")]
    # Updating the executable must also update the manual in an already used database.
    database.initialize()
    service = MaintenanceService(database)
    assert "上方的“保存”" in service.help_topic("methods")["body"]
    assert service.help_topics()[0]["slug"] == "quickstart"
    assert service.help_topics("斜杠作用于队尾")[0]["slug"] == "samples"
    assert service.help_topics("不存在的中文主题词") == []
    assert not any(topic["slug"] == "quality" for topic in service.help_topics())
    assert service.help_topic("quality")["slug"] == "quality"
    assert service.help_topic("quality")["body"] == service.help_topic("analysis")["body"]
    assert service.help_topic_for_error("MERCURY_NOT_READY")["topic"]["body"] == service.help_topic("devices")["body"]
    assert service.help_topic_for_error("REPORT_FINAL_RESULTS_MISSING")["topic"]["slug"] == "reports"
    with database.read() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM methods ORDER BY id")] == before
        assert [tuple(row) for row in connection.execute("SELECT * FROM schema_migrations ORDER BY version")] == migrations
