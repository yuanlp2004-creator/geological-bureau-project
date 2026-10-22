import {
  type SpectralLine,
  type MethodConditions,
  type SpectralLineInput
} from '../../api'

export function methodExposureMode(conditions: MethodConditions, lines: SpectralLine[]) {
  return conditions.exposure_mode ?? (conditions.legacy_exposure_mode || lines.some(
    (line) => line.exposure_start_frame != null && line.exposure_end_frame != null
  ) ? 'line_interval' : 'simple_mean')
}

export const lineTypeLabel: Record<SpectralLineInput['line_type'], string> = {
  baseline: '参考基线',
  analysis: '分析线',
  internal_standard: '内标线',
  positioning: '定位线'
}

export const defaultLine = (): SpectralLineInput => ({
  exposure_start_frame: null,
  exposure_end_frame: null,
  line_type: 'analysis',
  element: 'Fe',
  wavelength_nm: 254,
  actual_wavelength_nm: 254,
  enabled: true,
  critical_band: false,
  priority: 0,
  background_line_id: 'reference-baseline',
  alignment_line_id: null,
  internal_standard_mode: 'none',
  internal_standard_line_id: null,
  scan_width_points: 9,
  background_offset_points: 0,
  peak_mode: 'max_single_point',
  peak_width_points: 1,
  fit_mode: 'linear',
  coordinate_type: 'normal',
  unit: 'ug/g',
  value_kind: 'content',
  decimal_places: 2,
  lower_peak: 300,
  minimum_peak_ratio: 1.5,
  valid_range_min: 0,
  valid_range_max: 1000,
  over_limit_tolerance_percent: 0,
  standard_points: [1, 2, 3, 4].map((value) => ({ name: `S${value}`, value, active: true }))
})

export function lineToInput(line: SpectralLine): SpectralLineInput {
  const { id: _id, order: _order, reference_baseline: _reference, detectability: _detectability, ...input } = line
  return structuredClone(input)
}
