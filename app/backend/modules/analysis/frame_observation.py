"""Read-only observation of a sample acquisition frame."""
from functools import cache

from ..acquisition import AcquisitionError
from .concentration_preview import calculate_preview
from .errors import AnalysisError


def observe_frame(database, methods, acquisition, task_id, repeat_index, turn_index, frame_index, ccd, *, can_analyze):
    task = acquisition.get_task(task_id)
    if task['task_kind'] != 'sample' or task['sample_kind'] == 'preheat':
        raise AcquisitionError('acquisition_measurement_task_invalid', '请选择正式样品摄谱任务')
    turns = task.get('turns')
    turn = next((item for item in turns['plan'] if item['turn_index'] == turn_index), None) if turns else None
    if (turns and not turn) or (not turns and turn_index != 0):
        raise AcquisitionError('acquisition_measurement_turn_invalid', '所选转角不属于当前任务')
    with database.read() as db:
        db.execute('BEGIN')
        rows, _ = acquisition.measurement_frames(
            db, task_id, repeat_index, turn_index if turns else None,
            phase='burn', frame_index=frame_index, include_points=True,
        )
        selected = next((frame for frame in rows if frame['ccd_index'] == ccd), None)
        if selected is None:
            raise AcquisitionError('acquisition_measurement_frame_missing', '所选 CCD 的燃烧帧尚未保存', status_code=404)
        result = {'frame_index': frame_index, 'repeat_index': repeat_index, 'turn_index': turn_index, 'ccd_index': ccd,
                  'points': selected.get('points') or [], 'frame_sha256': selected.get('points_sha256'),
                  'method_name': None, 'method_version': None, 'rows': [], 'message': None}
        if selected['damaged'] or not result['points']:
            return result | {'message': '该帧损坏或缺少完整原始点，无法估值'}
        if not can_analyze:
            return result | {'message': '需要分析读取权限才能查看谱线诊断和参考含量'}
        if not task['method_version_id']:
            return result | {'message': '该摄谱任务没有绑定已发布方法'}

        raw = {row['ccd_index']: row['points'] for row in rows if not row['damaged'] and row.get('points')}
        dark_count = int(task['dark_frame_count'])

        version = methods.bind_snapshots(db).by_id(task['method_version_id'], published_only=True)
        if version is None:
            return result | {'message': '摄谱任务绑定的方法版本不可用'}

        positions = {str(line['id']): (item['turn_index'], line['ccd_index'], line['point_index'])
                     for item in turns['plan'] for line in item['lines']} if turns else {}
        geometry = None if turns else methods.bind_geometry(db, version.payload['conditions'])

        def locate(line):
            if turns:
                return positions.get(str(line['id']))
            position = geometry.locate(line.get('actual_wavelength_nm') or line['wavelength_nm'])
            return (turn_index, position.ccd_index, position.point) if position else None

        def frame_values(line_turn, index, _interval):
            if line_turn != turn_index:
                raise AnalysisError('analysis_frame_other_turn', '该谱线由其他转角采集')
            return raw.get(index)

        @cache
        def reference_frames(line_turn, index):
            rows, provisional = acquisition.measurement_frames(
                db, task_id, repeat_index, line_turn if turns else None, ccd_index=index, include_points=True,
            )
            by_phase = {'burn': {}, 'dark': {}}
            for row in rows:
                if not row['damaged'] and row.get('points'):
                    by_phase[row['phase']][row['frame_index']] = row['points']
            return by_phase, provisional

        def estimate_values(line_turn, index, interval):
            line_plan = turns['plan'][line_turn] if turns else None
            start, end = interval or ((line_plan['start_frame'], line_plan['end_frame']) if line_plan else (1, task['burn_frame_count']))
            if line_turn == turn_index and frame_index + 1 < end:
                raise AnalysisError('analysis_frame_exposure_incomplete',
                                    f'第 {frame_index + 1} 帧尚未覆盖方法曝光区间 {start}–{end}')
            frames, provisional = reference_frames(line_turn, index)
            burn_indices = range(start - 1, end)
            if not set(burn_indices) <= frames['burn'].keys():
                raise AnalysisError('analysis_frame_exposure_incomplete', f'方法曝光区间 {start}–{end} 的燃烧帧未收齐或有损坏')
            dark_indices = range(dark_count)
            if not set(dark_indices) <= frames['dark'].keys():
                raise AnalysisError('analysis_frame_dark_pending', '暗帧未收齐或有损坏，无法完成扣暗')
            if provisional:
                return acquisition.measurement_interval(task, [frames['burn'][i] for i in burn_indices],
                                                        [frames['dark'][i] for i in dark_indices])
            return acquisition.interval_band(db, selected['sample_id'], index, (start, end),
                                             turn_index=line_turn if turns else None, allow_single_frame=True)['points']

        try:
            observed = calculate_preview(db, version, locate, frame_values, observe_frame=True)
            preview = calculate_preview(db, version, locate, estimate_values, require_peak=True)
        except AnalysisError as exc:
            return result | {'message': exc.message}
    estimates = {row['line_id']: row for row in preview['rows']}
    rows = []
    for row in observed['rows']:
        if row['code'] == 'analysis_frame_other_turn':
            continue
        estimate = estimates[row['line_id']]
        diagnostic = row['message'] or None
        if row['code'] == 'analysis_frame_saturated':
            estimate = {**estimate, 'concentration': None, 'message': '本帧信号饱和，参考含量不可用', 'code': row['code']}
        reference_interval = estimate.get('exposure_interval') or (
            (turn['start_frame'], turn['end_frame']) if turn else (1, task['burn_frame_count']))
        rows.append({**estimate, **{key: row[key] for key in ('ccd_index', 'point_index', 'expected_point_index', 'raw_intensity', 'peak_found')},
                     'diagnostic_code': row['code'] if diagnostic else None, 'diagnostic': diagnostic,
                     'reference_interval': reference_interval})
    message = '当前转角没有可诊断的分析谱线' if not rows else None
    return result | preview | {'rows': rows, 'message': message}
