/** legacyMigration requests and models; moved without changing payloads or responses. */
import { request } from './client'

export type LegacyMigrationDiagnostic = {
  available: boolean
  code: string
  message: string
  reader: string | null
  provider: string
  process_bits: number | null
  attempts: Array<Record<string, unknown>>
}

export type LegacyMigrationIssue = {
  level: 'warning' | 'error' | 'info'
  code: string
  field?: string
  message: string
}

export type LegacyMigrationRun = {
  id: string
  fingerprint: string
  status: 'staged' | 'committed' | 'failed'
  source_files: Record<string, { path: string; name: string; size: number; mtime_ns: number; sha256: string }>
  reader: LegacyMigrationDiagnostic
  report: {
    phase: string
    counts: { methods: number; spectral_lines: number; dispersion_curves: number; users_ignored: number }
    checks: Record<string, boolean>
    issues: LegacyMigrationIssue[]
    atomic_scope: string
    already_committed: boolean
    imported?: Record<string, unknown>
  }
  staging?: {
    counts: { methods: number; spectral_lines: number; dispersion_curves: number; users_ignored: number }
    checks: Record<string, boolean>
    issues: LegacyMigrationIssue[]
    configuration: {
      cfg: { encoding: string; sections: Record<string, Record<string, string>>; normalized: Record<string, unknown> }
      opt: { encoding: string; sections: Record<string, Record<string, string>>; normalized: Record<string, unknown> }
    }
  }
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
  committed_at: string | null
  already_committed?: boolean
}

export const legacyMigrationApi = {
  legacyMigrationDiagnostics: (token: string) => request<LegacyMigrationDiagnostic>('/api/v1/legacy-migration/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  legacyMigrationRuns: (token: string) => request<{ runs: LegacyMigrationRun[] }>('/api/v1/legacy-migration/runs', { headers: { Authorization: `Bearer ${token}` } }),
  stageLegacyMigration: (token: string, payload: { mtd_path: string; cfg_path: string; opt_path: string }) => request<LegacyMigrationRun>('/api/v1/legacy-migration/stage', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  commitLegacyMigration: (token: string, runId: string) => request<LegacyMigrationRun>('/api/v1/legacy-migration/commit', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ run_id: runId }) }),
  legacyMigrationRun: (token: string, runId: string) => request<LegacyMigrationRun>(`/api/v1/legacy-migration/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
}
