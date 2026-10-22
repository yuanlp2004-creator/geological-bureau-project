"""Frame peak/integral query over immutable EDT snapshots, without resampling."""
import hashlib
import json
import struct
from ..legacy_migration import LegacyMigrationError


def evaporation_curve(service, identifier):
    with service.database.read() as db:
        source = service.source_record(db, identifier)
    if source['format'] != 'edt':
        raise LegacyMigrationError('evaporation_edt_required', '蒸发曲线只接受 EDT 数据')
    geometry, ignition = json.loads(source['layout_json']), json.loads(source['ignition_json'])
    indices, points = geometry['ccd_indices'], geometry['points_per_ccd']
    count = int(ignition.get('burn_count') or 0)
    raw = bytes(source['burn_adcs_blob'] or b'')
    if count < 1 or len(raw) != count * len(indices) * points * 2 or hashlib.sha256(raw).hexdigest() != source['burn_sha256']:
        raise LegacyMigrationError('evaporation_frames_invalid', 'EDT 原始帧长度或哈希校验失败')
    cycle = float(ignition.get('burn_cyc') or 0)
    if cycle <= 0:
        raise LegacyMigrationError('evaporation_period_missing', 'EDT 缺少有效采样周期，无法生成时间曲线')
    damaged = {int(item.get('frame_index', -1)) for item in json.loads(source['bad_frame_indices_json']) if item.get('phase') == 'burn'}
    rows = []
    for frame in range(count):
        for slot, ccd in enumerate(indices):
            values = struct.unpack_from(f'<{points}H', raw, (frame * len(indices) + slot) * points * 2)
            rows.append(dict(id=frame * len(indices) + slot, frame_index=frame, ccd_index=ccd, phase='burn',
                             virtual_time_ms=(frame + 1) * cycle * 1000, damaged=frame in damaged,
                             peak_value=max(values), integral_value=sum(values)))
    return dict(record_id=identifier, sample_name=source['sample_name'], ccd_indices=indices, frames=rows)
