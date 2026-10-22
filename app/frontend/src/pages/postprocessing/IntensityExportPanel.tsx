import { useEffect, useState } from 'react'
import type { PrinterOption } from '../../api'
import { request } from '../../api/client'
import { PrintExportPanel, type OutputFormat } from '../../components/PrintExportPanel'

export function IntensityExportPanel({ token, runId, legacyIds = [], disabled, canPrint, onBusyChange, onToast }: {
  token: string; runId?: number; legacyIds?: number[]; disabled: boolean; canPrint: boolean
  onBusyChange: (busy: boolean) => void; onToast: (message: string) => void
}) {
  const [printers, setPrinters] = useState<PrinterOption[]>([])
  useEffect(() => {
    let current = true
    void request<{printers: PrinterOption[]}>('/api/v1/analyses/printers', { headers: {Authorization: `Bearer ${token}`} })
      .then(result => { if(current) setPrinters(result.printers) })
      .catch(error => { if(current) onToast(error instanceof Error ? error.message : '无法读取系统打印机') })
    return () => { current = false }
  }, [token])
  const execute = (format: OutputFormat, printer: string) => request<{files: Array<{filename:string;content_base64:string;media_type:string}>;print_job?:{status:string}}>((legacyIds.length ? '/api/v1/postprocessing/legacy-intensity-output' : `/api/v1/analyses/runs/${runId}/intensity-output`), {
    method: 'POST', timeoutMs: format === 'print' ? 300000 : 8000, headers: {Authorization: `Bearer ${token}`},
    body: JSON.stringify(legacyIds.length ? {record_ids:legacyIds,format,printer_name:format === 'print' ? printer : undefined} : {save_intensity:false,print_intensity:format === 'print',print_to_text:false,save_positions:false,
      export_format: format === 'print' ? null : format, printer_name: format === 'print' ? printer : undefined})
  })
  return <PrintExportPanel printers={printers} disabled={disabled || (!runId && !legacyIds.length)} canPrint={canPrint} execute={execute} onBusyChange={onBusyChange} onToast={onToast}/>
}
