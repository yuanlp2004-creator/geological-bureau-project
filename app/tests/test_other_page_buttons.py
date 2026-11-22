from pathlib import Path

from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from .test_s17_quality_curves import _seed_completed_run


def test_legacy_restore_all_retains_point_activation_and_preserves_api_default(tmp_path: Path):
    database = Database(tmp_path / 'restore-points.sqlite3')
    run_id, _ = _seed_completed_run(database)
    service = Runtime(AppConfig(data_dir=tmp_path), database=database).analysis_service()
    service.build_quality(run_id)
    service.curve_action(run_id, 'L1', {'action': 'set_active', 'point_index': 0, 'active': False, 'reason': '停用异常标准点'})
    adjusted = service.curve_action(run_id, 'L1', {'action': 'adjust', 'point_index': 1, 'adjusted_intensity': 999, 'reason': '人工修正'})
    workspace = adjusted['curves']['lines'][0]['workspace']
    assert not workspace['points'][0]['active']
    restored = service.curve_action(run_id, 'L1', {'action': 'restore_all', 'restore_activation': False, 'reason': '旧版全部强度还原'})
    points = restored['curves']['lines'][0]['workspace']['points']
    assert not points[0]['active']
    assert all(point['adjusted_intensity'] == point['original_intensity'] for point in points)
    full_reset = service.curve_action(run_id, 'L1', {'action': 'restore_all', 'reason': '既有API全量恢复'})
    assert all(point['active'] == point['original_active'] for point in full_reset['curves']['lines'][0]['workspace']['points'])
    with database.read() as db:
        assert db.execute("SELECT COUNT(*) FROM analysis_curve_actions WHERE action='restore_all'").fetchone()[0] == 2
