"""Synthetic review data plus actual stored spectra for the integrated UI workflow."""
from pathlib import Path
import copy
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from tests.seed_legacy_operator_workflows import seed
from tests.test_s17_quality_curves import _seed_completed_run


def seed_workspace(directory: Path):
    fixture = seed(directory)
    database = Database(AppConfig(data_dir=directory).database_path)
    def two_lines(payload):
        second = copy.deepcopy(payload['lines'][0])
        second.update(id='L2', order=2, element='Zn', wavelength_nm=334.502, actual_wavelength_nm=334.502)
        payload['lines'].append(second)
        return payload
    run_id, _ = _seed_completed_run(database, payload_transform=two_lines)
    with database.write() as db:
        for original in db.execute('SELECT * FROM analysis_line_results WHERE run_id=?', (run_id,)).fetchall():
            row = dict(original); row.pop('id')
            row.update(line_id='L2', line_position=1, element='Zn', wavelength_nm=334.502)
            for key in ['peak_height', 'net_signal', 'quantitative_signal']:
                row[key] *= 2
            db.execute(f"INSERT INTO analysis_line_results({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    service = Runtime(AppConfig(data_dir=directory), database=database).analysis_service()
    service.build_quality(run_id, 1)
    fixture['review_run_id'] = run_id
    (directory/'operator-fixture.json').write_text(json.dumps(fixture), encoding='utf-8')
    return fixture


if __name__ == '__main__':
    print(json.dumps(seed_workspace(Path(sys.argv[1]))))
