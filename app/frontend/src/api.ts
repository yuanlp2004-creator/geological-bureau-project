export type EventSeverity = 'debug' | 'info' | 'success' | 'warning' | 'error'

export type RuntimeEvent = {
  id: number
  category: string
  severity: EventSeverity
  message: string
  details: Record<string, unknown> | null
  correlation_id: string | null
  created_at: string
}

export type Settings = {
  directories: Record<string, string>
  logging: { level: string; max_bytes: number; retention_days: number }
  display: { theme: string; density: string; show_status_bar: boolean }
  printing: MethodPrintSettings
  time: { timezone: string; format: string }
}

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

export type Capability = {
  key: string
  version: string
  title: string
  api_prefix: string
  route: string
  enabled: boolean
  permissions: string[]
  audit_actions: string[]
}

export type About = {
  name: string
  display_name: string
  version: string
  api_version: string
  stage: string
  description: string
  runtime: string
  database: string
  modules: Array<Record<string, unknown>>
}

export type Diagnostics = {
  service: string
  database_path: string
  runtime_log_path: string
  schema_version: number
  sqlite_integrity: string
  journal_mode: string
  foreign_keys: number
  event_count: number
  manifest_valid: boolean
}

export type LegacyMigrationDiagnostic = {
  available: boolean
  code: string
  message: string
  reader: string | null
  provider: string
  process_bits: number | null
  attempts: Array<Record<string, unknown>>
}

export type LegacyMigrationIssue = {
  level: 'warning' | 'error' | 'info'
  code: string
  field?: string
  message: string
}

export type LegacyMigrationRun = {
  id: string
  fingerprint: string
  status: 'staged' | 'committed' | 'failed'
  source_files: Record<string, { path: string; name: string; size: number; mtime_ns: number; sha256: string }>
  reader: LegacyMigrationDiagnostic
  report: {
    phase: string
    counts: { methods: number; spectral_lines: number; dispersion_curves: number; users_ignored: number }
    checks: Record<string, boolean>
    issues: LegacyMigrationIssue[]
    atomic_scope: string
    already_committed: boolean
    imported?: Record<string, unknown>
  }
  staging?: {
    counts: { methods: number; spectral_lines: number; dispersion_curves: number; users_ignored: number }
    checks: Record<string, boolean>
    issues: LegacyMigrationIssue[]
    configuration: {
      cfg: { encoding: string; sections: Record<string, Record<string, string>>; normalized: Record<string, unknown> }
      opt: { encoding: string; sections: Record<string, Record<string, string>>; normalized: Record<string, unknown> }
    }
  }
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
  committed_at: string | null
  already_committed?: boolean
}

export type SpectrumMigrationDiagnostic = LegacyMigrationDiagnostic & {
  formats: string[]
  layout_tables: string[]
  read_only: boolean
  parser_version: string
}

export type SpectrumMigrationRun = {
  id: string
  fingerprint: string
  format: 'cdt' | 'cmt' | 'edt' | 'wdt'
  status: 'staged' | 'committed' | 'failed'
  source_file: { path: string; name: string; size: number; mtime_ns: number; sha256: string }
  reader: Record<string, unknown>
  report: {
    phase: string
    format: string
    record_count: number
    table_counts: Record<string, number>
    checks: Record<string, boolean>
    issues: Array<{ level: string; code: string; message: string }>
    atomic_scope: string
    already_committed: boolean
    imported?: { spectrum_bands: number }
  }
  staging?: {
    format: string
    record_count: number
    table_counts: Record<string, number>
    layout: { frame_count: number; ccds_per_frame: number; points_per_ccd: number; ccd_count: number; ccd_indices: number[]; endianness: string }
    ignition: { present: boolean; pre_burn: number | null; burn_cyc: number | null; dark_cyc: number | null; burn_count: number; dark_count: number }
    records: Array<{ layout: Record<string, unknown>; sampled_values: Record<string, unknown>; bad_frame_indices: Array<Record<string, unknown>>; [key: string]: unknown }>
    checks: Record<string, boolean>
    issues: Array<{ level: string; code: string; message: string }>
    parser_version: string
  }
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
  committed_at: string | null
  already_committed?: boolean
}

