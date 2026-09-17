/** spectrumViewer requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'

export type SpectrumRecordSummary = {
  id: string
  kind: 'raw' | 'result'
  source_sha256: string
  record_index: number
  format: string
  sample_name: string | null
  sample_names?: string[]
  band_name: string | null
  measure_time: string | null
  angle_deg?: number | null
  frame_count?: number
  ccd_count?: number
  points_per_ccd?: number
  line_count?: number
  band_count?: number
  sample_count?: number
  matrix_kind?: string | null
  available?: Record<string, boolean>
}

export type SpectrumPoint = {
  point_index: number
  step?: number
  wavelength_nm?: number | null
  x?: number
  value?: number
  adc?: number
  peak?: number
  back?: number
  sample_index?: number | null
  repeat_index?: number | null
  sample_name?: string | null
}

export type SpectrumRecord = {
  id: string
  kind: 'raw' | 'result'
  format: string
  source_sha256: string
  record_index: number
  sample_name?: string | null
  sample_names?: string[]
  sample_reps?: number[]
  band_name?: string | null
  measure_time: string | null
  reference_step?: number | null
  angle_deg?: number | null
  exposure_segment?: { start: number; end: number; count: number } | null
  layout?: Record<string, unknown>
  ignition?: Record<string, unknown>
  bad_frame_indices?: Array<Record<string, unknown>>
  ccd?: { position: number; index: number; points: SpectrumPoint[] }
  frame_detail?: { phase: string; index: number; frame_count: number; ccd: { position: number; index: number; points: SpectrumPoint[] } } | null
  line_count?: number
  band_count?: number
  matrix_kind?: string
  matrix_order?: string
  exposure_segments?: Array<Record<string, number>>
  sample_rows?: Array<Record<string, unknown>>
  line?: Record<string, unknown> & { points: SpectrumPoint[] }
}

export const spectrumViewerApi = {
  spectrumRecords: (token: string, kind = 'all', angleDeg?: number) => {
    const query = new URLSearchParams({ kind })
    if (angleDeg !== undefined) query.set('angle_deg', String(angleDeg))
    return request<SpectrumRecordSummary[]>(`/api/v1/spectra/records?${query}`, { headers: { Authorization: `Bearer ${token}` } })
  },
  spectrum: (token: string, recordId: string, params: { ccd?: number; line?: number; detail?: 'summary' | 'frame'; phase?: 'burn' | 'dark'; frame?: number; exposureStart?: number; exposureEnd?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.ccd !== undefined) query.set('ccd', String(params.ccd))
    if (params.line !== undefined) query.set('line', String(params.line))
    if (params.detail) query.set('detail', params.detail)
    if (params.phase) query.set('phase', params.phase)
    if (params.frame !== undefined) query.set('frame', String(params.frame))
    if (params.exposureStart !== undefined) query.set('exposure_start', String(params.exposureStart))
    if (params.exposureEnd !== undefined) query.set('exposure_end', String(params.exposureEnd))
    return request<SpectrumRecord>(`/api/v1/spectra/${encodeURIComponent(recordId)}${query.size ? `?${query}` : ''}`, { headers: { Authorization: `Bearer ${token}` } })
  },
  exportSpectrum: async (token: string, recordId: string, params: { ccd: number; line: number; detail?: 'summary' | 'frame'; phase?: 'burn' | 'dark'; frame?: number; exposureStart?: number; exposureEnd?: number; xMin: number; xMax: number; referenceShift: number }) => {
    const query = new URLSearchParams({ ccd: String(params.ccd), line: String(params.line), x_min: String(params.xMin), x_max: String(params.xMax), reference_shift: String(params.referenceShift) })
    if (params.detail) query.set('detail', params.detail)
    if (params.phase) query.set('phase', params.phase)
    if (params.frame !== undefined) query.set('frame', String(params.frame))
    if (params.exposureStart !== undefined) query.set('exposure_start', String(params.exposureStart))
    if (params.exposureEnd !== undefined) query.set('exposure_end', String(params.exposureEnd))
    const response = await requestRaw(`/api/v1/spectra/${encodeURIComponent(recordId)}/export?${query}`, { headers: { Authorization: `Bearer ${token}` } })
    return { blob: await response.blob(), filename: response.headers.get('Content-Disposition') ?? `spectrum-${recordId}.csv` }
  },
  auditSpectrumPrint: (token: string, recordId: string, payload: { visible_x_min: number; visible_x_max: number; visible_y_min: number; visible_y_max: number; ccd: number; line: number; mode: 'mean' | 'peak' | 'back' | 'value' | 'frame'; reference_shift: number; selected_record_ids: string[] }) =>
    request<{ status: string }>(`/api/v1/spectra/${encodeURIComponent(recordId)}/print`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  printSpectrumPdf: async (token: string, recordId: string, payload: { visible_x_min: number; visible_x_max: number; visible_y_min: number; visible_y_max: number; ccd: number; line: number; mode: 'mean' | 'peak' | 'back' | 'value' | 'frame'; reference_shift: number; selected_record_ids: string[]; priority_record_id?: string; frame_phase: 'burn' | 'dark'; frame_index: number; exposure_start?: number; exposure_end?: number }) => {
    const response = await requestRaw(`/api/v1/spectra/${encodeURIComponent(recordId)}/print-pdf`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) })
    return { blob: await response.blob(), filename: response.headers.get('Content-Disposition') ?? `spectrum-${recordId.replace(':', '-')}.pdf`, curveCount: Number(response.headers.get('X-Curve-Count') ?? 0), pointCount: Number(response.headers.get('X-Visible-Point-Count') ?? 0) }
  },
}
