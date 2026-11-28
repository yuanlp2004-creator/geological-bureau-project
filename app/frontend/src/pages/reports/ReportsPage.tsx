import { PageFileActions } from '../../components/PageFileActions'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { ReportBuilder, type ReportDraft, type ReportSource } from './ReportBuilder'
import type { ReportSummary } from '../../api/reports'
import { ReportExportPanel } from './ReportExportPanel'
import { ReportOutput, ReportPreview, type ReportPreviewState } from './ReportOutput'
import { api, type PrinterOption, type Report, type ReportTemplate } from '../../api'

type Props = { source: ReportSource | null; onSourceChange: (source: ReportSource) => void; actionsTarget?: HTMLElement | null; actionsActive?: boolean; embedded?: boolean; canReadAnalysis?: boolean; token: string; canWrite: boolean; canExport: boolean; onToast: (message: string) => void }
type SelectedPreview = ReportPreviewState & { reportId: number; requestId: number; selectionId: number }

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
  const [previewState, setPreviewState] = useState<SelectedPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState<Report | null>(null)

  const actionsActiveRef = useRef(actionsActive)
  const detailRequest = useRef(0)
  const previewRequest = useRef(0)
  const listRequest = useRef(0)
  const resourcesRequest = useRef(0)
  const creating = useRef(false)
  const outputLock = useRef(false)
  useLayoutEffect(() => () => { listRequest.current++; resourcesRequest.current++ }, [token])
  useLayoutEffect(() => () => { detailRequest.current++; previewRequest.current++ }, [token])
  const closePreview = () => {
    previewRequest.current++
    setPreviewState(null)
    setPreviewLoading(null)
  }
  useLayoutEffect(() => {
    detailRequest.current++
    closePreview()
    setActive(null)
    setSelected(null)
    setDetailLoading(false)
    setDetailError(null)
  }, [currentSource?.kind, currentSource?.id])

  useLayoutEffect(() => {
    actionsActiveRef.current = actionsActive
    if (!actionsActive) closePreview()
  }, [actionsActive])

  const loadReports = useCallback(async () => {
    const request = ++listRequest.current
    try {
      const next = await api.reports(token)
      if (request === listRequest.current) setReports(next)
    } catch (error) {
      if (request === listRequest.current) onToast(error instanceof Error ? error.message : '无法加载报告列表')
    }
  }, [token, onToast])
  const load = useCallback(async () => {
    const request = ++resourcesRequest.current
    await Promise.all([
      loadReports(),
      api.reportTemplates(token).then((next) => {
        if (request === resourcesRequest.current) setTemplates(next)
      }, (error: unknown) => {
        if (request === resourcesRequest.current) onToast(error instanceof Error ? error.message : '无法加载报告模板')
      }),
      api.reportPrinters(token).then((next) => {
        if (request === resourcesRequest.current) setPrinters(next.printers)
      }, () => {
        if (request === resourcesRequest.current) setPrinters([])
      }),
    ])
  }, [loadReports, token, onToast])
  useEffect(() => { void load() }, [load])
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
    if (!canWrite || busy || creating.current || !actionsActiveRef.current) return
    creating.current = true
    setBusy(true)
    const requestId = ++detailRequest.current
    closePreview()
    setDetailLoading(false)
    setDetailError(null)
    try {
      const next = await api.createReport(token, input)
      setReports((current) => [next, ...current.filter((item) => item.id !== next.id)])
      void loadReports()
      if (requestId === detailRequest.current) {
        setSelected(next)
        setActive(next)
        await preview(next)
      }
    } catch (error) {
      if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '报告建立失败')
    } finally {
      creating.current = false
      setBusy(false)
    }
  }
  const preview = async (report: Report) => {
    if (!actionsActiveRef.current) return
    const requestId = ++previewRequest.current
    const selectionId = detailRequest.current
    const isCurrent = () => requestId === previewRequest.current && selectionId === detailRequest.current
    setPreviewState(null)
    setPreviewLoading(report)
    try {
      const markup = await api.reportPreview(token, report.id)
      if (isCurrent()) setPreviewState({ title: `${report.report_number} v${report.version} · 报告预览`,
        html: markup, reportId: report.id, requestId, selectionId })
    } catch (error) {
      if (isCurrent()) onToast(error instanceof Error ? error.message : '预览失败')
    } finally {
      if (isCurrent()) setPreviewLoading(null)
    }
  }
  const runOutput = async (action: () => Promise<void>) => {
    if (outputLock.current) return
    outputLock.current = true
    setOutputBusy(true)
    try {
      await action()
    } finally {
      outputLock.current = false
      setOutputBusy(false)
    }
  }
  return <div className="page-content reports-page refined-page remaining-page" data-testid="reports-page">
    <section className="page-action-toolbar" style={embedded ? {display: 'contents'} : undefined}>
      
      <PageFileActions target={actionsTarget} hidden={!actionsActive}><OpenLegacyFile onBusyChange={setBusy} token={token} purpose="reports" label="打开报告文件" disabled={busy || outputBusy} onOpened={async (result, path) => {
        if (result.record_ids.length !== 1) throw new Error('每次请选择一个 DAT 报告文件')
        const opened = (await api.legacyReportSources(token)).find(item => item.id === result.record_ids[0])
        if (!opened) throw new Error('无法读取已打开的 DAT 数据，请重试')
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
        disabled={busy}
        selectReport={selectReport} preview={preview} />
    </div>
    <ReportPreview previewLoading={previewLoading} previewState={previewState} closePreview={closePreview}>
      {active && previewState?.reportId === active.id && <ReportExportPanel token={token} report={active}
        printers={printers} canWrite={canWrite} canExport={canExport} pending={outputBusy} onToast={onToast}
        isCurrent={() => actionsActiveRef.current && previewState.requestId === previewRequest.current &&
          previewState.selectionId === detailRequest.current} run={runOutput}
        onConfirmed={(report) => {
          if (previewState.selectionId !== detailRequest.current) return
          setActive(report)
          setReports((current) => current.map((item) => item.id === report.id ? report : item))
          void loadReports()
        }} />}
    </ReportPreview>
  </div>
}
