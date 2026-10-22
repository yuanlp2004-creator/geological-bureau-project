"""Isolated output QA: stored full-time records plus the existing analysis fixtures."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import AppConfig
from backend.db import Database
from tests.seed_analysis_workspace import seed_workspace


def seed(directory: Path):
    fixture = seed_workspace(directory)
    database = Database(AppConfig(data_dir=directory).database_path)
    with database.write() as db:
        row = dict(db.execute('SELECT * FROM spectrum_bands ORDER BY id LIMIT 1').fetchone())
        row.pop('id')
        row.update(format='cmt', record_index=100, sample_name='Full-time output QA')
        db.execute(f"INSERT INTO spectrum_bands({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    (directory / 'operator-fixture.json').write_text(json.dumps(fixture), encoding='utf-8')
    return fixture


if __name__ == '__main__':
    print(json.dumps(seed(Path(sys.argv[1]))))
