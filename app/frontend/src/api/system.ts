/** system requests and models; moved without changing payloads or responses. */
import { request } from './client'
import type { MethodPrintSettings } from './methods'

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
  analysis?: { dark_round_time_seconds: number;log_analysis?:boolean;look_band?:boolean;wait_time_ms?:number;cmt_band_mean?:boolean }
  intensity_output?: {save_intensity:boolean;print_intensity:boolean;print_to_text:boolean;save_positions:boolean}
  preliminary?: { evaporation: PreliminaryConditions; dispersion: PreliminaryConditions }
  directories: { data: string; methods: string; samples: string; exports: string; backups: string }
  logging: { level: string; max_bytes: number; retention_days: number }
  display: { theme: string; density: string; show_status_bar: boolean;screen_width_mm?:number;screen_resolution_px?:number }
  printing: MethodPrintSettings
  time: { timezone: string; format: string }
}

export type PreliminaryConditions = {
  pre_excitation_seconds: number
  sampling_period_seconds: number
  frame_count: number
  dark_frame_count: number
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
  navigation_entries: Array<{
    key: string
    group: 'workspace' | 'methods' | 'analysis-tests' | 'data' | 'tools' | 'system' | 'help'
    section_label: string
    label: string
    description: string
    page: string
    view: string | null
    required_any: string[]
    order: number
    status: 'normal' | 'deferred_external' | 'test_only'
    required_context: 'none' | 'current_method' | 'current_method_exp_seg' | 'page_scoped'
  }>
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
  license: string
  copyright: string
  build: Record<string, unknown>
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
  manifest_error?: string | null
  checked_at?: string | null
  modules?: ModuleDiagnostic[]
}

export type ModuleDiagnostic = {
  key: string
  title: string
  version: string
  route: string
  enabled: boolean
  status: 'active' | 'disabled' | 'error' | 'restricted' | 'unchecked'
  message: string
  probe_path: string | null
  http_status: number | null
  note: string
}

export const systemApi = {
  health: () => request<{ status: string; version: string; uptime_seconds: number }>('/health'),
  about: (token: string) => request<About>('/about', { headers: { Authorization: `Bearer ${token}` } }),
  capabilities: () => request<{ capabilities: Capability[] }>('/api/v1/capabilities'),
  diagnostics: (token: string) =>
    request<Diagnostics>('/api/v1/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  settings: (token: string) => request<Settings>('/api/v1/settings', { headers: { Authorization: `Bearer ${token}` } }),
  saveSettings: (token: string, settings: Partial<Settings>) =>
    request<Settings>('/api/v1/settings', {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(settings)
    }),
  resetSettings: (token: string) =>
    request<Settings>('/api/v1/settings/reset', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  logs: (token: string, params = '') =>
    request<RuntimeEvent[]>(`/api/v1/logs${params}`, { headers: { Authorization: `Bearer ${token}` } }),
  clearLogs: (token: string) =>
    request<{ deleted: number }>('/api/v1/logs', { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  executeExtension: (token: string, key: string) =>
    request<Record<string, unknown>>(`/api/v1/extensions/${encodeURIComponent(key)}/execute`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  appendLog: (token: string, event: Pick<RuntimeEvent, 'category' | 'severity' | 'message'>) =>
    request<RuntimeEvent>('/api/v1/logs', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(event)
    })
}
