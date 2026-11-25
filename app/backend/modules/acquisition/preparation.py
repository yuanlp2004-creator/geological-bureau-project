"""Read completed evaporation records in the caller's preparation transaction."""

import hashlib
import json
import struct

from ..acquisition_import import ImportedBand
from .values import AcquisitionError


_COMPLETED_EVAPORATION = """
    FROM acquisition_samples s JOIN acquisition_tasks t ON t.id=s.task_id
    WHERE t.task_kind='evaporation' AND t.sample_kind='evaporation'
    AND t.status='completed' AND t.discarded_at IS NULL
    AND s.finalized=1 AND s.status='completed' AND s.storage_mode='full_interval'
    AND s.result_sha256 IS NOT NULL
    AND NOT EXISTS(SELECT 1 FROM acquisition_sample_disposals d WHERE d.sample_id=s.id)
"""


def evaporation_sources(db):
    rows = db.execute(
        "SELECT t.id, t.name, t.excitation_condition_json, COUNT(*) AS record_count "
        + _COMPLETED_EVAPORATION + " GROUP BY t.id ORDER BY t.id DESC"
    )
    sources = []
    for row in rows:
        turn = json.loads(row['excitation_condition_json'] or '{}').get('capture_turn') or {}
        sources.append({
            'task_id': row['id'], 'name': row['name'], 'record_count': row['record_count'],
            'angle_deg': turn.get('angle_deg'),
        })
    return sources


def evaporation_records(db, task_id, methods):
    rows = db.execute(
        "SELECT s.id, s.sample_name, s.completed_at, s.repeat_index, s.result_sha256, t.name AS task_name, "
        "t.ccd_layout_id, t.ccd_indices_json, t.burn_frame_count, t.dark_frame_count, "
        "t.burn_cycle_seconds, t.dark_cycle_seconds, t.pre_excitation_seconds, t.excitation_condition_json "
        + _COMPLETED_EVAPORATION + " AND t.id=? ORDER BY s.repeat_index, s.id", (task_id,)
    ).fetchall()
    if not rows:
        return []
    layout = methods.layout_geometry(db, rows[0]['ccd_layout_id'])
    indices = json.loads(rows[0]['ccd_indices_json'])
    turn = json.loads(rows[0]['excitation_condition_json'] or '{}').get('capture_turn') or {}
    group = turn.get('group') if turn.get('multiple') else None
    viewer_group = f'evaporation:{group}' if group else f'task:{task_id}'
    return [{
        'id': f"sample:{row['id']}", 'sample_id': row['id'], 'task_id': task_id,
        'viewer_group': viewer_group,
        'kind': 'sample', 'format': 'acquisition', 'source_sha256': row['result_sha256'],
        'record_index': row['repeat_index'], 'measure_time': row['completed_at'],
        'sample_name': row['sample_name'], 'band_name': row['sample_name'] or row['task_name'], 'long_name': None,
        'frame_count': row['burn_frame_count'], 'points_per_ccd': layout['points_per_ccd'],
        'ccd_count': len(indices), 'ccd_indices': indices,
        'layout': layout, 'ignition': {
            'burn_count': row['burn_frame_count'], 'dark_count': row['dark_frame_count'],
            'burn_cyc': row['burn_cycle_seconds'], 'dark_cyc': row['dark_cycle_seconds'],
            'pre_burn': row['pre_excitation_seconds'],
        },
    } for row in rows]


def evaporation_bands(db, record, indices, start, end):
    def invalid():
        return AcquisitionError('prepared_acquisition_frames_invalid', '蒸发记录的原始帧缺失或校验失败', status_code=409)

    rows = db.execute(
        'SELECT * FROM acquisition_sample_bands WHERE sample_id=?', (record['sample_id'],)
    )
    bands = {row['ccd_index']: row for row in rows}
    points = record['points_per_ccd']
    ignition = record['ignition']
    if set(bands) != set(record['ccd_indices']):
        raise invalid()

    def phase_frames(band, phase, first, last):
        count = ignition[f'{phase}_count']
        if band[f'{phase}_frame_count'] != count:
            raise invalid()
        if not count:
            return []
        blob = band[f'{phase}_frames_blob']
        stride = points * 2
        if blob is None or len(blob) != count * stride or hashlib.sha256(blob).hexdigest() != band[f'{phase}_sha256']:
            raise invalid()
        return [list(struct.unpack_from(f'<{points}H', blob, index * stride)) for index in range(first, last)]

    result = []
    for index in indices:
        band = bands[index]
        if band['storage_mode'] != 'full_interval' or band['points_count'] != points:
            raise invalid()
        result.append(ImportedBand(index, points, phase_frames(band, 'burn', start - 1, end),
                                   phase_frames(band, 'dark', 0, ignition['dark_count'])))
    return result
