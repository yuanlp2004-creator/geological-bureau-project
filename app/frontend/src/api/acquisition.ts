/** acquisition requests and models; moved without changing payloads or responses. */
import { request } from './client'
import type { DeviceEvent } from './devices'
import type { SampleQueue } from './sampleQueues'

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

export const acquisitionApi = {
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
}
