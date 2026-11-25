"""Acquisition-owned physical turn snapshots, frame evidence and band reads."""
import hashlib
import json
import math

from ...db import utc_now
from .codec import _pack_uint16, _unpack_uint16, _unpack_float32, average_points
from .values import AcquisitionError, _json


def context(db, task_id):
    row = db.execute('SELECT * FROM acquisition_turn_tasks WHERE task_id=?', (task_id,)).fetchone()
    return (json.loads(row['config_json']), json.loads(row['runtime_json'])) if row else (None, None)


def runtime(db, task_id, **changes):
    config, state = context(db, task_id)
    if config is not None:
        state.update(changes)
        db.execute('UPDATE acquisition_turn_tasks SET runtime_json=? WHERE task_id=?', (_json(state), task_id))


def line_location(db, sample_id, line_id):
    row = db.execute('SELECT task_id FROM acquisition_samples WHERE id=?', (sample_id,)).fetchone()
    config, _ = context(db, row['task_id']) if row else (None, None)
    if config:
        for turn in config['plan']:
            line = next((line for line in turn['lines'] if line['id'] == str(line_id)), None)
            if line:
                return {**line, 'turn_index': turn['turn_index'], 'angle_deg': turn['angle_deg']}
        raise AcquisitionError('sample_line_turn_missing', '任务方法中没有该谱线的有效转角关联')
    return None


def band_rows(db, sample_id):
    turns = db.execute('SELECT * FROM acquisition_turn_bands WHERE sample_id=? ORDER BY turn_index,ccd_index', (sample_id,)).fetchall()
    if turns:
        return [dict(row) for row in turns]
    rows = [dict(row) for row in db.execute('SELECT * FROM acquisition_sample_bands WHERE sample_id=? ORDER BY ccd_index', (sample_id,))]
    task = db.execute('SELECT task_id FROM acquisition_samples WHERE id=?', (sample_id,)).fetchone()
    config, _ = context(db, task['task_id']) if task else (None, None)
    if config and not config['multiple']:
        for row in rows:
            row.update(turn_index=0, angle_deg=config['plan'][0]['angle_deg'])
    return rows


def decoded_bands(db, sample_id, include_points=False):
    result = []
    for row in band_rows(db, sample_id):
        for column, size, digest in (('mean_blob', row['points_count'] * 4, 'mean_sha256'),
                ('burn_frames_blob', row['points_count'] * row['burn_frame_count'] * 2, 'burn_sha256'),
                ('dark_frames_blob', row['points_count'] * row['dark_frame_count'] * 2, 'dark_sha256')):
            blob = row[column]
            if blob is not None and (len(blob) != size or hashlib.sha256(blob).hexdigest() != row[digest]):
                raise AcquisitionError('acquisition_band_integrity_failed', '转角谱带形状或SHA-256校验失败')
        if include_points:
            row['mean_points'] = _unpack_float32(row['mean_blob'], row['points_count'])
        for column in ('mean_blob', 'burn_frames_blob', 'dark_frames_blob'):
            row.pop(column)
        result.append(row)
    sample = db.execute('SELECT task_id FROM acquisition_samples WHERE id=?', (sample_id,)).fetchone()
    config, _ = context(db, sample['task_id']) if sample else (None, None)
    if config and include_points:
        for band in result:
            turn = config['plan'][band['turn_index']]
            band['wavelengths_nm'] = [wavelength_at(turn['geometry'], band['ccd_index'], i) for i in range(band['points_count'])]
    return result


def wavelength_at(geometry, ccd, point):
    step = ccd * geometry['points_per_ccd'] + sum(geometry['gap_points'][:ccd]) + point
    a, b, c = geometry['ws_cof'][:3]
    if abs(a) < 1e-15:
        return (step - c) / b if b else None
    value = b * b - 4 * a * (c - step)
    return (math.sqrt(value) - b) / (2 * a) if value >= 0 else None


