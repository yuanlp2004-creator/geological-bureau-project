import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { calculationProfileLabel } from '../../components/calculationProfile'
import {
  BarChart3,
  PlayCircle,
  RefreshCw,
  ShieldAlert,
  Square,
  StepForward,
  PanelLeftClose,
  PanelLeftOpen
} from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { api, savePdfFile, type AnalysisCurveSnapshot, type AnalysisOptions, type AnalysisRun } from '../../api'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { FormDisclosure } from '../../layout/TaskLayout'
import { AnalysisCurves } from './AnalysisCurves'
import { AnalysisIntervention } from './AnalysisIntervention'
import { AnalysisQuality } from './AnalysisQuality'
import { AnalysisRawResults } from './AnalysisRawResults'
import { IntensityOutput } from './IntensityOutput'
import { AnalysisSpectrum } from './AnalysisSpectrum'
import { AnalysisRunForm } from './AnalysisRunForm'
import { AnalysisSamples } from './AnalysisSamples'
import { AnalysisStandards } from './AnalysisStandards'
import { active, AnalysisView, Props, statusLabels } from './analysisView'

export function AnalysisPage({
  token,
  initialView,
  onViewChange,
  canExecute,
  canIntervene,
  canQuality,
  canCurve,
  canPrint,
  canSaveMethod = false,
  onCurrentRunChange,
  onToast
}: Props) {
  const [options, setOptions] = useState<AnalysisOptions | null>(null)
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [selected, setSelected] = useState<AnalysisRun | null>(null)
  useEffect(() => { if (selected) onCurrentRunChange?.(selected) }, [selected, onCurrentRunChange])
  const [openedLegacy, setOpenedLegacy] = useState(0)
  const [legacyIds, setLegacyIds] = useState<number[]>([])
  const [legacyMethod, setLegacyMethod] = useState<number | null>(null)
  const [sampleIds, setSampleIds] = useState<number[]>([])
  const [name, setName] = useState('定量与曲线分析')
  const [profile, setProfile] = useState<'legacy_2_0_2' | 'modern_v1'>('modern_v1')
  const [slowMode, setSlowMode] = useState(true)
  const [timeout, setTimeout] = useState(300)
  const [adjustedPosition, setAdjustedPosition] = useState<number | null>(null)
  const [reason, setReason] = useState('人工复核峰位')
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [viewByRun, setViewByRun] = useState<Record<number, AnalysisView>>({})
  const [lineByRun, setLineByRun] = useState<Record<number, string>>({})
  const [adjustments, setAdjustments] = useState<Record<string, number>>({})
  const [preview, setPreview] = useState<{ title: string; html: string } | null>(null)
  const [railCollapsed, setRailCollapsed] = useState(false)

  const epoch = useRef(0),
    mounted = useRef(false),
    identity = useRef(token)
  const pending = useRef<Promise<unknown> | null>(null)
  const cancelIntent = useRef(false)
  identity.current = token
  const ticket = () => {
    const generation = epoch.current
    return () => mounted.current && identity.current === token && epoch.current === generation
  }
  useLayoutEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      epoch.current++
      cancelIntent.current = true
    }
  }, [token])

  // Retain each batch's local view; the old quality deep-link opens the shared review area.
  const priorStatus = useRef<Record<number, string>>({})

  const update = useCallback((next: AnalysisRun) => {
    if (next.status === 'completed' && ['running', 'paused'].includes(priorStatus.current[next.id]))
      setViewByRun((current) => ({ ...current, [next.id]: 'curve' }))
    priorStatus.current[next.id] = next.status
    setSelected(next)
    setRuns((current) =>
      current.some((item) => item.id === next.id)
        ? current.map((item) => (item.id === next.id ? next : item))
        : [next, ...current]
    )
    if (next.checkpoint?.status === 'pending') setAdjustedPosition(next.checkpoint.automatic_position)
  }, [])

  const loadRequest = useRef(0)
  const load = useCallback(async () => {
    const current = ticket(),
      requestId = ++loadRequest.current
    const valid = () => current() && requestId === loadRequest.current
    setBusy(true)
    try {
      const [nextOptions, nextRuns] = await Promise.all([api.analysisOptions(token), api.analysisRuns(token)])
      if (!valid()) return
      setOptions(nextOptions)
      setRuns(nextRuns)
      if (nextRuns[0]) {
        const next = await api.analysisRun(token, nextRuns[0].id)
        if (valid()) update(next)
      }
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '无法读取分析数据')
    } finally {
      if (valid()) setBusy(false)
    }
  }, [onToast, token, update])

  useEffect(() => {
    void load()
  }, [load])

  const grouped = useMemo(() => {
    const groups = new Map<number, AnalysisOptions['samples']>()
    for (const sample of options?.samples ?? [])
      groups.set(sample.acquisition_task_id, [...(groups.get(sample.acquisition_task_id) ?? []), sample])
    return [...groups.values()]
  }, [options])

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    const reject = (message: string) => {
      setCreateError(message)
      onToast(message)
    }
    if (!canExecute) return reject('当前账户没有执行分析的权限')
    if (!reportInvalidNumericInput(event.currentTarget)) return reject('请先修正慢进超时（秒）的无效数值')
    if (!sampleIds.length) return reject('请至少选择一个已完成采集样品')
    setCreateError(null)
    const methodVersionId = options?.samples.find((sample) => sampleIds.includes(sample.id))?.method_version_id
    await mutate(
      () =>
        api.createAnalysisRun(token, {
          name,
          acquisition_sample_ids: sampleIds,
          method_version_id: methodVersionId,
          calculation_profile: profile,
          slow_mode: slowMode,
          intervention_timeout_seconds: timeout
        }),
      '分析运行已建立，输入哈希和方法版本已锁定'
    )
  }

  const choose = async (run: AnalysisRun) => {
    if (busy || pending.current) return
    epoch.current++
    cancelIntent.current = true
    setSelected(run)
    setPreview(null)
    setBusy(false)
    const valid = ticket()
    try {
      const next = await api.analysisRun(token, run.id)
      if (valid()) update(next)
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '无法读取分析批次')
    }
  }
  const mutate = async (operation: () => Promise<AnalysisRun>, success: string, continuous = false) => {
    if (pending.current) {
      onToast('上一操作仍在完成，请稍后重试')
      return false
    }
    const valid = ticket()
    setBusy(true)
    const work = (async () => {
      let next = await operation()
      if (!valid()) return false
      update(next)
      while (continuous && !cancelIntent.current && !next.slow_mode && next.status === 'running' && valid()) {
        if (options?.preferences?.look_band && options.preferences.wait_time_ms>0)
          await new Promise(resolve => window.setTimeout(resolve,options.preferences!.wait_time_ms))
        if (!valid() || cancelIntent.current)break
        next = await api.stepAnalysisRun(token, next.id)
        if (!valid()) return false
        update(next)
      }
      if (valid() && next.status === 'completed' && !next.quality.latest_snapshot && canQuality) {
        next = await api.recalculateAnalysisQuality(token, next.id)
        if (!valid()) return false
        update(next)
      }
      if (valid() && success) onToast(success)
      return valid()
    })()
    pending.current = work
    try {
      return await work
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '分析操作失败')
      return false
    } finally {
      if (pending.current === work) pending.current = null
      if (valid()) setBusy(false)
    }
  }
  const act = async (action: 'start' | 'step' | 'cancel') => {
    if (!selected || !canExecute) return
    const id = selected.id
    if (action === 'cancel') {
      cancelIntent.current = true
      const valid = ticket()
      await pending.current?.catch(() => { })
      try {
        const next = await api.cancelAnalysisRun(token, id)
        if (valid()) update(next)
      } catch (error) {
        if (valid()) onToast(error instanceof Error ? error.message : '取消失败，请重试')
      }
      return
    }
    cancelIntent.current = false
    await mutate(() => (action === 'start' ? api.startAnalysisRun : api.stepAnalysisRun)(token, id), '', true)
  }
  const intervene = async (action: 'accept' | 'discard') => {
    if (!selected || !canIntervene) return onToast('当前账户没有人工干预权限')
    if (action === 'accept' && !reportInvalidNumericInput(document.querySelector('.checkpoint-controls')))
      return onToast('请先修正调整后的峰位')
    await mutate(
      () =>
        api.interveneAnalysisRun(token, selected.id, {
          action,
          adjusted_position: action === 'accept' ? adjustedPosition : null,
          reason
        }),
      '慢进检查点已处理'
    )
  }

  const qualityDecision = (
    group: NonNullable<AnalysisRun['quality']['latest_snapshot']>['groups'][number],
    action: 'accept' | 'exclude' | 'restore',
    lineResultId: number | null,
    reason: string
  ) => {
    if (!selected || !canQuality) return onToast('当前账户没有重复质控权限')
    void mutate(
      () =>
        api.decideAnalysisQuality(token, selected.id, {
          acquisition_task_id: group.acquisition_task_id,
          line_id: group.line_id,
          action,
          line_result_id: lineResultId,
          reason
        }),
      action === 'accept'
        ? '质控提示已接受并保留审计记录'
        : action === 'exclude'
          ? '该重复已剔除并重新统计'
          : '该重复已恢复并重新统计'
    )
  }

  const curveAction = (
    lineId: string,
    payload: Record<string, unknown>,
    success: string,
    afterSuccess?: () => void
  ) => {
    if (!selected || !canCurve) return onToast('当前账户没有曲线调整权限')
    if (payload.action === 'adjust' && !reportInvalidNumericInput(document.querySelector('.analysis-matrix')))
      return onToast('请先修正标准点数值')
    void mutate(() => api.analysisCurveAction(token, selected.id, lineId, payload), success).then((saved) => {
      if (saved) afterSuccess?.()
    })
  }

  const previewRequest = useRef(0)
  const showPreview = async (snapshot: AnalysisCurveSnapshot, mode: 'image' | 'text') => {
    if (!selected) return
    const current = ticket(),
      request = ++previewRequest.current
    const valid = () => current() && request === previewRequest.current
    setBusy(true)
    try {
      const html = await api.analysisCurvePreview(token, selected.id, snapshot.id, mode)
      if (!valid()) return
      setPreview({ title: `${snapshot.line_id} · ${mode === 'image' ? '图像' : '文本'}预览`, html })
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '无法生成曲线预览')
    } finally {
      if (valid()) setBusy(false)
    }
  }

  const printCurve = async (snapshot: AnalysisCurveSnapshot, mode: 'image' | 'text') => {
    if (!selected || !canPrint) return onToast('当前账户没有曲线打印权限')
    const valid = ticket()
    setBusy(true)
    try {
      const result = await api.printAnalysisCurve(token, selected.id, snapshot.id, mode)
      if (!valid()) return
      const path = await savePdfFile(result.blob, `analysis-${selected.id}-curve-${snapshot.id}-${mode}.pdf`)
      if (!valid()) return
      const next = await api.analysisRun(token, selected.id)
      if (!valid()) return
      update(next)
      onToast(path ? `打印快照 #${result.jobId} 已保存至 ${path}` : `打印快照 #${result.jobId} 已生成，文件保存已取消`)
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '曲线打印失败')
    } finally {
      if (valid()) setBusy(false)
    }
  }

  const importLegacy = async (ids = legacyIds, method = legacyMethod) => {
    if (!canExecute || busy || !method || !ids.length) return
    const valid = ticket()
    setBusy(true)
    try {
      const result = await api.importLegacyAnalysisSources(token, ids, method)
      if (!valid()) return
      const next = await api.analysisOptions(token)
      if (!valid()) return
      setOptions(next)
      setSampleIds(result.sample_ids)
      setProfile('legacy_2_0_2')
      onToast('旧样品已按确切方法适配，请建立分析运行；源文件保持只读')
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '旧样品适配失败')
    } finally {
      if (valid()) setBusy(false)
    }
  }

  const toggleSample = (id: number, methodVersionId: number) => {
    setSampleIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [
          ...current.filter(
            (value) => options?.samples.find((item) => item.id === value)?.method_version_id === methodVersionId
          ),
          id
        ]
    )
  }

  const checkpoint = selected?.checkpoint?.status === 'pending' ? selected.checkpoint : null
  const chart = checkpoint?.spectrum_window ?? []
  const maxValue = Math.max(1, ...chart.map((point) => point.value))
  const minPoint = chart[0]?.point_index ?? 0
  const span = Math.max(1, (chart[chart.length - 1]?.point_index ?? minPoint + 1) - minPoint)
  const requestedView = selected ? (viewByRun[selected.id] ?? (selected.status === 'completed' && initialView === 'raw' ? 'curve' : initialView)) : initialView
  const currentView = requestedView === 'quality' ? 'curve' : requestedView
  const curveLineId = selected ? (lineByRun[selected.id] ?? selected.curves.lines[0]?.line_id ?? '') : ''
  const curveLine = selected?.curves.lines.find((item) => item.line_id === curveLineId) ?? selected?.curves.lines[0]
  const activeSnapshot = curveLine?.snapshots.find((item) => item.id === curveLine.active_curve_snapshot_id)
  const shownSnapshot = curveLine?.snapshots[curveLine.snapshots.length - 1] ?? activeSnapshot
  const qcGroups =
    selected?.quality.latest_snapshot?.groups.filter((group) => !curveLineId || group.line_id === curveLineId) ?? []

  const lineIndex = selected?.curves.lines.findIndex((line) => line.line_id === curveLine?.line_id) ?? -1
  const lineSaved = Boolean(activeSnapshot && activeSnapshot.qc_snapshot_id === selected?.quality.latest_snapshot?.id
    && activeSnapshot.adjustment_set_id === curveLine?.workspace.adjustment_set_id
    && activeSnapshot.fit_mode === curveLine?.workspace.fit_mode
    && activeSnapshot.coordinate_type === curveLine?.workspace.coordinate_type)
  const allSaved = Boolean(selected?.curves.lines.length && selected.curves.lines.every((line) => {
    const snapshot = line.snapshots.find((item) => item.id === line.active_curve_snapshot_id)
    return snapshot && snapshot.qc_snapshot_id === selected.quality.latest_snapshot?.id
      && snapshot.adjustment_set_id === line.workspace.adjustment_set_id
      && snapshot.fit_mode === line.workspace.fit_mode && snapshot.coordinate_type === line.workspace.coordinate_type
  }))
  const changeView = (view: AnalysisView) => {
    if (!selected) return
    setViewByRun((current) => ({ ...current, [selected.id]: view }))
    onViewChange(view)
  }
  const nextLine = async () => {
    if (!selected || busy || !lineSaved) return
    const next = selected.curves.lines[lineIndex + 1]
    if (next) {
      setLineByRun((current) => ({ ...current, [selected.id]: next.line_id }))
      changeView('curve')
    } else if (allSaved && canCurve) {
      const saved = await mutate(() => api.mergeAnalysisResults(token, selected.id, '逐线复核完成，合并保存样品结果'), '全部谱线复核完成，样品结果已保存')
      if (saved) changeView('samples')
    }
  }

  return (
    <div className={`page-content analysis-page refined-page remaining-page analysis-workbench${!selected ? ' analysis-preparing' : ''}${!runs.length ? ' analysis-no-batches' : ''}`} data-navigation-view={currentView}>
      <section className="analysis-hero">
        <div className="analysis-title"><span className="analysis-title-icon"><BarChart3 size={22} /></span><div><h1>样品分析</h1><p>测量与复核 · 标准曲线 · 样品结果</p></div></div>
        <div className="analysis-header-actions file-actions">
          <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="analysis" label="打开样品文件" disabled={busy || active.has(selected?.status ?? '')} onOpened={async result => {
            const ids = result.records?.filter(record => record.sample_no > 0 && Boolean(record.sample_name?.trim())).map(record => record.id) ?? result.record_ids
            setLegacyIds(ids)
            const next = await api.analysisOptions(token)
            setOptions(next)
            if (!ids.length) { setOpenedLegacy(value => value + 1); onToast('文件已保存，但没有可直接分析的已编号样品，请核对样号'); return }
            const candidates = next.method_versions.filter(method => method.calculation_profile === 'legacy_2_0_2')
            const method = candidates.find(method => method.method_version_id === legacyMethod) ?? (candidates.length === 1 ? candidates[0] : null)
            if (!method) { setOpenedLegacy(value => value + 1); onToast('文件已保存，请选择对应方法，随后自动接入分析'); return }
            const adapted = await api.importLegacyAnalysisSources(token, ids, method.method_version_id)
            setLegacyMethod(method.method_version_id); setSampleIds(adapted.sample_ids); setProfile('legacy_2_0_2')
            setOptions(await api.analysisOptions(token))
            onToast('旧样品已打开并接入准备分析')
          }}/><button className="secondary-button" aria-expanded={!railCollapsed} onClick={() => setRailCollapsed(!railCollapsed)}>
          {railCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}{railCollapsed ? '展开列表' : '收起列表'}
        </button><button className="secondary-button" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={15} />刷新
        </button></div>
      </section>
      <div className={`analysis-layout task-columns ${railCollapsed ? 'rail-hidden' : ''}`}>
        <aside className="surface analysis-sidebar">
          <div className="surface-heading">
            <div>
              <h2>分析批次 <span className="analysis-count">{runs.length}</span></h2>
            </div>
          </div>
          <div className="analysis-run-list">
            {runs.map((run) => (
              <button key={run.id} disabled={busy} className={selected?.id === run.id ? 'active' : ''} onClick={() => void choose(run)}>
                <strong>{run.name}</strong>
                <span>
                  {statusLabels[run.status]} · {run.samples.length} 样品
                </span>
                <small><span title={run.calculation_profile}>{calculationProfileLabel(run.calculation_profile)}</span></small>
              </button>
            ))}
          </div>
          {selected && <>
              {currentView !== 'raw' && selected.curves.lines.length > 0 && (
                <div className="analysis-line-nav">
                  <span>分析谱线 <small>{selected.curves.lines.length}</small></span>
                  {selected.curves.lines.map((line) => (
                    <button
                      disabled={busy}
                      key={line.line_id}
                      className={curveLine?.line_id === line.line_id ? 'active' : ''}
                      onClick={() => setLineByRun((current) => ({ ...current, [selected.id]: line.line_id }))}
                    >
                      <strong>{line.element}</strong>
                      <small>{line.wavelength_nm.toFixed(3)} nm</small>
                      {line.active_curve_snapshot_id && <i>已有曲线</i>}
                    </button>
                  ))}
                </div>
              )}
          </>}
        </aside>
        <main className="analysis-main">

          <div className="analysis-setup" onClickCapture={(event) => {
            const toggle = event.target instanceof Element ? event.target.closest('button.disclosure-toggle') : null
            if (!toggle || toggle.getAttribute('aria-expanded') !== 'false') return
            // The anchored forms share one area; closing a form retains its mounted draft.
            event.currentTarget.querySelectorAll<HTMLButtonElement>('button.disclosure-toggle[aria-expanded="true"]')
              .forEach((other) => { if (other !== toggle) other.click() })
          }}>
            <FormDisclosure title="旧 CDT/CMT 再分析" hasItems={!openedLegacy} objectKey={openedLegacy ? `opened-${openedLegacy}` : selected?.id}>
              <section className="surface analysis-legacy-import">
                <p>打开样品文件，选择对应的已保存兼容算法方法；完整重复组校验通过后自动接入分析。</p>
                <select
                  aria-label="旧样品分析方法"
                  value={legacyMethod ?? ''}
                  onChange={(event) => { const method = Number(event.target.value) || null; setLegacyMethod(method); if (method && legacyIds.length) void importLegacy(legacyIds, method) }}
                >
                  <option value="">选择确切方法版本</option>
                  {options?.method_versions
                    .filter((method) => method.calculation_profile === 'legacy_2_0_2')
                    .map((method) => (
                      <option key={method.method_version_id} value={method.method_version_id}>
                        {method.name} v{method.version}
                      </option>
                    ))}
                </select>
                <div className="analysis-legacy-list">
                  <select
                    multiple
                    size={Math.min(6, Math.max(2, options?.legacy_sources?.length ?? 0))}
                    aria-label="旧样品记录"
                    value={legacyIds.map(String)}
                    onChange={(event) =>
                      setLegacyIds(Array.from(event.target.selectedOptions, (option) => Number(option.value)))
                    }
                  >
                    {options?.legacy_sources?.map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.format.toUpperCase()} #{source.id} · {source.sample_name} · 样号 {source.sample_no}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                className="primary-button"
                  disabled={!canExecute || busy || !legacyMethod || !legacyIds.length}
                  onClick={() => void importLegacy()}
                >
                  适配所选旧样品
                </button>
              </section>
            </FormDisclosure>
            <FormDisclosure
              title="建立分析运行"
              error={createError}
              hasItems={Boolean(runs.length)}
              objectKey={selected?.id}
            >
              <AnalysisRunForm
                create={create}
                name={name}
                setName={setName}
                profile={profile}
                setProfile={setProfile}
                timeout={timeout}
                setTimeout={setTimeout}
                slowMode={slowMode}
                setSlowMode={setSlowMode}
                grouped={grouped}
                sampleIds={sampleIds}
                toggleSample={toggleSample}
                busy={busy}
                canExecute={canExecute}
              />
            </FormDisclosure>
          </div>
          {selected && (
            <section className="surface analysis-detail">
              {selected.curves.lines.some(
                (line) =>
                  line.active_curve_snapshot_id &&
                  line.snapshots.find((snapshot) => snapshot.id === line.active_curve_snapshot_id)?.qc_snapshot_id !==
                  selected.quality.latest_snapshot?.id
              ) && <div className="auth-error">质控已变化：请重新拟合、保存曲线并合并结果，新报告不能使用旧值。</div>}
              <div className="analysis-status-row">
                <div>
                  <h2>{selected.name}</h2>
                  <span className={`analysis-status ${selected.status}`}>{statusLabels[selected.status]}</span>
                  <p>
                    {selected.method_name} v{selected.method_version} · <span title={selected.calculation_profile}>{calculationProfileLabel(selected.calculation_profile)}</span>
                  </p>
                </div>
                <div className="analysis-actions">
                  {selected.status === 'draft' && (
                    <button className="primary-button" onClick={() => void act('start')} disabled={busy || !canExecute}>
                      <PlayCircle size={15} />
                      开始
                    </button>
                  )}
                  {selected.status === 'running' && (
                    <button className="primary-button" onClick={() => void act('step')} disabled={busy || !canExecute}>
                      <StepForward size={15} />
                      推进一条谱线
                    </button>
                  )}
                  {canExecute && active.has(selected.status) && (
                    <button className="secondary-button danger" onClick={() => void act('cancel')}>
                      <Square size={14} />
                      取消
                    </button>
                  )}
                </div>
              </div>
              {selected.failure_code && (
                <div className="analysis-failure">
                  <ShieldAlert size={17} />
                  <div>
                    <strong>{selected.failure_code}</strong>
                    <span>{selected.failure_message}</span>
                  </div>
                </div>
              )}
              {checkpoint && (
                <AnalysisIntervention
                  checkpoint={checkpoint}
                  chart={chart}
                  minPoint={minPoint}
                  span={span}
                  maxValue={maxValue}
                  adjustedPosition={adjustedPosition}
                  setAdjustedPosition={setAdjustedPosition}
                  reason={reason}
                  setReason={setReason}
                  intervene={intervene}
                  busy={busy}
                  canIntervene={canIntervene}
                />
              )}
              <nav className="analysis-view-tabs" aria-label="分析视图">
                {(
                  [
                    ['raw', '谱图与测量'],
                    ['curve', '曲线图'],
                    ['standards', '标准点'],
                    ['samples', '样品结果']
                  ] as Array<[AnalysisView, string]>
                ).map(([id, label]) => (
                  <button
                    key={id}
                    className={currentView === id ? 'active' : ''}
                    onClick={() => changeView(id)}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              {currentView === 'raw' && (
                <div className="analysis-measurement-content">
                <AnalysisSpectrum key={selected.id} token={token} run={selected} canSaveMethod={canSaveMethod} onToast={onToast} preferences={options?.preferences} />
                {options?.preferences?.log_analysis && selected.messages.length>0 && <p role="status">{selected.messages[selected.messages.length-1]?.message}</p>}
                <AnalysisRawResults
                  selected={selected}
                />
                {selected.status==='completed' && <IntensityOutput key={selected.id} token={token} runId={selected.id} defaults={options?.intensity_output_defaults}
                  canPrint={canPrint} canSaveMethod={canSaveMethod} canExecute={canExecute} onToast={onToast}/>}
                </div>
              )}
              <div className={`analysis-review-layout ${currentView === 'raw' ? 'measurement-view' : ''}`}>
                <div className="analysis-review-content">
              {currentView === 'curve' && curveLine && (
                <AnalysisCurves
                  curveLine={curveLine}
                  canCurve={canCurve}
                  curveAction={curveAction}
                  busy={busy}
                  selected={selected}
                  mutate={mutate}
                  token={token}
                  shownSnapshot={shownSnapshot}
                  showPreview={showPreview}
                  canPrint={canPrint}
                  printCurve={printCurve}
                />
              )}
              {currentView === 'standards' && curveLine && (
                <AnalysisStandards
                  curveLine={curveLine}
                  selected={selected}
                  setAdjustments={setAdjustments}
                  adjustments={adjustments}
                  busy={busy}
                  canCurve={canCurve}
                  curveAction={curveAction}
                />
              )}
              {currentView === 'samples' && curveLine && (
                <AnalysisSamples
                  busy={busy}
                  canCurve={canCurve}
                  selected={selected}
                  mutate={mutate}
                  token={token}
                  curveLine={curveLine}
                />
              )}
                </div>
                <aside className="analysis-review-qc" aria-label="当前谱线复核">
              {currentView !== 'raw' && (
                <AnalysisQuality
                  selected={selected}
                  busy={busy}
                  canQuality={canQuality}
                  mutate={mutate}
                  token={token}
                  qcGroups={qcGroups}
                  qualityDecision={qualityDecision}
                />
              )}

                </aside>
              </div>
              {selected.status === 'completed' && <div className="analysis-progress-actions">
                <span>{lineIndex + 1} / {selected.curves.lines.length} 条谱线 · {lineSaved ? '本线曲线已保存' : '检查重复值后，拟合并保存本线曲线'}</span>
                <button className="secondary-button" disabled={busy || lineIndex <= 0}
                  onClick={() => { setLineByRun((current) => ({ ...current, [selected.id]: selected.curves.lines[lineIndex - 1].line_id })); changeView('curve') }}>上一条谱线</button>
                <button className="primary-button" disabled={busy || !lineSaved || (lineIndex === selected.curves.lines.length - 1 && (!allSaved || !canCurve))}
                  onClick={() => void nextLine()}>{lineIndex === selected.curves.lines.length - 1 ? '完成并保存结果' : '下一条谱线'}</button>
              </div>}

            </section>
          )}

        </main>
      </div>
      {preview && (
        <div className="analysis-preview-modal" role="dialog" aria-modal="true" aria-label={preview.title}>
          <div>
            <header>
              <strong>{preview.title}</strong>
              <button className="secondary-button" onClick={() => setPreview(null)}>
                关闭
              </button>
            </header>
            <iframe title={preview.title} srcDoc={preview.html} />
          </div>
        </div>
      )}
    </div>
  )
}
