import { SectionHeading } from '../../components/SectionHeading'
import { PageFileActions } from '../../components/PageFileActions'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { calculationProfileLabel } from '../../components/calculationProfile'
import { useEffect, useMemo, useState } from 'react'
import { Database, Download, RefreshCw, Search } from 'lucide-react'
import {
  api,
  type PostProcessingRecalculationOptions,
  type PostProcessingRun
} from '../../api'
import { shortHash, formatMeasureTime } from './formatting'
import type { AnalysisCurveSnapshot } from '../../api'
import type { RecalculationCurveDetail, RecalculationCurveDraft } from '../../api/postprocessing'
import { StandardCurveWorkspace, standardCurveLineLabel, type StandardCurveAdjustment } from '../analysis/StandardCurveWorkspace'
import { ViewerDialog } from '../spectra/ViewerDialog'

type CurveWorkspace = Pick<AnalysisCurveSnapshot, 'points' | 'fit_mode' | 'coordinate_type'>
type WorkingCurve = { workspace: CurveWorkspace; snapshot?: AnalysisCurveSnapshot; fittedRequest?: RecalculationCurveDraft }

type Props = {
  actionsTarget?: HTMLElement | null
  active?: boolean
  embedded?: boolean
  token: string
  view: 'recalculate' | 'reports' | 'intensity'
  canWrite: boolean
  canExecute: boolean
  canExport: boolean
  onToast: (message: string) => void
}

const runStatusLabel: Record<string, string> = {
  completed: '已完成',
  blocked: '已阻断',
  failed: '失败',
  pending: '等待中',
  running: '执行中'
}