def measurement_bands(db, task, sample):
    config, _ = context(db, task['id'])
    if not config or not config['multiple']:
        return None
    if sample['finalized']:
        return [{**b, 'points': b['mean_points'], 'burn_count': b['burn_frame_count'], 'dark_count': b['dark_frame_count']}
                for b in decoded_bands(db, sample['id'], True)]
    result = []
    evidence = frames(db, task['id'], sample['repeat_index'], include_points=True)
    for turn in config['plan']:
        for ccd in turn['ccd_indices']:
            rows = [f for f in evidence if f['turn_index'] == turn['turn_index'] and f['ccd_index'] == ccd and not f['damaged']]
            burns = [f for f in rows if f['phase'] == 'burn' and turn['start_frame'] - 1 <= f['frame_index'] < turn['end_frame']]
            darks = [f for f in rows if f['phase'] == 'dark']
            if burns:
                count = turn['geometry']['points_per_ccd']
                mean = average_points([_pack_uint16(f['points']) for f in burns], [_pack_uint16(f['points']) for f in darks],
                    count, burn_cycle_seconds=task['burn_cycle_seconds'], dark_cycle_seconds=task['dark_cycle_seconds'])
                result.append({'ccd_index': ccd, 'turn_index': turn['turn_index'], 'angle_deg': turn['angle_deg'],
                    'points': _unpack_float32(mean, count), 'burn_count': len(burns), 'dark_count': len(darks)})
    return result


def store_frame(db, task, sample, phase, frame_index, event, virtual_time_ms, damaged=False):
    config, state = context(db, task['id'])
    if not config or not config['multiple']:
        return False
    turn = config['plan'][state['turn_index']]
    received = {ccd['ccd_index']: ccd for ccd in event.ccds or []}
    event_metadata = event.to_dict()
    event_metadata['ccds'] = [{key: value for key, value in ccd.items() if key != 'points'} for ccd in event_metadata.get('ccds', [])]
    for index in turn['ccd_indices']:
        points = received.get(index, {}).get('points', [])
        invalid = damaged or len(points) != turn['geometry']['points_per_ccd']
        if invalid and not damaged:
            raise AcquisitionError('sample_turn_frame_incomplete', '转角返回的CCD或点数不完整，已停止采集')
        blob = None if invalid else _pack_uint16(points)
        digest = hashlib.sha256(blob).hexdigest() if blob is not None else None
        metrics = {'virtual_time_ms': virtual_time_ms, 'peak_value': max(points) if points else None,
                   'peak_position': points.index(max(points)) if points else None, 'integral_value': sum(points) if points else None}
        db.execute('INSERT INTO acquisition_turn_frames(task_id,repeat_index,turn_index,attempt,phase,frame_index,'
            'ccd_index,points_blob,points_count,points_sha256,metrics_json,event_json,damaged,accepted,captured_at) '
            'VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?,0,?)',
            (task['id'], sample['repeat_index'], state['turn_index'], phase, frame_index, index, blob,
             len(points) if blob is not None else 0, digest, _json(metrics), _json(event_metadata), int(invalid), utc_now()))
    return True


def frames(db, task_id, repeat_index=None, phase=None, ccd_index=None, include_points=False, *, turn_index=None, frame_index=None):
    config, _ = context(db, task_id)
    if not config or not config['multiple']:
        return None
    result = []
    where = ['f.task_id=?']
    args = [task_id]
    for column, value in [('repeat_index', repeat_index), ('phase', phase), ('ccd_index', ccd_index), ('turn_index', turn_index), ('frame_index', frame_index)]:
        if value is not None:
            where.append(f'f.{column}=?')
            args.append(value)
    for raw in db.execute('SELECT f.*,s.id AS sample_id FROM acquisition_turn_frames f '
            'JOIN acquisition_samples s ON s.task_id=f.task_id AND s.repeat_index=f.repeat_index '
            f"WHERE {' AND '.join(where)} ORDER BY f.repeat_index,f.turn_index,f.phase,f.frame_index,f.ccd_index", args):
        row = dict(raw)
        blob = row.pop('points_blob')
        if blob is not None and (len(blob) != row['points_count'] * 2 or hashlib.sha256(blob).hexdigest() != row['points_sha256']):
            raise AcquisitionError('acquisition_frame_integrity_failed', '转角原始帧校验失败')
        if include_points and blob is not None:
            row['points'] = _unpack_uint16(blob, row['points_count'])
        event = json.loads(row.pop('event_json'))
        row.update(json.loads(row.pop('metrics_json')))
        row.update(angle_deg=config['plan'][row['turn_index']]['angle_deg'], headers_json='[]', dtype='uint16',
                   endianness='little', raw_transfer_sha256=event.get('details', {}).get('sha256'),
                   raw_byte_length=event.get('details', {}).get('byte_length', 0))
        result.append(row)
    return result


