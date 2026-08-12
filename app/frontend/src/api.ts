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

export type DeviceProfile = {
  id: number
  name: string
  transport: 'simulator' | 'serial'
  port: number
  baud_rate: number
  mirror: boolean
  frame_count: number
  ccds_per_frame: number
  points_per_ccd: number
  ccd_indices: number[]
  point_width_um: number
  protection_time_ms: number
  screen_width_mm: number
  screen_resolution_px: number
  enabled: boolean
  created_at: string
  updated_at: string
  screen_conversion: { pixels_per_mm: number; um_per_pixel: number; point_width_px: number }
}

export type DeviceCcd = {
  ccd_index: number
  points?: number[]
  points_count: number
  dtype: 'uint16'
  endianness: 'little'
  compression: 'zlib'
  points_sha256: string
  raw_transfer_sha256: string
  raw_byte_length: number
  peak: number
  peak_position: number
}

export type DeviceEvent = {
  event_type: string
  state: string
  occurred_at: string
  correlation_id: string
  frame_index: number | null
  frame_count: number | null
  ccds: DeviceCcd[]
  message: string
  details: { sha256?: string; frame_size?: number; byte_length?: number; headers?: number[]; mirror?: boolean; ccd_indices?: number[]; seed?: number; [key: string]: unknown }
}

export type DeviceDiagnostics = {
  adapter: { adapter: string; state: string; session_id: string | null; connected: boolean; contract: Record<string, number> }
  profiles: DeviceProfile[]
}

export type DeviceDebugResult = {
  session_id: string | null
  event: DeviceEvent
  diagnostics: DeviceDiagnostics['adapter']
  sample_records_created: number
  spectrum_records_created: number
}

export type DispersionState = 'draft' | 'pre_excitation' | 'burn' | 'dark' | 'paused' | 'stopping' | 'completed' | 'failed' | 'stopped'

export type DispersionLine = {
  id: number
  task_id: number
  element: string
  wavelength_nm: number
  ccd_index: number
  expected_position: number | null
  located_position: number | null
  saved_position: number | null
  position_state: 'pending' | 'located' | 'saved'
  position_source: string | null
  position_frame_id: number | null
  adjustment_points: number
  created_at: string
  updated_at: string
}

export type DispersionCalibrationVersion = {
  id: number
  name: string
  version: number
  state: 'draft' | 'published' | 'superseded'
  calibration_id: number | null
  ccd_layout_id: number
  source_task_id: number | null
  coefficients: number[]
  residuals: Array<{ line_id: number; element: string; wavelength_nm: number; ccd_index: number; measured_position: number; predicted_position: number; residual_points: number }>
  wavelength_min: number
  wavelength_max: number
  residual_rms: number
  residual_max: number
  point_count: number
  residual_limit_points: number
  publishable: boolean
  created_at: string
}

export type DispersionTask = {
  id: number
  name: string
  status: DispersionState
  paused_from: string | null
  device_profile_id: number
  ccd_layout_id: number
  method_id: number | null
  method_version: number | null
  frame_count: number
  dark_frame_count: number
  pre_excitation_seconds: number
  sampling_period_seconds: number
  residual_limit_points: number
  ccd_indices: number[]
  condition: Record<string, unknown>
  adapter_session_id: string | null
  burn_frames_captured: number
  dark_frames_captured: number
  last_frame_index: number | null
  last_event: DeviceEvent | null
  failure_code: string | null
  failure_message: string | null
  lines: DispersionLine[]
  frame_summary: Array<{ phase: 'burn' | 'dark'; frame_count: number; last_frame_index: number }>
  calibrations: DispersionCalibrationVersion[]
  layout: { id: number; name: string; frame_count: number; ccds_per_frame: number; points_per_ccd: number; ccd_indices: number[] }
  profile: { id: number; name: string; transport: string }
  created_at: string
  updated_at: string
}

