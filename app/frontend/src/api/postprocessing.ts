/** postprocessing requests and models; moved without changing payloads or responses. */
import { request } from './client'
import type { AnalysisCurvePoint, AnalysisCurveSnapshot } from './analysis'

export type PostProcessingRecord = {
  id: string
  kind: 'raw'
  format: 'edt' | 'cmt'
  source_sha256: string
  record_index: number
  sample_name: string | null
  band_name: string | null
  measure_time: string | null
  frame_count: number
  ccd_count: number
  points_per_ccd: number
  ccd_indices: number[]
  ignition: Record<string, number>
}

export type PreparedTarget = {
  id: string; name: string; storage_mode: 'averaged' | 'full_interval'; method_version_id: number | null
  legacy_method_id: number | null; revision: number; updated_at: string
  records: Array<{ id: number; task_id: number; name: string; measure_time: string | null
    source_record_id: string; start_frame: number; end_frame: number
    source_task_id?: number; source_sha256?: string; source_viewer_group?: string }>
}

export type PreparedImportOptions = {
  method: { id: number | null; title: string | null; version_id: number | null }
  sources: Array<{ sha256: string; name: string; path: string | null; record_count: number }>
  acquisition_sources?: Array<{ task_id: number; name: string; record_count: number; angle_deg: number | null }>
  targets: PreparedTarget[]
  records: Array<PostProcessingRecord | (Omit<PostProcessingRecord, 'kind' | 'format'> & {
    kind: 'sample'; format: 'acquisition'; viewer_group: string
  })>
  saved_dispersion: { method_version_id: number; updated_at: string } | null
}

export type PreparedImportInput = {
  request_id: string; source_sha256?: string; source_task_id?: number; record_ids: string[]; target_name: string
  storage_mode: 'averaged' | 'full_interval'; start_frame: number; end_frame: number
  use_method_id: boolean; same_name_strategy: 'error' | 'replace' | 'append'
  expected_target_revision?: number; expected_method_version_id: number
}

export type PostProcessingRecalculationOptions = {
  methods: Array<{ method_version_id: number; method_id: number; version: number; name: string }>
  sources: Array<{
    id: string
    kind: 'result' | 'sample'
    format?: string
    label: string
    source_sha256: string | null
    method_id?: number | null
    method_version_id?: number | null
    method_match_status?: string | null
    measure_time?: string | null
  }>
  curve_snapshots: Array<{
    id: number
    line_id: string
    fit_mode: AnalysisCurveSnapshot['fit_mode']
    coordinate_type: AnalysisCurveSnapshot['coordinate_type']
    result_sha256: string
    method_version_id: number
    calculation_profile: 'legacy_2_0_2' | 'modern_v1'
    method_name: string
    method_version: number
    element?: string
    wavelength_nm?: number
  }>
}

export type RecalculationCurveDraft = Pick<AnalysisCurveSnapshot, 'fit_mode' | 'coordinate_type'> & {
  points: Array<Pick<AnalysisCurvePoint, 'point_index' | 'active' | 'adjusted_intensity'>>
}

export type RecalculationCurveDetail = {
  line_id: string
  element: string
  wavelength_nm: number
  unit: string
  decimal_places?: number
  snapshot: AnalysisCurveSnapshot
}

export type PostProcessingInterval = {
  id: string
  source_sha256: string
  measure_time: string | null
  ccd: number
  phase: string
  start_frame: number
  end_frame: number
  frame_count: number
  points_per_ccd: number
  frames: Array<{ frame_index: number; adc: number[]; sha256: string }>
  mean: { values: number[]; sha256: string }
}

export type PostProcessingRun = {
  id: string
  status: string
  input_sha256: string
  source_record_ids?: string[]
  source_hashes?: string[]
  sample_ids?: number[]
  task_ids?: number[]
  result?: Record<string, unknown> & { sources?: Array<{ lines?: Array<{
    line_id: string; sample_name: string; quantitative_signal: number; calculated_value: number; curve_snapshot_id: number
  }> }> }
  report: Record<string, unknown>
  result_sha256?: string
}

