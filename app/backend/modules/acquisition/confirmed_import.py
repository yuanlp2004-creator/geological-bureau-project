"""Acquisition-owned storage for an already confirmed, versioned spectrum.

The caller supplies detached evidence in its transaction. No device is started,
and mean values are preserved byte for byte rather than recalculated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import sqlite3
import struct
from typing import Any

from ...db import utc_now
from ..sample_queues import normalize_name


@dataclass(frozen=True)
class ConfirmedSpectrum:
    source_record_id: str
    source_sha256: str
    layout_id: int
    device_profile_id: int
    method_id: int
    method_version: int
    method_version_id: int
    sample_name: str
    sample_kind: str
    name_length: int
    sampling_period_seconds: float
    bands: list[dict[str, Any]]
    evidence: dict[str, Any]
    captured_at: str


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _sha(value: bytes):
    return hashlib.sha256(value).hexdigest()


def find_confirmed_source(db: sqlite3.Connection, source_record_id: str) -> dict | None:
    row = db.execute(
        'SELECT t.id AS acquisition_task_id,s.id AS acquisition_sample_id,s.sample_name,t.simulator_json '
        'FROM acquisition_tasks t JOIN acquisition_samples s ON s.task_id=t.id '
        "WHERE json_extract(t.simulator_json,'$.source_record_id')=? ORDER BY t.id LIMIT 1",
        (source_record_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result['source_sha256'] = json.loads(result.pop('simulator_json'))['source_sha256']
    return result


def import_confirmed_spectrum(db: sqlite3.Connection, record: ConfirmedSpectrum, actor: int | None) -> dict:
    existing = find_confirmed_source(db, record.source_record_id)
    if existing:
        if existing['source_sha256'] != record.source_sha256:
            raise ValueError('已保存来源的哈希发生变化')
        return {**existing, 'already_saved': True}
    name, _ = normalize_name(record.sample_name, record.name_length)
    if not name or record.sample_kind not in {'test', 'standard'}:
        raise ValueError('正式样号或样品类型无效')
    indices = [band['ccd_index'] for band in record.bands]
    if not indices or len(indices) != len(set(indices)):
        raise ValueError('已确认谱带的 CCD 必须唯一且完整')
    for band in record.bands:
        count = band['points_count']
        mean = band['mean_blob']
        if len(mean) != count * 4 or _sha(mean) != band['mean_sha256']:
            raise ValueError('已确认均值谱带校验失败')
        if not all(math.isfinite(x) for x in struct.unpack(f'<{count}f', mean)):
            raise ValueError('均值谱带包含非有限数值')
        if band['storage_mode'] not in {'averaged', 'full_interval'}:
            raise ValueError('保存模式无效')
        if [f['frame_index'] for f in band['frames']] != list(range(band['end_frame'])):
            raise ValueError('原始帧序号不完整')
        for frame in band['frames']:
            if len(frame['blob']) != count * 2 or _sha(frame['blob']) != frame['sha256']:
                raise ValueError('原始帧校验失败')
    now = utc_now()
    mode = 'full_interval' if any(b['storage_mode'] == 'full_interval' for b in record.bands) else 'averaged'
    metadata = {**record.evidence, 'source_kind': 'confirmed_hardware_turn',
                'source_record_id': record.source_record_id, 'source_sha256': record.source_sha256,
                'name_length': record.name_length,
                'exposure_by_ccd': {str(b['ccd_index']): {key: b[key] for key in ('start_frame','end_frame','storage_mode')}
                                    for b in record.bands}}
    columns = ('task_kind,name,status,device_profile_id,ccd_layout_id,method_version_id,method_id,method_version,'
               'sample_name,sample_kind,naming_mode,storage_mode,repeat_count,current_repeat_index,'
               'completed_repeats,burn_frame_count,dark_frame_count,countdown_seconds,countdown_remaining,'
               'pre_excitation_seconds,sampling_period_seconds,burn_cycle_seconds,dark_cycle_seconds,ccd_indices_json,'
               'excitation_condition_json,evaporation_condition_json,simulator_json,created_by,created_at,updated_at,completed_at')
    values = ('sample', f'转角结果 · {name}', 'completed', record.device_profile_id, record.layout_id,
              record.method_version_id, record.method_id, record.method_version, name, record.sample_kind,
              'pre_recorded', mode, 1, 0, 1, max(b['end_frame'] for b in record.bands), 0, 0, 0,
              0, record.sampling_period_seconds, 1, 1, _json(indices), '{}', '{}', _json(metadata), actor, now, now,
              record.captured_at)
    task_id = db.execute(f"INSERT INTO acquisition_tasks({columns}) VALUES ({','.join('?' for _ in values)})", values).lastrowid
    sample_id = db.execute(
        'INSERT INTO acquisition_samples(task_id,repeat_index,sample_name_original,sample_name,sample_kind,storage_mode,'
        "status,finalized,created_at,completed_at,updated_at) VALUES (?,0,?,?,?,?,'completed',1,?,?,?)",
        (task_id, name, name, record.sample_kind, mode, now, record.captured_at, now)).lastrowid
    hashes = []
    for band in record.bands:
        selected = band['frames'][band['start_frame']-1:band['end_frame']]
        raw = b''.join(f['blob'] for f in selected) if band['storage_mode'] == 'full_interval' else None
        digest = _sha(raw) if raw is not None else None
        hashes.append([band['ccd_index'], band['mean_sha256'], digest])
        db.execute('INSERT INTO acquisition_sample_bands(sample_id,ccd_index,storage_mode,points_count,burn_frame_count,'
                   'dark_frame_count,mean_blob,mean_sha256,burn_frames_blob,burn_sha256,created_at) VALUES (?,?,?,?,?,0,?,?,?,?,?)',
                   (sample_id, band['ccd_index'], band['storage_mode'], band['points_count'], len(selected),
                    band['mean_blob'], band['mean_sha256'], raw, digest, now))
        # Retain original frame indices, including interval prefixes; per-line analysis consumes these indices.
        for frame in band['frames']:
            points = struct.unpack(f"<{band['points_count']}H", frame['blob'])
            db.execute('INSERT INTO acquisition_frames(task_id,sample_id,repeat_index,phase,frame_index,ccd_index,'
                       'points_blob,points_count,points_sha256,raw_transfer_sha256,raw_byte_length,headers_json,'
                       'virtual_time_ms,peak_value,peak_position,integral_value,damaged,captured_at) '
                       "VALUES (?,?,0,'burn',?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
                       (task_id, sample_id, frame['frame_index'], band['ccd_index'], frame['blob'], band['points_count'],
                        frame['sha256'], record.source_sha256, len(frame['blob']), _json(frame['evidence']),
                        frame['frame_index'] * record.sampling_period_seconds * 1000, max(points), points.index(max(points)),
                        float(sum(points)), record.captured_at))
    result_hash = _sha(_json({'source': record.source_sha256, 'bands': hashes}).encode('utf-8'))
    db.execute('UPDATE acquisition_tasks SET result_sha256=? WHERE id=?', (result_hash, task_id))
    db.execute('UPDATE acquisition_samples SET result_sha256=? WHERE id=?', (result_hash, sample_id))
    return {'acquisition_task_id': task_id, 'acquisition_sample_id': sample_id, 'sample_name': name,
            'source_sha256': record.source_sha256, 'already_saved': False}
