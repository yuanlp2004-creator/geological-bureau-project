/** legacySources requests and models; moved without changing payloads or responses. */
import { request } from './client'

export type LegacySourceKind = 'legacy-migration' | 'spectrum-migration' | 'result-migration'

export type LegacySource = {
  path: string; name: string; directory: string; size: number; missing: string[]
  paths: { mtd_path?: string; cfg_path?: string; opt_path?: string }
}

export type LegacySourceScan = { candidates: LegacySource[]; roots: string[]; warnings: string[]; truncated: boolean }

export const legacySourcesApi = {
  discoverLegacySources: (token: string, kind: LegacySourceKind, root?: string) => request<LegacySourceScan>(`/api/v1/${kind}/sources${root ? `?root=${encodeURIComponent(root)}` : ''}`, { headers: { Authorization: `Bearer ${token}` } }),
}
