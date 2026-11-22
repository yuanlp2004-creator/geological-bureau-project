"""Resolve physical sample turns from a published method, never transport groups."""
import math

from .errors import MethodDomainError


def configured_angles(conditions):
    exposures = conditions.get('angle_exposures')
    if not isinstance(exposures, list) or not exposures:
        raise MethodDomainError('sample_turns_missing', '方法没有有效的工作转角')
    angles = set()
    for source_index, exposure in enumerate(exposures):
        if not isinstance(exposure, dict):
            raise MethodDomainError('sample_turn_invalid', '方法转角配置不完整')
        angle = exposure.get('angle_deg')
        if isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle) or not 0 <= angle <= 360 or angle in angles:
            raise MethodDomainError('sample_turn_invalid', '方法工作转角无效或重复')
        angles.add(angle)
        yield {**exposure, 'angle_deg': float(angle), 'source_index': source_index}


def sample_plan(methods, connection, snapshot):
    from ..spectral_lines import canonical_lines, exposure_interval

    conditions = snapshot.payload.get('conditions', {})
    exposures = list(configured_angles(conditions))
    selected = conditions.get('selected_ccds', [])
    multiple = len(exposures) > 1
    turns = []
    for exposure in exposures:
        angle = exposure['angle_deg']
        # Multiple physical positions must each declare their own installed CCDs
        # and calibrated wavelength geometry. A transport frame is not an angle.
        indices = exposure.get('ccd_indices') if multiple else selected
        calibration = exposure.get('dispersion_calibration_id') if multiple else conditions.get('dispersion_calibration_id')
        if not indices or calibration is None:
            raise MethodDomainError('sample_turn_mapping_missing',
                '多转角方法缺少转角与CCD、色散标定的明确关联，请先核实方法',
                details={'angle_deg': angle})
        if (not isinstance(indices, list) or any(isinstance(index, bool) or not isinstance(index, int) for index in indices)
                or len(set(indices)) != len(indices) or not set(indices) <= set(selected)):
            raise MethodDomainError('sample_turn_ccds_invalid', '转角关联的CCD不属于方法已选CCD', details={'angle_deg': angle})
        if isinstance(calibration, bool) or not isinstance(calibration, (int, str)) or not str(calibration).strip():
            raise MethodDomainError('sample_turn_calibration_invalid', '转角没有有效的色散标定引用')
        if 'line_ids' in exposure and (not isinstance(exposure['line_ids'], list) or not exposure['line_ids']
                or any(not isinstance(value, str) or not value for value in exposure['line_ids'])):
            raise MethodDomainError('sample_turn_lines_invalid', '转角的谱线关联无效')
        geometry_conditions = {**conditions, 'dispersion_calibration_id': calibration}
        locator = methods.bind_geometry(connection, geometry_conditions)
        geometry = locator.prepared_layout()
        coefficients = geometry['ws_cof']
        if len(coefficients) < 3 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in coefficients[:3]) or coefficients[:2] == [0, 0]:
            raise MethodDomainError('sample_turn_calibration_invalid', '转角色散标定无效，不能推测点位')
        if not set(indices) <= set(geometry['ccd_indices']):
            raise MethodDomainError('sample_turn_ccds_invalid', '转角关联的CCD不属于实际布局')
        turns.append({**exposure,
                      'ccd_indices': list(indices), 'dispersion_calibration_id': calibration,
                      'geometry': geometry, 'lines': [], 'key_band': False, 'priority': 0})
    for line in canonical_lines(snapshot.payload.get('lines'), conditions):
        if not line.get('enabled'):
            continue
        matches = []
        for turn in turns:
            if turn.get('line_ids') is not None and str(line['id']) not in {str(value) for value in turn['line_ids']}:
                continue
            locator = methods.bind_geometry(connection, {**conditions, 'dispersion_calibration_id': turn['dispersion_calibration_id']})
            detected = locator.locate(float(line.get('actual_wavelength_nm') or line['wavelength_nm']))
            if detected is not None and locator.calibrated(float(line.get('actual_wavelength_nm') or line['wavelength_nm'])) and detected.ccd_index in turn['ccd_indices'] and detected.within_margin:
                matches.append((turn, detected))
        if len(matches) != 1:
            raise MethodDomainError('sample_line_turn_ambiguous' if matches else 'sample_line_turn_missing',
                '谱线对应多个转角，关联不明确' if matches else '谱线没有有效的转角、CCD及标定关联',
                details={'line_id': line['id'], 'wavelength_nm': line['wavelength_nm']})
        turn, detected = matches[0]
        turn['lines'].append({'id': str(line['id']), 'element': line['element'],
            'wavelength_nm': line['wavelength_nm'], 'actual_wavelength_nm': line.get('actual_wavelength_nm') or line['wavelength_nm'],
            'ccd_index': detected.ccd_index, 'point_index': detected.point,
            'exposure_interval': exposure_interval(line, conditions)})
        if line.get('critical_band'):
            turn['key_band'] = True
            turn['priority'] = max(turn['priority'], int(line.get('priority', 0)))
    if not any(turn['lines'] for turn in turns):
        raise MethodDomainError('sample_lines_missing', '方法没有本次需要采集的有效谱线')
    for turn in turns:
        turn['wavelength_nm'] = min((line['wavelength_nm'] for line in turn['lines']), default=None)
        if any(line['exposure_interval'] for line in turn['lines']):
            turn['storage_mode'] = 'full_interval'
    turns.sort(key=lambda turn: (not turn['key_band'], -turn['priority'] if turn['key_band'] else 0,
                               turn['wavelength_nm'] if turn['wavelength_nm'] is not None else math.inf, turn['angle_deg']))
    for index, turn in enumerate(turns):
        turn['turn_index'] = index
    return {'method_version_id': snapshot.version_id, 'method_content_sha256': snapshot.content_sha256,
            'multiple': multiple, 'plan': turns}
