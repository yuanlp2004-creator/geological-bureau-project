/** auth requests and models; moved without changing payloads or responses. */
import { request } from './client'

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

export const authApi = {
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
}
