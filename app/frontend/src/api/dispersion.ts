/** dispersion requests and models; moved without changing payloads or responses. */
import { request } from './client'
import type { DeviceEvent } from './devices'

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

export const dispersionApi = {
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
}
