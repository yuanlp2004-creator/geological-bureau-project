import { PageFileActions } from '../../components/PageFileActions'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { ReportBuilder, type ReportDraft, type ReportSource } from './ReportBuilder'
import type { ReportSummary } from '../../api/reports'
import { ReportExportPanel } from './ReportExportPanel'
import { ReportOutput, ReportPreview, type ReportPreviewState } from './ReportOutput'
import { api, type PrinterOption, type Report, type ReportTemplate } from '../../api'

type Props = { source: ReportSource | null; onSourceChange: (source: ReportSource) => void; actionsTarget?: HTMLElement | null; actionsActive?: boolean; embedded?: boolean; canReadAnalysis?: boolean; token: string; canWrite: boolean; canExport: boolean; onToast: (message: string) => void }

export function ReportsPage({ source, onSourceChange, actionsTarget, actionsActive = true, embedded = false, canReadAnalysis = true, token, canWrite, canExport, onToast }: Props) {
  const currentSource = source?.kind === 'analysis' && !canReadAnalysis ? null : source
  const [reports, setReports] = useState<ReportSummary[]>([])
  const [templates, setTemplates] = useState<ReportTemplate[]>([])
  const [printers, setPrinters] = useState<PrinterOption[]>([])
  const [active, setActive] = useState<Report | null>(null)
  const [selected, setSelected] = useState<ReportSummary | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [outputBusy, setOutputBusy] = useState(false)
  const [previewState, setPreviewState] = useState<ReportPreviewState | null>(null)
  const [previewLoading, setPreviewLoading] = useState<Report | null>(null)

  const detailRequest = useRef(0)
  const previewRequest = useRef(0)
  useEffect(() => () => { detailRequest.current++; previewRequest.current++ }, [token])
  const closePreview = () => {
    previewRequest.current++
    setPreviewState(null)
    setPreviewLoading(null)
  }
  useEffect(() => {
    detailRequest.current++
    closePreview()
    setActive(null)
    setSelected(null)
    setDetailLoading(false)
    setDetailError(null)
  }, [currentSource?.kind, currentSource?.id])

  const load = async () => {
    try {
      const [nextReports, nextTemplates, nextPrinters] = await Promise.all([
        api.reports(token), api.reportTemplates(token), api.reportPrinters(token),
      ])
      setReports(nextReports)
      setTemplates(nextTemplates)
      setPrinters(nextPrinters.printers)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法加载报告数据')
    }
  }
  useEffect(() => { void load() }, [token, canReadAnalysis])
  const selectReport = async (report: ReportSummary) => {
    const requestId = ++detailRequest.current
    closePreview()
    setSelected(report)
    setActive(null)
    setDetailLoading(true)
    setDetailError(null)
    try {
      const next = await api.report(token, report.id)
      if (requestId === detailRequest.current) setActive(next)
    } catch (error) {
      if (requestId === detailRequest.current) {
        const message = error instanceof Error ? error.message : '无法读取报告详情'
        setDetailError(message)
        onToast(message)
      }
    } finally {
      if (requestId === detailRequest.current) setDetailLoading(false)
    }
  }
  const create = async (input: ReportDraft) => {
    if (!currentSource) return onToast('请先打开要建立报告的数据')
    setBusy(true)
    const requestId = ++detailRequest.current
    closePreview()
    setDetailLoading(false)
    setDetailError(null)
    try {
      const next = await api.createReport(token, input)
      if (requestId === detailRequest.current) {
        setSelected(next)
        setActive(next)
      }
      setReports((current) => [next, ...current])
      onToast(`报告 ${next.report_number} v${next.version} 已建立`)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '报告建立失败')
    } finally {
      setBusy(false)
    }
  }
  const preview = async (report: Report) => {
    const requestId = ++previewRequest.current
    const selectionId = detailRequest.current
    const isCurrent = () => requestId === previewRequest.current && selectionId === detailRequest.current
    setPreviewState(null)
    setPreviewLoading(report)
    try {
      const markup = await api.reportPreview(token, report.id)
      if (isCurrent()) setPreviewState({ title: `${report.report_number} v${report.version} · 报告预览`, html: markup })
    } catch (error) {
      if (isCurrent()) onToast(error instanceof Error ? error.message : '预览失败')
    } finally {
      if (isCurrent()) setPreviewLoading(null)
    }
  }
  const confirm = async () => {
    if (!active || !canWrite) return onToast('请选择报告并确认写入权限')
    try {
      const next = await api.confirmReport(token, active.id)
      setActive((current) => current?.id === next.id ? next : current)
      setReports((current) => current.map((item) => item.id === next.id ? next : item))
      onToast('报告已确认，可导出或打印')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '报告确认失败')
    }
  }
  return <div className="page-content reports-page refined-page remaining-page" data-testid="reports-page">
    <section className="page-action-toolbar" style={embedded ? {display: 'contents'} : undefined}>
      
      <PageFileActions target={actionsTarget} hidden={!actionsActive}><OpenLegacyFile onBusyChange={setBusy} token={token} purpose="reports" label="打开报告文件" disabled={busy || outputBusy} onOpened={async (result, path) => {
        if (result.record_ids.length !== 1) throw new Error('每次请选择一个 DAT 报告文件')
        const opened = (await api.legacyReportSources(token)).find(item => item.id === result.record_ids[0])
        if (!opened) throw new Error('无法读取已打开的 DAT 数据，请重试')
        await load()
        onSourceChange({ kind: 'dat', id: opened.id, name: path.split(/[\\/]/).pop() || path, sampleCount: opened.sample_names.length })
      }}/>
      <button className="secondary-button" disabled={outputBusy} onClick={() => void load()}>
        <RefreshCw size={16} />刷新</button></PageFileActions>
    </section>
    <div className="reports-grid">
      <ReportBuilder key={currentSource ? `${currentSource.kind}-${currentSource.id}` : 'empty'} source={currentSource}
        templates={templates}
        canWrite={canWrite} busy={busy || outputBusy} onCreate={create} onToast={onToast} />
      <ReportOutput reports={reports} active={active} selectedId={selected?.id}
        loading={detailLoading} error={detailError} retry={() => selected ? selectReport(selected) : Promise.resolve()}
        canWrite={canWrite} disabled={busy || outputBusy}
        selectReport={selectReport} preview={preview} confirm={confirm} />
    </div>
    <ReportExportPanel token={token} active={active} printers={printers} canExport={canExport} onBusyChange={setOutputBusy} onToast={onToast} />
    <ReportPreview previewLoading={previewLoading} previewState={previewState} closePreview={closePreview} />
  </div>
}
