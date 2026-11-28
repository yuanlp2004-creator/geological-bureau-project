"""Legacy read-only display values. Original BLOBs and analysis pipelines are never rewritten."""
import hashlib
import json
import math
import struct
from dataclasses import dataclass


class LegacyObservationError(ValueError):
    pass


def single(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


@dataclass
class ExposureFrames:
    burns: list[list[int]]
    darks: list[list[int]]
    burn_cycle: float
    dark_cycle: float

    def __post_init__(self):
        if not self.burns or not math.isfinite(self.burn_cycle) or self.burn_cycle <= 0:
            raise LegacyObservationError('缺少有效燃烧帧或燃烧周期')
        if self.darks and (not math.isfinite(self.dark_cycle) or self.dark_cycle <= 0):
            raise LegacyObservationError('缺少有效空白周期，不能扣除暗电流')

    def dark_current(self, point):
        return sum(frame[point] for frame in self.darks) / (len(self.darks) * self.dark_cycle) if self.darks else 0

    def mean(self, start, end):
        if not 1 <= start <= end <= len(self.burns):
            raise LegacyObservationError('曝光区间超出已保存燃烧帧')
        burns = self.burns[start - 1:end]
        return [single(max(0.1, sum(column) / (len(burns) * self.burn_cycle) - self.dark_current(point)))
                for point, column in enumerate(zip(*burns))]

    def intensities(self, point, start, end):
        dark = self.dark_current(point)
        return [single(max(0.1, frame[point] / self.burn_cycle - dark)) for frame in self.burns[start - 1:end]]


def legacy_exposure_source(record):
    """Verify each stored integration BLOB once, then decode CCDs on demand."""
    if json.loads(record['layout_json'] or '{}').get('endianness', 'little') != 'little':
        raise LegacyObservationError('原始积分字节序不受支持')
    ignition = json.loads(record['ignition_json'])
    count = int(ignition.get('burn_count') or 0)
    points, ccds = int(record['points_per_ccd']), int(record['ccd_count'])
    bad = json.loads(record['bad_frame_indices_json'] or '[]')

    def verified_phase(phase, size):
        blob = bytes(record[f'{phase}_adcs_blob'] or b'')
        if len(blob) != size * ccds * points * 2:
            raise LegacyObservationError('原始积分长度不符，不能按旧版口径查看')
        digest = record[f'{phase}_sha256']
        if digest and hashlib.sha256(blob).hexdigest() != digest:
            raise LegacyObservationError('原始积分哈希不符，不能按旧版口径查看')
        indices = sorted({int(item['index']) for item in bad if item.get('phase') == phase})
        if len(indices) > 1:
            raise LegacyObservationError('多个损坏积分超出旧版单ErrIndex规则')
        if any(size < 2 or not 0 <= index < size for index in indices):
            raise LegacyObservationError('损坏积分缺少可用相邻积分')
        return blob, size, indices

    def frames(ccd, phase, verified):
        blob, size, indices = verified
        rows = [list(struct.unpack_from(f'<{points}H', blob, (index * ccds + ccd) * points * 2)) for index in range(size)]
        # SpecDirect FillErrCcdCyc repairs one flagged integration from its neighbors.
        for index in indices:
            if phase == 'dark' or index in {0, size - 1}:
                rows[index] = rows[index - 1 if index == size - 1 else index + 1].copy()
            else:
                rows[index] = [(left + right) >> 1 for left, right in zip(rows[index - 1], rows[index + 1])]
        return rows

    burn_cycle = single(float(ignition.get('burn_cyc') or 0))
    dark_count = int(ignition.get('dark_count') or 0)
    dark_cycle = single(float(ignition.get('dark_cyc') or 0))
    burn = verified_phase('burn', count)
    dark = verified_phase('dark', dark_count) if dark_count else None

    def decode(ccd):
        if not 0 <= ccd < ccds:
            raise LegacyObservationError('CCD 超出原始积分布局')
        return ExposureFrames(frames(ccd, 'burn', burn), frames(ccd, 'dark', dark) if dark else [],
                              burn_cycle, dark_cycle)

    return decode


def legacy_observation_points(record, ccd, start=None, end=None):
    """uCcdBand.CalAllAvgs, ending in the original Single precision."""
    frames = legacy_exposure_source(record)(ccd)
    start, end = (1 if start is None else start), (len(frames.burns) if end is None else end)
    return frames.mean(start, end), {'start': start, 'end': end, 'count': end - start + 1}


def acquired_exposure_frames(snapshot, slot):
    """Use the arrays verified against the stored BLOB in the acquisition snapshot."""
    sample = snapshot['sample']
    band = snapshot['bands'][slot]
    frames = [item for item in snapshot['frames'] if item['ccd_index'] == band['ccd_index']
              and item.get('turn_index') == band.get('turn_index')]

    def phase_frames(phase):
        expected = int(sample[f'{phase}_frame_count'])
        selected = sorted((item for item in frames if item['phase'] == phase and not item['damaged']),
                          key=lambda item: item['frame_index'])
        if [item['frame_index'] for item in selected] != list(range(expected)):
            raise LegacyObservationError('采集记录缺少完整的燃烧或空白帧')
        rows = []
        for frame in selected:
            points = frame.get('points') or []
            if len(points) != band['points_count']:
                raise LegacyObservationError('原始积分形状校验失败')
            rows.append(points)
        return rows

    return ExposureFrames(phase_frames('burn'), phase_frames('dark'),
                          float(sample['burn_cycle_seconds']), float(sample['dark_cycle_seconds']))
