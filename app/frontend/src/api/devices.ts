/** devices requests and models; moved without changing payloads or responses. */
import { request } from './client'

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

export const devicesApi = {
  deviceProfiles: (token: string) => request<DeviceProfile[]>('/api/v1/devices/profiles', { headers: { Authorization: `Bearer ${token}` } }),
  deviceDiagnostics: (token: string) => request<DeviceDiagnostics>('/api/v1/devices/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  createDeviceProfile: (token: string, payload: Omit<DeviceProfile, 'id' | 'created_at' | 'updated_at' | 'screen_conversion'>) => request<DeviceProfile>('/api/v1/devices/profiles', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateDeviceProfile: (token: string, profileId: number, payload: Partial<Omit<DeviceProfile, 'id' | 'created_at' | 'updated_at' | 'screen_conversion'>>) => request<DeviceProfile>(`/api/v1/devices/profiles/${profileId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  connectDevice: (token: string, profileId: number) => request<{ profile: DeviceProfile; diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent }>('/api/v1/devices/connect', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ profile_id: profileId }) }),
  disconnectDevice: (token: string) => request<{ diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent }>('/api/v1/devices/disconnect', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  startDeviceDebug: (token: string, payload: { sample?: string; seed?: number; fault_frame?: number | null }) => request<DeviceDebugResult>('/api/v1/devices/debug/start', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  stepDeviceDebug: (token: string) => request<DeviceDebugResult>('/api/v1/devices/debug/step', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stopDeviceDebug: (token: string) => request<Omit<DeviceDebugResult, 'session_id'>>('/api/v1/devices/debug/stop', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
}
