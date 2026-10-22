import { useEffect, useRef, useState } from 'react'
import { Download, Printer } from 'lucide-react'
import type { PrinterOption } from '../api'
import { saveFile } from '../platform/files'

export type OutputFormat = 'excel' | 'pdf' | 'print'
type Output = { files?: Array<{ filename: string; content_base64: string; media_type: string }>; print_job?: { status: string } }

export function PrintExportPanel({ printers, disabled, canPrint, execute, onBusyChange, onToast }: {
  printers: PrinterOption[]; disabled: boolean; canPrint: boolean
  execute: (format: OutputFormat, printer: string) => Promise<Output>
  onBusyChange?: (busy: boolean) => void; onToast: (message: string) => void
}) {
  const [printer, setPrinter] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  useEffect(() => { setPrinter(current => printers.some(item => item.name === current) ? current : (printers.find(item => item.default) ?? printers[0])?.name ?? '') }, [printers])
  useEffect(() => { onBusyChange?.(busy) }, [busy, onBusyChange])
  useEffect(() => () => onBusyChange?.(false), [onBusyChange])
  const output = async (format: OutputFormat) => {
    if (lock.current || disabled || (format === 'print' && (!canPrint || !printer))) return
    lock.current = true
    setBusy(true)
    try {
      const result = await execute(format, printer)
      if (format === 'print') {
        onToast(result.print_job?.status === 'cancelled' ? '已取消 Windows 打印' : `打印任务已提交到 Windows 队列：${printer}`)
      } else {
        const files = result.files ?? []
        if (!files.length) throw new Error('未生成导出文件')
        let saved = 0
        for (const file of files) {
          const name = file.filename.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
          const blob = new Blob([Uint8Array.from(atob(file.content_base64), char => char.charCodeAt(0))], { type: file.media_type })
          if (await saveFile(blob, name)) saved++
        }
        onToast(saved ? `${format === 'excel' ? 'Excel' : 'PDF'} 文件已保存` : '已取消保存')
      }
    } catch (error) { onToast(error instanceof Error ? error.message : '输出失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <section className="surface report-export">
    <div className="surface-heading"><h2>打印与导出</h2><Download size={18}/></div>
    <div className="report-export-form">
      <label className="field"><span>Windows 打印机</span><select aria-label="Windows 打印机" disabled={busy || !canPrint} value={printer} onChange={event => setPrinter(event.target.value)}>
        {!printers.length && <option value="">未检测到系统打印机</option>}
        {printers.map(item => <option key={item.name} value={item.name}>{item.display_name}</option>)}
      </select></label>
    </div>
    <div className="report-format-actions">
      <button className="secondary-button" disabled={busy || disabled} onClick={() => void output('excel')}>Excel</button>
      <button className="primary-button" disabled={busy || disabled} onClick={() => void output('pdf')}><Download size={15}/>PDF</button>
      <button className="secondary-button" disabled={busy || disabled || !canPrint || !printer} onClick={() => void output('print')}><Printer size={15}/>打印</button>
    </div>
  </section>
}
