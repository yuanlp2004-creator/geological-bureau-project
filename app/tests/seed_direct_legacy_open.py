"""Isolated browser/desktop fixtures and untouched copies of real legacy files."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.seed_data_output import seed
from tests.test_s09_result_migration import source_file


def prepare(directory):
    directory = directory.resolve()
    fixture = seed(directory)
    app = Path(__file__).resolve().parents[1]
    sources = directory / 'open-sources'
    sources.mkdir()
    paths = {}
    originals = []
    for path in (app / 'tests/fixtures/legacy_runtime').iterdir():
        if path.suffix.lower() in {'.mtd', '.cfg', '.opt'}:
            target = Path(shutil.copy2(path, sources / path.name))
            originals.append(path)
            paths[path.suffix.lower()[1:]] = str(target)
    for fmt in ['cdt', 'cmt', 'wdt', 'edt']:
        source = min((app.parent / 'Spec Source/Bin').rglob('*.' + fmt), key=lambda p: p.stat().st_size)
        originals.append(source)
        paths[fmt] = str(shutil.copy2(source, sources / ('old.' + fmt)))
    for fmt in ['pdt', 'dat']:
        originals.append(source_file(fmt))
        paths[fmt] = str(shutil.copy2(source_file(fmt), sources / ('old.' + fmt)))
    sam = sources / 'names.sam'
    from backend.modules.sample_queues import SampleQueueService
    from backend.db import Database
    from backend.config import AppConfig
    content, _ = SampleQueueService(Database(AppConfig(data_dir=directory).database_path)).export_sam(fixture['queue_id'])
    sam.write_bytes(content)
    paths['sam'] = str(sam)
    # The old analysis fixtures intentionally use minimal method payloads. Start the
    # method editor on a complete migrated method instead of editing that fixture.
    from backend.runtime import Runtime
    runtime = Runtime(AppConfig(data_dir=directory), database=Database(AppConfig(data_dir=directory).database_path))
    migration = runtime.legacy_migration_service()
    staged = migration.stage(paths['mtd'], paths['cfg'], paths['opt'], 1)
    imported = migration.commit(staged['id'], 1)
    runtime.methods_service().open(imported['report']['imported']['methods'][0], 1)
    fixture['open_paths'] = paths
    fixture['open_facts'] = {str(p): dict(size=p.stat().st_size, mtime_ns=str(p.stat().st_mtime_ns),
                                         sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources.iterdir()}
    fixture['original_facts'] = {str(p): dict(size=p.stat().st_size, mtime_ns=str(p.stat().st_mtime_ns),
                                              sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in originals}
    (directory / 'operator-fixture.json').write_text(json.dumps(fixture), encoding='utf-8')
    return fixture


if __name__ == '__main__':
    print(json.dumps(prepare(Path(sys.argv[1]))))
