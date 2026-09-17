/** resultMigration requests and models; moved without changing payloads or responses. */
import { request } from './client'

export type ResultMigrationDiagnostic = {
  available: boolean
  code: string
  message: string
  formats: string[]
  headers: Record<string, string | string[]>
  read_only: boolean
  parser_version: string
  short_strings: Record<string, number>
}

export type ResultMigrationRun = {
  id: string
  fingerprint: string
  format: 'dat' | 'pdt'
  status: 'staged' | 'committed' | 'failed'
  source_file: { path: string; name: string; size: number; mtime_ns: number; sha256: string }
  parser: { parser_version: string; header: number; endianness: string; encoding: string }
  report: {
    phase: string
    format: string
    counts: { files: number; samples: number; lines: number; bands: number; matrix_values: number }
    checks: Record<string, boolean | null>
    issues: Array<{ level: string; code: string; message: string }>
    method_match_status: string
    sampled_values: Array<Record<string, unknown>>
    imported?: { result_matrices: number }
  }
  staging?: {
    records: Array<{
      header: number
      format: string
      method_legacy_id: number | null
      method_target_id: number | null
      method_match_status: string
      measure_time: string
      sample_count: number
      line_count: number
      band_count: number
      sample_names: string[]
      sample_reps: number[]
      sample_rows: Array<Record<string, unknown>>
      lines: Array<Record<string, unknown>>
      exposure_segments: Array<Record<string, number>>
      matrix_kind: string
      matrix_order: string
      matrix_sha256: string
      matrix_samples: Array<Record<string, unknown>>
      endianness: string
      encoding: string
    }>
    record_count: number
    parser_version: string
    issues: Array<{ level: string; code: string; message: string }>
  }
  error: { code: string; message: string } | null
  created_at: string
  updated_at: string
  committed_at: string | null
  already_committed?: boolean
}

export const resultMigrationApi = {
  resultMigrationDiagnostics: (token: string) => request<ResultMigrationDiagnostic>('/api/v1/result-migration/diagnostics', { headers: { Authorization: `Bearer ${token}` } }),
  resultMigrationRuns: (token: string) => request<{ runs: ResultMigrationRun[] }>('/api/v1/result-migration/runs', { headers: { Authorization: `Bearer ${token}` } }),
  stageResultMigration: (token: string, path: string) => request<ResultMigrationRun>('/api/v1/result-migration/stage', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ path }) }),
  commitResultMigration: (token: string, runId: string) => request<ResultMigrationRun>('/api/v1/result-migration/commit', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ run_id: runId }) }),
  resultMigrationRun: (token: string, runId: string) => request<ResultMigrationRun>(`/api/v1/result-migration/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
}