export function PostProcessingPage({
  actionsTarget,
  active = true,
  embedded = false,
  token,
  view,
  canWrite,
  canExecute,
  canExport,
  onToast
}: Props) {
  const [methodVersionId, setMethodVersionId] = useState<number | undefined>()
  const [options, setOptions] = useState<PostProcessingRecalculationOptions>({
    methods: [],
    sources: [],
    curve_snapshots: []
  })
  const [exportBatch, setExportBatch] = useState('')
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [sourceQuery, setSourceQuery] = useState('')
  const [selectedCurves, setSelectedCurves] = useState<number[]>([])
  const [profile, setProfile] = useState<'legacy_2_0_2' | 'modern_v1'>('legacy_2_0_2')
  const [allowOlderMethod, setAllowOlderMethod] = useState(false)
  const [format, setFormat] = useState<'txt' | 'csv' | 'excel'>('csv')
  const [directory, setDirectory] = useState('')
  const [filename, setFilename] = useState('s18-export')
  const [runs, setRuns] = useState<PostProcessingRun[]>([])
  const [busy, setBusy] = useState(false)
  const [setupOpen, setSetupOpen] = useState(false)
  const [viewedId, setViewedId] = useState<number>()
  const [curveDetails, setCurveDetails] = useState<RecalculationCurveDetail>()
  const [curveError, setCurveError] = useState('')
  const [drafts, setDrafts] = useState<Record<number, WorkingCurve>>({})
  const [lastBatch, setLastBatch] = useState<PostProcessingRun>()


  const filteredSources = useMemo(() => {
    const query = sourceQuery.trim().toLocaleLowerCase()
    if (!query) return options.sources
    return options.sources.filter((source) =>
      [source.id, source.label, source.kind, source.source_sha256, source.measure_time].some((value) =>
        value?.toLocaleLowerCase().includes(query)
      )
    )
  }, [options.sources, sourceQuery])
  const availableCurves = useMemo(
    () =>
      options.curve_snapshots.filter(
        (curve) => curve.method_version_id === methodVersionId && curve.calculation_profile === profile
      ),
    [options.curve_snapshots, methodVersionId, profile]
  )
  const viewedCurve = availableCurves.find((curve) => curve.id === viewedId)
    ?? availableCurves.find((curve) => selectedCurves.includes(curve.id)) ?? availableCurves[0]
  const curveId = viewedCurve?.id
  const details = curveDetails?.snapshot.id === curveId ? curveDetails : undefined
  const draft = curveId == null ? undefined : drafts[curveId]
  const workspace = draft?.workspace ?? details?.snapshot
  const draftPending = selectedCurves.some((id) => drafts[id] && !drafts[id].fittedRequest)
  const exportSelectionCount = exportBatch ? 1 : selectedSources.length

  const load = async () => {
    try {
      const [nextRecalculations, nextOptions] = await Promise.all([
        api.postprocessingRecalculations(token),
        api.postprocessingRecalculationOptions(token)
      ])
      setRuns(nextRecalculations.runs)
      setOptions(nextOptions)
      setMethodVersionId((current) => current ?? nextOptions.methods[0]?.method_version_id)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法加载 S18 数据')
    }
  }

  useEffect(() => {
    void load()
  }, [token])

  useEffect(() => {
    setCurveError('')
    setCurveDetails(undefined)
    if (!active || curveId == null) return
    let cancelled = false
    void api.postprocessingRecalculationCurve(token, curveId).then((next) => {
      if (!cancelled) setCurveDetails(next)
    }).catch((error) => {
      if (!cancelled) setCurveError(error instanceof Error ? error.message : '无法读取曲线快照')
    })
    return () => { cancelled = true }
  }, [active, curveId, token])

  useEffect(() => { setLastBatch(undefined) }, [methodVersionId, profile, selectedSources, selectedCurves, allowOlderMethod, drafts])

  const toggleSource = (id: string) =>
    setSelectedSources((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]))
  const toggleCurve = (id: number) => {
    const lineId = availableCurves.find((curve) => curve.id === id)?.line_id
    setViewedId(id)
    setSelectedCurves((current) => {
      const otherLines = current.filter((value) => availableCurves.find((curve) => curve.id === value)?.line_id !== lineId)
      return current.includes(id) ? otherLines : [...otherLines, id]
    })
  }

  const selectVisibleSources = () => {
    const visibleIds = filteredSources.map((source) => source.id)
    setSelectedSources((current) => [...new Set([...current, ...visibleIds])])
  }
  const invertVisibleSources = () => {
    const currentSet = new Set(selectedSources)
    filteredSources.forEach((source) =>
      currentSet.has(source.id) ? currentSet.delete(source.id) : currentSet.add(source.id)
    )
    setSelectedSources([...currentSet])
  }
  const curvesByLine = new Map(availableCurves.slice().reverse().map((curve) => [curve.line_id, curve]))
  const selectAllCurves = () => setSelectedCurves([...curvesByLine.values()].map((curve) => curve.id))
  const invertCurves = () => {
    const selectedLines = new Set(availableCurves.filter((curve) => selectedCurves.includes(curve.id)).map((curve) => curve.line_id))
    setSelectedCurves([...curvesByLine.values()].filter((curve) => !selectedLines.has(curve.line_id)).map((curve) => curve.id))
  }

  const fitDraft = async (id: number, value: CurveWorkspace) => {
    if (busy || !canExecute) return
    const request: RecalculationCurveDraft = {
      fit_mode: value.fit_mode, coordinate_type: value.coordinate_type,
      points: value.points.map(({ point_index, active, adjusted_intensity }) => ({ point_index, active, adjusted_intensity })),
    }
    setBusy(true)
    try {
      const { snapshot } = await api.fitPostprocessingRecalculationCurve(token, id, request)
      setDrafts((current) => ({ ...current, [id]: { workspace: snapshot, snapshot, fittedRequest: request } }))
      onToast('重算草稿已拟合')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '拟合失败')
    } finally {
      setBusy(false)
    }
  }

  const adjustDraft = (action: StandardCurveAdjustment, _message: string, refit?: boolean) => {
    if (curveId == null || !workspace || busy || !canExecute) return
    let value = { ...workspace }
    if (action.action === 'set_fit') value.fit_mode = action.fit_mode
    else if (action.action === 'set_coordinate') value.coordinate_type = action.coordinate_type
    else {
      value = { ...value, points: workspace.points.map((point) => {
        if (action.action === 'restore_all') return { ...point, adjusted_intensity: point.original_intensity }
        if (point.point_index !== action.point_index) return point
        if (action.action === 'set_active') return { ...point, active: action.active }
        return { ...point, adjusted_intensity: action.action === 'restore' ? point.original_intensity : action.adjusted_intensity }
      }) }
    }
    setDrafts((current) => ({ ...current, [curveId]: { workspace: value, snapshot: draft?.snapshot } }))
    if (profile === 'legacy_2_0_2' && refit) void fitDraft(curveId, value)
  }

  const recalculate = async () => {
    if (busy || !canExecute || !selectedSources.length || !methodVersionId || !selectedCurves.length)
      return onToast('请选择源记录、确切方法版本和曲线快照')
    if (draftPending) return onToast('请先重新拟合所选曲线的草稿')
    setBusy(true)
    try {
      const curveDrafts = selectedCurves.flatMap((id) => {
        const fitted = drafts[id]?.fittedRequest
        return fitted ? [[id, fitted] as const] : []
      })
      const batch = await api.recalculatePostprocessing(token, {
        ...(allowOlderMethod ? { allow_older_method: true } : {}),
        source_record_ids: selectedSources,
        method_version_id: methodVersionId,
        calculation_profile: profile,
        curve_snapshot_ids: selectedCurves,
        ...(curveDrafts.length ? { curve_drafts: Object.fromEntries(curveDrafts) } : {})
      })
      setLastBatch(batch)
      if (batch.status === 'completed') {
        setExportBatch(`recalc:${batch.id}`)
      }
      onToast(batch.status === 'completed' ? '重算已完成，导出来源已选中本批次' : '重算已阻断，请查看批次诊断')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '重算失败')
    } finally {
      setBusy(false)
    }
  }

  const exportMatrix = async () => {
    if (!canExport || !directory.trim()) return onToast('请输入输出目录')
    const recordIds = exportBatch ? [exportBatch] : selectedSources
    if (!recordIds.length) return onToast('请选择要导出的记录')
    setBusy(true)
    try {
      await api.exportPostprocessing(token, {
        record_ids: recordIds,
        kind: 'result_matrix',
        format,
        output_directory: directory,
        filename,
        same_name_strategy: 'suffix'
      })
      onToast('矩阵已原子导出')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '导出失败')
    } finally {
      setBusy(false)
    }
  }

  const [recalculateActionsTarget, setRecalculateActionsTarget] = useState<HTMLDivElement | null>(null)
  const refreshActions = <PageFileActions target={view === 'recalculate' ? recalculateActionsTarget : actionsTarget} hidden={!active}>
    <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="recalculate" label="打开强度文件" disabled={busy} onOpened={async result => {
      await load(); setSelectedSources(result.record_ids.map(id => `result:${id}`)); setSourceQuery('')
      if (profile !== 'legacy_2_0_2') { setProfile('legacy_2_0_2'); setSelectedCurves([]) }
    }}/>

    <span className="postprocessing-count-pill"><Database size={14}/>{options.sources.length} 条源记录</span>
    <button className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={15}/>刷新数据</button>
  </PageFileActions>
  const executeButton = <button type="button" className="primary-button postprocessing-recalculate-button"
    disabled={!canExecute || !selectedSources.length || !selectedCurves.length || busy || draftPending}
    onClick={() => void recalculate()}>执行精确重算</button>
  const samplePreview = (lastBatch?.result?.sources ?? []).flatMap((source) => (source.lines ?? [])
    .filter((line) => line.curve_snapshot_id === curveId)
    .map((line) => ({ sample_name: line.sample_name, calculated_value: line.calculated_value, intensity: line.quantitative_signal })))
  const nextCurve = viewedCurve && [...curvesByLine.values()][[...curvesByLine.keys()].indexOf(viewedCurve.line_id) + 1]
  return (
    <div
      className="page-content postprocessing-page refined-page remaining-page"
      data-testid="postprocessing-page"
      data-navigation-view={view}
    >
      {!embedded && view !== 'recalculate' && <section className="page-action-toolbar">
        
        {refreshActions}
      </section>}

      {(embedded || view === 'recalculate') && refreshActions}
      <div className="postprocessing-workbench">
        <section style={view === 'recalculate' || view === 'intensity' ? undefined : { display: 'none' }} className="surface postprocessing-surface postprocessing-recalculation-surface">
            <div className="surface-heading">
              <SectionHeading title={<>{view === 'recalculate' ? '确切版本重算' : '结果来源'}</>} />
              {view === 'recalculate' && <button type="button" className="secondary-button" disabled={busy}
                onClick={() => setSetupOpen(true)}>重算设置 · {selectedSources.length} 源 / {selectedCurves.length} 曲线</button>}
              <div ref={setRecalculateActionsTarget} className="page-file-actions-slot" />
            </div>

            {view === 'recalculate' && <div className="recalculation-curve-surface">
              {details && workspace && viewedCurve ? <StandardCurveWorkspace key={viewedCurve.id} line={details} workspace={workspace}
                profile={profile} shownSnapshot={draft?.snapshot ?? details.snapshot} currentFit={!draft || Boolean(draft.fittedRequest)}
                canEdit={canExecute && !busy} adjust={adjustDraft} fit={() => void fitDraft(viewedCurve.id, workspace)}
                samplePreview={samplePreview}
                status={lastBatch?.status === 'completed' ? '重算已完成，请查看数据预览'
                  : lastBatch?.status === 'blocked' ? '重算已阻断，请查看批次诊断' : draft ? '本次重算草稿已拟合' : `曲线快照 #${viewedCurve.id}`}
                toolbar={<>
                  <button type="button" disabled={busy || !nextCurve} onClick={() => nextCurve && setViewedId(nextCurve.id)}>下一条谱线</button>
                  <select aria-label="重算谱线和曲线版本" disabled={busy} value={viewedCurve.id} onChange={(event) => setViewedId(Number(event.target.value))}>
                    {availableCurves.map((curve) => <option key={curve.id} value={curve.id}>
                      {curve.element && curve.wavelength_nm != null ? standardCurveLineLabel({element: curve.element, wavelength_nm: curve.wavelength_nm}) : curve.line_id} · #{curve.id}
                    </option>)}
                  </select>
                  <label><input type="checkbox" checked={selectedCurves.includes(viewedCurve.id)} disabled={busy}
                    onChange={() => toggleCurve(viewedCurve.id)} />用于重算</label>
                </>}
                footer={<>
                  {draft && <button type="button" disabled={busy} onClick={() => setDrafts((current) => {
                    const next = { ...current }; delete next[viewedCurve.id]; return next
                  })}>恢复曲线快照</button>}
                  {executeButton}
                </>}
              /> : <div className="postprocessing-empty">{curveError || (viewedCurve ? '正在读取标准曲线…' : '请选择有可用曲线的目标方法和计算模式')}</div>}
            </div>}

            {setupOpen && <ViewerDialog title="重算设置" onClose={() => setSetupOpen(false)}>
            <div className="postprocessing-version-grid" style={view === 'recalculate' ? undefined : { display: 'none' }}>
              <label className="field">
                <span>方法版本</span>
                <select
                  aria-label="方法版本"
                  value={methodVersionId ?? ''}
                  onChange={(event) => {
                    setMethodVersionId(event.target.value ? Number(event.target.value) : undefined)
                    setSelectedCurves([])
                  }}
                >
                  <option value="">请选择</option>
                  {options.methods.map((method) => (
                    <option key={method.method_version_id} value={method.method_version_id}>
                      {method.name} · v{method.version}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>计算模式</span>
                <select
                  aria-label="计算模式"
                  value={profile}
                  onChange={(event) => {
                    setProfile(event.target.value as typeof profile)
                    setSelectedCurves([])
                  }}
                >
                  <option value="legacy_2_0_2">{calculationProfileLabel('legacy_2_0_2')}</option>
                  <option value="modern_v1">{calculationProfileLabel('modern_v1')}</option>
                </select>
              </label>
            </div>

            <div className="postprocessing-list-section">
              <div className="postprocessing-list-heading">
                <div>
                  <strong>源记录</strong>
                  <span>
                    {selectedSources.length} / {options.sources.length}
                  </span>
                </div>
                <div>
                  <button type="button" onClick={selectVisibleSources}>
                    全选
                  </button>
                  <button type="button" onClick={invertVisibleSources}>
                    反选
                  </button>
                </div>
              </div>
              <label className="postprocessing-search compact">
                <Search size={13} />
                <input
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="筛选重算源记录"
                  aria-label="筛选重算源记录"
                />
              </label>
              <div className="postprocessing-choice-list sources">
                {filteredSources.length === 0 && <div className="postprocessing-empty">没有可选的重算源记录</div>}
                {filteredSources.map((source) => (
                  <label
                    className={`postprocessing-choice ${selectedSources.includes(source.id) ? 'selected' : ''}`}
                    key={source.id}
                  >
                    <input
                      type="checkbox"
                      checked={selectedSources.includes(source.id)}
                      onChange={() => toggleSource(source.id)}
                    />
                    <span>
                      <strong title={source.label}>{source.label}</strong>
                      <small title={source.id}>
                        {source.kind === 'result' ? '结果' : '样品'} · {formatMeasureTime(source.measure_time)}
                      </small>
                    </span>
                    <code title={source.source_sha256 || source.id}>{shortHash(source.source_sha256, 9)}</code>
                  </label>
                ))}
              </div>
            </div>

            <div style={view === 'recalculate' ? undefined : { display: 'none' }}>
            <div className="postprocessing-list-section">
              <div className="postprocessing-list-heading">
                <div>
                  <strong>曲线快照</strong>
                  <span>
                    {selectedCurves.length} / {availableCurves.length}
                  </span>
                </div>
                <div>
                  <button type="button" onClick={selectAllCurves}>
                    全选
                  </button>
                  <button type="button" onClick={invertCurves}>
                    反选
                  </button>
                </div>
              </div>
              <div className="postprocessing-choice-list curves">
                {availableCurves.length === 0 && (
                  <div className="postprocessing-empty">当前方法与计算模式没有可发布曲线</div>
                )}
                {availableCurves.map((curve) => (
                  <label
                    className={`postprocessing-choice ${selectedCurves.includes(curve.id) ? 'selected' : ''}`}
                    key={curve.id}
                  >
                    <input
                      type="checkbox"
                      checked={selectedCurves.includes(curve.id)}
                      onChange={() => toggleCurve(curve.id)}
                    />
                    <span>
                      <strong>{curve.line_id}</strong>
                      <small>
                        {curve.fit_mode} · {curve.coordinate_type}
                      </small>
                    </span>
                    <code>#{curve.id}</code>
                  </label>
                ))}
              </div>
            </div>

            <label className="checkbox-row"><input type="checkbox" checked={allowOlderMethod} onChange={(event) => setAllowOlderMethod(event.target.checked)}/>
              已核对方法修改，允许重算较旧 PDT（记录此确认）</label>
            <button type="button" className="primary-button" onClick={() => setSetupOpen(false)}>确定</button>

            </div>
            </ViewerDialog>}
            <div className="postprocessing-run-section">
              <div className="postprocessing-list-heading">
                <div>
                  <strong>最近运行</strong>
                  <span>{runs.length} 个批次</span>
                </div>
              </div>
              <div className="postprocessing-run-list">
                {runs.length === 0 && <div className="postprocessing-empty compact">尚无转换或重算记录</div>}
                {runs.slice(0, 5).map((run) => (
                  <div className="postprocessing-run" key={run.id}>
                    <span>
                      <strong title={run.id}>{run.id}</strong>
                      <small title={run.input_sha256}>{shortHash(run.input_sha256)}</small>
                    </span>
                    <em className={`run-status ${run.status}`}>{runStatusLabel[run.status] || run.status}</em>
                    {Array.isArray(run.result?.blocked) && run.result.blocked.length > 0 &&
                      <small>{run.result.blocked.map((item) => item.message ?? item.code).join('、')}</small>}
                  </div>
                ))}
              </div>
            </div>
          </section>
      </div>

      <section style={view === 'intensity' ? undefined : { display: 'none' }} className="surface postprocessing-surface postprocessing-export-surface">
          <div className="surface-heading">
            <div>
              <h2>重算结果与已导入结果导出</h2>
            </div>
            <Download size={18} />
          </div>
          <div className="postprocessing-export-grid">
            <label className="field">
              <span>文件格式</span>
              <select value={format} onChange={(event) => setFormat(event.target.value as typeof format)}>
                <option value="txt">文本（TXT）</option>
                <option value="csv">CSV</option>
                <option value="excel">Excel（XLS）</option>
              </select>
            </label>
            <label className="field postprocessing-directory-field">
              <span>输出目录</span>
              <input
                value={directory}
                onChange={(event) => setDirectory(event.target.value)}
                placeholder="例如 C:\\Exports"
              />
            </label>
            <label className="field">
              <span>文件名</span>
              <input value={filename} onChange={(event) => setFilename(event.target.value)} />
            </label>
          </div>
          <div className="postprocessing-export-footer">
              <label className="field">
                <span>矩阵输出来源</span>
                <select value={exportBatch} onChange={(event) => setExportBatch(event.target.value)}>
                  <option value="">所选原始结果（DAT 数值 / PDT 峰值与背景）</option>
                  {runs
                    .filter((run) => run.status === 'completed' && run.result)
                    .map((run) => (
                      <option key={run.id} value={`recalc:${run.id}`}>
                        重算批次 {run.id}
                      </option>
                    ))}
                </select>
              </label>
            <div>
              <strong>{exportSelectionCount} 条记录待导出</strong>
              <span>
                {exportBatch ? '使用所选重算批次数值' : '使用所选原始结果'}{' '}
                · 同名文件自动追加后缀
              </span>
            </div>
            <button
              className="primary-button"
              disabled={!canExport || !exportSelectionCount || busy}
              onClick={() => void exportMatrix()}
            >
              <Download size={15} />
              导出数据
            </button>
          </div>
        </section>
    </div>
  )
}
