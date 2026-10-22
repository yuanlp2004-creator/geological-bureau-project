import { AdvancedSettings } from '../../components/AdvancedSettings'
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Download, FileText, Info, Printer, RefreshCw, Save } from 'lucide-react'
import { api, saveFile, type MethodPrintSettings, type PrinterOption, type PrintJob } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { NumberField } from './NumberField'
import { formatDateTime } from '../../components/dateFormat'

export function MethodPrintPanel({
  methodId,
  methodName,
  version,
  token,
  canWrite,
  onToast
}: {
  methodId: number
  methodName: string
  version: number | null
  token: string
  canWrite: boolean
  onToast: (message: string) => void
}) {
  const [settings, setSettings] = useState<MethodPrintSettings | null>(null)
  const [printers, setPrinters] = useState<PrinterOption[]>([])
  const [papers, setPapers] = useState<{ code: string; display_name: string; width_mm: number; height_mm: number }[]>([])
  const [papersLoading, setPapersLoading] = useState(false)
  const [jobs, setJobs] = useState<PrintJob[]>([])
  const [previewHtml, setPreviewHtml] = useState('')
  const [metrics, setMetrics] = useState({ pageCount: 0, fieldCount: 0 })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reportError = (cause: unknown, fallback: string) => {
    const message = cause instanceof Error ? cause.message : fallback
    setError(message)
    onToast(message)
  }

  const refreshPreview = useCallback(
    async (applied: MethodPrintSettings) => {
      const result = await api.methodPreview(token, methodId, version, applied)
      setPreviewHtml(result.html)
      setMetrics({ pageCount: result.pageCount, fieldCount: result.fieldCount })
      setError(null)
    },
    [methodId, token, version]
  )

  const load = useCallback(async () => {
    setBusy(true)
    try {
      const [nextSettings, printerResult, jobResult] = await Promise.all([
        api.methodPrintSettings(token),
        api.methodPrinters(token),
        api.methodPrintJobs(token, methodId)
      ])
      setSettings(nextSettings)
      setPrinters(printerResult.printers)
      setJobs(jobResult.jobs)
      await refreshPreview(nextSettings)
    } catch (cause) {
      reportError(cause, '无法加载方法预览')
    } finally {
      setBusy(false)
    }
  }, [methodId, refreshPreview, token])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const printer = settings?.default_printer
    let cancelled = false
    setPapers([])
    if (!printer || !printers.some(item => item.name === printer)) return
    setPapersLoading(true)
    api.printerPapers(token, printer).then(result => {
      if (!cancelled) setPapers(result.papers)
    }).catch(cause => {
      if (!cancelled) reportError(cause, '无法读取打印机纸张')
    }).finally(() => { if (!cancelled) setPapersLoading(false) })
    return () => { cancelled = true }
  }, [settings?.default_printer, printers, token])

  const update = <K extends keyof MethodPrintSettings>(key: K, value: MethodPrintSettings[K]) => {
    setSettings((previous) => (previous ? { ...previous, [key]: value } : previous))
  }

  const preview = async () => {
    if (!settings) return
    if (!reportInvalidNumericInput(document.querySelector('.print-settings-panel')))
      return reportError(new Error('请先修正打印参数'), '请先修正打印参数')
    setBusy(true)
    try {
      await refreshPreview(settings)
    } catch (cause) {
      reportError(cause, '预览生成失败')
    } finally {
      setBusy(false)
    }
  }

  const saveDefaults = async () => {
    if (!settings) return
    if (!reportInvalidNumericInput(document.querySelector('.print-settings-panel')))
      return reportError(new Error('请先修正打印参数'), '请先修正打印参数')
    setBusy(true)
    try {
      const saved = await api.saveMethodPrintSettings(token, settings)
      setSettings(saved)
      await refreshPreview(saved)
      onToast('打印机、纸张、方向、边距与版式默认值已保存')
    } catch (cause) {
      reportError(cause, '打印设置保存失败')
    } finally {
      setBusy(false)
    }
  }

  const exportPdf = async () => {
    if (!settings) return
    if (!reportInvalidNumericInput(document.querySelector('.print-settings-panel')))
      return reportError(new Error('请先修正打印参数'), '请先修正打印参数')
    setBusy(true)
    try {
      const result = await api.methodPdf(token, methodId, version, settings)
      const path = await saveFile(result.blob, `${methodName}-v${version ?? 'latest'}-方法参数.pdf`)
      setMetrics({ pageCount: result.pageCount, fieldCount: result.fieldCount })
      onToast(path ? `PDF 已保存：${path}；${result.pageCount} 页、${result.fieldCount} 个字段` : '已取消保存')
    } catch (cause) {
      reportError(cause, 'PDF 导出失败')
    } finally {
      setBusy(false)
    }
  }

  const submitPrint = async () => {
    if (!settings) return
    if (!reportInvalidNumericInput(document.querySelector('.print-settings-panel')))
      return reportError(new Error('请先修正打印参数'), '请先修正打印参数')
    setBusy(true)
    try {
      if (settings.preview_before_print) await refreshPreview(settings)
      const job = await api.printMethod(token, methodId, version, settings, settings.default_printer)
      setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)])
      onToast(job.error_code === 'print_cancelled' ? '已取消 Windows 打印' : '打印任务已提交到 Windows 队列')
    } catch (cause) {
      reportError(cause, '打印任务提交失败')
    } finally {
      setBusy(false)
    }
  }

  if (!settings)
    return (
      <section className="surface method-empty compact">
        <Printer size={26} />
        <h2>正在准备打印工作区</h2>
        <p>{error ?? '读取打印机、页面默认值与方法版本。'}</p>
      </section>
    )

  return (
    <div className="print-workbench" data-testid="method-print-panel">
      {error && (
        <div className="auth-error">
          <AlertTriangle size={15} />
          {error}
        </div>
      )}
      <aside className="surface print-settings-panel">
        <div className="surface-heading">
          <div>
            <h2>打印设置</h2>
          </div>
          <Printer size={17} />
        </div>
        <div className="print-setting-grid">
          <label className="field span-2">
            <span>打印机</span>
            <select
              aria-label="打印机"
              value={settings.default_printer}
              disabled={busy}
              onChange={(event) => { update('default_printer', event.target.value); update('paper', 'A4') }}
            >
              {!printers.some(item => item.name === settings.default_printer) && <option value={settings.default_printer}>请连接 Windows 打印机</option>}
              {printers.map((item) => (
                <option value={item.name} key={item.name}>
                  {item.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="field print-paper-field">
            <span>纸张</span>
            <select
              aria-label="纸张"
              value={settings.paper}
              disabled={busy || papersLoading || papers.length === 0}
              onChange={(event) => update('paper', event.target.value as MethodPrintSettings['paper'])}
            >
              {!papers.some(item => item.code === settings.paper) && <option value={settings.paper}>{papersLoading ? '正在读取纸张…' : '请选择驱动支持的纸张'}</option>}
              {papers.map(item => <option key={item.code} value={item.code}>{item.display_name} · {item.width_mm} × {item.height_mm} mm</option>)}
            </select>
          </label>
          <label className="field">
            <span>方向</span>
            <select
              aria-label="方向"
              value={settings.orientation}
              onChange={(event) => update('orientation', event.target.value as MethodPrintSettings['orientation'])}
            >
              <option value="portrait">纵向</option>
              <option value="landscape">横向</option>
            </select>
          </label>
          <label className="field">
            <span>版式</span>
            <select
              value={settings.layout}
              onChange={(event) => update('layout', event.target.value as MethodPrintSettings['layout'])}
            >
              <option value="standard">标准</option>
              <option value="compact">紧凑</option>
            </select>
          </label>
          <label className="field">
            <span>字体大小 (pt)</span>
            <select aria-label="字体大小 (pt)" value={settings.font_size_pt} disabled={busy} onChange={event => update('font_size_pt', Number(event.target.value))}>
              {settings.font_size_pt === 8 && <option value={8}>8（已有设置）</option>}
              {[9, 10, 11, 12, 13].map(size => <option key={size} value={size}>{size}</option>)}
            </select>
          </label>
        </div>
        <AdvancedSettings title="高级打印设置">
          <div className="advanced-field-grid">
            <NumberField label="报告每行元素数" value={settings.elements_per_line ?? 15} min={1} max={50} disabled={busy} onChange={value => update('elements_per_line',value)} />
            <NumberField label="报告每页样品数" value={settings.samples_per_page ?? 50} min={1} max={1000} disabled={busy} onChange={value => update('samples_per_page',value)} />
            <label className="field"><span>报告时间</span><select value={settings.time_mode ?? 'analysis'} onChange={e => update('time_mode',e.target.value as 'analysis'|'system')}>
              <option value="analysis">分析时间</option><option value="system">系统时间</option></select></label>
            <NumberField
            label="上边距 (mm)"
            value={settings.margin_top_mm}
            min={5}
            max={40}
            step={0.5}
            disabled={busy}
            onChange={(value) => update('margin_top_mm', value)}
          />
            <NumberField
            label="右边距 (mm)"
            value={settings.margin_right_mm}
            min={5}
            max={40}
            step={0.5}
            disabled={busy}
            onChange={(value) => update('margin_right_mm', value)}
          />
            <NumberField
            label="下边距 (mm)"
            value={settings.margin_bottom_mm}
            min={5}
            max={40}
            step={0.5}
            disabled={busy}
            onChange={(value) => update('margin_bottom_mm', value)}
          />
            <NumberField
            label="左边距 (mm)"
            value={settings.margin_left_mm}
            min={5}
            max={40}
            step={0.5}
            disabled={busy}
            onChange={(value) => update('margin_left_mm', value)}
          />
          </div>
        </AdvancedSettings>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.preview_before_print}
            onChange={(event) => update('preview_before_print', event.target.checked)}
          />
          <span>
            <strong>打印前刷新预览</strong>
            <small>保证预览和本次任务使用同一输入</small>
          </span>
        </label>
        <div className="print-setting-actions">
          <button className="secondary-button" disabled={busy || papersLoading || !papers.some(item => item.code === settings.paper)} onClick={async () => {
            setBusy(true)
            try {
              const result = await api.checkPrinterConnection(token, settings)
              setError(null)
              onToast(`已接通 ${result.printer_name}；未提交打印任务`)
            } catch (cause) { reportError(cause, '打印机连接检查失败') } finally { setBusy(false) }
          }}>检查连接</button>
          <button className="secondary-button" onClick={() => void preview()} disabled={busy}>
            <RefreshCw size={15} />
            更新预览
          </button>
          {canWrite && (
            <button className="primary-button" onClick={() => void saveDefaults()} disabled={busy}>
              <Save size={15} />
              保存默认值
            </button>
          )}
        </div>
        <div className="print-fact-note">
          <Info size={14} />
          <span>纸张由 Windows 驱动提供；Microsoft Print to PDF 会打开系统保存窗口，可取消。</span>
        </div>
      </aside>
      <main className="surface print-preview-panel">
        <div className="surface-heading">
          <div>
            <h2>
              方法参数预览 <span className="count-badge">{metrics.pageCount} 页</span>
            </h2>
          </div>
          <div className="preview-actions">
            <span>
              {metrics.fieldCount} 个字段 · v{version ?? 'latest'}
            </span>
            <button className="secondary-button" onClick={() => void exportPdf()} disabled={busy}>
              <Download size={15} />
              导出 PDF
            </button>
            <button className="secondary-button" disabled={busy} onClick={async () => {
              setBusy(true)
              try { const path=await saveFile(await api.methodText(token,methodId,version),`${methodName}-方法参数.txt`);onToast(path?'方法参数 TXT 已保存':'已取消保存') }
              catch(error) { reportError(error,'TXT 导出失败') } finally { setBusy(false) }
            }}>导出 TXT</button>
            {canWrite && (
              <button className="primary-button" onClick={() => void submitPrint()} disabled={busy || papersLoading || !papers.some(item => item.code === settings.paper)}>
                <Printer size={15} />
                打印
              </button>
            )}
          </div>
        </div>
        <div className="preview-frame-shell">
          {previewHtml ? (
            <iframe
              className={settings.orientation}
              title={`${methodName} 方法参数预览`}
              srcDoc={previewHtml}
              sandbox=""
            />
          ) : (
            <div className="method-empty compact">
              <FileText size={24} />
              <p>等待生成 HTML 预览</p>
            </div>
          )}
        </div>
        <div className="print-jobs">
          <div className="print-jobs-heading">
            <strong>
              最近打印任务 <span className="count-badge">{jobs.length}</span>
            </strong>
            <span>失败任务会保留渲染输入和错误 PDF</span>
          </div>
          {jobs.length === 0 ? (
            <div className="empty-job">尚无打印记录</div>
          ) : (
            <div className="full-list">
              {jobs.map((job) => {
                const metadata = `v${job.method_version} · ${job.page_count} 页 · ${formatDateTime(job.created_at)}`
                return (
                  <div className={`print-job ${job.status}`} key={job.id}>
                    <span className="job-status">
                      {
                        (
                          { completed: '已完成', queued: '已排队', rendered: '已渲染', failed: '失败', cancelled: '已取消' } as Record<
                            string,
                            string
                          >
                        )[job.error_code === 'print_cancelled' ? 'cancelled' : job.status]
                      }
                    </span>
                    <div>
                      <strong title={job.printer_name}>{job.printer_name}</strong>
                      <small title={metadata}>{metadata}</small>
                    </div>
                    <CopyableCode value={job.output_path ?? job.error_code ?? job.id} visibleLength={28} />
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