export type PostProcessingExport = {
  id: string
  status: string
  input_sha256: string
  path: string
  content_sha256: string
  byte_length: number
  report: Record<string, unknown>
}

export const postprocessingApi = {
  preparedImportOptions: (token: string, source?: string) => request<PreparedImportOptions>(
    '/api/v1/postprocessing/prepared-import' + (source?.startsWith('task:')
      ? `?source_task_id=${encodeURIComponent(source.slice(5))}`
      : source ? `?source_sha256=${encodeURIComponent(source)}` : ''),
    { headers: { Authorization: `Bearer ${token}` } }),
  importPreparedRecords: (token: string, payload: PreparedImportInput) => request<{ run_id: string; reused: boolean; target: PreparedTarget }>(
    '/api/v1/postprocessing/prepared-import', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  savePreparedDispersion: (token: string, source_sha256: string, expected_method_version_id: number) => request<{ message: string }>(
    '/api/v1/postprocessing/prepared-dispersion', { method: 'POST', headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ source_sha256, expected_method_version_id }) }),
  postprocessingEdtRecords: (token: string) =>
    request<{ records: PostProcessingRecord[] }>('/api/v1/postprocessing/edt-records', {
      headers: { Authorization: `Bearer ${token}` }
    }),
  postprocessingRecalculationOptions: (token: string) =>
    request<PostProcessingRecalculationOptions>('/api/v1/postprocessing/recalculation-options', {
      headers: { Authorization: `Bearer ${token}` }
    }),
  postprocessingRecalculationCurve: (token: string, snapshotId: number) =>
    request<RecalculationCurveDetail>(`/api/v1/postprocessing/recalculation-curves/${snapshotId}`, {
      headers: { Authorization: `Bearer ${token}` }
    }),
  fitPostprocessingRecalculationCurve: (token: string, snapshotId: number, draft: RecalculationCurveDraft) =>
    request<RecalculationCurveDetail>(`/api/v1/postprocessing/recalculation-curves/${snapshotId}/fit`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(draft)
    }),
  postprocessingInterval: (
    token: string,
    recordId: string,
    params: { ccd: number; startFrame: number; endFrame: number; phase?: 'burn' | 'dark' }
  ) => {
    const query = new URLSearchParams({
      ccd: String(params.ccd),
      start_frame: String(params.startFrame),
      end_frame: String(params.endFrame),
      phase: params.phase ?? 'burn'
    })
    return request<PostProcessingInterval>(
      `/api/v1/postprocessing/raw/${encodeURIComponent(recordId)}/interval?${query}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
  },
  postprocessingConversions: (token: string) =>
    request<{ runs: PostProcessingRun[] }>('/api/v1/postprocessing/conversions', {
      headers: { Authorization: `Bearer ${token}` }
    }),
  convertPostprocessingEdt: (
    token: string,
    payload: {
      record_ids: string[]
      start_frame: number
      end_frame?: number
      target_ccd_layout_id: number
      target_ccd_indices?: number[]
      method_version_id?: number
      name?: string
    }
  ) =>
    request<PostProcessingRun>('/api/v1/postprocessing/conversions', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  postprocessingRecalculations: (token: string) =>
    request<{ runs: PostProcessingRun[] }>('/api/v1/postprocessing/recalculations', {
      headers: { Authorization: `Bearer ${token}` }
    }),
  recalculatePostprocessing: (
    token: string,
    payload: {
      source_record_ids: string[]
      method_version_id: number
      calculation_profile: 'legacy_2_0_2' | 'modern_v1'
      curve_snapshot_ids: number[]
      curve_drafts?: Record<number, RecalculationCurveDraft>
      expected_measure_time?: string
      allow_older_method?: boolean
    }
  ) =>
    request<PostProcessingRun>('/api/v1/postprocessing/recalculations', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  exportPostprocessing: (
    token: string,
    payload: {
      record_ids: string[]
      kind: 'raw_intensity' | 'processed_intensity' | 'result_matrix'
      format: 'txt' | 'csv' | 'excel'
      output_directory: string
      filename: string
      same_name_strategy: 'suffix' | 'error' | 'overwrite'
    }
  ) =>
    request<PostProcessingExport>('/api/v1/postprocessing/exports', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    })
}
