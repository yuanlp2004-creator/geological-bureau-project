/** postprocessing requests and models; moved without changing payloads or responses. */
import { request } from './client'

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

export type PostProcessingRecalculationOptions = {
  methods: Array<{ method_version_id: number; method_id: number; version: number; name: string }>
  sources: Array<{ id: string; kind: 'result' | 'sample'; label: string; source_sha256: string | null; method_id?: number | null; method_version_id?: number | null; method_match_status?: string | null; measure_time?: string | null }>
  curve_snapshots: Array<{ id: number; line_id: string; fit_mode: string; coordinate_type: string; result_sha256: string; method_version_id: number; calculation_profile: 'legacy_2_0_2' | 'modern_v1'; method_name: string; method_version: number }>
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
  result?: Record<string, unknown>
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
  postprocessingEdtRecords: (token: string) => request<{ records: PostProcessingRecord[] }>('/api/v1/postprocessing/edt-records', { headers: { Authorization: `Bearer ${token}` } }),
  postprocessingRecalculationOptions: (token: string) => request<PostProcessingRecalculationOptions>('/api/v1/postprocessing/recalculation-options', { headers: { Authorization: `Bearer ${token}` } }),
  postprocessingInterval: (token: string, recordId: string, params: { ccd: number; startFrame: number; endFrame: number; phase?: 'burn' | 'dark' }) => {
    const query = new URLSearchParams({ ccd: String(params.ccd), start_frame: String(params.startFrame), end_frame: String(params.endFrame), phase: params.phase ?? 'burn' })
    return request<PostProcessingInterval>(`/api/v1/postprocessing/raw/${encodeURIComponent(recordId)}/interval?${query}`, { headers: { Authorization: `Bearer ${token}` } })
  },
  postprocessingConversions: (token: string) => request<{ runs: PostProcessingRun[] }>('/api/v1/postprocessing/conversions', { headers: { Authorization: `Bearer ${token}` } }),
  convertPostprocessingEdt: (token: string, payload: { record_ids: string[]; start_frame: number; end_frame?: number; target_ccd_layout_id: number; target_ccd_indices?: number[]; method_version_id?: number; name?: string }) => request<PostProcessingRun>('/api/v1/postprocessing/conversions', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  postprocessingRecalculations: (token: string) => request<{ runs: PostProcessingRun[] }>('/api/v1/postprocessing/recalculations', { headers: { Authorization: `Bearer ${token}` } }),
  recalculatePostprocessing: (token: string, payload: { source_record_ids: string[]; method_version_id: number; calculation_profile: 'legacy_2_0_2' | 'modern_v1'; curve_snapshot_ids: number[]; expected_measure_time?: string }) => request<PostProcessingRun>('/api/v1/postprocessing/recalculations', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  exportPostprocessing: (token: string, payload: { record_ids: string[]; kind: 'raw_intensity' | 'processed_intensity' | 'result_matrix'; format: 'txt' | 'csv' | 'excel'; output_directory: string; filename: string; same_name_strategy: 'suffix' | 'error' | 'overwrite' }) => request<PostProcessingExport>('/api/v1/postprocessing/exports', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
}
