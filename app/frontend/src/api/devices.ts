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
  details: {
    sha256?: string
    frame_size?: number
    byte_length?: number
    headers?: number[]
    mirror?: boolean
    ccd_indices?: number[]
    seed?: number
    [key: string]: unknown
  }
}

export type DeviceDiagnostics = {
  adapter: {
    adapter: string
    state: string
    session_id: string | null
    connected: boolean
    port?: string
    instrument_responded?: boolean
    profile_id?: number | null
    angle_deg?: number | null
    turning?: boolean
    last_error?: { code: string; message: string } | null
    contract: Record<string, number>
  }
  profiles: DeviceProfile[]
  active_captures?: Array<{ task_id: number; owner: string; port: string; state: string; profile_id?: number | null }>
}

export type DevicePort = { device: string; port: number; description: string; is_bluetooth: boolean
  bluetooth_address?: string | null; direction?: 'outgoing' | 'incoming' | null }
export type BluetoothDevice = { address: string; name: string; connected: boolean; paired: boolean; ports: DevicePort[] }
export type MotorPositionEvidence = {
  reference_source: string
  reference_file: string
  observed_file: string
  reference_sha256?: string
  observed_sha256?: string
  ccd_index: number
  reference_angle_deg: number
  reference_peak: number
  observed_peak: number
  target_angle_deg: number
}
export type MotorBinding = {
  bluetooth_address: string
  motor_port: number
  api_port: number
  calibration_id: string
  angles: { method_angle_deg: number; motor_angle_deg: number; evidence?: MotorPositionEvidence | null }[]
}

export type DeviceDebugResult = {
  session_id: string | null
  event: DeviceEvent
  diagnostics: DeviceDiagnostics['adapter']
  sample_records_created: number
  spectrum_records_created: number
}

export type DeviceDebugTurn = {
  profile_id: number | null
  angles: number[]
  current_angle_deg: number | null
  moving: boolean
  simulated: boolean
}

export const devicesApi = {
  deviceDebugTurn: (token: string) => request<DeviceDebugTurn>('/api/v1/devices/debug/turn', { headers: { Authorization: `Bearer ${token}` } }),
  switchDeviceDebugTurn: (token: string, profileId: number, angle: number) =>
    request<DeviceDebugTurn>('/api/v1/devices/debug/turn', { method: 'POST', timeoutMs: 390000,
      headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ profile_id: profileId, angle_deg: angle }) }),
  motorBinding: (token: string, profileId: number) =>
    request<MotorBinding | null>(`/api/v1/devices/profiles/${profileId}/motor-binding`, { headers: { Authorization: `Bearer ${token}` } }),
  saveMotorBinding: (token: string, profileId: number, binding: MotorBinding) =>
    request<MotorBinding>(`/api/v1/devices/profiles/${profileId}/motor-binding`, {
      method: 'PUT', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(binding),
    }),
  deleteBluetoothDevice: (token: string, address: string) => request<{ deleted: boolean }>(`/api/v1/devices/bluetooth/${encodeURIComponent(address)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  bluetoothDevices: (token: string) => request<{ devices: BluetoothDevice[] }>('/api/v1/devices/bluetooth', { headers: { Authorization: `Bearer ${token}` } }),
  selectDevicePort: (token: string, transport: 'serial' | 'simulator', port?: number, bluetoothAddress?: string) =>
    request<DeviceProfile>('/api/v1/devices/port', {
      method: 'PUT', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ transport, port, bluetooth_address: bluetoothAddress }) }),
  devicePorts: (token: string) => request<DevicePort[]>('/api/v1/devices/ports', { headers: { Authorization: `Bearer ${token}` } }),
  currentDeviceProfile: (token: string) => request<DeviceProfile | null>('/api/v1/devices/current', { headers: { Authorization: `Bearer ${token}` } }),
  selectDeviceProfile: (token: string, profileId: number) => request<DeviceProfile>('/api/v1/devices/current', {
    method: 'PUT', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ profile_id: profileId }) }),
  testDeviceConnection: (token: string, profileId: number, purpose = 'devices') =>
    request<{ passed: boolean; instrument_responded: boolean; connected: boolean }>(
      `/api/v1/devices/profiles/${profileId}/connection-test?purpose=${encodeURIComponent(purpose)}`,
      { method: 'POST', timeoutMs: 25000, headers: { Authorization: `Bearer ${token}` } }),
  deviceProfiles: (token: string) =>
    request<DeviceProfile[]>('/api/v1/devices/profiles', { headers: { Authorization: `Bearer ${token}` } }),
  deviceDiagnostics: (token: string) =>
    request<DeviceDiagnostics>('/api/v1/devices/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  createDeviceProfile: (
    token: string,
    payload: Omit<DeviceProfile, 'id' | 'created_at' | 'updated_at' | 'screen_conversion'>
  ) =>
    request<DeviceProfile>('/api/v1/devices/profiles', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  updateDeviceProfile: (
    token: string,
    profileId: number,
    payload: Partial<Omit<DeviceProfile, 'id' | 'created_at' | 'updated_at' | 'screen_conversion'>>
  ) =>
    request<DeviceProfile>(`/api/v1/devices/profiles/${profileId}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  connectDevice: (token: string, profileId: number) =>
    request<{ profile: DeviceProfile; diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent }>(
      '/api/v1/devices/connect',
      { method: 'POST', timeoutMs: 25000, headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ profile_id: profileId }) }
    ),
  disconnectDevice: (token: string) =>
    request<{ diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent }>('/api/v1/devices/disconnect', {
      method: 'POST',
      timeoutMs: 70000,
      headers: { Authorization: `Bearer ${token}` }
    }),
  startDeviceDebug: (token: string, payload: { sample?: string; seed?: number; fault_frame?: number | null }) =>
    request<DeviceDebugResult>('/api/v1/devices/debug/start', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  stepDeviceDebug: (token: string) =>
    request<DeviceDebugResult>('/api/v1/devices/debug/step', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  stopDeviceDebug: (token: string) =>
    request<Omit<DeviceDebugResult, 'session_id'>>('/api/v1/devices/debug/stop', {
      method: 'POST',
      timeoutMs: 70000,
      headers: { Authorization: `Bearer ${token}` }
    })
}
