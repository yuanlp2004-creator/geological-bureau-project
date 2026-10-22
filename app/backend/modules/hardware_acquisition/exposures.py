"""转角按区间采集，原始帧和浮点均值独立保存并校验哈希。"""

import json
import struct
from typing import Any
from ...db import utc_now
from .codec import _pack_points, _unpack_points
from .rules import _metrics
from .values import HardwareError, _sha


# 读取任务固化计划中的区间，兼容升级前的一帧转角任务。
def exposure_config(task: Any, step: Any) -> dict[str, Any]:
    plan = next(item for item in json.loads(task['plan_json']) if item['order_index'] == step['order_index'])
    return {'start_frame': 1, 'end_frame': 1, 'storage_mode': 'averaged',
            'expected_baseline_position': 256, 'search_radius_points': 64, **plan}


# 保存当前全部 CCD，未到区间末尾时保持采集中；异常帧立即交给现有闭环。
def capture_exposure(db: Any, task: Any, step: Any, attempt: int, event: dict, faults: list[str]) -> bool:
    config = exposure_config(task, step)
    indices = config.get('ccd_indices', json.loads(task['ccd_indices_json']))
    count = db.execute('SELECT points_per_ccd FROM ccd_layouts WHERE id=?', (task['ccd_layout_id'],)).fetchone()[0]
    by_ccd = {item['ccd_index']: item for item in event.get('ccds', [])}
    if any(index not in by_ccd or len(by_ccd[index].get('points', [])) != count for index in indices):
        event['event_type'] = 'fault'
        event['ccds'] = []
        return True
    frame_index = db.execute('SELECT COALESCE(MAX(frame_index),0)+1 FROM hardware_exposure_frames '
                            'WHERE step_id=? AND attempt=?', (step['id'], attempt)).fetchone()[0]
    for index in indices:
        points = by_ccd[index]['points']
        blob = _pack_points(points)
        db.execute('INSERT INTO hardware_exposure_frames(task_id,step_id,attempt,frame_index,ccd_index,'
                   'points_blob,points_count,points_sha256,captured_at) VALUES (?,?,?,?,?,?,?,?,?)',
                   (task['id'], step['id'], attempt, frame_index, index, blob, count, _sha(blob), utc_now()))
    abnormal = any(_metrics(dict(task), dict(step), by_ccd[index], faults)[2] for index in indices)
    if frame_index < config['end_frame']:
        return abnormal
    for index in indices:
        rows = db.execute('SELECT * FROM hardware_exposure_frames WHERE step_id=? AND attempt=? AND ccd_index=? '
                          'AND frame_index BETWEEN ? AND ? ORDER BY frame_index',
                          (step['id'], attempt, index, config['start_frame'], config['end_frame'])).fetchall()
        if len(rows) != config['end_frame'] - config['start_frame'] + 1:
            raise HardwareError('hardware_exposure_incomplete', '转角区间帧数不足')
        raw = [bytes(row['points_blob']) for row in rows]
        if any(_sha(blob) != row['points_sha256'] for row, blob in zip(rows, raw)):
            raise HardwareError('hardware_exposure_integrity_failed', '转角原始帧哈希不符')
        values = [_unpack_points(blob, count) for blob in raw]
        mean = struct.pack(f'<{count}f', *(sum(frame[i] for frame in values) / len(values) for i in range(count)))
        full = b''.join(raw) if config['storage_mode'] == 'full_interval' else None
        db.execute('INSERT INTO hardware_exposure_results(task_id,step_id,attempt,ccd_index,storage_mode,'
                   'start_frame,end_frame,points_count,mean_blob,mean_sha256,frames_blob,frames_sha256,created_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (task['id'], step['id'], attempt, index, config['storage_mode'], config['start_frame'],
                    config['end_frame'], count, mean, _sha(mean), full, _sha(full) if full is not None else None, utc_now()))
    return True


# 提取区间结果，只有已确认尝试可标为可用，包含点值时验证实际 BLOB。
def exposure_results(db: Any, task_id: int, include_points: bool = False) -> list[dict]:
    results = []
    for row in db.execute('SELECT r.*, f.confirmed FROM hardware_exposure_results r JOIN hardware_frames f '
                          'ON f.step_id=r.step_id AND f.attempt=r.attempt AND f.ccd_index=r.ccd_index '
                          'WHERE r.task_id=? ORDER BY r.step_id,r.attempt,r.ccd_index', (task_id,)):
        item = dict(row)
        mean, full = bytes(item.pop('mean_blob')), item.pop('frames_blob')
        if _sha(mean) != row['mean_sha256'] or (full is not None and _sha(full) != row['frames_sha256']):
            raise HardwareError('hardware_exposure_integrity_failed', '转角区间结果哈希不符')
        item['confirmed'] = bool(item['confirmed'])
        if include_points:
            item['mean_points'] = list(struct.unpack(f"<{row['points_count']}f", mean))
            item['frames'] = [_unpack_points(full[offset:offset + row['points_count'] * 2], row['points_count'])
                              for offset in range(0, len(full), row['points_count'] * 2)] if full is not None else []
        results.append(item)
    return results
