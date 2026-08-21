import { useEffect, useMemo, useState } from 'react'
import { CheckSquare, Download, Eye, FileBarChart, FileText, Printer, RefreshCw } from 'lucide-react'
import { api, type AnalysisRun, type PrinterOption, type Report, type ReportTemplate } from './api'

type Props = { token: string; canWrite: boolean; canExport: boolean; onToast: (message: string) => void }

export function ReportsPage({ token, canWrite, canExport, onToast }: Props) {
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [reports, setReports] = useState<Report[]>([])
  const [templates, setTemplates] = useState<ReportTemplate[]>([])
  const [printers, setPrinters] = useState<PrinterOption[]>([])
  const [printerName, setPrinterName] = useState('geospectrum-pdf')
  const [selected, setSelected] = useState<number[]>([])
  const [active, setActive] = useState<Report | null>(null)
  const [arrangement, setArrangement] = useState<'standard' | 'exchange'>('standard')
  const [sampleFilter, setSampleFilter] = useState('')
  const [elementFilter, setElementFilter] = useState('')
  const [templateKey, setTemplateKey] = useState('analysis-standard')
  const [reportNumber, setReportNumber] = useState('')
  const [directory, setDirectory] = useState('')
  const [filename, setFilename] = useState('')
  const [busy, setBusy] = useState(false)
  const [previewState, setPreviewState] = useState<{ title: string; html: string } | null>(null)
  const [previewLoading, setPreviewLoading] = useState<Report | null>(null)

  const load = async () => {
    try { const [nextRuns, nextReports, nextTemplates, nextPrinters] = await Promise.all([api.analysisRuns(token), api.reports(token), api.reportTemplates(token), api.reportPrinters(token)]); setRuns(nextRuns); setReports(nextReports); setTemplates(nextTemplates); setPrinters(nextPrinters.printers); if (nextTemplates[0]) setTemplateKey(nextTemplates[0].key); if (nextPrinters.printers[0]) setPrinterName((current) => nextPrinters.printers.some((item) => item.name === current) ? current : nextPrinters.printers[0].name) } catch (error) { onToast(error instanceof Error ? error.message : '无法加载报告数据') }
  }
  useEffect(() => { void load() }, [token])
  const completedRuns = useMemo(() => runs.filter((run) => run.status === 'completed'), [runs])
  const toggle = (id: number) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  const selectAll = () => setSelected(selected.length === completedRuns.length ? [] : completedRuns.map((run) => run.id))
  const selectReport = async (report: Report) => {
    try { setActive(await api.report(token, report.id)) } catch (error) { onToast(error instanceof Error ? error.message : '无法读取报告详情') }
  }
  const create = async () => {
    if (!canWrite || selected.length === 0) return onToast('请选择已完成的分析运行')
    setBusy(true)
    try { const next = await api.createReport(token, { analysis_run_ids: selected, template_key: templateKey, report_number: reportNumber.trim() || undefined, arrangement, filters: { sample_name: sampleFilter, element: elementFilter } }); setActive(next); setReports((current) => [next, ...current]); onToast(`报告 ${next.report_number} v${next.version} 已建立`) } catch (error) { onToast(error instanceof Error ? error.message : '报告建立失败') } finally { setBusy(false) }
  }
  const preview = async (report: Report) => {
    setPreviewState(null)
    setPreviewLoading(report)
    try {
      const markup = await api.reportPreview(token, report.id)
      setPreviewState({ title: `${report.report_number} v${report.version} · 报告预览`, html: markup })
      setActive(report)
    } catch (error) { onToast(error instanceof Error ? error.message : '预览失败') } finally { setPreviewLoading(null) }
  }
  const confirm = async () => {
    if (!active || !canWrite) return onToast('请选择报告并确认写入权限')
    try { const next = await api.confirmReport(token, active.id); setActive(next); setReports((current) => current.map((item) => item.id === next.id ? next : item)); onToast('报告已确认，可导出或打印') } catch (error) { onToast(error instanceof Error ? error.message : '报告确认失败') }
  }
  const exportReport = async (format: 'txt' | 'csv' | 'excel' | 'pdf' | 'print') => {
    if (!active || !canExport) return onToast('请选择报告并确认导出权限')
    if (format !== 'print' && !directory.trim()) return onToast('请输入输出目录')
    try { const result = await api.exportReport(token, active.id, { format, output_directory: directory, filename: filename || `${active.report_number}-v${active.version}`, printer_name: format === 'print' ? printerName : undefined, same_name_strategy: 'suffix' }); onToast(format === 'print' ? `打印任务已完成：${result.path ?? printerName}` : `报告已导出：${result.path ?? '已完成'}`) } catch (error) { onToast(error instanceof Error ? error.message : '报告导出失败') }
  }

  return <div className="page-content reports-page" data-testid="reports-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S19 / REPORTS</span><h1>报告预览与导出</h1><p>统一报告模型驱动预览、PDF、Excel、文本和打印，方法版本、计算档案与质控状态随报告固化。</p></div><button className="secondary-button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></section>
    <div className="reports-grid">
      <section className="surface report-builder"><div className="surface-heading"><div><span className="section-kicker">1 · SELECT FILES</span><h2>分析运行</h2></div><button className="icon-button" title="全选或反选" onClick={selectAll}><CheckSquare size={17} /></button></div><div className="report-run-list">{completedRuns.length === 0 ? <div className="empty-state">暂无已完成分析运行</div> : completedRuns.map((run) => <label className="report-run-row" key={run.id}><input type="checkbox" checked={selected.includes(run.id)} onChange={() => toggle(run.id)} /><span><strong>{run.name}</strong><small>#{run.id} · {run.method_name} v{run.method_version} · {run.calculation_profile}</small></span><em>{run.samples?.length ?? 0} 样品</em></label>)}</div><div className="report-form"><label className="field"><span>报告编号（可选）</span><input value={reportNumber} onChange={(event) => setReportNumber(event.target.value)} placeholder="自动生成" /></label><label className="field"><span>报告模板</span><select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>{templates.map((template) => <option key={template.key} value={template.key}>{template.name} v{template.version}</option>)}</select></label><div className="field"><span>排列</span><div className="segmented"><button className={arrangement === 'standard' ? 'active' : ''} onClick={() => setArrangement('standard')}>常规排列</button><button className={arrangement === 'exchange' ? 'active' : ''} onClick={() => setArrangement('exchange')}>交换排列</button></div></div><div className="filter-grid"><label className="field"><span>样品筛选</span><input value={sampleFilter} onChange={(event) => setSampleFilter(event.target.value)} placeholder="全部样品" /></label><label className="field"><span>元素筛选</span><input value={elementFilter} onChange={(event) => setElementFilter(event.target.value)} placeholder="全部元素" /></label></div><button className="primary-button" disabled={!canWrite || busy} onClick={() => void create()}><FileBarChart size={16} />建立报告版本</button></div></section>
      <section className="surface report-output"><div className="surface-heading"><div><span className="section-kicker">2 · PREVIEW / CONFIRM</span><h2>报告版本</h2></div>{active && <span className={`state-chip ${active.status}`}>v{active.version} · {active.status}</span>}</div>{reports.length === 0 ? <div className="empty-state">建立报告后将在此显示版本</div> : <div className="report-list">{reports.slice(0, 12).map((report) => <button className={`report-row ${active?.id === report.id ? 'active' : ''}`} key={report.id} onClick={() => void selectReport(report)}><span><strong>{report.report_number} v{report.version}</strong><small>{report.arrangement === 'standard' ? '常规排列' : '交换排列'} · {report.source_run_ids.length} 个运行</small></span><em>{report.status}</em></button>)}</div>}{active && <><div className="report-summary"><strong>{active.report_number} v{active.version}</strong><span>{active.model.rows.length} 行 · SHA-256 {active.model_sha256.slice(0, 16)}...</span><span>方法/计算档案与质控状态已随模型保存</span></div><div className="report-format-actions"><button className="secondary-button" onClick={() => void preview(active)}><Eye size={16} />预览</button><button className="primary-button" disabled={active.status !== 'draft' || !canWrite} onClick={() => void confirm()}>确认报告</button></div></>}</section>
    </div>
    <section className="surface report-export"><div className="surface-heading"><div><span className="section-kicker">3 · OUTPUT</span><h2>格式与输出</h2></div><Download size={18} /></div><div className="report-export-form"><label className="field"><span>输出目录</span><input value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="C:\Reports" /></label><label className="field"><span>文件名</span><input value={filename} onChange={(event) => setFilename(event.target.value)} placeholder={active ? `${active.report_number}-v${active.version}` : '报告文件名'} /></label><label className="field"><span>Windows 打印机</span><select value={printerName} onChange={(event) => setPrinterName(event.target.value)}>{printers.map((printer) => <option key={printer.name} value={printer.name}>{printer.display_name}{printer.virtual ? ' · 可自动验收' : ''}</option>)}</select></label></div><div className="report-format-actions"><button className="secondary-button" disabled={!active || !canExport} onClick={() => void exportReport('txt')}><FileText size={15} />文本</button><button className="secondary-button" disabled={!active || !canExport} onClick={() => void exportReport('csv')}>CSV</button><button className="secondary-button" disabled={!active || !canExport} onClick={() => void exportReport('excel')}>Excel</button><button className="primary-button" disabled={!active || !canExport} onClick={() => void exportReport('pdf')}><Download size={15} />PDF</button><button className="secondary-button" disabled={!active || !canExport || !printerName} onClick={() => void exportReport('print')}><Printer size={15} />打印</button></div></section>
    {(previewLoading || previewState) && <div className="report-preview-modal" role="dialog" aria-modal="true" aria-label={previewState?.title ?? '正在生成报告预览'}><div>{previewState ? <><header><strong>{previewState.title}</strong><button className="secondary-button" onClick={() => setPreviewState(null)}>关闭</button></header><iframe title={previewState.title} srcDoc={previewState.html} /></> : <div className="report-preview-loading">正在生成报告预览...</div>}</div></div>}
  </div>
}
