"""The legacy EDT preparation workflow, with native output collections.

Old Access sources and historical acquisitions are never replaced. Replacing an
output changes its collection membership; immutable samples remain in history.
"""
from __future__ import annotations

import json
import math
import uuid

from ...db import utc_now
from ..acquisition.preparation import evaporation_records, evaporation_sources
from ..methods import MethodDomainError
from .errors import PostProcessingError
from .serialization import _json, _sha


def _error(code, message, status=422):
    raise PostProcessingError('prepared_' + code, message, status_code=status)


def _same_geometry(left, right):
    keys = ('frame_count', 'ccds_per_frame', 'points_per_ccd', 'ccd_indices')
    if any(left.get(key) != right.get(key) for key in keys):
        return False
    if not math.isclose(float(left.get('point_width', 0)), float(right.get('point_width', 0)), abs_tol=1e-6):
        return False
    a, b = left.get('gap_points', []), right.get('gap_points', [])
    tolerance = float(right.get('allow_gap_error_um', 0))
    return len(a) == len(b) and all(abs(x-y) * float(right['point_width']) <= tolerance + 1e-6 for x, y in zip(a, b))


def _target(row):
    if row is None:
        return None
    return {key: row[key] for key in ('id', 'name', 'storage_mode', 'method_version_id', 'legacy_method_id', 'revision')} | {
        'records': json.loads(row['records_json']), 'updated_at': row['updated_at'],
    }


def prepared_collections(database):
    """Public read boundary used by spectrum viewing, without loading CCD data."""
    with database.read() as db:
        return [_target(row) for row in db.execute('SELECT * FROM postprocessing_prepared_targets ORDER BY updated_at DESC')]


def prepared_working_layout(database, source_sha256):
    with database.read() as db:
        row = db.execute('SELECT layout_json FROM postprocessing_prepared_dispersion WHERE source_sha256=?', (source_sha256,)).fetchone()
        return json.loads(row['layout_json']) if row else None


