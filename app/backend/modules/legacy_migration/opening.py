"""Compose existing public migration services; original files stay read-only."""
from pathlib import Path
from .errors import LegacyMigrationError


OPEN_RULES = {
    'batch-methods': ({'.mtd'}, 'migration.write'),
    'batch-spectra': ({'.cdt', '.cmt', '.edt', '.wdt'}, 'spectrum-migration.write'),
    'batch-results': ({'.pdt', '.dat'}, 'result-migration.write'),
    'methods': ({'.mtd'}, 'migration.write', 'methods.write'),
    'spectra': ({'.cdt', '.cmt', '.edt', '.wdt'}, 'spectrum-migration.write', 'spectra.read'),
    'analysis': ({'.cdt', '.cmt'}, 'spectrum-migration.write', 'analysis.execute'),
    'dispersion': ({'.wdt'}, 'spectrum-migration.write', 'dispersion.write'),
    'evaporation': ({'.edt'}, 'spectrum-migration.write', 'acquisition.read'),
    'edt-conversion': ({'.edt'}, 'spectrum-migration.write', 'postprocessing.write'),
    'recalculate': ({'.pdt'}, 'result-migration.write', 'postprocessing.execute'),
    'reports': ({'.dat'}, 'result-migration.write', 'reports.write'),
    'intensity': ({'.pdt'}, 'result-migration.write', 'postprocessing.export'),
}


def open_legacy_file(path_value, purpose, actor, *, methods, spectra, results):
    path = Path(path_value.strip()).expanduser()
    if path.suffix.lower() not in OPEN_RULES[purpose][0]:
        raise LegacyMigrationError('legacy_open_format_invalid', '所选文件类型不适用于当前功能')
    if purpose in {'methods', 'batch-methods'}:
        siblings = {p.name.casefold(): p for p in path.parent.iterdir() if p.is_file()}
        missing = [name for name in ('direct.cfg', 'direct.opt') if name not in siblings]
        if missing:
            raise LegacyMigrationError('legacy_open_companion_missing', '方法库同目录缺少：' + '、'.join(missing))
        run = methods.stage(str(path), str(siblings['direct.cfg']), str(siblings['direct.opt']), actor)
        run = methods.commit(run['id'], actor)
        return dict(format='mtd', run_id=run['id'], reused=bool(run.get('already_committed')),
                    method_ids=run['report']['imported']['methods'], record_ids=[],
                    source_sha256=run['source_files']['mtd']['sha256'], issues=run['report'].get('issues', []))
    service = spectra if path.suffix.lower() in {'.cdt', '.cmt', '.edt', '.wdt'} else results
    staged = service.stage(str(path), actor)
    run = service.commit(staged['id'], actor)
    sha = run['source_file']['sha256']
    records = service.opened_records(sha)
    return dict(format=path.suffix.lower()[1:], run_id=run['id'], reused=bool(staged.get('already_committed')),
                method_ids=[], record_ids=[row['id'] for row in records], records=records,
                source_sha256=sha, issues=run['report'].get('issues', []))
