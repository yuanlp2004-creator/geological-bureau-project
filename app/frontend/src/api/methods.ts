/** methods requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'

export type MethodPrintSettings = {
  default_printer: string
  paper: 'A4' | 'A3' | 'Letter'
  orientation: 'portrait' | 'landscape'
  margin_top_mm: number
  margin_right_mm: number
  margin_bottom_mm: number
  margin_left_mm: number
  layout: 'standard' | 'compact'
  font_size_pt: number
  copies: number
  duplex: 'none' | 'long_edge' | 'short_edge'
  color: boolean
  preview_before_print: boolean
}

export type PrinterOption = {
  name: string
  display_name: string
  virtual: boolean
  system: boolean
  default: boolean
}

export type PrintJob = {
  id: string
  method_id: number
  method_version: number
  printer_name: string
  status: 'rendered' | 'queued' | 'completed' | 'failed'
  pdf_path: string
  output_path: string | null
  page_count: number
  field_count: number
  error_code: string | null
  error_message: string | null
  created_at: string
}

export type MethodValidationIssue = {
  field: string
  code: string
  message: string
}

export type AngleExposure = {
  angle_deg: number
  storage_mode: 'averaged' | 'full_interval'
  start_frame: number
  end_frame: number
}

export type MethodConditions = {
  ccd_layout_id: string | number
  selected_ccds: number[]
  dispersion_calibration_id: string | number
  reference_wavelength_nm: number
  actual_reference_wavelength_nm: number
  reference_width_points: number
  analysis_unit: 'ug/g' | 'mg/g' | '%'
  calculation_profile: 'legacy_2_0_2' | 'modern_v1'
  pre_excitation_seconds: number
  sampling_period_seconds: number
  frame_count: number
  dark_frame_count: number
  sample_repeats: number
  standard_repeats: number
  control_repeats: number
  standard_sample_name: string
  maximum_id_deviation: number
  rsd_enabled: boolean
  rsd_threshold: number
  calibration_threshold: number
  qc_threshold: number
  abnormal_threshold: number
  angle_exposures: AngleExposure[]
  storage_profile?: string
}

export type MethodVersion = {
  id: number
  version: number
  state: 'draft' | 'published'
  conditions: MethodConditions
  lines: SpectralLine[]
  validation_errors: MethodValidationIssue[]
  content_sha256: string
  created_at: string
}

export type StandardPoint = {
  name: string
  value: number
  active: boolean
}

export type LineDetectability = {
  detectable: boolean
  reason_code: string
  message: string
  ccd_index?: number
  ccd_label?: string
  point_index?: number
  frame_index?: number
  angle_slot?: number
  angle_deg?: number | null
}

export type SpectralLineInput = {
  line_type: 'baseline' | 'analysis' | 'internal_standard' | 'positioning'
  element: string
  wavelength_nm: number
  actual_wavelength_nm: number | null
  enabled: boolean
  critical_band: boolean
  priority: number
  background_line_id: string | null
  alignment_line_id: string | null
  internal_standard_mode: 'none' | 'background' | 'line'
  internal_standard_line_id: string | null
  scan_width_points: number
  background_offset_points: number
  peak_mode: 'max_single_point' | 'gaussian'
  peak_width_points: number
  fit_mode: 'linear' | 'quadratic' | 'cubic' | 'spline'
  coordinate_type: 'normal' | 'logarithmic'
  unit: 'ug/g' | 'mg/g' | '%'
  value_kind: 'content' | 'concentration'
  decimal_places: number
  lower_peak: number
  minimum_peak_ratio: number
  valid_range_min: number
  valid_range_max: number
  over_limit_tolerance_percent: number
  standard_points: StandardPoint[]
}

export type SpectralLine = SpectralLineInput & {
  id: string
  order: number
  reference_baseline: boolean
  detectability?: LineDetectability
}

export type SpectralLineOptions = {
  element_symbols: string[]
  line_types: Array<{ value: SpectralLineInput['line_type']; label: string }>
  internal_standard_modes: Array<{ value: SpectralLineInput['internal_standard_mode']; label: string }>
  peak_modes: Array<{ value: SpectralLineInput['peak_mode']; label: string }>
  fit_modes: Array<{ value: SpectralLineInput['fit_mode']; label: string }>
  coordinate_types: Array<{ value: SpectralLineInput['coordinate_type']; label: string }>
  limits: Record<string, number[] | number>
}

export type MethodLineCollection = {
  method_id: number
  version: number
  state: 'draft' | 'published'
  lines: SpectralLine[]
}

export type MethodRecord = {
  id: number
  name: string
  description: string
  work_type: string
  status: 'active' | 'paused' | 'deleted'
  current_version: number | null
  latest_version: number | null
  version: MethodVersion | null
  published_version: MethodVersion | null
  is_current: boolean
  created_at: string
  updated_at: string
}

export type CurrentMethodState = {
  method_id: number | null
  version: number | null
  work_type: string | null
  title: string | null
  status: string | null
  action_state: string
  actions: Record<string, boolean>
  method: MethodRecord | null
  referenced_version: MethodVersion | null
}

export type CcdLayoutOption = {
  id: number
  name: string
  frame_count: number
  ccds_per_frame: number
  points_per_ccd: number
  point_width_um: number
  allow_drift_um: number
  ccd_indices: number[]
  ccd_labels: string[]
}

export type DispersionOption = {
  id: number
  name: string
  ccd_layout_id: number
  wavelength_min: number
  wavelength_max: number
  enabled: boolean
  ccd_ranges: Array<{
    ccd_index: number
    wavelength_start_nm: number
    wavelength_end_nm: number
    safe_start_nm: number
    safe_end_nm: number
  }>
}

export type MethodOptions = {
  ccd_layouts: CcdLayoutOption[]
  dispersion_calibrations: DispersionOption[]
  storage_modes: Array<{ value: AngleExposure['storage_mode']; label: string }>
  limits: Record<string, number[] | number>
}

export const methodsApi = {
  methods: (token: string, includeDeleted = false) => request<MethodRecord[]>(`/api/v1/methods${includeDeleted ? '?include_deleted=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  methodOptions: (token: string) => request<MethodOptions>('/api/v1/methods/options', { headers: { Authorization: `Bearer ${token}` } }),
  currentMethod: (token: string) => request<CurrentMethodState>('/api/v1/methods/current', { headers: { Authorization: `Bearer ${token}` } }),
  createMethod: (token: string, payload: { name: string; description?: string; work_type?: string }) => request<MethodRecord>('/api/v1/methods', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateMethod: (token: string, methodId: number, payload: { name?: string; description?: string; work_type?: string; conditions?: MethodConditions }) => request<MethodRecord>(`/api/v1/methods/${methodId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  publishMethod: (token: string, methodId: number) => request<MethodRecord>(`/api/v1/methods/${methodId}/publish`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  copyMethod: (token: string, methodId: number, name: string) => request<MethodRecord>(`/api/v1/methods/${methodId}/copy`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ name }) }),
  openMethod: (token: string, methodId: number) => request<MethodRecord>(`/api/v1/methods/${methodId}/open`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  pauseMethod: (token: string, methodId: number) => request<MethodRecord>(`/api/v1/methods/${methodId}/pause`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  resumeMethod: (token: string, methodId: number) => request<MethodRecord>(`/api/v1/methods/${methodId}/resume`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  deleteMethod: (token: string, methodId: number) => request<{ id: number; deleted: boolean }>(`/api/v1/methods/${methodId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  spectralLineOptions: (token: string) => request<SpectralLineOptions>('/api/v1/spectral-lines/options', { headers: { Authorization: `Bearer ${token}` } }),
  methodLines: (token: string, methodId: number) => request<MethodLineCollection>(`/api/v1/methods/${methodId}/lines`, { headers: { Authorization: `Bearer ${token}` } }),
  detectLine: (token: string, methodId: number, payload: { wavelength_nm: number; actual_wavelength_nm?: number | null; scan_width_points?: number }) => request<LineDetectability>(`/api/v1/methods/${methodId}/lines/detect`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  createLine: (token: string, methodId: number, payload: SpectralLineInput) => request<MethodRecord>(`/api/v1/methods/${methodId}/lines`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateLine: (token: string, methodId: number, lineId: string, payload: SpectralLineInput) => request<MethodRecord>(`/api/v1/methods/${methodId}/lines/${lineId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  deleteLine: (token: string, methodId: number, lineId: string) => request<MethodRecord>(`/api/v1/methods/${methodId}/lines/${lineId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  reorderLines: (token: string, methodId: number, lineIds: string[]) => request<MethodRecord>(`/api/v1/methods/${methodId}/lines/reorder`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ line_ids: lineIds }) }),
  methodPrintSettings: (token: string) => request<MethodPrintSettings>('/api/v1/method-print/settings', { headers: { Authorization: `Bearer ${token}` } }),
  saveMethodPrintSettings: (token: string, settings: MethodPrintSettings) => request<MethodPrintSettings>('/api/v1/method-print/settings', { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(settings) }),
  methodPrinters: (token: string) => request<{ printers: PrinterOption[] }>('/api/v1/method-print/printers', { headers: { Authorization: `Bearer ${token}` } }),
  methodPreview: async (token: string, methodId: number, version: number | null, settings: MethodPrintSettings) => {
    const response = await requestRaw(`/api/v1/methods/${methodId}/preview`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ version, settings }) })
    return {
      html: await response.text(),
      pageCount: Number(response.headers.get('X-Page-Count') ?? 0),
      fieldCount: Number(response.headers.get('X-Field-Count') ?? 0),
      version: Number(response.headers.get('X-Method-Version') ?? version ?? 0),
    }
  },
  methodPdf: async (token: string, methodId: number, version: number | null, settings: MethodPrintSettings) => {
    const response = await requestRaw(`/api/v1/methods/${methodId}/pdf`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ version, settings }) })
    return {
      blob: await response.blob(),
      pageCount: Number(response.headers.get('X-Page-Count') ?? 0),
      fieldCount: Number(response.headers.get('X-Field-Count') ?? 0),
    }
  },
  printMethod: (token: string, methodId: number, version: number | null, settings: MethodPrintSettings, printerName: string) => request<PrintJob>(`/api/v1/methods/${methodId}/print`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ version, settings, printer_name: printerName }) }),
  methodPrintJobs: (token: string, methodId: number) => request<{ jobs: PrintJob[] }>(`/api/v1/methods/${methodId}/print-jobs`, { headers: { Authorization: `Bearer ${token}` } }),
}
