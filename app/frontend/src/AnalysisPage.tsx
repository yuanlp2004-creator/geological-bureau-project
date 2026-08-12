import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { BarChart3, CheckCircle2, CirclePause, ListChecks, PlayCircle, RefreshCw, ShieldAlert, Square, StepForward } from 'lucide-react'
import { api, type AnalysisOptions, type AnalysisRun } from './api'
import { SimpleChartAxes } from './SimpleChartAxes'
import './analysis.css'

type Props = { token: string; canExecute: boolean; canIntervene: boolean; onToast: (message: string) => void }

const statusLabels: Record<string, string> = { draft: '草稿', running: '分析中', paused: '慢进待确认', completed: '已完成', cancelled: '已取消', failed: '失败' }
const active = new Set(['running', 'paused'])

export function AnalysisPage({ token, canExecute, canIntervene, onToast }: Props) {
  const [options, setOptions] = useState<AnalysisOptions | null>(null)
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [selected, setSelected] = useState<AnalysisRun | null>(null)
  const [sampleIds, setSampleIds] = useState<number[]>([])
  const [name, setName] = useState('S16 定量分析')
  const [profile, setProfile] = useState<'legacy_2_0_2' | 'modern_v1'>('modern_v1')
  const [slowMode, setSlowMode] = useState(true)
  const [timeout, setTimeout] = useState(300)
  const [adjustedPosition, setAdjustedPosition] = useState<number | null>(null)
  const [reason, setReason] = useState('人工复核峰位')
  const [busy, setBusy] = useState(false)

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
    setBusy(true)
    try {
      update(await api.interveneAnalysisRun(token, selected.id, { action, adjusted_position: action === 'accept' ? adjustedPosition : null, reason }))
      onToast(action === 'accept' ? '人工调整已确认并写入最终谱线结果' : '已放弃调整并采用自动定位结果')
    } catch (error) { onToast(error instanceof Error ? error.message : '处理慢进检查点失败') }
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

  return <div className="analysis-page">
    <section className="analysis-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S16 · QUANTITATIVE ANALYSIS</span><h1>定量分析与慢进干预</h1><p>锁定采集谱带、方法版本和计算档案，逐谱线生成可重放结果。</p></div><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} />刷新</button></section>
    <div className="analysis-layout">
      <aside className="surface analysis-sidebar"><div className="surface-heading"><div><span className="section-kicker">RUNS</span><h2>分析批次</h2></div><BarChart3 size={17} /></div>
        <div className="analysis-run-list">{runs.map((run) => <button key={run.id} className={selected?.id === run.id ? 'active' : ''} onClick={() => void api.analysisRun(token, run.id).then(update)}><strong>{run.name}</strong><span>{statusLabels[run.status]} · {run.samples.length} 样品</span><small>{run.calculation_profile}</small></button>)}</div>
      </aside>
      <main className="analysis-main">
        <form className="surface analysis-create" onSubmit={create}><div className="surface-heading"><div><span className="section-kicker">NEW RUN</span><h2>建立分析运行</h2></div><ListChecks size={17} /></div>
          <div className="analysis-form-grid"><label className="field"><span>批次名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field"><span>计算档案</span><select value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)}><option value="modern_v1">modern_v1 · 高斯面积定量</option><option value="legacy_2_0_2">legacy_2_0_2 · 旧版峰高</option></select></label><label className="field"><span>慢进超时（秒）</span><input type="number" min="1" max="86400" value={timeout} onChange={(event) => setTimeout(Number(event.target.value))} /></label><label className="analysis-switch"><input type="checkbox" checked={slowMode} onChange={(event) => setSlowMode(event.target.checked)} /><span><strong>逐谱线慢进</strong><small>每条谱线暂停并等待接受或放弃</small></span></label></div>
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
            <div className="checkpoint-controls"><label className="field"><span>调整后峰位</span><input type="number" min={checkpoint.window_start} max={checkpoint.window_end} value={adjustedPosition ?? ''} onChange={(event) => setAdjustedPosition(Number(event.target.value))} /></label><label className="field grow"><span>调整理由</span><input value={reason} onChange={(event) => setReason(event.target.value)} /></label><button className="primary-button" onClick={() => void intervene('accept')} disabled={busy || !canIntervene}><CheckCircle2 size={15} />接受调整</button><button className="secondary-button" onClick={() => void intervene('discard')} disabled={busy || !canIntervene}>放弃调整</button></div>
          </div>}
          <div className="analysis-matrix"><div className="surface-heading"><div><span className="section-kicker">RESULT MATRIX</span><h3>单/多样品结果矩阵</h3></div><span>{selected.line_results.filter((item) => item.line_type === 'analysis').length} 条结果</span></div><table><thead><tr><th>样品</th><th>谱线</th><th>峰位</th><th>峰高</th><th>背景</th><th>Sigma</th><th>面积</th><th>定量信号</th></tr></thead><tbody>{selected.line_results.filter((item) => item.line_type === 'analysis').map((item) => <tr key={item.id}><td>{selected.samples[item.sample_position]?.sample_name}</td><td>{item.element} {item.wavelength_nm.toFixed(3)}</td><td>{item.peak_position}{item.intervention_id ? ' · 人工' : ''}</td><td>{item.peak_height.toFixed(3)}</td><td>{item.background.toFixed(3)}</td><td>{item.gaussian_sigma?.toFixed(4) ?? '—'}</td><td>{item.gaussian_area?.toFixed(3) ?? '—'}</td><td><strong>{item.quantitative_signal.toFixed(5)}</strong></td></tr>)}</tbody></table></div>
        </section>}
      </main>
    </div>
  </div>
}
