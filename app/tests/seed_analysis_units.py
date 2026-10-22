"""仅在新的隔离运行目录创建百分含量曲线/报告，供浏览器和冻结 EXE 核验。"""
from pathlib import Path
import hashlib
import json
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from backend.modules.methods.units import convert_line_unit
from backend.schemas.methods import MethodCondition
from tests.test_s17_quality_curves import _seed_completed_run


def seed(directory: Path):
    config = AppConfig(data_dir=directory)
    assert not config.database_path.exists(), "QA seed requires a new empty database"
    database = Database(config.database_path)
    def transform(payload):
        payload["conditions"] = {**MethodCondition().model_dump(mode="json"), **payload["conditions"]}
        payload["lines"][0]["decimal_places"] = 2
        payload["lines"][0] = convert_line_unit(payload["lines"][0], "%")
        payload["conditions"]["analysis_unit"] = "%"
        return payload
    run_id, _ = _seed_completed_run(database, payload_transform=transform)
    runtime = Runtime(config, database=database)
    analysis = runtime.analysis_service()
    # 曲线单元夹具只写入计算结果；浏览器还会查看原谱，补齐隔离的合成谱带，
    # 并用正式输入准备器生成快照，避免把简化夹具当作可回溯的采集记录。
    with database.write() as db:
        rows = db.execute(
            "SELECT s.acquisition_sample_id, r.peak_height, a.created_at, l.points_per_ccd "
            "FROM analysis_run_samples s JOIN analysis_line_results r "
            "ON r.run_id=s.run_id AND r.sample_position=s.position "
            "JOIN acquisition_samples a ON a.id=s.acquisition_sample_id "
            "JOIN acquisition_tasks t ON t.id=a.task_id JOIN ccd_layouts l ON l.id=t.ccd_layout_id "
            "WHERE s.run_id=? ORDER BY s.position", (run_id,),
        ).fetchall()
        for row in rows:
            points = [0.0] * int(row['points_per_ccd'])
            points[100] = row['peak_height']
            blob = struct.pack(f'<{len(points)}f', *points)
            digest = hashlib.sha256(blob).hexdigest()
            db.execute(
                "INSERT INTO acquisition_sample_bands(sample_id, ccd_index, storage_mode, points_count, "
                "burn_frame_count, dark_frame_count, mean_blob, mean_sha256, created_at) "
                "VALUES (?, 0, 'averaged', ?, 1, 0, ?, ?, ?)",
                (row['acquisition_sample_id'], len(points), blob, digest, row['created_at']),
            )
            db.execute("UPDATE acquisition_samples SET result_sha256=? WHERE id=?",
                       (hashlib.sha256(digest.encode('ascii')).hexdigest(), row['acquisition_sample_id']))
        sample_ids = [row['acquisition_sample_id'] for row in rows]
        *_, snapshot = analysis.inputs.prepare_run(db, {'calculation_profile': 'modern_v1'}, sample_ids)
        serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        db.execute("UPDATE analysis_runs SET input_snapshot_json=?, input_sha256=? WHERE id=?",
                   (serialized, hashlib.sha256(serialized.encode('utf-8')).hexdigest(), run_id))
    analysis.build_quality(run_id)
    run = analysis.fit_standard_curve(run_id, "L1", {"reason": "隔离单位显示验证"})
    curve_id = run["curves"]["lines"][0]["snapshots"][-1]["id"]
    analysis.publish_standard_curve(run_id, "L1", curve_id, "隔离单位验证")
    analysis.merge_results(run_id, "隔离单位验证")
    report = runtime.reports_service().create({"analysis_run_ids": [run_id], "template_key": "analysis-standard", "arrangement": "standard"})
    print(f"QA percentage run {run_id}, curve {curve_id}, report {report['id']}")


if __name__ == "__main__":
    seed(Path(sys.argv[1]))
