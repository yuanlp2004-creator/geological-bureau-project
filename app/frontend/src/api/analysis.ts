/** analysis requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'

export type AnalysisStatus = 'draft' | 'running' | 'paused' | 'completed' | 'cancelled' | 'failed'

export type AnalysisSampleOption = {
  id: number
  sample_name: string
  sample_kind: string
  repeat_index: number
  input_sha256: string
  acquisition_task_id: number
  acquisition_task_name: string
  method_version_id: number
  method_id: number
  method_version: number
}

export type AnalysisOptions = {
  profiles: Array<'legacy_2_0_2' | 'modern_v1'>
  samples: AnalysisSampleOption[]
  method_versions: Array<{ method_version_id: number; method_id: number; version: number; name: string; calculation_profile: 'legacy_2_0_2' | 'modern_v1' }>
}

export type AnalysisLineResult = {
  id: number
  sample_position: number
  line_position: number
  line_id: string
  line_type: string
  element: string
  wavelength_nm: number
  ccd_index: number
  expected_position: number
  peak_position: number
  peak_height: number
  background: number
  net_signal: number
  gaussian_center: number | null
  gaussian_peak_height: number | null
  gaussian_sigma: number | null
  gaussian_area: number | null
  quantitative_signal: number
  calculation_profile: 'legacy_2_0_2' | 'modern_v1'
  intervention_id: number | null
  intermediates: Record<string, unknown>
  result_sha256: string
}

export type AnalysisCheckpoint = {
  id: number
  sequence: number
  sample_position: number
  line_position: number
  line_id: string
  status: 'pending' | 'accepted' | 'discarded' | 'cancelled'
  automatic_position: number
  accepted_position: number | null
  window_start: number
  window_end: number
  spectrum_window: Array<{ point_index: number; value: number }>
  candidate: AnalysisLineResult & { corrected_expected_position: number }
  deadline_at: string
}

export type AnalysisQcMember = { line_result_id: number; sample_position: number; repeat_index: number; value: number; included: boolean; source_sha256: string; last_decision_id: number | null }

export type AnalysisQcGroup = {
  acquisition_task_id: number; sample_name: string; sample_kind: string; standard_index: number | null; line_id: string; element: string; wavelength_nm: number; repeat_count: number
  members: AnalysisQcMember[]
  statistics: { effective_count: number; mean: number | null; minimum: number | null; maximum: number | null; range: number | null; stddev: number | null; rsd: number | null; id: number | null }
  warnings: Array<{ code: string; message: string; actual?: number; threshold?: number }>
  warning_accepted: boolean
}

export type AnalysisQcSnapshot = { id: number; sequence: number; groups: AnalysisQcGroup[]; publishable: boolean; result_sha256: string; created_at: string }

export type AnalysisCurvePoint = { point_index: number; name: string; standard_value: number; original_intensity: number | null; adjusted_intensity: number | null; original_active: boolean; active: boolean; qc_group: { acquisition_task_id: number; effective_count: number } | null }

export type AnalysisCurveSnapshot = {
  id: number; sequence: number; line_id: string; qc_snapshot_id: number; adjustment_set_id: number; fit_mode: 'linear' | 'quadratic' | 'cubic' | 'spline'; coordinate_type: 'normal' | 'logarithmic'; publishable: boolean; result_sha256: string; created_at: string
  points: AnalysisCurvePoint[]; fit: Record<string, unknown>; chart: Array<{ intensity: number; value: number }>
  diagnostics: { points: Array<AnalysisCurvePoint & { calculated_value: number; residual: number; relative_error_percent: number | null }>; correlation: number | null; rmse: number; maximum_absolute_error: number }
}

export type AnalysisCurveLine = {
  line_id: string; element: string; wavelength_nm: number; unit: string; active_curve_snapshot_id: number | null
  workspace: { fit_mode: 'linear' | 'quadratic' | 'cubic' | 'spline'; coordinate_type: 'normal' | 'logarithmic'; points: AnalysisCurvePoint[]; adjustment_set_id: number | null; sequence: number }
  snapshots: AnalysisCurveSnapshot[]
}

export type AnalysisRun = {
  id: number
  name: string
  status: AnalysisStatus
  method_id: number
  method_name: string
  method_version_id: number
  method_version: number
  calculation_profile: 'legacy_2_0_2' | 'modern_v1'
  slow_mode: boolean
  intervention_timeout_seconds: number
  current_sample_position: number
  current_line_position: number
  input_sha256: string
  result_sha256: string | null
  failure_code: string | null
  failure_message: string | null
  failure_details: Record<string, unknown>
  samples: Array<{ id: number; position: number; acquisition_sample_id: number; sample_name: string; input_sha256: string; result_matrix: Array<{ line_id: string; element: string; wavelength_nm: number; quantitative_signal: number; calculation_profile: string }>; result_sha256: string | null }>
  line_results: AnalysisLineResult[]
  checkpoint: AnalysisCheckpoint | null
  interventions: Array<{ id: number; action: 'accept' | 'discard'; before_position: number; after_position: number; reason: string; created_at: string }>
  messages: Array<{ id: number; level: string; code: string; message: string; details: Record<string, unknown>; created_at: string }>
  quality: { latest_snapshot: AnalysisQcSnapshot | null; snapshot_history: Array<{ id: number; sequence: number; publishable: boolean; result_sha256: string; created_at: string }>; decisions: Array<Record<string, unknown>> }
  curves: {
    lines: AnalysisCurveLine[]; actions: Array<Record<string, unknown>>
    results: Array<{ id: number; curve_snapshot_id: number; acquisition_task_id: number; sample_name: string; sample_kind: string; is_standard: boolean; standard_value: number | null; effective_count: number; intensity: number; calculated_value: number; result_sha256: string }>
    merges: Array<{ id: number; sequence: number; curve_snapshot_ids: number[]; results: Array<{ acquisition_task_id: number; sample_name: string; sample_kind: string; values: Array<{ element: string; line_id: string; curve_snapshot_id: number; value: number; intensity: number; candidate_count: number }> }>; result_sha256: string; created_at: string }>
    print_jobs: Array<{ id: number; curve_snapshot_id: number; mode: 'image' | 'text'; content_sha256: string; byte_length: number; created_at: string }>
  }
  created_at: string
  updated_at: string
}

export const analysisApi = {
  analysisOptions: (token: string) => request<AnalysisOptions>('/api/v1/analyses/options', { headers: { Authorization: `Bearer ${token}` } }),
  analysisRuns: (token: string) => request<AnalysisRun[]>('/api/v1/analyses/runs', { headers: { Authorization: `Bearer ${token}` } }),
  createAnalysisRun: (token: string, payload: Record<string, unknown>) => request<AnalysisRun>('/api/v1/analyses/runs', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  analysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }),
  startAnalysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/start`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  stepAnalysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/step`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  interveneAnalysisRun: (token: string, runId: number, payload: { action: 'accept' | 'discard'; adjusted_position?: number | null; reason: string }) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/intervene`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  cancelAnalysisRun: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/cancel`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  recalculateAnalysisQuality: (token: string, runId: number) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/quality/recalculate`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  decideAnalysisQuality: (token: string, runId: number, payload: { acquisition_task_id: number; line_id: string; action: 'accept' | 'exclude' | 'restore'; line_result_id?: number | null; reason: string }) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/quality/decisions`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  analysisCurveAction: (token: string, runId: number, lineId: string, payload: Record<string, unknown>) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/curves/${encodeURIComponent(lineId)}/actions`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  fitAnalysisCurve: (token: string, runId: number, lineId: string, payload: Record<string, unknown>) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/curves/${encodeURIComponent(lineId)}/fit`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  publishAnalysisCurve: (token: string, runId: number, lineId: string, curveSnapshotId: number, reason: string) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/curves/${encodeURIComponent(lineId)}/publish`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ curve_snapshot_id: curveSnapshotId, reason }) }),
  mergeAnalysisResults: (token: string, runId: number, reason: string) => request<AnalysisRun>(`/api/v1/analyses/runs/${runId}/results/merge`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ reason }) }),
  analysisCurvePreview: async (token: string, runId: number, curveSnapshotId: number, mode: 'image' | 'text') => {
    const response = await requestRaw(`/api/v1/analyses/runs/${runId}/curves/${curveSnapshotId}/preview?mode=${mode}`, { headers: { Authorization: `Bearer ${token}` } })
    return response.text()
  },
  printAnalysisCurve: async (token: string, runId: number, curveSnapshotId: number, mode: 'image' | 'text') => {
    const response = await requestRaw(`/api/v1/analyses/runs/${runId}/curves/${curveSnapshotId}/print?mode=${mode}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
    return { blob: await response.blob(), jobId: Number(response.headers.get('X-Print-Job-Id')), sha256: response.headers.get('X-Content-SHA256') ?? '' }
  },
}