export type DispersionFrame = {
  id: number
  task_id: number
  phase: 'burn' | 'dark'
  frame_index: number
  ccd_index: number
  points: number[]
  sha256: string
  headers: number[]
  byte_length: number
  virtual_time_ms: number
  captured_at: string
}

export type DispersionOptions = {
  ccd_layouts: Array<{ id: number; name: string; frame_count: number; ccds_per_frame: number; points_per_ccd: number; point_width_um: number; ccd_indices: number[]; wavelength_min: number; wavelength_max: number }>
  calibration_versions: DispersionCalibrationVersion[]
  device_profiles: Array<{ id: number; name: string; transport: string; frame_count: number; ccds_per_frame: number; points_per_ccd: number; ccd_indices: number[] }>
  states: DispersionState[]
}

export type AcquisitionState = 'draft' | 'countdown' | 'pre_excitation' | 'burn' | 'dark' | 'between_repeats' | 'paused' | 'stopping' | 'completed' | 'failed' | 'stopped'

export type AcquisitionSample = {
  id: number
  task_id: number
  queue_item_id: number | null
  repeat_index: number
  sample_name_original: string
  sample_name: string
  sample_kind: 'evaporation' | 'blank' | 'normal' | 'standard' | 'test' | 'preheat'
  storage_mode: 'averaged' | 'full_interval'
  status: 'collecting' | 'completed' | 'failed' | 'stopped'
  finalized: boolean
  result_sha256: string | null
  failure_code: string | null
  failure_message: string | null
  bands: Array<{ id: number; ccd_index: number; storage_mode: string; points_count: number; burn_frame_count: number; dark_frame_count: number; mean_sha256: string; burn_sha256: string | null; dark_sha256: string | null }>
}

export type AcquisitionMessage = {
  id: number
  task_id: number
  level: 'info' | 'warning' | 'error' | 'success'
  code: string
  message: string
  details: Record<string, unknown>
  created_at: string
}

export type AcquisitionTask = {
  id: number
  task_kind: 'evaporation' | 'sample'
  name: string
  status: AcquisitionState
  paused_from: string | null
  device_profile_id: number
  ccd_layout_id: number
  method_id: number | null
  method_version: number | null
  queue_id: number | null
  queue_item_id: number | null
  sample_name: string
  sample_kind: AcquisitionSample['sample_kind']
  naming_mode: 'pre_recorded' | 'temporary' | 'post'
  storage_mode: 'averaged' | 'full_interval'
  repeat_count: number
  current_repeat_index: number
  completed_repeats: number
  burn_frame_count: number
  dark_frame_count: number
  countdown_seconds: number
  countdown_remaining: number
  pre_excitation_seconds: number
  sampling_period_seconds: number
  burn_cycle_seconds: number
  dark_cycle_seconds: number
  ccd_indices: number[]
  excitation_condition: Record<string, unknown>
  evaporation_condition: Record<string, unknown>
  simulator: Record<string, unknown>
  adapter_session_id: string | null
  burn_frames_captured: number
  dark_frames_captured: number
  last_event: DeviceEvent | null
  last_message: string
  progress: number
  result_sha256: string | null
  failure_code: string | null
  failure_message: string | null
  layout: { id: number; name: string; points_per_ccd: number; ccd_indices: number[] }
  profile: { id: number; name: string; transport: string; mirror: boolean }
  samples: AcquisitionSample[]
  messages: AcquisitionMessage[]
  intervals: Array<{ id: number; repeat_index: number; label: string; start_frame_index: number; end_frame_index: number }>
  created_at: string
  updated_at: string
}

export type AcquisitionFrame = {
  id: number
  task_id: number
  sample_id: number
  repeat_index: number
  phase: 'burn' | 'dark'
  frame_index: number
  ccd_index: number
  points_count: number
  points?: number[]
  dtype: 'uint16'
  endianness: 'little'
  points_sha256: string | null
  raw_transfer_sha256: string | null
  raw_byte_length: number
  headers_json: string
  virtual_time_ms: number
  peak_value: number | null
  peak_position: number | null
  integral_value: number | null
  interval_label: string | null
  damaged: boolean
  damage_code: string | null
  damage_message: string | null
  captured_at: string
}

