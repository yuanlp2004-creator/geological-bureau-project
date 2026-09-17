/** reports requests and models; moved without changing payloads or responses. */
import { request, requestRaw } from './client'
import type { PrinterOption } from './methods'

export type ReportTemplate = { id: number; key: string; name: string; version: number; schema: Record<string, unknown>; enabled: boolean }

export type ReportRow = { report_number: string; sample_name: string; element: string; wavelength_nm: number; calculated_value: number; unit: string; curve_snapshot_id: number; calculation_profile: string; qc_status: string; analysis_run_id: number; line_id: string; merge_snapshot_id: number }

export type Report = { id: number; report_number: string; version: number; template_id: number; template_key?: string; template_name?: string; template_version?: number; source_run_ids: number[]; filter: Record<string, unknown>; arrangement: 'standard' | 'exchange'; model: { columns: string[]; rows: ReportRow[]; runs: Array<Record<string, unknown>>; arrangement: string; filters: Record<string, unknown> }; model_sha256: string; status: string; created_at: string; updated_at: string }

export type ReportExport = { id: string; report_id: number; format: string; status: string; path: string | null; content_sha256: string; byte_length: number; page_count: number; media_type: string }

export const reportsApi = {
  reportTemplates: (token: string) => request<ReportTemplate[]>('/api/v1/reports/templates', { headers: { Authorization: `Bearer ${token}` } }),
  reportPrinters: (token: string) => request<{ printers: PrinterOption[] }>('/api/v1/reports/printers', { headers: { Authorization: `Bearer ${token}` } }),
  reports: (token: string) => request<Report[]>('/api/v1/reports', { headers: { Authorization: `Bearer ${token}` } }),
  report: (token: string, reportId: number) => request<Report>(`/api/v1/reports/${reportId}`, { headers: { Authorization: `Bearer ${token}` } }),
  createReport: (token: string, payload: { analysis_run_ids: number[]; template_key: string; report_number?: string; arrangement: 'standard' | 'exchange'; filters: Record<string, unknown> }) => request<Report>('/api/v1/reports', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  reportPreview: async (token: string, reportId: number) => (await requestRaw(`/api/v1/reports/${reportId}/preview`, { headers: { Authorization: `Bearer ${token}` } })).text(),
  confirmReport: (token: string, reportId: number) => request<Report>(`/api/v1/reports/${reportId}/confirm`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  exportReport: (token: string, reportId: number, payload: { format: 'txt' | 'csv' | 'excel' | 'pdf' | 'print'; output_directory?: string; filename?: string; printer_name?: string; same_name_strategy: 'suffix' | 'error' | 'overwrite' }) => request<ReportExport>(`/api/v1/reports/${reportId}/exports`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
}
