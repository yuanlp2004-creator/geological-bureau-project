/** spectrumViewer requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'

export type SpectrumRecordSummary = {
  id: string
  kind: 'raw' | 'result' | 'sample'
  source_sha256: string
  record_index: number
  coordinate_system?: string
  format: string
  sample_name: string | null
  sample_names?: string[]
  band_name: string | null
  measure_time: string | null
  angle_deg?: number | null
  frame_count?: number | null
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
  kind: 'raw' | 'result' | 'sample'
  coordinate_system?: string
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
  frame_detail?: {
    phase: string
    index: number
    frame_count: number
    ccd: { position: number; index: number; points: SpectrumPoint[] }
  } | null
  line_count?: number
  band_count?: number
  matrix_kind?: string
  matrix_order?: string
  exposure_segments?: Array<Record<string, number>>
  sample_rows?: Array<Record<string, unknown>>
  line?: Record<string, unknown> & { points: SpectrumPoint[] }
}

export type SpectrumPointDetails = {
  record_id: string; sample_name: string; ccd_index: number; point_index: number
  wavelength_nm: number | null; pre_excitation_seconds: number | null
  burn_cycle_seconds: number | null; dark_cycle_seconds: number | null
  burn_count: number; dark_count: number; source_sha256: string; sha256: string
  rows: Array<{ phase: 'burn' | 'dark'; integration: number; value: number }>
}

export const spectrumPointDetailsPath = (recordId: string, analysis?: { runId: number; samplePosition: number }) =>
  analysis ? `/api/v1/analyses/runs/${analysis.runId}/spectra/${analysis.samplePosition}/point-details`
    : `/api/v1/spectra/${encodeURIComponent(recordId)}/point-details`

export const spectrumViewerApi = {
  spectrumDisplayProfiles: (token: string) => request<Array<{id:number;name:string;screen_width_mm:number;screen_resolution_px:number}>>('/api/v1/spectra/display-profiles', {headers:{Authorization:`Bearer ${token}`}}),
  copySpectrumPointDetails: (token: string, recordId: string, ccd: number, point: number, vertical: boolean,
    analysis?: { runId: number; samplePosition: number }) =>
    request<{ text: string; sha256: string }>(`${spectrumPointDetailsPath(recordId, analysis)}/copy?ccd=${ccd}&point=${point}&orientation=${vertical ? 'vertical' : 'horizontal'}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    }),
  spectrumPointDetails: (token: string, recordId: string, ccd: number, point: number,
    analysis?: { runId: number; samplePosition: number }) =>
    request<SpectrumPointDetails>(`${spectrumPointDetailsPath(recordId, analysis)}?ccd=${ccd}&point=${point}`, {
      headers: { Authorization: `Bearer ${token}` }
    }),
  printSpectrumPointDetails: async (token: string, recordId: string, ccd: number, point: number,
    analysis?: { runId: number; samplePosition: number }) =>
    (await requestRaw(`${spectrumPointDetailsPath(recordId, analysis)}/print?ccd=${ccd}&point=${point}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    })).blob(),
  spectrumRecords: (token: string, kind = 'all', angleDeg?: number, offset = 0, search = '') => {
    const query = new URLSearchParams({ kind, offset: String(offset), query: search })
    if (angleDeg !== undefined) query.set('angle_deg', String(angleDeg))
    return request<SpectrumRecordSummary[]>(`/api/v1/spectra/records?${query}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
  },
  spectrum: (
    token: string,
    recordId: string,
    params: {
      ccd?: number
      line?: number
      detail?: 'summary' | 'frame'
      phase?: 'burn' | 'dark'
      frame?: number
      exposureStart?: number
      exposureEnd?: number
    } = {}
  ) => {
    const query = new URLSearchParams()
    if (params.ccd !== undefined) query.set('ccd', String(params.ccd))
    if (params.line !== undefined) query.set('line', String(params.line))
    if (params.detail) query.set('detail', params.detail)
    if (params.phase) query.set('phase', params.phase)
    if (params.frame !== undefined) query.set('frame', String(params.frame))
    if (params.exposureStart !== undefined) query.set('exposure_start', String(params.exposureStart))
    if (params.exposureEnd !== undefined) query.set('exposure_end', String(params.exposureEnd))
    return request<SpectrumRecord>(`/api/v1/spectra/${encodeURIComponent(recordId)}${query.size ? `?${query}` : ''}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
  },
  exportSpectrum: async (
    token: string,
    recordId: string,
    params: {
      ccd: number
      line: number
      detail?: 'summary' | 'frame'
      phase?: 'burn' | 'dark'
      frame?: number
      exposureStart?: number
      exposureEnd?: number
      xMin: number
      xMax: number
      referenceShift: number
    }
  ) => {
    const query = new URLSearchParams({
      ccd: String(params.ccd),
      line: String(params.line),
      x_min: String(params.xMin),
      x_max: String(params.xMax),
      reference_shift: String(params.referenceShift)
    })
    if (params.detail) query.set('detail', params.detail)
    if (params.phase) query.set('phase', params.phase)
    if (params.frame !== undefined) query.set('frame', String(params.frame))
    if (params.exposureStart !== undefined) query.set('exposure_start', String(params.exposureStart))
    if (params.exposureEnd !== undefined) query.set('exposure_end', String(params.exposureEnd))
    const response = await requestRaw(`/api/v1/spectra/${encodeURIComponent(recordId)}/export?${query}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    return {
      blob: await response.blob(),
      filename: response.headers.get('Content-Disposition') ?? `spectrum-${recordId}.csv`
    }
  },
  auditSpectrumPrint: (
    token: string,
    recordId: string,
    payload: {
      visible_x_min: number
      visible_x_max: number
      visible_y_min: number
      visible_y_max: number
      ccd: number
      line: number
      mode: 'mean' | 'peak' | 'back' | 'value' | 'frame'
      reference_shift: number
      selected_record_ids: string[]
    }
  ) =>
    request<{ status: string }>(`/api/v1/spectra/${encodeURIComponent(recordId)}/print`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  printSpectrumPdf: async (
    token: string,
    recordId: string,
    payload: {
      print_scope?: 'visible' | 'ccd'
      print_layers?: Array<'curve' | 'grayscale'>
      print_scale?: 'fit_long' | 'fit_short' | 'ccd_10x'
      paper?: 'A4' | 'A3' | 'Letter'
      visible_x_min: number
      visible_x_max: number
      visible_y_min: number
      visible_y_max: number
      ccd: number
      line: number
      mode: 'mean' | 'peak' | 'back' | 'value' | 'frame'
      reference_shift: number
      selected_record_ids: string[]
      priority_record_id?: string
      frame_phase: 'burn' | 'dark'
      frame_index: number
      exposure_start?: number
      exposure_end?: number
    }
  ) => {
    const response = await requestRaw(`/api/v1/spectra/${encodeURIComponent(recordId)}/print-pdf`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    })
    return {
      blob: await response.blob(),
      filename: response.headers.get('Content-Disposition') ?? `spectrum-${recordId.replace(':', '-')}.pdf`,
      curveCount: Number(response.headers.get('X-Curve-Count') ?? 0),
      pointCount: Number(response.headers.get('X-Visible-Point-Count') ?? 0)
    }
  }
}
