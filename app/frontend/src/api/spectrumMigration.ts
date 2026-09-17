/** spectrumMigration requests and models; moved without changing payloads or responses. */
import { request } from './client'
import type { LegacyMigrationDiagnostic } from './legacyMigration'

export type SpectrumMigrationDiagnostic = LegacyMigrationDiagnostic & {
  formats: string[]
  layout_tables: string[]
  read_only: boolean
  parser_version: string
}

export type SpectrumMigrationRun = {
  id: string
  fingerprint: string
  format: 'cdt' | 'cmt' | 'edt' | 'wdt'
  status: 'staged' | 'committed' | 'failed'
  source_file: { path: string; name: string; size: number; mtime_ns: number; sha256: string }
  reader: Record<string, unknown>
  report: {
    phase: string
    format: string
    record_count: number
    table_counts: Record<string, number>
    checks: Record<string, boolean>
    issues: Array<{ level: string; code: string; message: string }>
    atomic_scope: string
    already_committed: boolean
    imported?: { spectrum_bands: number }
  }
  staging?: {
    format: string
    record_count: number
    table_counts: Record<string, number>
    layout: { frame_count: number; ccds_per_frame: number; points_per_ccd: number; ccd_count: number; ccd_indices: number[]; endianness: string }
    ignition: { present: boolean; pre_burn: number | null; burn_cyc: number | null; dark_cyc: number | null; burn_count: number; dark_count: number }
    records: Array<{ layout: Record<string, unknown>; sampled_values: Record<string, unknown>; bad_frame_indices: Array<Record<string, unknown>>; [key: string]: unknown }>
    checks: Record<string, boolean>
    issues: Array<{ level: string; code: string; message: string }>
    parser_version: string
  }
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
  committed_at: string | null
  already_committed?: boolean
}

export const spectrumMigrationApi = {
  spectrumMigrationDiagnostics: (token: string) => request<SpectrumMigrationDiagnostic>('/api/v1/spectrum-migration/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  spectrumMigrationRuns: (token: string) => request<{ runs: SpectrumMigrationRun[] }>('/api/v1/spectrum-migration/runs', { headers: { Authorization: `Bearer ${token}` } }),
  stageSpectrumMigration: (token: string, path: string) => request<SpectrumMigrationRun>('/api/v1/spectrum-migration/stage', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ path }) }),
  commitSpectrumMigration: (token: string, runId: string) => request<SpectrumMigrationRun>('/api/v1/spectrum-migration/commit', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ run_id: runId }) }),
  spectrumMigrationRun: (token: string, runId: string) => request<SpectrumMigrationRun>(`/api/v1/spectrum-migration/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
}
