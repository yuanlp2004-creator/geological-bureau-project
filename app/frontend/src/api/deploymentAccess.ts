import { request } from './client'

export type ActivationStatus = {
  state: 'unmanaged' | 'pending' | 'active' | 'expired' | 'invalid' | 'configuration_error'
  installation_id?: string
  expires_at?: string
}

export type SupportStatus = {
  active: boolean
  port: number | null
  expires_at: string | null
  checked_at: string | null
}

export const deploymentAccess = {
  activation: (token: string) =>
    request<ActivationStatus>('/api/v1/activation', { headers: { Authorization: `Bearer ${token}` } }),
  install: (token: string, content: string) => request<ActivationStatus>('/api/v1/activation', {
    method: 'PUT', body: JSON.stringify({ content }), headers: { Authorization: `Bearer ${token}` }
  }),
  support: (token: string) =>
    request<SupportStatus>('/api/v1/support/session', { headers: { Authorization: `Bearer ${token}` } }),
  openSupport: (token: string, minutes: number) =>
    request<SupportStatus & { access_token: string }>('/api/v1/support/session', {
      method: 'POST', body: JSON.stringify({ minutes }), headers: { Authorization: `Bearer ${token}` }, timeoutMs: 20000
    }),
  refreshSnapshot: (token: string) => request<SupportStatus>('/api/v1/support/session/refresh', {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, timeoutMs: 20000
  }),
  closeSupport: (token: string) => request<void>('/api/v1/support/session', {
    method: 'DELETE', headers: { Authorization: `Bearer ${token}` }
  })
}