def finalize(db, task, sample):
    config, _ = context(db, task['id'])
    if not config or not config['multiple']:
        return None
    evidence = frames(db, task['id'], sample['repeat_index'], include_points=True)
    hashes = []
    for turn in config['plan']:
        for ccd in turn['ccd_indices']:
            selected = [f for f in evidence if f['turn_index'] == turn['turn_index'] and f['ccd_index'] == ccd]
            if any(f['damaged'] for f in selected):
                raise AcquisitionError('acquisition_frames_incomplete', '转角有损坏帧，不能完成本次重复')
            burns = [f for f in selected if f['phase'] == 'burn']
            darks = [f for f in selected if f['phase'] == 'dark']
            for rows, count in ((burns, task['burn_frame_count']), (darks, task['dark_frame_count'])):
                if sorted(f['frame_index'] for f in rows) != list(range(count)):
                    raise AcquisitionError('acquisition_frames_incomplete', '转角帧数不足，不能完成本次重复')
            chosen = [f for f in burns if turn['start_frame'] - 1 <= f['frame_index'] < turn['end_frame']]
            burn = [_pack_uint16(f['points']) for f in chosen]
            dark = [_pack_uint16(f['points']) for f in darks]
            count = turn['geometry']['points_per_ccd']
            mean = average_points(burn, dark, count, burn_cycle_seconds=task['burn_cycle_seconds'], dark_cycle_seconds=task['dark_cycle_seconds'])
            mode = turn['storage_mode']
            full_burn, full_dark = (b''.join(burn), b''.join(dark)) if mode == 'full_interval' else (None, None)
            sha = lambda blob: hashlib.sha256(blob).hexdigest() if blob is not None else None
            hashes.append([turn['turn_index'], turn['angle_deg'], ccd, sha(mean), sha(full_burn), sha(full_dark)])
            db.execute('INSERT INTO acquisition_turn_bands(sample_id,turn_index,angle_deg,ccd_index,storage_mode,points_count,'
                'burn_frame_count,dark_frame_count,mean_blob,mean_sha256,burn_frames_blob,burn_sha256,dark_frames_blob,dark_sha256,created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (sample['id'], turn['turn_index'], turn['angle_deg'], ccd, mode, count,
                    len(burn), len(dark), mean, sha(mean), full_burn, sha(full_burn), full_dark, sha(full_dark), utc_now()))
    db.execute('UPDATE acquisition_turn_frames SET accepted=1 WHERE task_id=? AND repeat_index=? AND damaged=0', (task['id'], sample['repeat_index']))
    return hashlib.sha256(_json({'method': config['method_content_sha256'], 'bands': hashes}).encode('utf-8')).hexdigest()


def interval_band(db, sample_id, ccd_index, interval=None, turn_index=None):
    sample = db.execute('SELECT s.*,t.burn_cycle_seconds,t.dark_cycle_seconds FROM acquisition_samples s '
                        'JOIN acquisition_tasks t ON t.id=s.task_id WHERE s.id=?', (sample_id,)).fetchone()
    config, _ = context(db, sample['task_id']) if sample else (None, None)
    if not config or not config['multiple']:
        return None
    candidates = [t for t in config['plan'] if ccd_index in t['ccd_indices'] and (turn_index is None or t['turn_index'] == turn_index)]
    if len(candidates) != 1:
        raise AcquisitionError('sample_turn_required', '该CCD在多个转角采集，请明确谱线或转角后读取')
    turn = candidates[0]
    band = next((b for b in band_rows(db, sample_id) if b['turn_index'] == turn['turn_index'] and b['ccd_index'] == ccd_index), None)
    if interval is None and band is not None:
        values = next(b for b in decoded_bands(db, sample_id, True) if b['id'] == band['id'])
        return {'points': values['mean_points'], 'mean_sha256': band['mean_sha256']}
    chosen_interval = interval or (turn['start_frame'], turn['end_frame'])
    start, end = chosen_interval
    evidence = frames(db, sample['task_id'], sample['repeat_index'], ccd_index=ccd_index, include_points=True)
    rows = [f for f in evidence if f['turn_index'] == turn['turn_index'] and not f['damaged']]
    burns = [f for f in rows if f['phase'] == 'burn' and start - 1 <= f['frame_index'] < end]
    darks = [f for f in rows if f['phase'] == 'dark']
    if not 1 <= start <= end or len(burns) != end - start + 1:
        raise AcquisitionError('analysis_interval_waiting', '等待该转角谱线的完整燃烧帧')
    mean = average_points([_pack_uint16(f['points']) for f in burns], [_pack_uint16(f['points']) for f in darks],
        turn['geometry']['points_per_ccd'], burn_cycle_seconds=sample['burn_cycle_seconds'], dark_cycle_seconds=sample['dark_cycle_seconds'])
    return {'points': _unpack_float32(mean, turn['geometry']['points_per_ccd']), 'interval': chosen_interval, 'provisional': not sample['finalized']}
