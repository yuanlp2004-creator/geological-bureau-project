"""Read-only peak positions shared by the spectrum viewer and full-time output."""
from functools import cache
import math


def legacy_location(layout, wavelength):
    coefficients = layout.get('ws_cof') or []
    if len(coefficients) < 3:
        return None
    a, b, c = coefficients[:3]
    step = (a * wavelength + b) * wavelength + c
    count = layout['points_per_ccd']
    gaps = layout.get('gap_points') or []
    for slot, index in enumerate(layout.get('ccd_indices') or range(layout['ccd_count'])):
        point = round(step - (index * count + sum(gaps[:index]))) if math.isfinite(step) else -1
        if 0 <= point < count:
            return slot, point
    return None


def find_peak(values, center, line):
    width = min(len(values), int(line.get('scan_width_points', 9)))
    if width < 3 or not 0 <= center < len(values):
        return None
    left = max(0, min(center - width // 2, len(values) - width))
    right = left + width - 1
    candidates = [i for i in range(max(left, 1), min(right + 1, len(values) - 1))
                  if values[i] > values[i - 1] and values[i] > values[i + 1]]
    if not candidates:
        return None
    peak = max(candidates, key=values.__getitem__)
    if line['line_type'] not in {'baseline', 'positioning'} and not (
        values[peak] > float(line.get('lower_peak', 300))
        and values[peak] > min(values[left:right + 1]) * float(line.get('minimum_peak_ratio', 1.5))
    ):
        return None
    return peak


def locate_peaks(lines, locate, values_for, interval_for=lambda line: None, group_for_slot=lambda slot: None):
    """Resolve reference and alignment offsets in detector points."""
    values_for = cache(values_for)
    offsets = {}
    reference_offsets = {}
    for line in lines:
        identifier = str(line['id'])
        target = locate(line)
        peak = None
        if target is not None:
            slot, original = target
            group = group_for_slot(slot)
            correction = reference_offsets.get(group, 0) + offsets.get((group, str(line.get('alignment_line_id'))), 0)
            expected = original + correction
            peak = find_peak(values_for(slot, interval_for(line)), expected, line)
            if peak is not None:
                offsets[(group, identifier)] = peak - expected
                if line.get('reference_baseline'):
                    reference_offsets[group] = peak - expected
        yield line, target, peak


def acquired_locations(snapshot, locator):
    bands = snapshot['bands']
    slots = {(band.get('turn_index'), band['ccd_index']): slot for slot, band in enumerate(bands)}
    plan = (snapshot.get('turns') or {}).get('plan')
    if plan:
        positions = {line['id']: (slots.get((turn['turn_index'], line['ccd_index'])), round(line['point_index']))
                     for turn in plan for line in turn['lines']}
        return {identifier: position for identifier, position in positions.items() if position[0] is not None}
    return {line_id: (slots[(None, position.ccd_index)], round(position.point))
            for line_id, position in locator.items() if position is not None and (None, position.ccd_index) in slots}
