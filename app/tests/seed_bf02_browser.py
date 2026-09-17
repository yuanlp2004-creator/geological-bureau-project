"""Create a fresh, isolated BF02 browser fixture; never use a production directory."""
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
        parser.error('The database already exists; choose a fresh test directory.')
    database = Database(path)
    runpy.run_path(str(ROOT / 'tests' / 'test_s16_analysis.py'))['_seed'](database, complete_conditions=True)
    AuthService(database).bootstrap('qa_admin', 'QaTest-2026!')
    print(path)
