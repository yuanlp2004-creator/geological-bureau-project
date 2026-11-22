/** spectrumViewer requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'

export type SpectrumRecordSummary = {
  file_group_key?: string
  file_group_name?: string
  id: string
  kind: 'raw' | 'result' | 'sample'
  source_sha256: string
  record_index: number
  band_id?: number | null
  coordinate_system?: string
  format: string
  sample_name: string | null
  sample_names?: string[]
  band_name: string | null
  measure_time: string | null
  angle_deg?: number | null
  turn_index?: number
  frame_count?: number | null
  burn_count?: number | null
  ccd_count?: number
  points_per_ccd?: number
  line_count?: number
  band_count?: number
  sample_count?: number
  matrix_kind?: string | null
  available?: Record<string, boolean>
  sample_no?: number | null
  task_id?: number
  task_name?: string
  task_kind?: 'sample' | 'evaporation'
  repeat_index?: number
  storage_mode?: string
  method_id?: number | null
  method_version?: number | null
}

export type SpectrumFileSummary = {key:string;id:string;kind:string;format:string;source_sha256:string;source_filename?:string;task_id?:number;task_name?:string;task_kind?:string;record_count:number}

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
  intensity_mode?: "stored"|"legacy_2_0_2"
  id: string
  kind: 'raw' | 'result' | 'sample'
  coordinate_system?: string
  format: string
  source_sha256: string
  record_index: number
  band_id?: number | null
  observation_lines?: Array<{id:string;element:string;wavelength_nm:number;ccd_index:number|null;point_index:number|null;exposure_start_frame?:number|null;exposure_end_frame?:number|null}>
  sample_name?: string | null
  sample_names?: string[]
  sample_reps?: number[]
  band_name?: string | null
  measure_time: string | null
  task_id?: number
  task_name?: string
  task_kind?: 'sample' | 'evaporation'
  repeat_index?: number
  storage_mode?: string
  method_id?: number | null
  method_version?: number | null
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

export type SpectrumPointFrames = Omit<SpectrumPointDetails, 'rows' | 'point_index' | 'wavelength_nm' | 'sha256'> & {
  point_count: number; frames_base64: string; wavelengths_nm?: (number | null)[]
}
export type PointDetailsAnalysis = { runId: number; samplePosition: number; bandPosition?: number }

export type SpectrumCalibrationPosition = {
  id: string; element: string; reference: boolean; ccd: number | null; point: number | null
  wavelength_nm: number | null; offset_points: number | null; reference_shift: number | null
}

export type SpectrumConcentrationPreview = {
  method_name: string
  method_version: number
  rows: Array<{
    line_id: string
    element: string
    wavelength_nm: number
    concentration: number | null
    unit: string
    decimal_places: number
    curve_source: 'published' | 'method_standards' | null
    message: string | null
  }>
}

export const spectrumPointDetailsPath = (recordId: string, analysis?: PointDetailsAnalysis) =>
  analysis ? `/api/v1/analyses/runs/${analysis.runId}/spectra/${analysis.samplePosition}/point-details`
    : recordId.startsWith('dispersion:') ? `/api/v1/dispersion/tasks/${encodeURIComponent(recordId.slice('dispersion:'.length))}/point-details`
    : `/api/v1/spectra/${encodeURIComponent(recordId)}/point-details`

const spectrumPointQuery = (ccd: number, point: number, analysis?: PointDetailsAnalysis) =>
  `ccd=${ccd}&point=${point}${analysis?.bandPosition == null ? '' : `&band_position=${analysis.bandPosition}`}`

export const spectrumViewerApi = {
  spectrumConcentrations: (token: string, recordId: string, signal: AbortSignal) =>
    request<SpectrumConcentrationPreview>(`/api/v1/spectra/${encodeURIComponent(recordId)}/concentrations`, {
      headers: { Authorization: `Bearer ${token}` }, signal,
    }),
  calibrateSpectrum: (token: string, recordId: string, ccd: number, scope: 'reference' | 'all', interval?: [number, number]) => {
    const query = new URLSearchParams({ ccd: String(ccd), scope })
    if (interval) {
      query.set('exposure_start', String(interval[0]))
      query.set('exposure_end', String(interval[1]))
    }
    return request<{ positions: SpectrumCalibrationPosition[] }>(
      `/api/v1/spectra/${encodeURIComponent(recordId)}/calibration?${query}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
  },
  spectrumDisplayProfiles: (token: string) => request<Array<{id:number;name:string;screen_width_mm:number;screen_resolution_px:number}>>('/api/v1/spectra/display-profiles', {headers:{Authorization:`Bearer ${token}`}}),
  copySpectrumPointDetails: (token: string, recordId: string, ccd: number, point: number, vertical: boolean,
    analysis?: PointDetailsAnalysis) =>
    request<{ text: string; sha256: string }>(`${spectrumPointDetailsPath(recordId, analysis)}/copy?${spectrumPointQuery(ccd, point, analysis)}&orientation=${vertical ? 'vertical' : 'horizontal'}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    }),
  spectrumPointDetails: (token: string, recordId: string, ccd: number, point: number,
    analysis?: PointDetailsAnalysis) =>
    request<SpectrumPointDetails>(`${spectrumPointDetailsPath(recordId, analysis)}?${spectrumPointQuery(ccd, point, analysis)}`, {
      headers: { Authorization: `Bearer ${token}` }
    }),
  spectrumPointFrames: (token: string, recordId: string, ccd: number, analysis?: PointDetailsAnalysis, signal?: AbortSignal) =>
    request<SpectrumPointFrames>(`${spectrumPointDetailsPath(recordId, analysis)}?${spectrumPointQuery(ccd, 0, analysis)}&all_points=true`, {
      headers: { Authorization: `Bearer ${token}` }, signal
    }),
  printSpectrumPointDetails: async (token: string, recordId: string, ccd: number, point: number,
    analysis?: PointDetailsAnalysis) =>
    (await requestRaw(`${spectrumPointDetailsPath(recordId, analysis)}/print?${spectrumPointQuery(ccd, point, analysis)}`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }
    })).blob(),
  spectrumFiles: (token:string, scope='all',kind='all',search='',angleDeg?:number) => {
    const query=new URLSearchParams({scope,kind,query:search})
    if(angleDeg!==undefined)query.set('angle_deg',String(angleDeg))
    return request<SpectrumFileSummary[]>(`/api/v1/spectra/files?${query}`,{headers:{Authorization:`Bearer ${token}`}})
  },
  spectrumRecords: (token: string, kind = 'all', angleDeg?: number, offset = 0, search = '', scope = 'all', group = '') => {
    const query = new URLSearchParams({ kind, offset: String(offset), query: search })
    if(scope!=='all')query.set('scope',scope)
    if(group)query.set('group',group)
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
      intensityMode?: "stored"|"legacy_2_0_2"
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
    if(params.intensityMode)query.set('intensity_mode',params.intensityMode)
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
      intensityMode?: "stored"|"legacy_2_0_2"
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
    if(params.intensityMode)query.set('intensity_mode',params.intensityMode)
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
      intensity_mode?: 'stored'|'legacy_2_0_2'
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
