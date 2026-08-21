import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { BarChart3, CheckCircle2, CirclePause, FileText, GitMerge, Image, ListChecks, PlayCircle, Printer, RefreshCw, RotateCcw, Save, ShieldAlert, Square, StepForward } from 'lucide-react'
import { api, savePdfFile, type AnalysisCurveSnapshot, type AnalysisOptions, type AnalysisRun } from './api'
import { NumericInput, reportInvalidNumericInput } from './NumericInput'
import { SimpleChartAxes } from './SimpleChartAxes'
import './analysis.css'

type Props = { token: string; initialView: 'raw' | 'quality' | 'curve'; onViewChange: (view: AnalysisView) => void; canExecute: boolean; canIntervene: boolean; canQuality: boolean; canCurve: boolean; canPrint: boolean; onToast: (message: string) => void }
type AnalysisView = 'raw' | 'quality' | 'curve' | 'standards' | 'samples'

const statusLabels: Record<string, string> = { draft: '草稿', running: '分析中', paused: '慢进待确认', completed: '已完成', cancelled: '已取消', failed: '失败' }
const active = new Set(['running', 'paused'])

function CurveChart({ snapshot }: { snapshot: AnalysisCurveSnapshot | undefined }) {
  if (!snapshot?.chart.length) return <div className="empty-state compact-empty">拟合后显示不可变曲线快照</div>
  const xValues = [...snapshot.chart.map((item) => item.intensity), ...snapshot.diagnostics.points.map((item) => item.adjusted_intensity ?? 0)]
  const yValues = [...snapshot.chart.map((item) => item.value), ...snapshot.diagnostics.points.map((item) => item.standard_value)]
  const minX = Math.min(...xValues); const maxX = Math.max(...xValues); const minY = Math.min(...yValues); const maxY = Math.max(...yValues)
  const spanX = Math.max(maxX - minX, 1e-12); const spanY = Math.max(maxY - minY, 1e-12)
  const point = (x: number, y: number) => `${40 + 820 * (x - minX) / spanX},${300 - 260 * (y - minY) / spanY}`
  return <div className="analysis-curve-chart simple-chart-plot-host"><div className="simple-chart-plot"><svg viewBox="0 0 900 340" role="img" aria-label="标准曲线"><rect x="40" y="40" width="820" height="260" /><polyline points={snapshot.chart.map((item) => point(item.intensity, item.value)).join(' ')} />{snapshot.diagnostics.points.map((item) => { const [cx, cy] = point(item.adjusted_intensity ?? 0, item.standard_value).split(','); return <circle key={item.point_index} cx={cx} cy={cy} r="5" /> })}</svg></div><SimpleChartAxes xMin={minX} xMax={maxX} yMin={minY} yMax={maxY} xLabel="强度" yLabel="分析值" /></div>
}

