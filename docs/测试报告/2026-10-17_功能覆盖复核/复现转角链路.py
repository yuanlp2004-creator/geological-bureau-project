"""Read current product through an isolated API; never opens the user database."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
APP = HERE.parents[2] / "app"
ROOT = APP.parent
sys.path.insert(0, str(APP))

SCRATCH=APP/".local/test-runs/coverage-audit-20261017/repro"
SCRATCH.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=SCRATCH,prefix="geospectrum-audit-20261017-") as folder:
    os.environ["SPECTRUM_DATA_DIR"] = folder
    from backend.config import AppConfig
    from backend.main import create_app
    from fastapi.testclient import TestClient

    application = create_app(AppConfig(data_dir=Path(folder)))
    runtime = application.state.runtime
    result = {"date": "2026-10-17", "isolated_user_data": True}
    with TestClient(application) as client:
        assert client.post('/api/v1/auth/bootstrap', json={"username": "audit", "password": "audit-local-20261017"}).status_code == 201
        login = client.post('/api/v1/auth/login', json={"username": "audit", "password": "audit-local-20261017"}).json()
        headers = {"Authorization": "Bearer " + login['access_token']}

        def call(url, payload=None, method=None):
            response = client.request(method or ('GET' if payload is None else 'POST'), url, headers=headers, **({} if payload is None else {"json": payload}))
            assert 200 <= response.status_code < 300, (url, response.status_code, response.text)
            return response.json()

        method = call('/api/v1/methods', {"name": "转角到分析链路复核"})
        line = json.loads((APP/'tests/fixtures/station17-line.json').read_text(encoding='utf-8'))
        call(f"/api/v1/methods/{method['id']}/lines", line)
        published = call(f"/api/v1/methods/{method['id']}/publish", {})
        hardware = runtime.hardware_acquisition_service()
        task = hardware.create_task({"method_id": method['id'], "method_version": published['current_version']})
        hardware.start(task['id'])
        for _ in range(150):
            task = hardware.get_task(task['id'], include_points=True)
            if task['status'] in {'completed', 'failed', 'safety_stopped', 'manual_intervention'}:
                break
            hardware.step(task['id'])
        assert task['status'] == 'completed', task['status']
        exposures = task['exposures']
        assert exposures and all(e['confirmed'] for e in exposures)
        with runtime.database.read() as db:
            counts = {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in ['hardware_tasks', 'hardware_exposure_results', 'acquisition_tasks', 'acquisition_samples', 'analysis_runs']}
        result['turn_to_analysis'] = {
            'turn_status': task['status'], 'confirmed_exposures': len(exposures),
            'counts_after_turn_only': counts,
            'analysis_selectable_samples': len(call('/api/v1/analyses/options')['samples']),
            'spectrum_viewer_records': len(runtime.spectrum_viewer_service().list()),
            'software_bridge_present': bool(counts['acquisition_samples']),
        }
        acquisition = runtime.acquisition_service()
        ordinary = acquisition.create_task({'method_id': method['id'], 'method_version': published['current_version'],
            'sample_name': '对照样品', 'burn_frame_count': 1, 'dark_frame_count': 0, 'pre_excitation_seconds': 0})
        ordinary = acquisition.start(ordinary['id'])
        for _ in range(40):
            if ordinary['status'] == 'completed': break
            ordinary = acquisition.step(ordinary['id'])
        assert ordinary['status'] == 'completed'
        result['ordinary_acquisition_control'] = {
            'status': ordinary['status'],
            'analysis_selectable_samples': len(call('/api/v1/analyses/options')['samples']),
            'spectrum_viewer_records': len(runtime.spectrum_viewer_service().list()),
        }
        caps = call('/api/v1/capabilities')['capabilities']
        result['modules'] = len(caps)
        result['navigation_entries'] = sum(len(c.get('navigation_entries', [])) for c in caps)

    old_matrix = json.loads((ROOT/'docs/测试报告/2026-10-16_旧新版软件全面对照复核/菜单参数分支对照.json').read_text(encoding='utf-8'))
    result['legacy_matrix_checkpoints'] = len(old_matrix)
    result['stale_consumer_paths'] = sorted({p for row in old_matrix for p in row.get('current_consumers', []) if not (ROOT/p).exists()})
    result['old_matrix_is_historical'] = True
    (HERE/'service-probe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
