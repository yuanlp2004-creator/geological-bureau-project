from __future__ import annotations

import os
from pathlib import Path

from backend.app.db import Database
from backend.app.modules.maintenance import MaintenanceService


def test_s20_backup_verify_restore_and_reclaim(tmp_path: Path) -> None:
    database = Database(tmp_path / "data" / "geospectrum.sqlite3")
    database.initialize()
    with database.write() as connection:
        connection.execute(
            "INSERT INTO methods(name, description, work_type, status, created_at, updated_at) VALUES (?, '', 'spectral', 'active', ?, ?)",
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
        "/workspace", "/methods", "/migration", "/spectrum-migration", "/result-migration",
        "/spectra", "/postprocessing", "/samples", "/acquisition", "/dispersion",
        "/sample-acquisition", "/hardware-acquisition", "/mercury-calibration", "/analysis",
        "/reports", "/maintenance", "/help", "/settings", "/about", "/users", "/audit",
    } <= covered_routes


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
