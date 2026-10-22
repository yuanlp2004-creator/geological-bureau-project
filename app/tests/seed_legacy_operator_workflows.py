"""Build a new isolated operator QA database from synthetic, reproducible fixtures."""
from pathlib import Path
import hashlib
import json
import sqlite3
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import AppConfig
from backend.db import Database
from backend.runtime import Runtime
from tests.test_spec_gap_closure import _sample_chain
from tests.test_s10_spectrum_viewer import seed_database


def seed(directory: Path) -> dict:
    config = AppConfig(data_dir=directory)
    assert not config.database_path.exists(), 'QA seed requires a new empty data directory'
    source = directory / 'fixture-source'
    source.mkdir(parents=True)
    database, runtime, method, line_id, task_id, sample_id, run = _sample_chain(source)
    seed_database(database.path)
    with database.write() as db:
        row = dict(db.execute('SELECT * FROM spectrum_bands WHERE id=1').fetchone())
        layout = json.loads(row['layout_json']); layout['point_width'] = 14
        db.execute('UPDATE spectrum_bands SET layout_json=? WHERE id=1', (json.dumps(layout),))
        row['layout_json'] = json.dumps(layout)
        for key, column in [('mean', 'mean_blob'), ('burn', 'burn_adcs_blob'), ('dark', 'dark_adcs_blob')]:
            db.execute(f'UPDATE spectrum_bands SET {key}_sha256=? WHERE id=1', (hashlib.sha256(bytes(row[column])).hexdigest(),))
        row.pop('id'); row.update(record_index=1, band_id=8, sample_name='Raw comparison', sample_no=2)
        row['mean_blob'] = struct.pack('<16f', *[float(i * 2) for i in range(16)])
        row['mean_sha256'] = hashlib.sha256(row['mean_blob']).hexdigest()
        db.execute(f"INSERT INTO spectrum_bands({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    queue = runtime.sample_queue_service().create('Legacy operator queue',
        [{'pre_name': 'QUEUEA', 'repeats': 1}, {'pre_name': 'QUEUEB', 'repeats': 2}], 1)
    acquisition = runtime.acquisition_service()
    queued = acquisition.create_task({'method_id': method['id'], 'queue_id': queue['id'],
        'queue_item_id': queue['items'][0]['id'], 'sample_kind': 'test', 'name': 'Queue operator QA',
        'use_method_conditions': True, 'use_method_intervals': True}, 1)
    analysis = runtime.analysis_service()
    run = analysis.build_quality(run['id'], 1)
    run = analysis.fit_standard_curve(run['id'], line_id, {})
    curve_id = run['curves']['lines'][0]['snapshots'][-1]['id']
    analysis.publish_standard_curve(run['id'], line_id, curve_id, 'synthetic operator QA', 1)
    metadata = {'method_id': method['id'], 'method_hash': method['published_version']['content_sha256'],
        'line_id': line_id, 'run_id': run['id'], 'sample_id': sample_id,
        'queue_id': queue['id'], 'queue_item_ids': [item['id'] for item in queue['items']], 'queue_task_id': queued['id'],
        'curve_id': curve_id, 'source_task_id': task_id}
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    with database.read() as connection, sqlite3.connect(config.database_path) as target:
        connection.backup(target)
    (directory / 'operator-fixture.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return metadata


if __name__ == '__main__':
    print(json.dumps(seed(Path(sys.argv[1])), ensure_ascii=False))
