/** dispersion requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'
import type { DeviceEvent } from './devices'

export type DispersionState =
  | 'draft'
  | 'pre_excitation'
  | 'burn'
  | 'dark'
  | 'paused'
  | 'stopping'
  | 'completed'
  | 'failed'
  | 'stopped'

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
  legacy_results?: {
    quadratic_coefficient: number; linear_coefficient: number; intercept: number
    wave_per_step: number | null; wavelength_range: [number, number]; step_range: [number, number]; maximum_error: number
    rows: Array<{line_id:number; measured_position:number; predicted_position:number; step_error:number}>
  } | null
  display_name?: string
  archived?: boolean
  id: number
  name: string
  version: number
  state: 'draft' | 'published' | 'superseded'
  calibration_id: number | null
  ccd_layout_id: number
  source_task_id: number | null
  coefficients: number[]
  residuals: Array<{
    line_id: number
    element: string
    wavelength_nm: number
    ccd_index: number
    measured_position: number
    predicted_position: number
    residual_points: number
  }>
  wavelength_min: number
  wavelength_max: number
  residual_rms: number
  residual_max: number
  point_count: number
  residual_limit_points: number
  publishable: boolean
  inputs_current?: boolean
  created_at: string
}

export type DispersionTask = {
  active_capture_id?: number
  positioning?: boolean
  position_controlled?: boolean
  capture_turn?: import('./acquisition').CaptureTurn
  capture_turns?: import('./acquisition').CaptureTurnPage[]
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
  legacy_lines?: Array<{line_id:number; ccd_index:number; point_index:number|null; measured_step:number|null}>
  frame_summary: Array<{ phase: 'burn' | 'dark'; frame_count: number; last_frame_index: number }>
  calibrations: DispersionCalibrationVersion[]
  layout: {
    id: number
    name: string
    frame_count: number
    ccds_per_frame: number
    points_per_ccd: number
    ccd_indices: number[]
    point_width_um: number
    gap_points: number[]
  }
  profile: { id: number; name: string; transport: string; screen_width_mm?: number; screen_resolution_px?: number }
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
  gap_limits_um?: [number, number]
  preliminary_defaults?: import('./system').PreliminaryConditions
  legacy_sources?: Array<{ id: number; sample_name: string; band_name: string; band_id?:number;source_sha256?:string;source_filename?:string;record_index?:number;measure_time?:string }>
  ccd_layouts: Array<{
    id: number
    name: string
    frame_count: number
    ccds_per_frame: number
    points_per_ccd: number
    point_width_um: number
    ccd_indices: number[]
    wavelength_min: number
    wavelength_max: number
  }>
  calibration_versions: DispersionCalibrationVersion[]
  device_profiles: Array<{
    id: number
    name: string
    transport: string
    frame_count: number
    ccds_per_frame: number
    points_per_ccd: number
    ccd_indices: number[]
  }>
  states: DispersionState[]
}

export const dispersionApi = {
  deleteDispersionTask: (token: string, taskId: number) =>
    request<void>(`/api/v1/dispersion/tasks/${taskId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` }
    }),
  createDispersionSession: (token: string, payload: import('./acquisition').PreliminaryCaptureCreate) => request<DispersionTask>('/api/v1/dispersion/capture-sessions', {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  dispersionCoordinate: (token: string, taskId: number, wavelength: number) =>
    request<{ccd_index:number;point_index:number}>(`/api/v1/dispersion/tasks/${taskId}/coordinate?wavelength_nm=${wavelength}`, {
      headers: { Authorization: `Bearer ${token}` }
    }),
  addDispersionPoint: (token: string, taskId: number, ccd: number, point: number) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/line-points`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ ccd_index: ccd, point_index: point })
    }),
  updateDispersionWavelength: (token: string, taskId: number, lineId: number, wavelength: number, legacyInput = false) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/wavelength?wavelength_nm=${wavelength}&legacy_input=${legacyInput}`, {
      method: 'PATCH', headers: { Authorization: `Bearer ${token}` }
    }),
  updateDispersionGap: (token: string, taskId: number, gap: number, gapUm: number, legacyLimits = false) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/gaps/${gap}?gap_um=${gapUm}&legacy_limits=${legacyLimits}`, {
      method: 'PATCH', headers: { Authorization: `Bearer ${token}` }
    }),
  saveDispersionDefaults: (token: string, payload: import('./system').PreliminaryConditions) =>
    request<import('./system').PreliminaryConditions>('/api/v1/dispersion/defaults', {
      method: 'PUT', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload)
    }),
  saveDispersionCurve: (token: string, id: number, name: string) =>
    request<DispersionCalibrationVersion>(`/api/v1/dispersion/calibrations/${id}/save?${new URLSearchParams({name})}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    }),
  allDispersionPositions: (token: string, taskId: number, action: 'save' | 'restore') =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/positions/${action}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    }),
  manageDispersionCalibration: (token: string, id: number, action: string, name?: string) =>
    request(
      `/api/v1/dispersion/calibrations/${id}/manage?${new URLSearchParams({ action, ...(name ? { name } : {}) })}`,
      { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
    ),
  setDispersionPosition: (token: string, taskId: number, lineId: number, position: number) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/position?position=${position}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  dispersionOptions: (token: string) =>
    request<DispersionOptions>('/api/v1/dispersion/options', { headers: { Authorization: `Bearer ${token}` } }),
  dispersionTasks: (token: string, limit=50, offset=0) =>
    request<DispersionTask[]>(`/api/v1/dispersion/tasks?limit=${limit}&offset=${offset}`, { headers: { Authorization: `Bearer ${token}` } }),
  createDispersionTask: (token: string, payload: Record<string, unknown>) =>
    request<DispersionTask>('/api/v1/dispersion/tasks', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  dispersionTask: (token: string, taskId: number) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}`, { headers: { Authorization: `Bearer ${token}` } }),
  startDispersionTask: (token: string, taskId: number, continuous = false) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/start${continuous ? '?continuous=true' : ''}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  stepDispersionTask: (token: string, taskId: number) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/step`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  preheatDispersionTask: (token: string, taskId: number) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/preheat`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    }),
  pauseDispersionTask: (token: string, taskId: number) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/pause`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  resumeDispersionTask: (token: string, taskId: number) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/resume`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  stopDispersionTask: (token: string, taskId: number) =>
    request<DispersionTask>(`/api/v1/dispersion/tasks/${taskId}/stop`, {
      method: 'POST',
      timeoutMs: 70000,
      headers: { Authorization: `Bearer ${token}` }
    }),
  dispersionFrames: (token: string, taskId: number, ccdIndex?: number) =>
    request<DispersionFrame[]>(
      `/api/v1/dispersion/tasks/${taskId}/frames${ccdIndex === undefined ? '' : `?ccd_index=${ccdIndex}`}`,
      { headers: { Authorization: `Bearer ${token}` } }
    ),
  dispersionObservationSpectrum: (token: string, taskId: number, ccd: number, start: number, end: number) =>
    request<{ points: number[] }>(`/api/v1/dispersion/tasks/${taskId}/observation-spectrum?ccd=${ccd}&exposure_start=${start}&exposure_end=${end}`,
      { headers: { Authorization: `Bearer ${token}` } }),
  printDispersionObservation: async (token: string, taskId: number, payload: {
    ccd: number; exposure_start: number; exposure_end: number; x_min: number; x_max: number; y_min: number; y_max: number
  }) => (await requestRaw(`/api/v1/dispersion/tasks/${taskId}/observation-spectrum/print-pdf`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload)
  })).blob(),
  addDispersionLine: (
    token: string,
    taskId: number,
    payload: { element: string; wavelength_nm: number; ccd_index: number; actual_position?: number | null }
  ) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  deleteDispersionLine: (token: string, taskId: number, lineId: number) =>
    request<{ id: number; deleted: boolean }>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` }
    }),
  locateDispersionLine: (token: string, taskId: number, lineId: number) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/locate`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  locateAllDispersionLines: (token: string, taskId: number, legacyWindow = false) =>
    request<{ located: DispersionLine[]; errors: Array<Record<string, unknown>>; all_succeeded: boolean }>(
      `/api/v1/dispersion/tasks/${taskId}/lines/locate-all?legacy_window=${legacyWindow}`,
      { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
    ),
  moveDispersionLine: (token: string, taskId: number, lineId: number, direction: 'short' | 'long', steps = 1) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/move`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ direction, steps })
    }),
  saveDispersionLinePosition: (token: string, taskId: number, lineId: number) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/position/save`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  restoreDispersionLinePosition: (token: string, taskId: number, lineId: number) =>
    request<DispersionLine>(`/api/v1/dispersion/tasks/${taskId}/lines/${lineId}/position/restore`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  fitDispersionCalibration: (
    token: string,
    taskId: number,
    payload: { name?: string; degree?: number; residual_limit_points?: number; use_legacy_limit?: boolean }
  ) =>
    request<DispersionCalibrationVersion>(`/api/v1/dispersion/tasks/${taskId}/calibrations/fit`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  publishDispersionCalibration: (token: string, calibrationVersionId: number) =>
    request<DispersionCalibrationVersion>(`/api/v1/dispersion/calibrations/${calibrationVersionId}/publish`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  bindDispersionCalibration: (token: string, calibrationVersionId: number, methodId: number, methodVersion?: number) =>
    request<Record<string, unknown>>(`/api/v1/dispersion/calibrations/${calibrationVersionId}/bind`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ method_id: methodId, method_version: methodVersion })
    })
}