export type ResultMigrationDiagnostic = {
  available: boolean
  code: string
  message: string
  formats: string[]
  headers: Record<string, string | string[]>
  read_only: boolean
  parser_version: string
  short_strings: Record<string, number>
}

export type ResultMigrationRun = {
  id: string
  fingerprint: string
  format: 'dat' | 'pdt'
  status: 'staged' | 'committed' | 'failed'
  source_file: { path: string; name: string; size: number; mtime_ns: number; sha256: string }
  parser: { parser_version: string; header: number; endianness: string; encoding: string }
  report: {
    phase: string
    format: string
    counts: { files: number; samples: number; lines: number; bands: number; matrix_values: number }
    checks: Record<string, boolean | null>
    issues: Array<{ level: string; code: string; message: string }>
    method_match_status: string
    sampled_values: Array<Record<string, unknown>>
    imported?: { result_matrices: number }
  }
  staging?: {
    records: Array<{
      header: number
      format: string
      method_legacy_id: number | null
      method_target_id: number | null
      method_match_status: string
      measure_time: string
      sample_count: number
      line_count: number
      band_count: number
      sample_names: string[]
      sample_reps: number[]
      sample_rows: Array<Record<string, unknown>>
      lines: Array<Record<string, unknown>>
      exposure_segments: Array<Record<string, number>>
      matrix_kind: string
      matrix_order: string
      matrix_sha256: string
      matrix_samples: Array<Record<string, unknown>>
      endianness: string
      encoding: string
    }>
    record_count: number
    parser_version: string
    issues: Array<{ level: string; code: string; message: string }>
  }
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
  committed_at: string | null
  already_committed?: boolean
}

export type SpectrumRecordSummary = {
  id: string
  kind: 'raw' | 'result'
  source_sha256: string
  record_index: number
  format: string
  sample_name: string | null
  sample_names?: string[]
  band_name: string | null
  measure_time: string | null
  angle_deg?: number | null
  frame_count?: number
  ccd_count?: number
  points_per_ccd?: number
  line_count?: number
  band_count?: number
  sample_count?: number
  matrix_kind?: string | null
  available?: Record<string, boolean>
}

export type SpectrumPoint = {
  point_index: number
  step?: number
  wavelength_nm?: number | null
  x?: number
  value?: number
  adc?: number
  peak?: number
  back?: number
  sample_index?: number | null
  repeat_index?: number | null
  sample_name?: string | null
}

export type SpectrumRecord = {
  id: string
  kind: 'raw' | 'result'
  format: string
  source_sha256: string
  record_index: number
  sample_name?: string | null
  sample_names?: string[]
  sample_reps?: number[]
  band_name?: string | null
  measure_time: string | null
  reference_step?: number | null
  angle_deg?: number | null
  exposure_segment?: { start: number; end: number; count: number } | null
  layout?: Record<string, unknown>
  ignition?: Record<string, unknown>
  bad_frame_indices?: Array<Record<string, unknown>>
  ccd?: { position: number; index: number; points: SpectrumPoint[] }
  frame_detail?: { phase: string; index: number; frame_count: number; ccd: { position: number; index: number; points: SpectrumPoint[] } } | null
  line_count?: number
  band_count?: number
  matrix_kind?: string
  matrix_order?: string
  exposure_segments?: Array<Record<string, number>>
  sample_rows?: Array<Record<string, unknown>>
  line?: Record<string, unknown> & { points: SpectrumPoint[] }
}

export type SampleQueueItem = {
  id: number
  queue_id: number
  position: number
  source_name: string
  pre_name: string
  post_name: string | null
  repeats: number
  expanded_bands: number
  spectrum_hash: string | null
  created_at: string
  updated_at: string
}

