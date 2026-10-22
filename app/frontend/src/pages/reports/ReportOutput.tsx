import { Eye } from 'lucide-react'
import type { Report } from '../../api'
import type { ReportSummary } from '../../api/reports'

type Props = {
  reports: ReportSummary[]
  active: Report | null
  selectedId?: number
  loading: boolean
  error: string | null
  retry: () => Promise<void>
  canWrite: boolean
  disabled?: boolean
  selectReport: (report: ReportSummary) => Promise<void>
  preview: (report: Report) => Promise<void>
  confirm: () => Promise<void>
}

// 版本列表只展示父页面确认过的当前报告，选择和确认仍交给父页面协调。
export function ReportOutput({ reports, active, selectedId, loading, error, retry, canWrite, disabled, selectReport, preview, confirm }: Props) {
  return (
    <section className="surface report-output">
      <div className="surface-heading">
        <div>
          <h2>报告版本</h2>
        </div>
        {active && (
          <span className={`state-chip ${active.status}`}>
            v{active.version} · {active.status}
          </span>
        )}
      </div>
      {reports.length === 0 ? (
        <div className="empty-state">建立报告后将在此显示版本</div>
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
                {report.report_number} v{report.version} · {report.status} · {report.source_run_ids.length} 个运行
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
            <span>
              {active.model.rows.length} 行 · SHA-256 {active.model_sha256.slice(0, 16)}...
            </span>
            <span>{active.model.source_kind === 'legacy_dat' ? active.model.provenance_note : '方法/计算模式与质控状态已随模型保存'}</span>
          </div>
          <div className="report-format-actions">
            <button className="secondary-button" disabled={disabled} onClick={() => void preview(active)}>
              <Eye size={16} />
              预览
            </button>
            <button
              className="primary-button"
              disabled={disabled || active.status !== 'draft' || !canWrite}
              onClick={() => void confirm()}
            >
              确认报告
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
  closePreview
}: {
  previewLoading: Report | null
  previewState: ReportPreviewState | null
  closePreview: () => void
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
          <div>
            {previewState ? (
              <>
                <header>
                  <strong>{previewState.title}</strong>
                  <button className="secondary-button" onClick={closePreview}>
                    关闭
                  </button>
                </header>
                <iframe title={previewState.title} srcDoc={previewState.html} />
              </>
            ) : (
              <div className="report-preview-loading">正在生成报告预览...</div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
