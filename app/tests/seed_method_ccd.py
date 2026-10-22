"""为方法 CCD 自动选择验证建立全新隔离库，绝不覆盖已有数据。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.auth import AuthService
from backend.db import Database

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    target = args.directory.resolve()/'geospectrum.sqlite3'
    if target.exists():
        parser.error('Choose a fresh directory; existing databases are never overwritten.')
    database = Database(target)
    database.initialize()
    AuthService(database).bootstrap('qa_admin', 'QaTest-2026!')
    with database.write() as db:
        layout = dict(db.execute("SELECT * FROM ccd_layouts WHERE name='default'").fetchone())
        layout.pop('id')
        layout.update(name='CCD自动测试布局', ccd_indices_json=json.dumps([0, 2]))
        keys = ','.join(layout)
        layout_id = db.execute(f"INSERT INTO ccd_layouts ({keys}) VALUES ({','.join('?' for _ in layout)})", list(layout.values())).lastrowid
        curve = dict(db.execute("SELECT * FROM dispersion_calibrations WHERE name='default'").fetchone())
        curve.pop('id')
        curve.update(name='CCD自动测试曲线', ccd_layout_id=layout_id)
        db.execute(f"INSERT INTO dispersion_calibrations ({','.join(curve)}) VALUES ({','.join('?' for _ in curve)})", list(curve.values()))
    print(target)
