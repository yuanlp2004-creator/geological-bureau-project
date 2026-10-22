import pytest
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from backend.modules.analysis import AnalysisError
from backend.modules.reports import ReportError
from tests.test_s17_quality_curves import _seed_completed_run


def test_qc_changes_block_new_outputs_but_preserve_history(tmp_path):
    database = Database(tmp_path / "validity.sqlite3")
    run_id, version = _seed_completed_run(database)
    runtime = Runtime(AppConfig(data_dir=tmp_path), database=database)
    analysis, reports = runtime.analysis_service(), runtime.reports_service()
    analysis.build_quality(run_id)

    def publish():
        run = analysis.fit_standard_curve(run_id, "L1", {})
        snapshot = run["curves"]["lines"][0]["snapshots"][-1]
        return analysis.publish_standard_curve(run_id, "L1", snapshot["id"], "test")

    run = publish()
    analysis.merge_results(run_id, "test")
    old = reports.create({"analysis_run_ids": [run_id]})
    assert old["model"]["rows"][0]["calculated_value"] == pytest.approx(9.50)
    group = next(g for g in run["quality"]["latest_snapshot"]["groups"] if g["sample_name"] == "N1")
    for action, expected in [("exclude", 9.47), ("restore", 9.50)]:
        analysis.decide_quality(
            run_id,
            {
                "acquisition_task_id": group["acquisition_task_id"],
                "line_id": "L1",
                "action": action,
                "line_result_id": group["members"][1]["line_result_id"],
                "reason": "test",
            },
        )
        with pytest.raises(AnalysisError, match="重新拟合"):
            analysis.merge_results(run_id, "stale")
        with pytest.raises(ReportError, match="重新拟合"):
            reports.create({"analysis_run_ids": [run_id]})
        publish()
        with pytest.raises(ReportError):
            reports.create({"analysis_run_ids": [run_id]})
        analysis.merge_results(run_id, "fresh")
        fresh = reports.create({"analysis_run_ids": [run_id]})
        assert fresh["model"]["rows"][0]["calculated_value"] == pytest.approx(expected)
        assert reports.get(old["id"])["model_sha256"] == old["model_sha256"]
        assert reports.get(old["id"])["model"] == old["model"]