export type AcquisitionOptions = {
  task_kinds: Array<'evaporation' | 'sample'>
  sample_kinds: AcquisitionSample['sample_kind'][]
  storage_modes: Array<'averaged' | 'full_interval'>
  states: AcquisitionState[]
  profiles: Array<{ id: number; name: string; transport: string; ccd_indices: number[]; points_per_ccd: number }>
  layouts: Array<{ id: number; name: string; frame_count: number; ccds_per_frame: number; points_per_ccd: number; ccd_indices: number[] }>
  methods: Array<{ method_id: number; method_version: number; name: string }>
  queues: SampleQueue[]
}

export type AcquisitionAnalysis = {
  task_id: number
  repeat_index: number
  points_per_ccd: number
  curves: AcquisitionFrame[]
  intervals: Array<Record<string, unknown> & { label: string; stats: Array<Record<string, unknown> & { ccd_index: number; point_mean: number[] }> }>
}

export type HardwareTaskState = 'draft' | 'connecting' | 'connected' | 'pre_excitation' | 'turning' | 'collecting' | 'anomaly' | 'manual_intervention' | 'paused' | 'stopping' | 'completed' | 'failed' | 'stopped' | 'safety_stopped' | 'deferred_external'

export type HardwarePlanStep = {
  id: number
  task_id: number
  order_index: number
  source_index: number
  angle_deg: number
  wavelength_nm: number
  priority: number
  key_band: boolean
  expected_peak_position: number
  status: string
  retry_count: number
  last_attempt: number
  correction_offset: number
}

