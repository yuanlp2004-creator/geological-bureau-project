from __future__ import annotations

import struct
from pathlib import Path

import pytest

from backend.app.db import Database, utc_now
from backend.app.modules.result_migration import ResultMigrationError, ResultMigrationService


def source_file(extension: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".." / "Spec Source" / "Bin" / "DATA"
    return next(path for path in root.resolve().glob(f"*.{extension}") if "20190421_1842" in path.name)


@pytest.mark.parametrize(("extension", "expected"), [("dat", (90, 3, 90)), ("pdt", (100, 10, 120))])
def test_s09_stage_commit_preserves_matrix_shape_and_metadata(tmp_path: Path, extension: str, expected: tuple[int, int, int]) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = ResultMigrationService(database)
    staged = service.stage(str(source_file(extension)), None)  # type: ignore[arg-type]
    record = staged["staging"]["records"][0]
    assert staged["status"] == "staged"
    assert staged["report"]["checks"]["atomic_commit"] is None
    assert (record["sample_count"], record["line_count"], record["band_count"]) == expected
    assert record["endianness"] == "little"
    assert record["matrix_sha256"] == staged["parser"].get("matrix_sha256", record["matrix_sha256"])
    if extension == "pdt":
        assert record["method_legacy_id"] == 24
        assert record["method_match_status"] == "orphan"
        assert len(record["exposure_segments"]) == 10
        assert record["matrix_kind"] == "peak_back"
    else:
        assert record["method_legacy_id"] is None
        assert record["matrix_kind"] == "value"
    committed = service.commit(staged["id"], None)  # type: ignore[arg-type]
    assert committed["status"] == "committed"
    assert committed["report"]["checks"]["atomic_commit"] is True
    assert committed["report"]["imported"]["result_matrices"] == 1
    with database.read() as db:
        row = db.execute("SELECT format, length(matrix_blob), matrix_sha256 FROM result_matrices").fetchone()
        assert row is not None
        assert row["format"] == extension
        assert row["matrix_sha256"] == record["matrix_sha256"]
        assert db.execute("SELECT COUNT(*) FROM result_matrices").fetchone()[0] == 1
    repeated = service.stage(str(source_file(extension)), None)  # type: ignore[arg-type]
    assert repeated["already_committed"] is True


def test_s09_rejects_unknown_header_and_truncated_matrix(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = ResultMigrationService(database)
    unknown = tmp_path / "bad.pdt"
    unknown.write_bytes(struct.pack("<H", 0x1234) + b"x")
    with pytest.raises(ResultMigrationError) as unknown_error:
        service.stage(str(unknown), None)  # type: ignore[arg-type]
    assert unknown_error.value.code == "result_header_unknown"
    truncated = tmp_path / "truncated.dat"
    raw = source_file("dat").read_bytes()
    truncated.write_bytes(raw[:-4])
    with pytest.raises(ResultMigrationError) as truncated_error:
        service.stage(str(truncated), None)  # type: ignore[arg-type]
    assert truncated_error.value.code == "result_file_truncated"


def test_s09_resolves_matching_legacy_method_without_reading_method_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    now = utc_now()
    with database.write() as db:
        db.execute("INSERT INTO legacy_migration_runs(id, fingerprint, status, source_files_json, reader_json, staging_json, report_json, created_at, updated_at) VALUES ('legacy-run', 'legacy-fingerprint', 'committed', '{}', '{}', '{}', '{}', ?, ?)", (now, now))
        db.execute("INSERT INTO legacy_import_entities(run_id, source_sha256, entity_type, legacy_key, target_id, payload_sha256, details_json, created_at) VALUES ('legacy-run', 'legacy-fingerprint', 'method', '24', 77, 'payload', '{}', ?)", (now,))
    staged = ResultMigrationService(database).stage(str(source_file("pdt")), None)  # type: ignore[arg-type]
    record = staged["staging"]["records"][0]
    assert record["method_legacy_id"] == 24
    assert record["method_target_id"] == 77
    assert record["method_match_status"] == "matched"
