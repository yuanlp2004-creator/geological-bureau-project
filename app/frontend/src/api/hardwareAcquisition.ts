import { request } from './client'
export type HardwareTaskState =
  | 'draft'
  | 'connecting'
  | 'connected'
  | 'pre_excitation'
  | 'turning'
  | 'collecting'
  | 'anomaly'
  | 'manual_intervention'
  | 'paused'
  | 'stopping'
  | 'completed'
  | 'failed'
  | 'stopped'
  | 'safety_stopped'
  | 'deferred_external'
export type HardwarePlanStep = {
  storage_mode: 'averaged' | 'full_interval'
  start_frame: number
  end_frame: number
  captured_frames: number
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
  method_id: number | null
  method_version: number | null
  analysis_sample?: HardwareAnalysisSample | null
  exposures: Array<{
    id: number
    ccd_index: number
    storage_mode: string
    start_frame: number
    end_frame: number
    confirmed: boolean
    mean_sha256: string
  }>
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
export type HardwareAnalysisSample = {
  acquisition_task_id: number
  acquisition_sample_id: number
  sample_name: string
  source_sha256: string
  already_saved?: boolean
}
export type HardwareOptions = {
  methods: Array<{
    method_id: number
    version: number
    name: string
  }>
  states: HardwareTaskState[]
  strategies: Array<'short_to_long' | 'key_first'>
  anomaly_policies: Array<'retry_then_stop' | 'manual'>
  anomaly_kinds: string[]
  profiles: Array<{
    id: number
    name: string
    transport: string
    port: number
    baud_rate: number
    ccd_indices: number[]
    points_per_ccd: number
  }>
  layouts: Array<Record<string, unknown>>
}
export const hardwareAcquisitionApi = {
  saveHardwareAnalysisSample: (token: string, taskId: number, payload: { sample_name: string; sample_kind: 'test' | 'standard'; name_length: 12 | 20 }) =>
    request<HardwareAnalysisSample>(`/api/v1/hardware-acquisitions/tasks/${taskId}/analysis-sample`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload)
    }),
  hardwareAcquisitionOptions: (token: string) =>
    request<HardwareOptions>('/api/v1/hardware-acquisitions/options', {
      headers: { Authorization: `Bearer ${token}` }
    }),
  hardwareAcquisitionTasks: (token: string) =>
    request<HardwareTask[]>('/api/v1/hardware-acquisitions/tasks', {
      headers: { Authorization: `Bearer ${token}` }
    }),
  createHardwareAcquisitionTask: (token: string, payload: Record<string, unknown>) =>
    request<HardwareTask>('/api/v1/hardware-acquisitions/tasks', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  hardwareAcquisitionTask: (token: string, taskId: number, includePoints = false) =>
    request<HardwareTask>(
      `/api/v1/hardware-acquisitions/tasks/${taskId}${includePoints ? '?include_points=true' : ''}`,
      { headers: { Authorization: `Bearer ${token}` } }
    ),
  startHardwareAcquisitionTask: (token: string, taskId: number) =>
    request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/start`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  stepHardwareAcquisitionTask: (token: string, taskId: number) =>
    request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/step`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  pauseHardwareAcquisitionTask: (token: string, taskId: number) =>
    request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/pause`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  resumeHardwareAcquisitionTask: (token: string, taskId: number) =>
    request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/resume`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  stopHardwareAcquisitionTask: (token: string, taskId: number) =>
    request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/stop`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  interveneHardwareAcquisitionTask: (
    token: string,
    taskId: number,
    action: 'accept' | 'retry' | 'stop',
    note = ''
  ) =>
    request<HardwareTask>(`/api/v1/hardware-acquisitions/tasks/${taskId}/intervene`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ action, note })
    }),
  hardwareAcquisitionFrames: (token: string, taskId: number, includePoints = false) =>
    request<Array<Record<string, unknown>>>(
      `/api/v1/hardware-acquisitions/tasks/${taskId}/frames${includePoints ? '?include_points=true' : ''}`,
      { headers: { Authorization: `Bearer ${token}` } }
    ),
  hardwareAcquisitionTraces: (token: string, taskId: number) =>
    request<Array<Record<string, unknown>>>(`/api/v1/hardware-acquisitions/tasks/${taskId}/traces`, {
      headers: { Authorization: `Bearer ${token}` }
    }),
  hardwareAcquisitionDecisions: (token: string, taskId: number) =>
    request<Array<Record<string, unknown>>>(`/api/v1/hardware-acquisitions/tasks/${taskId}/decisions`, {
      headers: { Authorization: `Bearer ${token}` }
    })
}
