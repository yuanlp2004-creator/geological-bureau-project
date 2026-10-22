"""Restore detached legacy method semantics from retained import evidence."""
from copy import deepcopy
from typing import Any
from .units import UNIT_POWERS, unit_scale


def legacy_payload(payload: dict[str, Any], connection=None, method_id: int | None = None) -> dict[str, Any]:
    result = deepcopy(payload)
    provenance = result.get('legacy_migration', {})
    evidence = provenance.get('evidence', {})
    if not evidence and connection is not None and method_id is not None and provenance.get('source_sha256'):
        from ..legacy_migration import LegacyMigrationService
        evidence = LegacyMigrationService.method_evidence(connection, method_id, provenance['source_sha256'])
        provenance['evidence'] = evidence
    if evidence:
        provenance.setdefault('modified_at', evidence.get('primary', {}).get('ModifyTime'))
    conditions = result.get('conditions', {})
    if conditions.get('calculation_profile') != 'legacy_2_0_2' or not evidence:
        return result
    def value(item, default=0):
        return item.get('value', default) if isinstance(item, dict) else item if item is not None else default
    primary = evidence.get('primary', {})
    count = int(conditions.get('frame_count', 20))
    conditions.setdefault('legacy_exposure_mode', bool(value(primary.get('ExpSegMode'))))
    conditions.setdefault('legacy_exposure_interval', [int(value(primary.get('RefSegL'), 1)) or 1,
                                                      int(value(primary.get('RefSegR'), count)) or count])
    by_id = {line.get('normalized_id'): line for line in evidence.get('lines', [])}
    for line in result.get('lines', []):
        source = by_id.get(line.get('id'), {})
        if conditions.get('legacy_exposure_mode') and 1 <= int(source.get('exposure_start_frame') or 0) < int(source.get('exposure_end_frame') or 0) <= count:
            line.setdefault('exposure_start_frame', source['exposure_start_frame'])
            line.setdefault('exposure_end_frame', source['exposure_end_frame'])
        standards = {f"S{record['index'] + 1}": record for record in source.get('standards_blob', {}).get('records', [])}
        for point in line.get('standard_points', []):
            old = standards.get(point.get('name'))
            source_unit = str(primary.get('MtdUnit') or line.get('unit', ''))
            target_unit = line.get('unit', '')
            compatible = source_unit == target_unit or source_unit in UNIT_POWERS and target_unit in UNIT_POWERS
            if old and compatible and abs(float(point['value']) * unit_scale(target_unit) - float(old['content']) * unit_scale(source_unit)) < 1e-7:
                point.setdefault('original_intensity', old['raw_black'])
                point.setdefault('adjusted_intensity', old['current_black'])
                point.setdefault('intensity_valid', bool(old['valid']))
    return result
