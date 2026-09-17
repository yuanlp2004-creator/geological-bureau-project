"""Seed S24 UI checks with existing independent S16/S17 golden inputs."""
import argparse
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.auth import AuthService
from backend.db import Database

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data_directory', type=Path)
    args = parser.parse_args()
    path = args.data_directory.resolve() / 'geospectrum.sqlite3'
    if path.exists():
        parser.error('Choose a fresh isolated directory; existing databases are never overwritten.')
    database = Database(path)
    runpy.run_path(str(ROOT / 'tests/test_s16_analysis.py'))['_seed'](database, complete_conditions=True)
    runpy.run_path(str(ROOT / 'tests/test_s17_quality_curves.py'))['_seed_completed_run'](database)
    AuthService(database).bootstrap('qa_admin', 'QaTest-2026!')
    print(path)
