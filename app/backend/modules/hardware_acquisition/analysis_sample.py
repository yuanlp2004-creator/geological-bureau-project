"""Adapt confirmed turn evidence through the acquisition owner's public writer."""
from __future__ import annotations
import hashlib
import json

from ..acquisition_import import AcquisitionRecordImporter
from ..acquisition.confirmed_import import ConfirmedSpectrum
from ..methods import MethodService
from ..spectral_lines import canonical_lines, exposure_interval
from ...db import utc_now
from .exposures import exposure_results, exposure_config
from .values import HardwareError


def save_analysis_sample(service, task_id: int, payload: dict, actor: int | None) -> dict:
    with service.database.write() as db:
        task, layout, _ = service.repository._context(task_id, db)
        if task['status'] != 'completed' or task['completed_steps'] != task['total_steps']:
            raise HardwareError('hardware_sample_incomplete', '全部转角采集完成并确认后才能保存分析样品', status_code=409)
        if not task['method_id'] or not task['method_version']:
            raise HardwareError('hardware_sample_method_missing', '任务须绑定已发布方法后才能生成分析样品', status_code=409)
        snapshots = MethodService(service.database).bind_snapshots(db)
        method = snapshots.for_print(task['method_id'], task['method_version'])
        conditions = method.payload['conditions']
        importer = AcquisitionRecordImporter().bind(db)
        source_id = f"hardware-task:{task_id}"
        existing = importer.confirmed_source(source_id)
        if existing:
            if existing['source_sha256'] != task['result_sha256']:
                raise HardwareError('hardware_sample_source_changed', '已保存转角结果的来源哈希不一致', status_code=409)
            return {**existing, 'already_saved': True}
        geometry = MethodService(service.database).bind_geometry(db, conditions)
        if geometry.layout_id != layout['id']:
            raise HardwareError('hardware_sample_layout_mismatch', '任务与已发布方法的 CCD 布局不一致', status_code=409)
        lines = [line for line in canonical_lines(method.payload.get('lines'), conditions) if line.get('enabled')]
        intervals = {}
        for line in lines:
            location = geometry.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm']))
            if location is None:
                raise HardwareError('hardware_sample_line_outside_ccd', '方法谱线超出当前布局')
            interval = exposure_interval(line, conditions)
            if interval:
                intervals.setdefault(location.ccd_index, []).append(interval)
        steps = {row['id']: row for row in db.execute('SELECT * FROM hardware_plan_steps WHERE task_id=?', (task_id,))}
        bands, provenance = [], []
        for exposure in exposure_results(db, task_id):
            if not exposure['confirmed']:
                continue
            ccd = exposure['ccd_index']
            if any(band['ccd_index'] == ccd for band in bands):
                raise HardwareError('hardware_sample_duplicate_ccd', '同一 CCD 有多个已确认转角结果，不能混合为一个样品')
            config = exposure_config(task, steps[exposure['step_id']])
            if config.get('method_content_sha256') != method.content_sha256:
                raise HardwareError('hardware_sample_method_changed', '已确认结果的方法快照不一致', status_code=409)
            raw = db.execute('SELECT * FROM hardware_exposure_frames WHERE task_id=? AND step_id=? AND attempt=? '
                             'AND ccd_index=? ORDER BY frame_index',
                             (task_id, exposure['step_id'], exposure['attempt'], ccd)).fetchall()
            if [r['frame_index'] for r in raw] != list(range(1, exposure['end_frame']+1)):
                raise HardwareError('hardware_sample_frames_missing', '已确认尝试的原始帧不完整')
            if any(len(bytes(r['points_blob'])) != exposure['points_count']*2
                   or hashlib.sha256(bytes(r['points_blob'])).hexdigest() != r['points_sha256'] for r in raw):
                raise HardwareError('hardware_exposure_integrity_failed', '转角原始帧校验失败')
            if any(start < 1 or end > len(raw) for start,end in intervals.get(ccd, [])):
                raise HardwareError('hardware_sample_line_interval_missing', '转角采集范围不足以覆盖方法逐线曝光区间')
            stored = db.execute('SELECT mean_blob FROM hardware_exposure_results WHERE id=?', (exposure['id'],)).fetchone()
            detail = {key: exposure[key] for key in ('id','step_id','attempt','ccd_index','start_frame','end_frame','mean_sha256')}
            detail.update(angle_deg=config['angle_deg'], method_content_sha256=method.content_sha256,
                          frame_sha256=[r['points_sha256'] for r in raw])
            bands.append({**exposure, 'mean_blob': bytes(stored['mean_blob']),
                          'storage_mode': 'full_interval' if intervals.get(ccd) else exposure['storage_mode'],
                          'frames': [{'frame_index': r['frame_index']-1, 'blob': bytes(r['points_blob']),
                                      'sha256': r['points_sha256'], 'evidence': {'hardware_task_id': task_id,
                                      **{key: detail[key] for key in ('step_id','attempt','angle_deg')},
                                      'source_frame_index': r['frame_index'], 'source_frame_id': r['id']}} for r in raw]})
            provenance.append(detail)
        expected = set(json.loads(task['ccd_indices_json']))
        if {band['ccd_index'] for band in bands} != expected:
            raise HardwareError('hardware_sample_bands_missing', '全部所选 CCD 均须有已确认结果')
        if any(geometry.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm'])).ccd_index not in expected for line in lines):
            raise HardwareError('hardware_sample_method_ccds_missing', '采集结果没有覆盖方法全部启用谱线')
        record = ConfirmedSpectrum(
            source_id, task['result_sha256'], layout['id'], task['device_profile_id'], task['method_id'],
            task['method_version'], method.version_id, payload.get('sample_name') or task['sample_name'],
            payload.get('sample_kind','test'), int(payload.get('name_length',12)), task['sampling_period_seconds'],
            bands, {'hardware_task_id': task_id, 'method_content_sha256': method.content_sha256,
                    'confirmed_exposures': provenance,
                    'decisions': [dict(r) for r in db.execute('SELECT * FROM hardware_decisions WHERE task_id=? ORDER BY id', (task_id,))]},
            task['completed_at'] or utc_now())
        try:
            result = importer.import_confirmed(record, actor)
        except ValueError as exc:
            raise HardwareError('hardware_sample_invalid', str(exc)) from exc
        service.repository._audit(db, actor, 'hardware.sample.save', task_id,
                                  {**result, 'method_content_sha256': method.content_sha256, 'exposures': provenance})
        return result