export type HardwareTask = {
  id: number
  name: string
  status: HardwareTaskState
  paused_from: HardwareTaskState | null
  device_profile_id: number
  ccd_layout_id: number
  transport: 'simulator' | 'serial'
  strategy: 'short_to_long' | 'key_first'
  anomaly_policy: 'retry_then_stop' | 'manual'
  sample_name: string
  retry_limit: number
  pre_excitation_seconds: number
  sampling_period_seconds: number
  ccd_indices: number[]
  plan: HardwarePlanStep[]
  thresholds: Record<string, number>
  simulator: Record<string, unknown>
  total_steps: number
  current_step_index: number
  current_retry_count: number
  completed_steps: number
  adapter_session_id: string | null
  last_event: Record<string, unknown> | null
  last_message: string
  progress: number
  result_sha256: string | null
  failure_code: string | null
  failure_message: string | null
  profile: { id: number; name: string; transport: string; port: number; baud_rate: number; mirror: boolean }
  layout: { id: number; name: string; points_per_ccd: number; ccd_indices: number[] }
  steps: HardwarePlanStep[]
  traces: Array<Record<string, unknown>>
  decisions: Array<Record<string, unknown>>
  frames: Array<Record<string, unknown>>
  messages: Array<Record<string, unknown>>
  latest_trace: Record<string, unknown> | null
  latest_decision: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type HardwareOptions = {
  states: HardwareTaskState[]
  strategies: Array<'short_to_long' | 'key_first'>
  anomaly_policies: Array<'retry_then_stop' | 'manual'>
  anomaly_kinds: string[]
  profiles: Array<{ id: number; name: string; transport: string; port: number; baud_rate: number; ccd_indices: number[]; points_per_ccd: number }>
  layouts: Array<Record<string, unknown>>
}

export type MercuryReferenceLine = {
  id: number
  label: string
  wavelength_nm: number
  relative_intensity: number
  source_name: string
  source_url: string
  enabled: boolean
}

export type MercuryAlignmentVersion = {
  id: number
  version: number
  offset_points: number
  before_rms: number
  after_rms: number
  max_before_offset: number
  max_after_offset: number
  snapshot_sha256: string
  snapshot: Record<string, unknown>
}

export type MercurySessionLine = {
  id: number
  label: string
  wavelength_nm: number
  expected_ccd_index: number
  expected_position: number
  observed_position: number | null
  peak_value: number | null
  offset_points: number | null
  after_offset_points: number | null
  state: 'pending' | 'located' | 'not_found'
}

export type MercurySession = {
  id: number
  name: string
  status: 'draft' | 'stabilizing' | 'acquiring' | 'ready' | 'applied' | 'rolled_back' | 'stopped' | 'safe_off' | 'deferred_external'
  device_profile_id: number
  ccd_layout_id: number
  transport: 'simulator' | 'serial'
  stabilization_frames: number
  stabilized_frames: number
  tolerance_points: number
  search_radius_points: number
  correction_limit_points: number
  simulator: { offset_points: number; seed: number; fault: string }
  adapter_session_id: string | null
  safe_off: boolean
  progress: number
  last_message: string
  failure_code: string | null
  failure_message: string | null
  analysis: null | { line_count: number; median_offset_points: number; suggestion_points: number; before_rms: number; after_rms: number; max_before_offset: number; max_after_offset: number; within_tolerance: boolean; candidate_version_id: number }
  last_event: null | { phase?: string; frame_index?: number; ccds?: Array<{ ccd_index: number; points?: number[]; points_sha256: string }> }
  profile: { id: number; name: string; transport: string; port: number; baud_rate: number }
  layout: { id: number; name: string; points_per_ccd: number; ccd_indices: number[]; wavelength_min: number; wavelength_max: number }
  lines: MercurySessionLine[]
  messages: Array<Record<string, unknown>>
  traces: Array<Record<string, unknown>>
  frames: Array<Record<string, unknown>>
  before_version: MercuryAlignmentVersion
  candidate_version: MercuryAlignmentVersion | null
  active_version: MercuryAlignmentVersion
}

export type MercuryOptions = {
  reference_lines: MercuryReferenceLine[]
  profiles: Array<{ id: number; name: string; transport: 'simulator' | 'serial'; port: number; baud_rate: number; ccd_indices: number[]; points_per_ccd: number; mercury_protocol_available: boolean; protocol_status: string }>
  layouts: Array<{ id: number; name: string; points_per_ccd: number; ccd_indices: number[]; wavelength_min: number; wavelength_max: number }>
  active_alignments: Array<Record<string, unknown>>
  faults: string[]
  real_protocol_available: boolean
  protocol_notice: string
}

export type AnalysisStatus = 'draft' | 'running' | 'paused' | 'completed' | 'cancelled' | 'failed'

export type AnalysisSampleOption = {
  id: number
  sample_name: string
  sample_kind: string
  repeat_index: number
  input_sha256: string
  acquisition_task_id: number
  acquisition_task_name: string
  method_version_id: number
  method_id: number
  method_version: number
}

export type AnalysisOptions = {
  profiles: Array<'legacy_2_0_2' | 'modern_v1'>
  samples: AnalysisSampleOption[]
  method_versions: Array<{ method_version_id: number; method_id: number; version: number; name: string; calculation_profile: 'legacy_2_0_2' | 'modern_v1' }>
}

export type AnalysisLineResult = {
  id: number
  sample_position: number
  line_position: number
  line_id: string
  line_type: string
  element: string
  wavelength_nm: number
  ccd_index: number
  expected_position: number
  peak_position: number
  peak_height: number
  background: number
  net_signal: number
  gaussian_center: number | null
  gaussian_peak_height: number | null
  gaussian_sigma: number | null
  gaussian_area: number | null
  quantitative_signal: number
  calculation_profile: 'legacy_2_0_2' | 'modern_v1'
  intervention_id: number | null
  intermediates: Record<string, unknown>
  result_sha256: string
}

export type AnalysisCheckpoint = {
  id: number
  sequence: number
  sample_position: number
  line_position: number
  line_id: string
  status: 'pending' | 'accepted' | 'discarded' | 'cancelled'
  automatic_position: number
  accepted_position: number | null
  window_start: number
  window_end: number
  spectrum_window: Array<{ point_index: number; value: number }>
  candidate: AnalysisLineResult & { corrected_expected_position: number }
  deadline_at: string
}

export type AnalysisRun = {
  id: number
  name: string
  status: AnalysisStatus
  method_id: number
  method_name: string
  method_version_id: number
  method_version: number
  calculation_profile: 'legacy_2_0_2' | 'modern_v1'
  slow_mode: boolean
  intervention_timeout_seconds: number
  current_sample_position: number
  current_line_position: number
  input_sha256: string
  result_sha256: string | null
  failure_code: string | null
  failure_message: string | null
  failure_details: Record<string, unknown>
  samples: Array<{ id: number; position: number; acquisition_sample_id: number; sample_name: string; input_sha256: string; result_matrix: Array<{ line_id: string; element: string; wavelength_nm: number; quantitative_signal: number; calculation_profile: string }>; result_sha256: string | null }>
  line_results: AnalysisLineResult[]
  checkpoint: AnalysisCheckpoint | null
  interventions: Array<{ id: number; action: 'accept' | 'discard'; before_position: number; after_position: number; reason: string; created_at: string }>
  messages: Array<{ id: number; level: string; code: string; message: string; details: Record<string, unknown>; created_at: string }>
  created_at: string
  updated_at: string
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
  deviceProfiles: (token: string) => request<DeviceProfile[]>('/api/v1/devices/profiles', { headers: { Authorization: `Bearer ${token}` } }),
  deviceDiagnostics: (token: string) => request<DeviceDiagnostics>('/api/v1/devices/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  createDeviceProfile: (token: string, payload: Omit<DeviceProfile, 'id' | 'created_at' | 'updated_at' | 'screen_conversion'>) => request<DeviceProfile>('/api/v1/devices/profiles', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateDeviceProfile: (token: string, profileId: number, payload: Partial<Omit<DeviceProfile, 'id' | 'created_at' | 'updated_at' | 'screen_conversion'>>) => request<DeviceProfile>(`/api/v1/devices/profiles/${profileId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  connectDevice: (token: string, profileId: number) => request<{ profile: DeviceProfile; diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent }>('/api/v1/devices/connect', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ profile_id: profileId }) }),
  disconnectDevice: (token: string) => request<{ diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent }>('/api/v1/devices/disconnect', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  startDeviceDebug: (token: string, payload: { sample?: string; seed?: number; fault_frame?: number | null }) => request<DeviceDebugResult>('/api/v1/devices/debug/start', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  stepDeviceDebug: (token: string) => request<DeviceDebugResult>('/api/v1/devices/debug/step', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopDeviceDebug: (token: string) => request<Omit<DeviceDebugResult, 'session_id'>>('/api/v1/devices/debug/stop', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  dispersionOptions: (token: string) => request<DispersionOptions>('/api/v1/dispersion/options', { headers: { Authorization: `Bearer ${token}` } }),
  dispersionTasks: (token: string) => request<DispersionTask[]>('/api/v1/dispersion/tasks', { headers: { Authorization: `Bearer ${token}` } }),
  createDispersionTask: (token: string, payload: Record<string, unknown>) => request<DispersionTask>('/api/v1/dispersion/tasks', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  dispersionTask: (token: string, taskId: number) => request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}`, { headers: { Authorization: `Bearer ${token}` } }),
  startDispersionTask: (token: string, taskId: number) => request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepDispersionTask: (token: string, taskId: number) => request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  pauseDispersionTask: (token: string, taskId: number) => request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/pause`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  resumeDispersionTask: (token: string, taskId: number) => request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/resume`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopDispersionTask: (token: string, taskId: number) => request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  dispersionFrames: (token: string, taskId: number, ccdIndex?: number) => request<DispersionFrame[]>(`/api/v1/dispersion/tasks/${taskId}/frames${ccdIndex === undefined ? '' : `?ccd_index=${ccdIndex}`}`, { headers: { Authorization: `Bearer ${token}` } }),
  addDispersionLine: (token: string, taskId: number, payload: { element: string; wavelength_nm: number; ccd_index: number; actual_position?: number | null }) => request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  deleteDispersionLine: (token: string, taskId: number, lineId: number) => request<{ id: number; deleted: boolean }>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  locateDispersionLine: (token: string, taskId: number, lineId: number) => request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/locate`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  locateAllDispersionLines: (token: string, taskId: number) => request<{ located: DispersionLine[]; errors: Array<Record<string, unknown>>; all_succeeded: boolean }>(`/api/v1/dispersion/tasks/${taskId}/lines/locate-all`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  moveDispersionLine: (token: string, taskId: number, lineId: number, direction: 'short' | 'long', steps = 1) => request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/move`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ direction, steps }) }),
  saveDispersionLinePosition: (token: string, taskId: number, lineId: number) => request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/position/save`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  restoreDispersionLinePosition: (token: string, taskId: number, lineId: number) => request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/position/restore`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  fitDispersionCalibration: (token: string, taskId: number, payload: { name?: string; degree?: number; residual_limit_points?: number }) => request<DispersionCalibrationVersion>(`/api/v1/dispersion/tasks/${taskId}/calibrations/fit`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  publishDispersionCalibration: (token: string, calibrationVersionId: number) => request<DispersionCalibrationVersion>(`/api/v1/dispersion/calibrations/${calibrationVersionId}/publish`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  bindDispersionCalibration: (token: string, calibrationVersionId: number, methodId: number, methodVersion?: number) => request<Record<string, unknown>>(`/api/v1/dispersion/calibrations/${calibrationVersionId}/bind`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ method_id: methodId, method_version: methodVersion }) }),
  acquisitionOptions: (token: string) => request<AcquisitionOptions>('/api/v1/acquisitions/options', { headers: { Authorization: `Bearer ${token}` } }),
  acquisitionTasks: (token: string) => request<AcquisitionTask[]>('/api/v1/acquisitions/tasks', { headers: { Authorization: `Bearer ${token}` } }),
  createAcquisitionTask: (token: string, payload: Record<string, unknown>) => request<AcquisitionTask>('/api/v1/acquisitions/tasks', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  acquisitionTask: (token: string, taskId: number, includePoints = false) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}${includePoints ? '?include_points=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  startAcquisitionTask: (token: string, taskId: number) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepAcquisitionTask: (token: string, taskId: number) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  pauseAcquisitionTask: (token: string, taskId: number) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}/pause`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  resumeAcquisitionTask: (token: string, taskId: number) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}/resume`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopAcquisitionTask: (token: string, taskId: number) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  acquisitionFrames: (token: string, taskId: number, params = '') => request<AcquisitionFrame[]>(`/api/v1/acquisitions/tasks/${taskId}/frames${params}`, { headers: { Authorization: `Bearer ${token}` } }),
  markAcquisitionInterval: (token: string, taskId: number, payload: { repeat_index: number; label: string; start_frame_index: number; end_frame_index: number }) => request<AcquisitionAnalysis>(`/api/v1/acquisitions/tasks/${taskId}/intervals`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  acquisitionAnalysis: (token: string, taskId: number, repeatIndex?: number) => request<AcquisitionAnalysis>(`/api/v1/acquisitions/tasks/${taskId}/analysis${repeatIndex === undefined ? '' : `?repeat_index=${repeatIndex}`}`, { headers: { Authorization: `Bearer ${token}` } }),
  acquisitionBands: (token: string, sampleId: number, includePoints = false) => request<Array<Record<string, unknown>>>(`/api/v1/acquisitions/samples/${sampleId}/bands${includePoints ? '?include_points=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  renameAcquisitionSample: (token: string, taskId: number, sampleId: number, postName: string) => request<AcquisitionTask>(`/api/v1/acquisitions/tasks/${taskId}/samples/${sampleId}/rename`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ post_name: postName }) }),
  hardwareAcquisitionOptions: (token: string) => request<HardwareOptions>('/api/v1/hardware-acquisitions/options', { headers: { Authorization: `Bearer ${token}` } }),
  hardwareAcquisitionTasks: (token: string) => request<HardwareTask[]>('/api/v1/hardware-acquisitions/tasks', { headers: { Authorization: `Bearer ${token}` } }),
  createHardwareAcquisitionTask: (token: string, payload: Record<string, unknown>) => request<HardwareTask>('/api/v1/hardware-acquisitions/tasks', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  hardwareAcquisitionTask: (token: string, taskId: number, includePoints = false) => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}${includePoints ? '?include_points=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  startHardwareAcquisitionTask: (token: string, taskId: number) => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepHardwareAcquisitionTask: (token: string, taskId: number) => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  pauseHardwareAcquisitionTask: (token: string, taskId: number) => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/pause`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  resumeHardwareAcquisitionTask: (token: string, taskId: number) => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/resume`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopHardwareAcquisitionTask: (token: string, taskId: number) => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  interveneHardwareAcquisitionTask: (token: string, taskId: number, action: 'accept' | 'retry' | 'stop', note = '') => request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/intervene`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ action, note }) }),
  hardwareAcquisitionFrames: (token: string, taskId: number, includePoints = false) => request<Array<Record<string, unknown>>>(`/api/v1/hardware-acquisitions/tasks/${taskId}/frames${includePoints ? '?include_points=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  hardwareAcquisitionTraces: (token: string, taskId: number) => request<Array<Record<string, unknown>>>(`/api/v1/hardware-acquisitions/tasks/${taskId}/traces`, { headers: { Authorization: `Bearer ${token}` } }),
  hardwareAcquisitionDecisions: (token: string, taskId: number) => request<Array<Record<string, unknown>>>(`/api/v1/hardware-acquisitions/tasks/${taskId}/decisions`, { headers: { Authorization: `Bearer ${token}` } }),
  mercuryCalibrationOptions: (token: string) => request<MercuryOptions>('/api/v1/mercury-calibrations/options', { headers: { Authorization: `Bearer ${token}` } }),
  mercuryCalibrationSessions: (token: string) => request<MercurySession[]>('/api/v1/mercury-calibrations/sessions', { headers: { Authorization: `Bearer ${token}` } }),
  createMercuryCalibrationSession: (token: string, payload: Record<string, unknown>) => request<MercurySession>('/api/v1/mercury-calibrations/sessions', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  mercuryCalibrationSession: (token: string, sessionId: number, includePoints = false) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}${includePoints ? '?include_points=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  startMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  applyMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/apply`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  rollbackMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/rollback`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  analysisOptions: (token: string) => request<AnalysisOptions>('/api/v1/analyses/options', { headers: { Authorization: `Bearer ${token}` } }),
  analysisRuns: (token: string) => request<AnalysisRun[]>('/api/v1/analyses/runs', { headers: { Authorization: `Bearer ${token}` } }),
  createAnalysisRun: (token: string, payload: Record<string, unknown>) => request<AnalysisRun>('/api/v1/analyses/runs', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  analysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
  startAnalysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepAnalysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  interveneAnalysisRun: (token: string, runId: number, payload: { action: 'accept' | 'discard'; adjusted_position?: number | null; reason: string }) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/intervene`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  cancelAnalysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/cancel`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
}