export type SampleQueue = {
  id: number
  name: string
  status: 'draft' | 'ready' | 'completed'
  record_count: number
  expanded_bands: number
  items: SampleQueueItem[]
  created_at: string
  updated_at: string
}

async function requestRaw(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    const body = await response.text()
    try {
      const parsed = JSON.parse(body) as { detail?: string | { message?: string } }
      const message = typeof parsed.detail === 'string' ? parsed.detail : parsed.detail?.message
      throw new Error(message || body || `${response.status} ${response.statusText}`)
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(body || `${response.status} ${response.statusText}`)
      throw error
    }
  }
  return response
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await requestRaw(path, init)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export type AuthUser = {
  id: number
  username: string
  roles: string[]
  permissions: string[]
  expires_at?: string
}

export type ManagedUser = {
  id: number
  username: string
  enabled: boolean
  created_at: string
  updated_at: string
  role_ids: number[]
  roles: string[]
}

export type ManagedRole = {
  id: number
  name: string
  description: string
  permission_keys: string[]
  built_in: boolean
}

export type AuditEvent = {
  id: number
  actor_user_id: number | null
  action: string
  target_type: string
  target_id: number | null
  details_json: string
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
  line_type: 'baseline' | 'analysis' | 'internal_standard' | 'alignment'
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
  peak_mode: 'maximum' | 'gaussian'
  peak_width_points: number
  fit_mode: 'linear' | 'quadratic' | 'cubic' | 'spline'
  coordinate_type: 'linear' | 'logarithmic'
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

export const api = {
  authStatus: () => request<{ bootstrapped: boolean }>('/api/v1/auth/status'),
  bootstrap: (username: string, password: string) => request<{ created: boolean }>('/api/v1/auth/bootstrap', { method: 'POST', body: JSON.stringify({ username, password }) }),
  login: (username: string, password: string) => request<{ access_token: string; user: AuthUser }>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: (token: string) => request<AuthUser>('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } }),
  logout: (token: string) => request<void>('/api/v1/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  users: (token: string) => request<ManagedUser[]>('/api/v1/users', { headers: { Authorization: `Bearer ${token}` } }),
  createUser: (token: string, payload: { username: string; password: string; role_ids: number[] }) => request<ManagedUser>('/api/v1/users', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateUser: (token: string, userId: number, payload: { enabled?: boolean; role_ids?: number[] }) => request<Record<string, unknown>>(`/api/v1/users/${userId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  roles: (token: string) => request<ManagedRole[]>('/api/v1/roles', { headers: { Authorization: `Bearer ${token}` } }),
  createRole: (token: string, payload: { name: string; description: string; permission_keys: string[] }) => request<ManagedRole>('/api/v1/roles', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateRole: (token: string, roleId: number, payload: { description?: string; permission_keys?: string[] }) => request<Record<string, unknown>>(`/api/v1/roles/${roleId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  audit: (token: string) => request<AuditEvent[]>('/api/v1/audit', { headers: { Authorization: `Bearer ${token}` } }),
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
  legacyMigrationDiagnostics: (token: string) => request<LegacyMigrationDiagnostic>('/api/v1/legacy-migration/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  legacyMigrationRuns: (token: string) => request<{ runs: LegacyMigrationRun[] }>('/api/v1/legacy-migration/runs', { headers: { Authorization: `Bearer ${token}` } }),
  stageLegacyMigration: (token: string, payload: { mtd_path: string; cfg_path: string; opt_path: string }) => request<LegacyMigrationRun>('/api/v1/legacy-migration/stage', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  commitLegacyMigration: (token: string, runId: string) => request<LegacyMigrationRun>('/api/v1/legacy-migration/commit', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ run_id: runId }) }),
  legacyMigrationRun: (token: string, runId: string) => request<LegacyMigrationRun>(`/api/v1/legacy-migration/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
  spectrumMigrationDiagnostics: (token: string) => request<SpectrumMigrationDiagnostic>('/api/v1/spectrum-migration/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  spectrumMigrationRuns: (token: string) => request<{ runs: SpectrumMigrationRun[] }>('/api/v1/spectrum-migration/runs', { headers: { Authorization: `Bearer ${token}` } }),
  stageSpectrumMigration: (token: string, path: string) => request<SpectrumMigrationRun>('/api/v1/spectrum-migration/stage', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ path }) }),
  commitSpectrumMigration: (token: string, runId: string) => request<SpectrumMigrationRun>('/api/v1/spectrum-migration/commit', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ run_id: runId }) }),
  spectrumMigrationRun: (token: string, runId: string) => request<SpectrumMigrationRun>(`/api/v1/spectrum-migration/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
  resultMigrationDiagnostics: (token: string) => request<ResultMigrationDiagnostic>('/api/v1/result-migration/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  resultMigrationRuns: (token: string) => request<{ runs: ResultMigrationRun[] }>('/api/v1/result-migration/runs', { headers: { Authorization: `Bearer ${token}` } }),
  stageResultMigration: (token: string, path: string) => request<ResultMigrationRun>('/api/v1/result-migration/stage', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ path }) }),
  commitResultMigration: (token: string, runId: string) => request<ResultMigrationRun>('/api/v1/result-migration/commit', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ run_id: runId }) }),
  resultMigrationRun: (token: string, runId: string) => request<ResultMigrationRun>(`/api/v1/result-migration/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
  spectrumRecords: (token: string, kind = 'all', angleDeg?: number) => {
    const query = new URLSearchParams({ kind })
    if (angleDeg !== undefined) query.set('angle_deg', String(angleDeg))
    return request<SpectrumRecordSummary[]>(`/api/v1/spectra/records?${query}`, { headers: { Authorization: `Bearer ${token}` } })
  },
  spectrum: (token: string, recordId: string, params: { ccd?: number; line?: number; detail?: 'summary' | 'frame'; phase?: 'burn' | 'dark'; frame?: number; exposureStart?: number; exposureEnd?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.ccd !== undefined) query.set('ccd', String(params.ccd))
    if (params.line !== undefined) query.set('line', String(params.line))
    if (params.detail) query.set('detail', params.detail)
    if (params.phase) query.set('phase', params.phase)
    if (params.frame !== undefined) query.set('frame', String(params.frame))
    if (params.exposureStart !== undefined) query.set('exposure_start', String(params.exposureStart))
    if (params.exposureEnd !== undefined) query.set('exposure_end', String(params.exposureEnd))
    return request<SpectrumRecord>(`/api/v1/spectra/${encodeURIComponent(recordId)}${query.size ? `?${query}` : ''}`, { headers: { Authorization: `Bearer ${token}` } })
  },
  exportSpectrum: async (token: string, recordId: string, params: { ccd: number; line: number; detail?: 'summary' | 'frame'; phase?: 'burn' | 'dark'; frame?: number; exposureStart?: number; exposureEnd?: number; xMin: number; xMax: number; referenceShift: number }) => {
    const query = new URLSearchParams({ ccd: String(params.ccd), line: String(params.line), x_min: String(params.xMin), x_max: String(params.xMax), reference_shift: String(params.referenceShift) })
    if (params.detail) query.set('detail', params.detail)
    if (params.phase) query.set('phase', params.phase)
    if (params.frame !== undefined) query.set('frame', String(params.frame))
    if (params.exposureStart !== undefined) query.set('exposure_start', String(params.exposureStart))
    if (params.exposureEnd !== undefined) query.set('exposure_end', String(params.exposureEnd))
    const response = await requestRaw(`/api/v1/spectra/${encodeURIComponent(recordId)}/export?${query}`, { headers: { Authorization: `Bearer ${token}` } })
    return { blob: await response.blob(), filename: response.headers.get('Content-Disposition') ?? `spectrum-${recordId}.csv` }
  },
  auditSpectrumPrint: (token: string, recordId: string, payload: { visible_x_min: number; visible_x_max: number; visible_y_min: number; visible_y_max: number; ccd: number; line: number; mode: 'mean' | 'peak' | 'back' | 'value' | 'frame'; reference_shift: number; selected_record_ids: string[] }) =>
    request<{ status: string }>(`/api/v1/spectra/${encodeURIComponent(recordId)}/print`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  printSpectrumPdf: async (token: string, recordId: string, payload: { visible_x_min: number; visible_x_max: number; visible_y_min: number; visible_y_max: number; ccd: number; line: number; mode: 'mean' | 'peak' | 'back' | 'value' | 'frame'; reference_shift: number; selected_record_ids: string[]; priority_record_id?: string; frame_phase: 'burn' | 'dark'; frame_index: number; exposure_start?: number; exposure_end?: number }) => {
    const response = await requestRaw(`/api/v1/spectra/${encodeURIComponent(recordId)}/print-pdf`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) })
    return { blob: await response.blob(), filename: response.headers.get('Content-Disposition') ?? `spectrum-${recordId.replace(':', '-')}.pdf`, curveCount: Number(response.headers.get('X-Curve-Count') ?? 0), pointCount: Number(response.headers.get('X-Visible-Point-Count') ?? 0) }
  },
  sampleQueues: (token: string) => request<SampleQueue[]>('/api/v1/sample-queues', { headers: { Authorization: `Bearer ${token}` } }),
  createSampleQueue: (token: string, payload: { name: string; items: Array<{ pre_name: string; repeats: number }> }) => request<SampleQueue>('/api/v1/sample-queues', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateSampleQueue: (token: string, queueId: number, items: Array<{ pre_name: string; repeats: number }>) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ items }) }),
  renameSampleItem: (token: string, queueId: number, itemId: number, postName: string) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}/items/${itemId}/rename`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ post_name: postName }) }),
  deleteSampleItem: (token: string, queueId: number, itemId: number) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}/items/${itemId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  clearSampleQueue: (token: string, queueId: number) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}/clear`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  importSampleQueue: (token: string, filename: string, content: string, queueName?: string) => request<SampleQueue & { source_sha256: string }>('/api/v1/sample-queues/import', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ filename, content, queue_name: queueName }) }),
  exportSampleQueue: async (token: string, queueId: number) => {
    const response = await requestRaw(`/api/v1/sample-queues/${queueId}/export`, { headers: { Authorization: `Bearer ${token}` } })
    return { blob: await response.blob(), filename: response.headers.get('Content-Disposition') ?? `queue-${queueId}.sam` }
  },
  health: () => request<{ status: string; version: string; uptime_seconds: number }>('/health'),
  about: () => request<About>('/about'),
  capabilities: () => request<{ capabilities: Capability[] }>('/api/v1/capabilities'),
  diagnostics: () => request<Diagnostics>('/api/v1/diagnostics'),
  settings: (token: string) => request<Settings>('/api/v1/settings', { headers: { Authorization: `Bearer ${token}` } }),
  saveSettings: (token: string, settings: Partial<Settings>) =>
    request<Settings>('/api/v1/settings', { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(settings) }),
  resetSettings: (token: string) => request<Settings>('/api/v1/settings/reset', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  logs: (token: string, params = '') => request<RuntimeEvent[]>(`/api/v1/logs${params}`, { headers: { Authorization: `Bearer ${token}` } }),
  clearLogs: (token: string) => request<{ deleted: number }>('/api/v1/logs', { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  appendLog: (token: string, event: Pick<RuntimeEvent, 'category' | 'severity' | 'message'>) =>
    request<RuntimeEvent>('/api/v1/logs', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(event) }),
}
