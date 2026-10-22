"""Open a validated WDT snapshot as a completed, reusable calibration task."""
import hashlib
import json
from ...db import utc_now
from ..spectrum_migration import SpectrumMigrationService
from .values import DispersionError, _json


def open_record(service, identifier, actor):
    with service.database.write() as db:
        source = SpectrumMigrationService.source_record(db, identifier)
        if source['format'] != 'wdt':
            raise DispersionError('dispersion_wdt_required', '色散曲线只接受 WDT 文件')
        for row in db.execute('SELECT id,condition_json FROM dispersion_tasks ORDER BY id'):
            condition = json.loads(row['condition_json'])
            if condition.get('source_record_id') == identifier and condition.get('source_sha256') == source['source_sha256']:
                return service.repository._task_dict(row['id'], db)
        geometry = json.loads(source['layout_json'])
        ignition = json.loads(source['ignition_json'])
        key = hashlib.sha256(_json(geometry).encode()).hexdigest()[:20]
        name = '旧 WDT 布局 ' + key
        layout = db.execute('SELECT * FROM ccd_layouts WHERE name=?', (name,)).fetchone()
        now = utc_now()
        if layout is None:
            db.execute('INSERT INTO ccd_layouts(name,frame_count,ccds_per_frame,points_per_ccd,point_width,'
                       'gap_points_json,ccd_indices_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
                       (name, geometry['frame_count'], geometry['ccds_per_frame'], geometry['points_per_ccd'],
                        geometry['point_width'], _json(geometry['gap_points']), _json(geometry['ccd_indices']), now))
            layout = db.execute('SELECT * FROM ccd_layouts WHERE name=?', (name,)).fetchone()
        profile = db.execute('SELECT id FROM device_profiles ORDER BY id LIMIT 1').fetchone()
        if profile is None:
            raise DispersionError('device_profile_not_found', '缺少色散任务档案')
        count, dark = int(ignition['burn_count']), int(ignition['dark_count'])
        if not 1 <= count <= 255 or not 0 <= dark <= 20:
            raise DispersionError('dispersion_source_frames_invalid', 'WDT 帧数超出色散任务支持范围')
        task = db.execute('INSERT INTO dispersion_tasks(name,device_profile_id,ccd_layout_id,frame_count,'
                          'dark_frame_count,pre_excitation_seconds,sampling_period_seconds,ccd_indices_json,'
                          'created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                          (source['sample_name'] or '旧 WDT 色散曲线', profile['id'], layout['id'], count, dark,
                           ignition.get('pre_burn') or 0, ignition.get('burn_cyc') or 1,
                           _json(geometry['ccd_indices']), actor, now, now))
        service.repository._import_wdt(db, task.lastrowid, layout, identifier, actor)
        return service.repository._task_dict(task.lastrowid, db)
