"""Daily peak-location preview and fixed-position, normalized time observations."""
from __future__ import annotations

import hashlib
import json
import struct
from .candidate import calculate_candidate
from .errors import AnalysisError
from ..acquisition import AcquisitionService, AcquisitionError
from ..spectral_lines import exposure_interval


def preview_positions(service, run_id: int, sample_position: int) -> dict:
    with service.database.read() as db:
        db.execute('BEGIN')
        run, payload, lines = service.repository._context(db, run_id)
        sample = db.execute('SELECT * FROM analysis_run_samples WHERE run_id=? AND position=?', (run_id, sample_position)).fetchone()
        if sample is None:
            raise AnalysisError('analysis_sample_not_found', '请选择运行中的样品')
        locator = service.methods.bind_geometry(db, payload['conditions'])
        prior, offsets, positions = {}, {}, []
        for index, line in enumerate(lines):
            theory = locator.locate(line['wavelength_nm'])
            stored = locator.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm']))
            if theory is None or stored is None:
                raise AnalysisError('analysis_line_outside_ccd', '校正谱线超出 CCD 范围')
            interval = exposure_interval(line, payload['conditions'])
            try:
                values = AcquisitionService.interval_band(db, sample['acquisition_sample_id'], stored.ccd_index, interval)['points']
            except AcquisitionError as exc:
                raise AnalysisError(exc.code, exc.message) from exc
            # Location is independent of concentration/internal-standard division.
            locating = {**line, 'internal_standard_mode': 'none', 'peak_mode': 'max_single_point'}
            candidate = calculate_candidate(locating, lines, sample_position, index, stored.ccd_index,
                                            stored.point, values, offsets, prior, run['calculation_profile'], None)
            prior[str(line['id'])] = candidate
            offsets[str(line['id'])] = candidate['peak_position'] - candidate['corrected_expected_position']
            wave = locator.wavelength_at(stored.ccd_index, candidate['peak_position'])
            positions.append({'line_id': line['id'], 'line_type': line['line_type'], 'element': line['element'],
                              'theoretical_wavelength_nm': line['wavelength_nm'],
                              'stored_wavelength_nm': float(line.get('actual_wavelength_nm') or line['wavelength_nm']),
                              'measured_wavelength_nm': wave, 'theoretical_point': theory.point,
                              'stored_point': stored.point, 'measured_point': candidate['peak_position'],
                              'ccd_index': stored.ccd_index, 'found': candidate['intermediates']['search']['found']})
        source_key = hashlib.sha256(json.dumps({'run_id': run_id, 'sample_position': sample_position,
            'positions': positions}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {'run_id': run_id, 'sample_position': sample_position, 'method_version_id': run['method_version_id'],
                'source_key': source_key, 'positions': positions, 'save_allowed': all(row['found'] for row in positions)}


def time_series(service, run_id: int, sample_position: int, acquisition, include_mean: bool) -> dict:
    with service.database.read() as db:
        run, _, lines = service.repository._context(db, run_id)
        sample = db.execute('SELECT * FROM analysis_run_samples WHERE run_id=? AND position=?', (run_id, sample_position)).fetchone()
        if sample is None or run['status'] != 'completed':
            raise AnalysisError('analysis_time_series_incomplete', '请选择已完成分析中的样品')
        results = {row['line_id']: dict(row) for row in db.execute('SELECT * FROM analysis_line_results WHERE run_id=? AND sample_position=?', (run_id, sample_position))}
        fixed = json.loads(run['input_snapshot_json'])['samples'][sample_position]
    snapshot = acquisition.spectrum_snapshot(sample['acquisition_sample_id'], include_frames=True)
    if snapshot['sample']['storage_mode'] != 'full_interval':
        raise AnalysisError('analysis_time_series_frames_required', '平均值样品不含全时帧，不能生成谱线时间表')
    if {band['ccd_index']: band['mean_sha256'] for band in snapshot['bands']} != {band['ccd_index']: band['mean_sha256'] for band in fixed['bands']}:
        raise AnalysisError('analysis_band_integrity_failed', '谱带与分析输入不一致')
    burn_period = float(snapshot['sample']['burn_cycle_seconds'])
    dark_period = float(snapshot['sample']['dark_cycle_seconds'])
    rows = []
    for line in (line for line in lines if line['line_type'] == 'analysis'):
        result = results.get(str(line['id']))
        if not result:
            raise AnalysisError('analysis_time_series_peak_missing', '谱线尚无固定实测峰位')
        frames = [frame for frame in snapshot['frames'] if frame['ccd_index'] == result['ccd_index'] and not frame['damaged']]
        for frame in frames:
            points = frame.get('points') or []
            blob = struct.pack(f'<{len(points)}H', *points)
            if not points or hashlib.sha256(blob).hexdigest() != frame['points_sha256']:
                raise AnalysisError('analysis_time_series_integrity_failed', '全时帧 SHA-256 校验失败')
        burns = sorted((frame for frame in frames if frame['phase'] == 'burn'), key=lambda frame: frame['frame_index'])
        darks = [frame for frame in frames if frame['phase'] == 'dark']
        if [frame['frame_index'] for frame in burns] != list(range(snapshot['sample']['burn_frame_count'])) or len(darks) != snapshot['sample']['dark_frame_count']:
            raise AnalysisError('analysis_time_series_frames_missing', '全时观察需要完整的燃烧与暗帧')
        peak = int(result['peak_position'])
        dark = sum(frame['points'][peak] for frame in darks) / (len(darks) * dark_period) if darks else 0
        values = [max(0.1, frame['points'][peak] / burn_period - dark) for frame in burns]
        for index, value in enumerate(values):
            rows.append({'sample_name': sample['sample_name'], 'line_id': line['id'], 'element': line['element'],
                         'wavelength_nm': line['wavelength_nm'], 'point': peak + 1, 'cycle': index + 1,
                         'seconds': (index + 1) * burn_period, 'intensity': value,
                         'background': result['background'] if index == 0 else None})
        if include_mean:
            rows.append({**rows[-1], 'cycle': 'mean', 'seconds': None, 'intensity': sum(values) / len(values), 'background': None})
    if not rows:
        raise AnalysisError('analysis_time_series_empty', '没有可导出的谱线')
    return {'rows': rows, 'input_sha256': run['input_sha256'], 'include_mean': include_mean,
            'burn_cycle_seconds': burn_period, 'dark_cycle_seconds': dark_period}
