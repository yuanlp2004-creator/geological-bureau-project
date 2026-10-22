import { api, type Report, type PrinterOption } from '../../api'
import { PrintExportPanel, type OutputFormat } from '../../components/PrintExportPanel'

export function ReportExportPanel({ token, active, printers, canExport, onBusyChange, onToast }: {
  token: string; active: Report | null; printers: PrinterOption[]; canExport: boolean
  onBusyChange?: (busy: boolean) => void; onToast: (message: string) => void
}) {
  const execute = async (format: OutputFormat, printer: string) => {
    if (!active) throw new Error('请选择报告')
    const result = await api.exportReport(token, active.id, { format, download: format !== 'print',
      printer_name: format === 'print' ? printer : undefined, same_name_strategy: 'suffix' })
    return { files: result.content_base64 && result.filename ? [{ filename: result.filename, content_base64: result.content_base64, media_type: result.media_type }] : [] }
  }
  return <PrintExportPanel printers={printers} canPrint={canExport} disabled={!canExport || !active || !['confirmed','published'].includes(active.status)} execute={execute} onBusyChange={onBusyChange} onToast={onToast}/>
}
