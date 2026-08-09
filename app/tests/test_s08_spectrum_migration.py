from __future__ import annotations

import base64
import hashlib
import struct
from pathlib import Path

import pytest

from backend.app.db import Database
from backend.app.modules.legacy_migration import LegacyMigrationError
from backend.app.modules.spectrum_migration import SpectrumMigrationService


def blob(raw: bytes) -> dict[str, object]:
    return {"kind": "blob", "byte_length": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "base64": base64.b64encode(raw).decode("ascii")}


def payload(fmt: str) -> dict[str, object]:
    gaps = struct.pack("<3f", 1.0, 2.0, 3.0)
    indices = bytes((1, 3))
    coefficients = struct.pack("<6f", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    layout = {"FrameCount": {"kind": "number", "value": "2"}, "CcdsPerFrame": {"kind": "number", "value": "2"}, "PointsPerCcd": {"kind": "number", "value": "3"}, "PointWidth": {"kind": "number", "value": "14"}, "CcdCount": {"kind": "number", "value": "2"}, "CcdGapPoints": blob(gaps), "CcdIndexs": blob(indices), "WsCof": blob(coefficients)}
    burn = struct.pack("<12H", *range(100, 112))
    dark = struct.pack("<6H", *range(200, 206))
    row: dict[str, object] = {"BandId": {"kind": "number", "value": "7"}, "SampNo": {"kind": "number", "value": "3"}, "SampName": "S-3", "LongName": "long", "BandName": "band", "MeasureTime": "2026-08-07T10:00:00", "ErrIndex": {"kind": "number", "value": "2"}}
    if fmt == "cdt":
        row["CcdAvgs"] = blob(struct.pack("<6f", 1.5, 2.5, 3.5, 4.5, 5.5, 6.5))
    else:
        row["BurnAdcs"] = blob(burn)
        row["DarkAdcs"] = blob(dark)
    return {"format_version": 1, "provider": "synthetic", "mode": "Read", "file": f"sample.{fmt}", "tables": {"LAYOUT": [layout], "MTD_BURN": [{"PreBurn": {"kind": "number", "value": "3"}, "BurnCyc": {"kind": "number", "value": "1"}, "DarkCyc": {"kind": "number", "value": "1"}, "BurnCount": {"kind": "number", "value": "2"}, "DarkCount": {"kind": "number", "value": "1"}}], "CCD_BAND": [row]}}


@pytest.mark.parametrize("fmt", ["cdt", "cmt", "edt", "wdt"])
def test_s08_stage_commit_preserves_arrays_and_reports_samples(tmp_path: Path, fmt: str) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    source = tmp_path / f"sample.{fmt}"
    source.write_bytes(f"synthetic-{fmt}".encode())
    service = SpectrumMigrationService(database)
    service._read_access = lambda path, before: (payload(fmt), {"reader": "synthetic", "available": True})  # type: ignore[method-assign]

    staged = service.stage(str(source), None)  # type: ignore[arg-type]
    assert staged["status"] == "staged"
    assert staged["format"] == fmt
    assert staged["report"]["record_count"] == 1
    assert staged["report"]["checks"]["little_endian_decoded"] is True
    record = staged["staging"]["records"][0]
    assert record["layout"]["ccd_indices"] == [1, 3]
    if fmt == "cdt":
        assert record["sampled_values"]["mean"]["first"] == 1.5
    else:
        assert record["sampled_values"]["mean"] is None
    assert record["bad_frame_indices"] == [{"phase": "burn", "index": 1, "legacy_value": 2}]

    committed = service.commit(staged["id"], None)  # type: ignore[arg-type]
    assert committed["status"] == "committed"
    assert committed["report"]["imported"]["spectrum_bands"] == 1
    with database.read() as db:
        final = db.execute("SELECT * FROM spectrum_bands").fetchone()
        staging_count = db.execute("SELECT COUNT(*) FROM spectrum_migration_staging_records").fetchone()[0]
    assert final is not None
    assert final["source_sha256"] == staged["fingerprint"]
    assert final["bad_frame_indices_json"] == '[{"index":1,"legacy_value":2,"phase":"burn"}]'
    assert staging_count == 1
    repeated = service.stage(str(source), None)  # type: ignore[arg-type]
    assert repeated["already_committed"] is True


def test_s08_rejects_layout_or_blob_mismatch_without_creating_run(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = SpectrumMigrationService(database)
    bad = payload("cdt")
    bad["tables"]["LAYOUT"][0]["CcdIndexs"] = blob(bytes((1, 1)))  # type: ignore[index]
    with pytest.raises(LegacyMigrationError) as exc:
        service._normalize(bad, "cdt")
    assert exc.value.code == "spectrum_ccd_mapping_invalid"


def test_s08_bad_frame_is_metadata_only(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = SpectrumMigrationService(database)
    normalized = service._normalize(payload("cmt"), "cmt")
    raw = normalized["_records"][0]["burn_adcs_blob"]
    assert raw == struct.pack("<12H", *range(100, 112))
    assert normalized["_records"][0]["bad_frame_indices"]


def test_s08_accepts_layout_embedded_ignition_and_blob_files(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    service = SpectrumMigrationService(database)
    access = payload("cmt")
    access["tables"].pop("MTD_BURN")  # type: ignore[union-attr]
    layout = access["tables"]["LAYOUT"][0]  # type: ignore[index]
    layout.update({
        "PreBurn": {"kind": "number", "value": "3"},
        "BurnCyc": {"kind": "number", "value": "1"},
        "DarkCyc": {"kind": "number", "value": "1"},
        "BurnCount": {"kind": "number", "value": "2"},
        "DarkCount": {"kind": "number", "value": "1"},
    })
    burn_path = tmp_path / "burn.bin"
    burn_raw = struct.pack("<12H", *range(100, 112))
    burn_path.write_bytes(burn_raw)
    access["tables"]["CCD_BAND"][0]["BurnAdcs"] = {  # type: ignore[index]
        "kind": "blob_file",
        "byte_length": len(burn_raw),
        "sha256": hashlib.sha256(burn_raw).hexdigest(),
        "path": str(burn_path),
    }

    normalized = service._normalize(access, "cmt")
    assert normalized["ignition"]["source_table"] == "LAYOUT"
    assert normalized["_records"][0]["burn_adcs_blob"] == burn_raw


def test_s08_source_snapshot_hashes_in_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "large.cmt"
    source.write_bytes(b"chunked-source" * 1000)

    def reject_read_bytes(_: Path) -> bytes:
        raise AssertionError("whole-file read_bytes must not be used")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    snapshot = SpectrumMigrationService._source_snapshot(source)
    assert snapshot["sha256"] == hashlib.sha256(b"chunked-source" * 1000).hexdigest()
