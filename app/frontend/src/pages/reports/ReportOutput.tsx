import { Eye, Files } from 'lucide-react'
import type { Report } from '../../api'
import type { ReportSummary } from '../../api/reports'
import { PreviewFrame } from '../../components/PreviewFrame'
import type { ReactNode } from 'react'
import { reportSourceLabel, reportStatusLabel } from './reportPreviewActions'

type Props = {
  reports: ReportSummary[]
  active: Report | null
  selectedId?: number
  loading: boolean
  error: string | null
  retry: () => Promise<void>
  disabled?: boolean
  selectReport: (report: ReportSummary) => Promise<void>
  preview: (report: Report) => Promise<void>
}

export function ReportOutput({ reports, active, selectedId, loading, error, retry, disabled, selectReport, preview }: Props) {
  return (
    <section className="surface report-output">
      <div className="surface-heading">
        <div>
          <h2>报告版本</h2>
        </div>
        {active && (
          <span className={`state-chip ${active.status}`}>
            v{active.version} · {reportStatusLabel(active.status)}
          </span>
        )}
      </div>
      {reports.length === 0 ? (
        <div className="empty-state report-empty">
          <Files size={20} aria-hidden="true" />
          <div><strong>暂无报告版本</strong><small>建立报告后将在此显示版本</small></div>
        </div>
      ) : (
        <label className="field report-version-selector">
          <span>选择报告版本</span>
          <select
            value={selectedId ?? ''}
            disabled={disabled}
            onChange={(event) => {
              const report = reports.find((item) => item.id === Number(event.target.value))
              if (report) void selectReport(report)
            }}
          >
            <option value="" disabled>
              请选择版本
            </option>
            {reports.map((report) => (
              <option key={report.id} value={report.id}>
                {report.report_number} v{report.version} · {reportStatusLabel(report.status)} · {reportSourceLabel(report)}
              </option>
            ))}
          </select>
        </label>
      )}
      {loading && <div className="empty-state" role="status">正在加载报告详情...</div>}
      {error && <div className="report-summary" role="alert">
        <span>报告详情加载失败：{error}</span>
        <button className="secondary-button" disabled={disabled} onClick={() => void retry()}>重试</button>
      </div>}
      {active && (
        <>
          <div className="report-summary">
            <strong>
              {active.report_number} v{active.version}
            </strong>
            <span>{reportSourceLabel(active)} · {active.model.rows.length} 行</span>
            {active.model.provenance_note && <span>{active.model.provenance_note}</span>}
            <details className="report-technical-details">
              <summary>版本详情</summary>
              {active.template_name && <div>{active.template_name} · 模板版本 {active.template_version}</div>}
              <div>SHA-256 <code>{active.model_sha256}</code></div>
            </details>
          </div>
          <div className="report-format-actions">
            <button className="secondary-button" disabled={disabled} onClick={() => void preview(active)}>
              <Eye size={16} />
              预览
            </button>
          </div>
        </>
      )}
    </section>
  )
}

export type ReportPreviewState = { title: string; html: string }

// 预览对话框保持在主网格之外，加载和关闭逻辑由父页面统一处理。
export function ReportPreview({
  previewLoading,
  previewState,
  closePreview,
  children,
}: {
  previewLoading: Report | null
  previewState: ReportPreviewState | null
  closePreview: () => void
  children?: ReactNode
}) {
  return (
    <>
      {(previewLoading || previewState) && (
        <div
          className="report-preview-modal"
          role="dialog"
          aria-modal="true"
          aria-label={previewState?.title ?? '正在生成报告预览'}
        >
          <div className={previewState && children ? 'report-preview-ready' : undefined}>
            {previewState ? (
              <>
                <header>
                  <strong>{previewState.title}</strong>
                  <button className="secondary-button" onClick={closePreview}>
                    关闭
                  </button>
                </header>
                <PreviewFrame title={previewState.title} srcDoc={previewState.html} />
                {children}
              </>
            ) : (
              <header><span role="status">正在生成报告预览...</span>
                <button className="secondary-button" onClick={closePreview}>关闭</button>
              </header>
            )}
          </div>
        </div>
      )}
    </>
  )
}