class PreparedImportService:
    def __init__(self, conversion):
        self.conversion = conversion
        self.database = conversion.database
        self.methods = conversion.methods
        self.repository = conversion.repository

    def _context(self, db, expected=None):
        state = self.methods.current()
        if not state['method_id'] or state['status'] != 'active' or state['action_state'] != 'idle':
            _error('method_required', '请先打开可用的当前方法')
        version = self.methods.bind_snapshots(db).by_id(state['referenced_version']['id'], published_only=True)
        if version is None:
            _error('method_required', '当前方法版本不可用')
        if expected is not None and expected != version.version_id:
            _error('method_changed', '当前方法已改变，请刷新后重新确认导入', 409)
        try:
            locator = self.methods.bind_geometry(db, version.payload['conditions'])
        except MethodDomainError as exc:
            raise PostProcessingError(exc.code, exc.message, status_code=exc.status_code) from exc
        layout = locator.prepared_layout()
        layout['reference_wavelength_nm'] = version.payload['conditions'].get('reference_wavelength_nm')
        return version, locator.layout_id, layout

    def options(self, source_sha256=None, source_task_id=None):
        current = self.methods.current()
        with self.database.read() as db:
            sources = []
            for row in db.execute("SELECT source_sha256, COUNT(*) AS record_count, MIN(import_run_id) AS run_id "
                                  "FROM spectrum_bands WHERE format='edt' GROUP BY source_sha256 ORDER BY MAX(id) DESC"):
                run = db.execute('SELECT source_json FROM spectrum_migration_runs WHERE id=?', (row['run_id'],)).fetchone()
                source = json.loads(run['source_json']) if run else {}
                sources.append({'sha256': row['source_sha256'], 'name': source.get('name') or source.get('path') or row['source_sha256'],
                                'path': source.get('path'), 'record_count': row['record_count']})
            targets = [_target(row) for row in db.execute('SELECT * FROM postprocessing_prepared_targets ORDER BY updated_at DESC')]
            saved = db.execute('SELECT method_version_id, updated_at FROM postprocessing_prepared_dispersion WHERE source_sha256=?',
                               (source_sha256,)).fetchone() if source_sha256 else None
            acquisitions = evaporation_sources(db)
            records = evaporation_records(db, source_task_id, self.methods) if source_task_id else []
        if source_sha256 and not source_task_id:
            records = [record for record in self.repository.edt_records(None, source_sha256) if record['format'] == 'edt']
        return {'method': {'id': current['method_id'], 'title': current['title'],
                           'version_id': (current['referenced_version'] or {}).get('id')},
                'sources': sources, 'acquisition_sources': acquisitions, 'targets': targets, 'records': records,
                'saved_dispersion': dict(saved) if saved else None}

    def save_dispersion(self, source_sha256, expected, actor):
        with self.conversion.work.write() as transaction:
            db = transaction.connection
            method, _, layout = self._context(db, expected)
            rows = db.execute("SELECT layout_json FROM spectrum_bands WHERE source_sha256=? AND format='edt'", (source_sha256,)).fetchall()
            if not rows:
                _error('source_missing', '请先打开蒸发摄谱文件', 404)
            if any(not _same_geometry(json.loads(row['layout_json']), layout) for row in rows):
                _error('layout_mismatch', '蒸发文件的谱板参数与当前方法不一致')
            now = utc_now()
            db.execute('INSERT INTO postprocessing_prepared_dispersion VALUES (?,?,?,?) '
                       'ON CONFLICT(source_sha256) DO UPDATE SET layout_json=excluded.layout_json, '
                       'method_version_id=excluded.method_version_id, updated_at=excluded.updated_at',
                       (source_sha256, _json(layout), method.version_id, now))
            self._audit(db, actor, 'postprocessing.prepared.dispersion', {'source_sha256': source_sha256, 'method_version_id': method.version_id})
        return {'saved': True, 'method_version_id': method.version_id, 'updated_at': now,
                'message': '色散已保存到该源文件的新版工作副本，旧 EDT 原件保持不变'}

    @staticmethod
    def _audit(db, actor, action, details):
        db.execute('INSERT INTO audit_events(actor_user_id,action,target_type,target_id,details_json,created_at) '
                   "VALUES (?,?,'postprocessing',NULL,?,?)", (actor, action, _json(details), utc_now()))

    def import_records(self, payload, actor):
        name = payload['target_name'].strip()
        if not name:
            _error('target_name', '请填写输出样品集名称')
        request_hash = _sha(payload)
        with self.conversion.work.write() as transaction:
            db = transaction.connection
            previous = db.execute("SELECT * FROM postprocessing_conversion_runs WHERE json_extract(report_json,'$.prepared_request_id')=?",
                                  (payload['request_id'],)).fetchone()
            if previous:
                report = json.loads(previous['report_json'])
                if report['prepared_request_sha256'] != request_hash:
                    _error('request_reused', '同一个导入请求不能更改参数', 409)
                return {'run_id': previous['id'], 'reused': True,
                        'target': _target(db.execute('SELECT * FROM postprocessing_prepared_targets WHERE id=?', (report['target_id'],)).fetchone())}
            method, layout_id, layout = self._context(db, payload.get('expected_method_version_id'))
            identifiers = payload['record_ids']
            if len(set(identifiers)) != len(identifiers):
                _error('selection_duplicate', '不能重复选择同一条源记录')
            task_id = payload.get('source_task_id')
            if task_id is not None:
                candidates = {row['id']: row for row in evaporation_records(db, task_id, self.methods)}
                if not candidates:
                    _error('source_missing', '蒸发摄谱任务没有可用的已完成记录', 404)
                if any(identifier not in candidates for identifier in identifiers):
                    _error('source_mismatch', '请仅选择当前蒸发任务中的记录')
                rows = [candidates[identifier] for identifier in identifiers]
                source_layouts = [row['layout'] for row in rows]
                ignitions = [row['ignition'] for row in rows]
            else:
                rows = [self.repository._raw(identifier, db) for identifier in identifiers]
                if any(row['format'] != 'edt' or row['source_sha256'] != payload['source_sha256'] for row in rows):
                    _error('source_mismatch', '请仅选择当前蒸发文件中的记录')
                source_layouts = [json.loads(row['layout_json']) for row in rows]
                ignitions = [json.loads(row['ignition_json']) for row in rows]
            if any(not _same_geometry(source, layout) for source in source_layouts):
                _error('layout_mismatch', '蒸发记录的谱板参数与当前方法不一致')
            if task_id is not None:
                captured = rows[0]['ccd_indices']
                if not captured or not set(captured) <= set(layout['ccd_indices']) or any(row['ccd_indices'] != captured for row in rows):
                    _error('layout_mismatch', '蒸发记录采集的 CCD 不匹配')
                layout = layout | {'ccd_indices': [ccd for ccd in layout['ccd_indices'] if ccd in captured]}
            start, end = payload['start_frame'], payload['end_frame']
            if not 1 <= start <= end or any(end > int(source.get('burn_count', 0)) for source in ignitions):
                _error('interval_invalid', '导入区间必须在每条所选记录的燃烧帧范围内')
            storage = payload['storage_mode']
            if storage == 'full_interval' and end-start+1 < int(method.payload['conditions'].get('frame_count', 1)):
                _error('interval_short', '蒸发文件取样区间小于当前方法采样次数')
            ignition = {key: ignitions[0].get(key, default) for key, default in
                        (('burn_cyc', 1), ('dark_cyc', 1), ('dark_count', 0))} | {'burn_count': end-start+1}
            if storage == 'full_interval' and any(any(source.get(key, default) != ignition[key]
                    for key, default in (('burn_cyc', 1), ('dark_cyc', 1), ('dark_count', 0))) for source in ignitions):
                _error('ignition_mismatch', '全时样品的源激发条件不一致，请分别导入')
            existing = db.execute('SELECT * FROM postprocessing_prepared_targets WHERE name=? COLLATE NOCASE', (name,)).fetchone()
            if existing and payload['same_name_strategy'] == 'error':
                _error('target_exists', '输出样品集已存在，请选择替换或追加', 409)
            if existing and payload.get('expected_target_revision') != existing['revision']:
                _error('target_changed', '输出样品集已更新，请刷新后重试', 409)
            append = existing is not None and payload['same_name_strategy'] == 'append'
            original_layout = source_layouts[0]
            # A legacy identifier is evidence, never a modern methods-table foreign key.
            legacy_id = original_layout.get('legacy_method_id')
            binding = method.version_id if payload['use_method_id'] else None
            if payload['use_method_id']:
                legacy_id = method.payload.get('legacy_migration', {}).get('legacy_method_id')
            if append:
                if existing['storage_mode'] != storage or not _same_geometry(json.loads(existing['layout_json']), layout):
                    _error('target_layout', '目标的格式或谱板参数不一致，不能追加')
                if storage == 'full_interval' and json.loads(existing['ignition_json']) != ignition:
                    _error('target_ignition', '源与目标的激发条件不一致，不能追加')
                # Existing targets keep their identity, method and dispersion, as in the legacy dialog.
                binding, legacy_id = existing['method_version_id'], existing['legacy_method_id']
                layout = json.loads(existing['layout_json'])
            layout = layout | {'legacy_method_id': legacy_id}
            target_id = existing['id'] if existing else 'prepared-' + uuid.uuid4().hex
            evidence = {'prepared_request_id': payload['request_id'], 'prepared_request_sha256': request_hash,
                        'target_id': target_id, 'strategy': payload['same_name_strategy']}
            if task_id is not None:
                evidence.update(source_task_id=task_id, source_record_ids=identifiers, start_frame=start, end_frame=end)
            result = self.conversion.convert_edt({
                'record_ids': identifiers, 'start_frame': start, 'end_frame': end,
                'storage_mode': storage, 'target_ccd_layout_id': layout_id,
                'target_ccd_indices': layout['ccd_indices'], 'method_version_id': binding, 'name': name,
            }, actor, transaction=transaction,
                fingerprint_context={'request_id': payload['request_id'], 'sha256': request_hash},
                source_layout=layout, report_extra=evidence, prefer_band_name=True,
                evaporation_records=rows if task_id is not None else None)
            output = json.loads(existing['records_json']) if append else []
            output.extend({'id': sample_id, 'task_id': output_task_id, 'name': row['band_name'] or row['long_name'] or row['sample_name'] or '',
                           'measure_time': row['measure_time'], 'source_record_id': identifier,
                           'start_frame': start, 'end_frame': end,
                           **({'source_task_id': task_id, 'source_sha256': row['source_sha256'],
                               'source_viewer_group': row['viewer_group']} if task_id is not None else {})}
                          for row, identifier, output_task_id, sample_id in zip(rows, identifiers, result['task_ids'], result['sample_ids']))
            now = utc_now()
            if existing:
                db.execute('UPDATE postprocessing_prepared_targets SET storage_mode=?,layout_json=?,ignition_json=?,method_version_id=?,'
                           'legacy_method_id=?,records_json=?,revision=revision+1,updated_at=? WHERE id=?',
                           (storage, _json(layout), _json(ignition), binding, legacy_id, _json(output), now, target_id))
            else:
                db.execute('INSERT INTO postprocessing_prepared_targets '
                           '(id,name,storage_mode,layout_json,ignition_json,method_version_id,legacy_method_id,records_json,created_at,updated_at) '
                           'VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (target_id, name, storage, _json(layout), _json(ignition), binding, legacy_id, _json(output), now, now))
            self._audit(db, actor, 'postprocessing.prepared.import', result['report'] | {'run_id': result['id']})
            return {'run_id': result['id'], 'reused': False,
                    'target': _target(db.execute('SELECT * FROM postprocessing_prepared_targets WHERE id=?', (target_id,)).fetchone())}
