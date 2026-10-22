"""Read-only legacy workflow verification; all mutations occur in a temporary database."""

from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from backend.modules.legacy_migration import LegacyMigrationService, LegacyMigrationError
from backend.modules.spectrum_migration import SpectrumMigrationService
from backend.modules.dispersion import DispersionService


def facts(path):
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upgrade-copy-of", type=Path)
    args = parser.parse_args()
    root = APP.parent
    work = Path(tempfile.mkdtemp(prefix="geospectrum-fix-verification-"))
    db = Database(work / "legacy.sqlite3")
    db.initialize()
    runtime = Runtime(AppConfig(data_dir=work), database=db)
    migration = SpectrumMigrationService(db)
    source_paths = [
        root / "Spec Source/Bin/DATA/20141029_测试.wdt",
        root / "Spec Source/Bin/DATA/测试15-5_20170509_[2-16].cdt",
        root / "Spec Source/Bin/DATA/测试15-5_20170509_[2-16].cmt",
    ]
    before = {str(path.relative_to(root)): facts(path) for path in source_paths}
    source_ids = {}
    for source in source_paths:
        copy = Path(shutil.copy2(source, work / source.name))
        staged = migration.stage(str(copy), None)
        migration.commit(staged["id"], None)
        with db.read() as connection:
            source_ids[source.suffix] = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM spectrum_bands WHERE import_run_id=? ORDER BY record_index", (staged["id"],)
                )
            ]
    fixture = APP / "tests/fixtures/legacy_runtime"
    methods = LegacyMigrationService(db)
    staged = methods.stage(*(str(fixture / name) for name in ["DIRECT.MTD", "DIRECT.CFG", "DIRECT.OPT"]), None)
    methods.commit(staged["id"], None)
    analysis = runtime.analysis_service()
    version = next(
        item["method_version_id"] for item in analysis.options()["method_versions"] if item["name"] == "测试15-5"
    )
    results = []
    for extension in [".cdt", ".cmt"]:
        ids = source_ids[extension][:2] + source_ids[extension][90:]
        imported = analysis.import_legacy_sources(ids, version)
        assert analysis.import_legacy_sources(ids, version) == imported
        run = analysis.start(
            analysis.create_run(
                {
                    "name": "真实旧样品复验",
                    "acquisition_sample_ids": imported["sample_ids"],
                    "method_version_id": version,
                    "calculation_profile": "legacy_2_0_2",
                }
            )["id"]
        )
        for _ in range(1000):
            if run["status"] in ("completed", "failed"):
                break
            run = analysis.step(run["id"])
        assert run["status"] == "completed", run.get("failure_details")
        quality = analysis.build_quality(run["id"])
        for line in quality["curves"]["lines"]:
            fitted = analysis.fit_standard_curve(run["id"], line["line_id"], {})
            entry = next(item for item in fitted["curves"]["lines"] if item["line_id"] == line["line_id"])
            analysis.publish_standard_curve(
                run["id"], line["line_id"], entry["snapshots"][-1]["id"], "real legacy verification"
            )
        analysis.merge_results(run["id"], "real legacy verification")
        reports = runtime.reports_service()
        report = reports.create({"analysis_run_ids": [run["id"]]})
        assert len(report["model"]["rows"]) == 6
        assert {row["sample_name"] for row in report["model"]["rows"]} == {"1", "2"}
        assert reports.preview(report["id"])
        reports.confirm(report["id"])
        pdf = reports.export(
            report["id"], {"format": "pdf", "output_directory": str(work / "reports"), "filename": extension[1:]}
        )
        assert Path(pdf["path"]).read_bytes().startswith(b"%PDF-")
        results.append(
            {
                "format": extension,
                "run_id": run["id"],
                "sample_ids": imported["sample_ids"],
                "line_results": len(run["line_results"]),
                "result_sha256": run["result_sha256"],
                "name_mappings": imported["name_mappings"],
                "report_rows": report["model"]["rows"],
                "pdf_sha256": facts(Path(pdf["path"]))["sha256"],
            }
        )
    assert results[0]["result_sha256"] == results[1]["result_sha256"], "paired CDT and CMT analyses differ"

    def values(result):
        return [
            (row["sample_name"], row["element"], row["calculated_value"], row["display_value"])
            for row in result["report_rows"]
        ]

    assert values(results[0]) == values(results[1]), "paired CDT and CMT reports differ"
    dispersion = DispersionService(db)
    with db.read() as connection:
        method = runtime.methods_service().bind_snapshots(connection).by_id(version)
        layout_id = runtime.methods_service().bind_geometry(connection, method.payload["conditions"]).layout_id
    task = dispersion.create_task(
        {"source_record_id": source_ids[".wdt"][0], "ccd_layout_id": layout_id, "name": "真实 WDT 只读再校准"}
    )
    frames = dispersion.frames(task["id"])
    assert task["status"] == "completed" and len(frames) == 115
    assert task["condition"]["source_sha256"] == before[str(source_paths[0].relative_to(root))]["sha256"]
    # UI/operator assignments are not evidence of a physical wavelength identity.
    calibration_points = []
    ccd = task["last_event"]["ccds"][0]
    for wavelength, center in [(260, 300), (270, 800), (280, 1300)]:
        position = max(range(center - 10, center + 11), key=lambda index: ccd["points"][index])
        line = dispersion.add_line(
            task["id"], {"element": "Fe", "wavelength_nm": wavelength, "ccd_index": ccd["ccd_index"]}
        )
        dispersion.set_line_position(task["id"], line["id"], position)
        dispersion.save_line_position(task["id"], line["id"])
        calibration_points.append({"test_reference_wavelength": wavelength, "actual_pixel": position})
    fitted = dispersion.fit_calibration(task["id"], {"name": "软件测试参考点", "degree": 2})
    published = dispersion.publish_calibration(fitted["id"])
    binding = dispersion.bind_calibration(
        published["id"],
        {
            "method_id": next(
                item["method_id"]
                for item in analysis.options()["method_versions"]
                if item["method_version_id"] == version
            ),
            "method_version": 1,
        },
    )
    dispersion.manage_calibration(published["id"], "archive", None, None)
    assert dispersion.calibration(published["id"])["coefficients"] == published["coefficients"]
    assert before == {str(path.relative_to(root)): facts(path) for path in source_paths}
    result = {
        "status": "passed",
        "work_directory": str(work),
        "source_facts": before,
        "legacy_analysis": results,
        "wdt": {
            "frames": len(frames),
            "task_id": task["id"],
            "calibration_id": published["id"],
            "binding_id": binding["id"],
            "manual_test_assignments": calibration_points,
            "physical_wavelength_identity_verified": False,
        },
        "originals_unchanged": True,
        "paired_cdt_cmt_results_equal": True,
    }
    if args.upgrade_copy_of:
        target = work / "upgrade.sqlite3"
        with (
            sqlite3.connect(f"file:{args.upgrade_copy_of.as_posix()}?mode=ro", uri=True) as source,
            sqlite3.connect(target) as dest,
        ):
            source.backup(dest)
        tables = [
            "methods",
            "method_versions",
            "analysis_line_results",
            "analysis_result_merges",
            "reports",
            "acquisition_sample_bands",
            "spectrum_bands",
        ]

        def digest_tables():
            with sqlite3.connect(target) as connection:
                present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                return {
                    table: hashlib.sha256(
                        repr(connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()).encode()
                    ).hexdigest()
                    for table in tables
                    if table in present
                }

        old = digest_tables()
        with sqlite3.connect(target) as connection:
            old_version = connection.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0]
        Database(target).initialize()
        assert digest_tables() == old
        with sqlite3.connect(target) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            new_version = connection.execute("SELECT value FROM app_metadata WHERE key='schema_version'").fetchone()[0]
        result["upgrade"] = {
            "source_database": str(args.upgrade_copy_of),
            "old_version": old_version,
            "new_version": new_version,
            "preserved_table_hashes": old,
            "integrity": "ok",
            "foreign_keys": "ok",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