export function AnalysisPage({ token, initialView, onViewChange, canExecute, canIntervene, canQuality, canCurve, canPrint, onToast }: Props) {
  const [options, setOptions] = useState<AnalysisOptions | null>(null)
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [selected, setSelected] = useState<AnalysisRun | null>(null)
  const [sampleIds, setSampleIds] = useState<number[]>([])
  const [name, setName] = useState('S17 定量与曲线分析')
  const [profile, setProfile] = useState<'legacy_2_0_2' | 'modern_v1'>('modern_v1')
  const [slowMode, setSlowMode] = useState(true)
  const [timeout, setTimeout] = useState(300)
  const [adjustedPosition, setAdjustedPosition] = useState<number | null>(null)
  const [reason, setReason] = useState('人工复核峰位')
  const [busy, setBusy] = useState(false)
  const [viewByRun, setViewByRun] = useState<Record<number, AnalysisView>>({})
  const [lineByRun, setLineByRun] = useState<Record<number, string>>({})
  const [adjustments, setAdjustments] = useState<Record<string, number>>({})
  const [preview, setPreview] = useState<{ title: string; html: string } | null>(null)

  useEffect(() => {
    if (!selected) return
    setViewByRun((current) => ({ ...current, [selected.id]: initialView }))
  }, [initialView, selected?.id])

  const update = useCallback((next: AnalysisRun) => {
    setSelected(next)
    setRuns((current) => current.some((item) => item.id === next.id) ? current.map((item) => item.id === next.id ? next : item) : [next, ...current])
    if (next.checkpoint?.status === 'pending') setAdjustedPosition(next.checkpoint.automatic_position)
  }, [])

  const load = useCallback(async () => {
    setBusy(true)
    try {
      const [nextOptions, nextRuns] = await Promise.all([api.analysisOptions(token), api.analysisRuns(token)])
      setOptions(nextOptions); setRuns(nextRuns)
      if (nextRuns[0]) update(await api.analysisRun(token, nextRuns[0].id))
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取分析数据') }
    finally { setBusy(false) }
  }, [onToast, token, update])

  useEffect(() => { void load() }, [load])

  const grouped = useMemo(() => {
    const groups = new Map<number, AnalysisOptions['samples']>()
    for (const sample of options?.samples ?? []) groups.set(sample.acquisition_task_id, [...(groups.get(sample.acquisition_task_id) ?? []), sample])
    return [...groups.values()]
  }, [options])

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canExecute) return onToast('当前账户没有执行分析的权限')
    if (!sampleIds.length) return onToast('请至少选择一个已完成采集样品')
    setBusy(true)
    try {
      const methodVersionId = options?.samples.find((sample) => sampleIds.includes(sample.id))?.method_version_id
      update(await api.createAnalysisRun(token, { name, acquisition_sample_ids: sampleIds, method_version_id: methodVersionId, calculation_profile: profile, slow_mode: slowMode, intervention_timeout_seconds: timeout }))
      onToast('分析运行已建立，输入哈希和方法版本已锁定')
    } catch (error) { onToast(error instanceof Error ? error.message : '创建分析运行失败') }
    finally { setBusy(false) }
  }

  const act = async (action: 'start' | 'step' | 'cancel') => {
    if (!selected || !canExecute) return
    setBusy(true)
    try {
      const fn = action === 'start' ? api.startAnalysisRun : action === 'step' ? api.stepAnalysisRun : api.cancelAnalysisRun
      update(await fn(token, selected.id))
    } catch (error) { onToast(error instanceof Error ? error.message : '分析控制失败') }
    finally { setBusy(false) }
  }

  const intervene = async (action: 'accept' | 'discard') => {
    if (!selected || !canIntervene) return onToast('当前账户没有人工干预权限')
    if (action === 'accept' && !reportInvalidNumericInput(document.querySelector('.checkpoint-controls'))) return onToast('请先修正调整后的峰位')
    setBusy(true)
    try {
      update(await api.interveneAnalysisRun(token, selected.id, { action, adjusted_position: action === 'accept' ? adjustedPosition : null, reason }))
      onToast(action === 'accept' ? '人工调整已确认并写入最终谱线结果' : '已放弃调整并采用自动定位结果')
    } catch (error) { onToast(error instanceof Error ? error.message : '处理慢进检查点失败') }
    finally { setBusy(false) }
  }

  const mutate = async (operation: () => Promise<AnalysisRun>, success: string) => {
    setBusy(true)
    try { update(await operation()); onToast(success); return true }
    catch (error) { onToast(error instanceof Error ? error.message : '分析操作失败'); return false }
    finally { setBusy(false) }
  }

  const qualityDecision = (group: NonNullable<AnalysisRun['quality']['latest_snapshot']>['groups'][number], action: 'accept' | 'exclude' | 'restore', lineResultId: number | null, reason: string) => {
    if (!selected || !canQuality) return onToast('当前账户没有重复质控权限')
    void mutate(() => api.decideAnalysisQuality(token, selected.id, { acquisition_task_id: group.acquisition_task_id, line_id: group.line_id, action, line_result_id: lineResultId, reason }), action === 'accept' ? '质控提示已接受并保留审计记录' : action === 'exclude' ? '该重复已剔除并重新统计' : '该重复已恢复并重新统计')
  }

  const curveAction = (lineId: string, payload: Record<string, unknown>, success: string, afterSuccess?: () => void) => {
    if (!selected || !canCurve) return onToast('当前账户没有曲线调整权限')
    if (payload.action === 'adjust' && !reportInvalidNumericInput(document.querySelector('.analysis-matrix'))) return onToast('请先修正标准点数值')
    void mutate(() => api.analysisCurveAction(token, selected.id, lineId, payload), success).then((saved) => { if (saved) afterSuccess?.() })
  }

  const showPreview = async (snapshot: AnalysisCurveSnapshot, mode: 'image' | 'text') => {
    if (!selected) return
    setBusy(true)
    try { setPreview({ title: `${snapshot.line_id} · ${mode === 'image' ? '图像' : '文本'}预览`, html: await api.analysisCurvePreview(token, selected.id, snapshot.id, mode) }) }
    catch (error) { onToast(error instanceof Error ? error.message : '无法生成曲线预览') }
    finally { setBusy(false) }
  }

  const printCurve = async (snapshot: AnalysisCurveSnapshot, mode: 'image' | 'text') => {
    if (!selected || !canPrint) return onToast('当前账户没有曲线打印权限')
    setBusy(true)
    try {
      const result = await api.printAnalysisCurve(token, selected.id, snapshot.id, mode)
      const path = await savePdfFile(result.blob, `analysis-${selected.id}-curve-${snapshot.id}-${mode}.pdf`)
      update(await api.analysisRun(token, selected.id)); onToast(path ? `打印快照 #${result.jobId} 已保存至 ${path}` : `打印快照 #${result.jobId} 已生成，文件保存已取消`)
    } catch (error) { onToast(error instanceof Error ? error.message : '曲线打印失败') }
    finally { setBusy(false) }
  }

  const toggleSample = (id: number, methodVersionId: number) => {
    setSampleIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current.filter((value) => options?.samples.find((item) => item.id === value)?.method_version_id === methodVersionId), id])
  }

  const checkpoint = selected?.checkpoint?.status === 'pending' ? selected.checkpoint : null
  const chart = checkpoint?.spectrum_window ?? []
  const maxValue = Math.max(1, ...chart.map((point) => point.value))
  const minPoint = chart[0]?.point_index ?? 0
  const span = Math.max(1, (chart[chart.length - 1]?.point_index ?? minPoint + 1) - minPoint)
  const currentView = selected ? (viewByRun[selected.id] ?? initialView) : initialView
  const curveLineId = selected ? (lineByRun[selected.id] ?? selected.curves.lines[0]?.line_id ?? '') : ''
  const curveLine = selected?.curves.lines.find((item) => item.line_id === curveLineId) ?? selected?.curves.lines[0]
  const activeSnapshot = curveLine?.snapshots.find((item) => item.id === curveLine.active_curve_snapshot_id)
  const shownSnapshot = curveLine?.snapshots[curveLine.snapshots.length - 1] ?? activeSnapshot
  const qcGroups = selected?.quality.latest_snapshot?.groups.filter((group) => !curveLineId || group.line_id === curveLineId) ?? []

  return <div className="analysis-page" data-navigation-view={currentView}>
    <section className="analysis-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S17 · QUALITY & CURVE</span><h1>定量分析、重复质控与标准曲线</h1><p>从原始信号到不可变曲线快照、样品结果和合并保存，全程可重放与审计。</p></div><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} />刷新</button></section>
    <div className="analysis-layout">
      <aside className="surface analysis-sidebar"><div className="surface-heading"><div><span className="section-kicker">RUNS</span><h2>分析批次</h2></div><BarChart3 size={17} /></div>
        <div className="analysis-run-list">{runs.map((run) => <button key={run.id} className={selected?.id === run.id ? 'active' : ''} onClick={() => void api.analysisRun(token, run.id).then(update)}><strong>{run.name}</strong><span>{statusLabels[run.status]} · {run.samples.length} 样品</span><small>{run.calculation_profile}</small></button>)}</div>
      </aside>
      <main className="analysis-main">
        <form className="surface analysis-create" onSubmit={create}><div className="surface-heading"><div><span className="section-kicker">NEW RUN</span><h2>建立分析运行</h2></div><ListChecks size={17} /></div>
          <div className="analysis-form-grid"><label className="field"><span>批次名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field"><span>计算档案</span><select value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)}><option value="modern_v1">modern_v1 · 高斯面积定量</option><option value="legacy_2_0_2">legacy_2_0_2 · 旧版峰高</option></select></label><label className="field"><span>慢进超时（秒）</span><NumericInput min={0.05} max={86_400} step="any" value={timeout} onValueChange={setTimeout} /></label><label className="analysis-switch"><input type="checkbox" checked={slowMode} onChange={(event) => setSlowMode(event.target.checked)} /><span><strong>逐谱线慢进</strong><small>每条谱线暂停并等待接受或放弃</small></span></label></div>
          <div className="analysis-sample-groups">{grouped.map((samples) => <div key={samples[0].acquisition_task_id}><strong>{samples[0].acquisition_task_name}</strong><div>{samples.map((sample) => <label key={sample.id} className={sampleIds.includes(sample.id) ? 'selected' : ''}><input type="checkbox" checked={sampleIds.includes(sample.id)} onChange={() => toggleSample(sample.id, sample.method_version_id)} /><span>{sample.sample_name}</span><small>重复 {sample.repeat_index + 1} · 方法 v{sample.method_version}</small></label>)}</div></div>)}</div>
          <button className="primary-button" disabled={busy || !canExecute}>建立并锁定输入</button>
        </form>
        {selected && <section className="surface analysis-detail"><div className="analysis-status-row"><div><span className={`analysis-status ${selected.status}`}>{statusLabels[selected.status]}</span><h2>{selected.name}</h2><p>{selected.method_name} v{selected.method_version} · {selected.calculation_profile} · 输入 {selected.input_sha256.slice(0, 12)}</p></div><div className="analysis-actions">{selected.status === 'draft' && <button className="primary-button" onClick={() => void act('start')} disabled={busy}><PlayCircle size={15} />开始</button>}{selected.status === 'running' && <button className="primary-button" onClick={() => void act('step')} disabled={busy}><StepForward size={15} />推进一条谱线</button>}{active.has(selected.status) && <button className="secondary-button danger" onClick={() => void act('cancel')} disabled={busy}><Square size={14} />取消</button>}</div></div>
          {selected.failure_code && <div className="analysis-failure"><ShieldAlert size={17} /><div><strong>{selected.failure_code}</strong><span>{selected.failure_message}</span></div></div>}
          {checkpoint && <div className="analysis-checkpoint"><div className="checkpoint-heading"><div><CirclePause size={20} /><div><span>慢进检查点 #{checkpoint.sequence}</span><strong>{checkpoint.candidate.element} {checkpoint.candidate.wavelength_nm.toFixed(4)} nm</strong></div></div><small>自动峰位 {checkpoint.automatic_position} · 截止 {new Date(checkpoint.deadline_at).toLocaleString()}</small></div>
            <div className="analysis-checkpoint-chart simple-chart-plot-host">
              <div className="simple-chart-plot"><svg viewBox="0 0 690 170" preserveAspectRatio="none" role="img" aria-label="峰位周边谱图"><rect x="0" y="0" width="690" height="170" /><polyline points={chart.map((point) => `${((point.point_index - minPoint) / span) * 690},${170 - (point.value / maxValue) * 160}`).join(' ')} /><line className="auto-line" x1={((checkpoint.automatic_position - minPoint) / span) * 690} x2={((checkpoint.automatic_position - minPoint) / span) * 690} y1="0" y2="170" /><line className="adjust-line" x1={(((adjustedPosition ?? checkpoint.automatic_position) - minPoint) / span) * 690} x2={(((adjustedPosition ?? checkpoint.automatic_position) - minPoint) / span) * 690} y1="0" y2="170" /></svg></div>
              <SimpleChartAxes xMin={minPoint + 1} xMax={minPoint + span + 1} yMin={0} yMax={maxValue} xLabel="CCD 点位" yLabel="强度 (ADC)" />
            </div>
            <div className="checkpoint-controls"><label className="field"><span>调整后峰位</span><NumericInput min={checkpoint.window_start} max={checkpoint.window_end} value={adjustedPosition ?? checkpoint.automatic_position} onValueChange={setAdjustedPosition} /></label><label className="field grow"><span>调整理由</span><input value={reason} onChange={(event) => setReason(event.target.value)} /></label><button className="primary-button" onClick={() => void intervene('accept')} disabled={busy || !canIntervene}><CheckCircle2 size={15} />接受调整</button><button className="secondary-button" onClick={() => void intervene('discard')} disabled={busy || !canIntervene}>放弃调整</button></div>
          </div>}
          <nav className="analysis-view-tabs" aria-label="分析视图">{([['raw', '原始结果'], ['quality', '重复质控'], ['curve', '曲线图'], ['standards', '标准点'], ['samples', '样品结果']] as Array<[AnalysisView, string]>).map(([id, label]) => <button key={id} className={currentView === id ? 'active' : ''} onClick={() => { setViewByRun((current) => ({ ...current, [selected.id]: id })); onViewChange(id) }}>{label}</button>)}</nav>
          {currentView !== 'raw' && <div className="analysis-line-nav"><span>分析谱线</span>{selected.curves.lines.map((line) => <button key={line.line_id} className={curveLine?.line_id === line.line_id ? 'active' : ''} onClick={() => setLineByRun((current) => ({ ...current, [selected.id]: line.line_id }))}><strong>{line.element}</strong><small>{line.wavelength_nm.toFixed(3)} nm</small>{line.active_curve_snapshot_id && <i>已发布 #{line.active_curve_snapshot_id}</i>}</button>)}</div>}
          {currentView === 'raw' && <div className="analysis-matrix"><div className="surface-heading"><div><span className="section-kicker">SOURCE SIGNALS</span><h3>原始单/多样品结果矩阵</h3></div><span>{selected.line_results.filter((item) => item.line_type === 'analysis').length} 条结果</span></div><table><thead><tr><th>样品</th><th>谱线</th><th>峰位</th><th>峰高</th><th>背景</th><th>Sigma</th><th>面积</th><th>定量信号</th></tr></thead><tbody>{selected.line_results.filter((item) => item.line_type === 'analysis').map((item) => <tr key={item.id}><td>{selected.samples[item.sample_position]?.sample_name}</td><td>{item.element} {item.wavelength_nm.toFixed(3)}</td><td>{item.peak_position}{item.intervention_id ? ' · 人工' : ''}</td><td>{item.peak_height.toFixed(3)}</td><td>{item.background.toFixed(3)}</td><td>{item.gaussian_sigma?.toFixed(4) ?? '—'}</td><td>{item.gaussian_area?.toFixed(3) ?? '—'}</td><td><strong>{item.quantitative_signal.toFixed(5)}</strong></td></tr>)}</tbody></table></div>}
          {currentView === 'quality' && <div className="analysis-workspace"><div className="surface-heading"><div><span className="section-kicker">REPEAT QUALITY</span><h3>重复测量统计与决定</h3></div><div className="analysis-actions"><span className={`snapshot-state ${selected.quality.latest_snapshot?.publishable ? 'ready' : 'blocked'}`}>{selected.quality.latest_snapshot ? `质控快照 #${selected.quality.latest_snapshot.sequence} · ${selected.quality.latest_snapshot.publishable ? '可用于拟合' : '阻断拟合'}` : '尚未计算'}</span><button className="secondary-button" disabled={busy || !canQuality || selected.status !== 'completed'} onClick={() => void mutate(() => api.recalculateAnalysisQuality(token, selected.id), '重复统计已形成新的不可变质控快照')}><RefreshCw size={14} />重新统计</button></div></div>
            {!selected.quality.latest_snapshot && <div className="empty-state compact-empty">分析完成后计算平均值、极差、标准差、RSD、ID 和有效次数。</div>}
            <div className="analysis-qc-groups">{qcGroups.map((group) => <article key={`${group.acquisition_task_id}-${group.line_id}`} className={group.warnings.length ? 'warning' : 'ready'}><header><div><strong>{group.sample_name}</strong><span>{group.element} {group.wavelength_nm.toFixed(3)} nm · {group.repeat_count} 次重复</span></div><div>{group.warnings.map((warning) => <span key={warning.code} className="qc-warning">{warning.message}</span>)}{group.warnings.length > 0 && !group.warning_accepted && <button disabled={busy || !canQuality} onClick={() => qualityDecision(group, 'accept', null, '人工复核后接受当前重复性提示')}>接受提示</button>}{group.warning_accepted && <span className="qc-accepted">已人工接受</span>}</div></header><div className="qc-stat-grid">{([['均值', group.statistics.mean], ['极差', group.statistics.range], ['标准差', group.statistics.stddev], ['RSD %', group.statistics.rsd], ['ID', group.statistics.id], ['有效次数', group.statistics.effective_count]] as Array<[string, number | null]>).map(([label, value]) => <div key={label}><span>{label}</span><strong>{value == null ? '—' : label === '有效次数' ? value : value.toFixed(5)}</strong></div>)}</div><div className="qc-members">{group.members.map((member) => <div key={member.line_result_id} className={member.included ? '' : 'excluded'}><span>重复 {member.repeat_index + 1}</span><strong>{member.value.toFixed(6)}</strong><small>{member.included ? '有效' : '已剔除'}</small>{member.included ? <button disabled={busy || !canQuality} onClick={() => qualityDecision(group, 'exclude', member.line_result_id, '重复测量复核后剔除')}>剔除</button> : <button disabled={busy || !canQuality} onClick={() => qualityDecision(group, 'restore', member.line_result_id, '恢复原始重复测量')}>恢复</button>}</div>)}</div></article>)}</div>
          </div>}
          {currentView === 'curve' && curveLine && <div className="analysis-workspace"><div className="curve-command-row"><label className="field"><span>拟合方式</span><select value={curveLine.workspace.fit_mode} disabled={!canCurve} onChange={(event) => curveAction(curveLine.line_id, { action: 'set_fit', fit_mode: event.target.value, reason: '切换拟合方式' }, '拟合方式已保存到新的修正集')}><option value="linear">直线函数</option><option value="quadratic">二次曲线</option><option value="cubic">三次曲线</option><option value="spline">样条函数</option></select></label><label className="field"><span>坐标方式</span><select value={curveLine.workspace.coordinate_type} disabled={!canCurve} onChange={(event) => curveAction(curveLine.line_id, { action: 'set_coordinate', coordinate_type: event.target.value, reason: '切换坐标方式' }, '坐标方式已保存到新的修正集')}><option value="normal">普通坐标</option><option value="logarithmic">对数坐标</option></select></label><button className="primary-button" disabled={busy || !canCurve || !selected.quality.latest_snapshot} onClick={() => void mutate(() => api.fitAnalysisCurve(token, selected.id, curveLine.line_id, { reason: '复核修正集后重新拟合' }), '新的不可变曲线快照已生成')}><RefreshCw size={14} />重新拟合</button><button className="secondary-button" disabled={busy || !canCurve} onClick={() => curveAction(curveLine.line_id, { action: 'restore_all', reason: '恢复全部原始标准强度和启用状态' }, '全部标准点已恢复到原始状态')}><RotateCcw size={14} />全部恢复</button>{shownSnapshot && <button className="primary-button" disabled={busy || !canCurve || !shownSnapshot.publishable || shownSnapshot.id === curveLine.active_curve_snapshot_id} onClick={() => void mutate(() => api.publishAnalysisCurve(token, selected.id, curveLine.line_id, shownSnapshot.id, '曲线复核通过并发布'), '曲线快照已发布，样品结果永久引用该版本')}><Save size={14} />发布快照 #{shownSnapshot.id}</button>}</div>
            <div className="curve-summary"><div><span>当前修正集</span><strong>#{curveLine.workspace.sequence || '基础'}</strong></div><div><span>最新拟合快照</span><strong>{shownSnapshot ? `#${shownSnapshot.id}` : '—'}</strong></div><div><span>已发布快照</span><strong>{curveLine.active_curve_snapshot_id ? `#${curveLine.active_curve_snapshot_id}` : '—'}</strong></div><div><span>相关系数 / RMSE</span><strong>{shownSnapshot ? `${shownSnapshot.diagnostics.correlation?.toFixed(6) ?? '—'} / ${shownSnapshot.diagnostics.rmse.toFixed(5)}` : '—'}</strong></div></div><CurveChart snapshot={shownSnapshot} />
            <div className="curve-footer-actions">{shownSnapshot && <><button className="secondary-button" onClick={() => void showPreview(shownSnapshot, 'image')}><Image size={14} />图像预览</button><button className="secondary-button" onClick={() => void showPreview(shownSnapshot, 'text')}><FileText size={14} />文本预览</button><button className="secondary-button" disabled={!canPrint} onClick={() => void printCurve(shownSnapshot, 'image')}><Printer size={14} />图像打印 PDF</button><button className="secondary-button" disabled={!canPrint} onClick={() => void printCurve(shownSnapshot, 'text')}><Printer size={14} />文本打印 PDF</button></>}<span>{curveLine.snapshots.length} 个不可变快照 · {selected.curves.print_jobs.filter((job) => job.curve_snapshot_id === shownSnapshot?.id).length} 条打印记录</span></div>
          </div>}
          {currentView === 'standards' && curveLine && <div className="analysis-workspace analysis-matrix"><div className="surface-heading"><div><span className="section-kicker">STANDARD POINTS</span><h3>标准点原始强度与修正集</h3></div><span>原始强度只读</span></div><table><thead><tr><th>#</th><th>名称</th><th>原始强度</th><th>修正强度</th><th>标准值</th><th>状态</th><th>操作</th></tr></thead><tbody>{curveLine.workspace.points.map((point) => { const key = `${selected.id}-${curveLine.line_id}-${point.point_index}`; const clearAdjustment = () => setAdjustments((current) => { const next = { ...current }; delete next[key]; return next }); return <tr key={point.point_index} className={point.active ? '' : 'muted-row'}><td>{point.point_index + 1}</td><td>{point.name}</td><td><strong>{point.original_intensity?.toFixed(6) ?? '缺少重复均值'}</strong></td><td><NumericInput step="any" value={adjustments[key] ?? point.adjusted_intensity ?? 0} disabled={!canCurve || point.original_intensity == null} onValueChange={(value) => setAdjustments((current) => ({ ...current, [key]: value }))} /></td><td>{point.standard_value}</td><td><label className="analysis-point-active"><input type="checkbox" checked={point.active} disabled={!canCurve} onChange={(event) => curveAction(curveLine.line_id, { action: 'set_active', point_index: point.point_index, active: event.target.checked, reason: `${event.target.checked ? '启用' : '停用'}标准点 ${point.name}` }, '标准点启用状态已保存')} />{point.active ? '参与拟合' : '已停用'}</label></td><td><div className="analysis-actions"><button disabled={!canCurve || point.original_intensity == null} onClick={() => curveAction(curveLine.line_id, { action: 'adjust', point_index: point.point_index, adjusted_intensity: adjustments[key] ?? point.adjusted_intensity, reason: `手工保存标准点 ${point.name} 修正强度` }, '修正强度已保存到新的修正集', clearAdjustment)}>保存修正</button><button disabled={!canCurve || point.original_intensity == null} onClick={() => curveAction(curveLine.line_id, { action: 'restore', point_index: point.point_index, reason: `恢复标准点 ${point.name} 原始强度` }, '标准点已恢复原始强度', clearAdjustment)}>恢复原始</button></div></td></tr>})}</tbody></table></div>}
          {currentView === 'samples' && curveLine && <div className="analysis-workspace analysis-matrix"><div className="surface-heading"><div><span className="section-kicker">SNAPSHOT RESULTS</span><h3>样品结果与合并保存</h3></div><button className="primary-button" disabled={busy || !canCurve || selected.curves.lines.some((line) => !line.active_curve_snapshot_id)} onClick={() => void mutate(() => api.mergeAnalysisResults(token, selected.id, '保存当前已发布曲线的批次合并结果'), '结果合并快照已保存')}><GitMerge size={14} />合并并保存</button></div><table><thead><tr><th>样品</th><th>谱线</th><th>曲线快照</th><th>有效次数</th><th>均值强度</th><th>分析值</th></tr></thead><tbody>{selected.curves.results.filter((item) => !item.is_standard && item.curve_snapshot_id === curveLine.active_curve_snapshot_id).map((item) => <tr key={item.id}><td>{item.sample_name}</td><td>{curveLine.element} {curveLine.wavelength_nm.toFixed(3)}</td><td><strong>#{item.curve_snapshot_id}</strong></td><td>{item.effective_count}</td><td>{item.intensity.toFixed(6)}</td><td><strong>{item.calculated_value.toFixed(6)} {curveLine.unit}</strong></td></tr>)}</tbody></table>{!curveLine.active_curve_snapshot_id && <div className="empty-state compact-empty">发布该谱线的曲线快照后生成永久引用的样品结果。</div>}<div className="merge-history">{selected.curves.merges.map((merge) => <article key={merge.id}><div><strong>合并快照 #{merge.sequence}</strong><span>{merge.results.length} 个样品 · 曲线 {merge.curve_snapshot_ids.map((id) => `#${id}`).join('、')}</span></div><code>{merge.result_sha256.slice(0, 20)}</code></article>)}</div></div>}
        </section>}
      </main>
    </div>
    {preview && <div className="analysis-preview-modal" role="dialog" aria-modal="true" aria-label={preview.title}><div><header><strong>{preview.title}</strong><button className="secondary-button" onClick={() => setPreview(null)}>关闭</button></header><iframe title={preview.title} srcDoc={preview.html} /></div></div>}
  </div>
}
