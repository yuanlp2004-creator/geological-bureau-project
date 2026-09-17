/** maintenance requests and models; moved without changing payloads or responses. */
import { request } from './client'

export type BackupRecord = {
  id: string
  kind: string
  source_path: string
  backup_path: string
  source_sha256: string
  backup_sha256: string
  byte_length: number
  integrity: string
  foreign_keys: number
  entity_counts: Record<string, number>
  blob_samples: Array<{ table: string; rowid: number; sha256: string; byte_length: number }>
  retention_expires_at: string | null
  status: string
  created_at: string
  completed_at: string | null
}

export type MaintenanceStatus = { database_path: string; database_bytes: number; wal_bytes: number; integrity: string; foreign_key_errors: number; backups: BackupRecord[]; operations: Array<{ id: string; operation: string; status: string; details: Record<string, unknown>; created_at: string }> }

export type HelpTopic = { slug: string; title: string; section: string; keywords: string[]; body: string; related_routes: string[]; updated_at: string }

export const maintenanceApi = {
  maintenanceStatus: (token: string) => request<MaintenanceStatus>('/api/v1/maintenance/status', { headers: { Authorization: `Bearer ${token}` } }),
  createBackup: (token: string, payload: { output_directory: string; filename?: string; retention_days: number }) => request<Record<string, unknown>>('/api/v1/backups', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  verifyBackup: (token: string, id: string) => request<Record<string, unknown>>(`/api/v1/backups/${encodeURIComponent(id)}/verify`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  restoreRehearsal: (token: string, id: string) => request<Record<string, unknown>>(`/api/v1/backups/${encodeURIComponent(id)}/restore-rehearsal`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  maintenanceAction: (token: string, action: 'checkpoint' | 'optimize' | 'reclaim' | 'logs/cleanup' | 'temp/cleanup' | 'retention', payload: Record<string, unknown> = {}) => request<Record<string, unknown>>(`/api/v1/${action === 'retention' ? 'backups/retention' : `maintenance/${action}`}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  helpTopics: (token: string, query = '') => request<HelpTopic[]>(`/api/v1/help/topics${query ? `?q=${encodeURIComponent(query)}` : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
  helpTopic: (token: string, slug: string) => request<HelpTopic>(`/api/v1/help/topics/${encodeURIComponent(slug)}`, { headers: { Authorization: `Bearer ${token}` } }),
}
