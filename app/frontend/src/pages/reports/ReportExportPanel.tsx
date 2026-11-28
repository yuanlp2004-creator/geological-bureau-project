import { api, type Report, type PrinterOption } from '../../api'
import { PrintExportPanel, type OutputFormat } from '../../components/PrintExportPanel'
import { reportOutputAllowed, runReportOutput } from './reportPreviewActions'

export function ReportExportPanel({ token, report, printers, canWrite, canExport, pending, isCurrent, run, onConfirmed, onToast }: {
  token: string; report: Report; printers: PrinterOption[]; canWrite: boolean; canExport: boolean; pending: boolean
  isCurrent: () => boolean; run: (action: () => Promise<void>) => Promise<void>
  onConfirmed: (report: Report) => void; onToast: (message: string) => void
}) {
  const confirm = async () => onConfirmed(await api.confirmReport(token, report.id))
  const execute = async (format: OutputFormat, printer: string) => (await runReportOutput({
    status: report.status, canWrite, canExport, isCurrent,
    confirm,
    output: async () => {
      const result = await api.exportReport(token, report.id, { format, download: format !== 'print',
        printer_name: format === 'print' ? printer : undefined, same_name_strategy: 'suffix' })
      return { files: result.content_base64 && result.filename ? [{ filename: result.filename, content_base64: result.content_base64, media_type: result.media_type }] : [] }
    },
  })) ?? {}
  const allowed = reportOutputAllowed(report.status, canWrite, canExport)
  if (!canExport) {
    if (!canWrite || report.status !== 'draft') return null
    return <div className="report-preview-output">
      <button className="primary-button" disabled={pending} onClick={() => void run(async () => {
        if (!isCurrent()) return
        try {
          await confirm()
          if (isCurrent()) onToast('报告已确认')
        } catch (error) {
          if (isCurrent()) onToast(error instanceof Error ? error.message : '报告确认失败')
        }
      })}>确认报告</button>
    </div>
  }
  return <div className="report-preview-output">
    {report.status === 'draft' && canExport && !canWrite && <p className="field-hint">草稿需由具有报告写入权限的用户确认后才能输出。</p>}
    <PrintExportPanel inPreview confirmBeforeOutput={report.status === 'draft'} printers={printers}
      canPrint={allowed} disabled={pending || !allowed} execute={execute} isCurrent={isCurrent} runOperation={run} onToast={onToast} />
  </div>
}
