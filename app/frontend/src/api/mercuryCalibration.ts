/** mercuryCalibration requests and models; moved without changing payloads or responses. */
import { request } from './client'

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

export const mercuryCalibrationApi = {
  mercuryCalibrationOptions: (token: string) => request<MercuryOptions>('/api/v1/mercury-calibrations/options', { headers: { Authorization: `Bearer ${token}` } }),
  mercuryCalibrationSessions: (token: string) => request<MercurySession[]>('/api/v1/mercury-calibrations/sessions', { headers: { Authorization: `Bearer ${token}` } }),
  createMercuryCalibrationSession: (token: string, payload: Record<string, unknown>) => request<MercurySession>('/api/v1/mercury-calibrations/sessions', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  mercuryCalibrationSession: (token: string, sessionId: number, includePoints = false) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}${includePoints ? '?include_points=true' : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  startMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  applyMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/apply`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  rollbackMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/rollback`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopMercuryCalibrationSession: (token: string, sessionId: number) => request<MercurySession>(`/api/v1/mercury-calibrations/sessions/${sessionId}/stop`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
}
