import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Clock3, Flame, ListChecks, PauseCircle, PlayCircle, RefreshCw, Save, Square, Tag, TestTube2, Waves } from 'lucide-react'
import { api, type AcquisitionOptions, type AcquisitionTask } from './api'
import { CopyableCode } from './InformationDisplay'
import { NumericInput, reportInvalidNumericInput } from './NumericInput'
import { SimpleChartAxes } from './SimpleChartAxes'
import './sample-acquisition.css'

type Props = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void }

const SAMPLE_OPTIONS = ['280-288.acq', '291-299.acq', '303-310.acq']

type CurveGeometry = { path: string; minimum: number; maximum: number }

const EMPTY_POINTS: number[] = []

function lineGeometry(points: number[]): CurveGeometry {
  if (!points.length) return { path: '', minimum: 0, maximum: 1 }
  const stride = Math.max(1, Math.ceil(points.length / 720))
  const visible = points.filter((_, index) => index % stride === 0)
  const max = Math.max(...visible, 1)
  const min = Math.min(...visible, 0)
  const span = Math.max(max - min, 1)
  const path = visible.map((value, index) => {
    const x = index / Math.max(visible.length - 1, 1) * 1000
    const y = 244 - (value - min) / span * 220
    return `${index ? 'L' : 'M'}${x.toFixed(2)},${Math.max(4, Math.min(248, y)).toFixed(2)}`
  }).join(' ')
  return { path, minimum: min, maximum: max }
}

const stateLabel: Record<string, string> = {
  draft: '草稿', countdown: '倒计时', pre_excitation: '预激发', burn: '燃烧', dark: '暗帧', between_repeats: '下一重复', paused: '已暂停', stopping: '停止中', completed: '已完成', failed: '失败', stopped: '已停止',
}

export function SampleAcquisitionPage({ token, canWrite, canExecute, onToast }: Props) {
  const [options, setOptions] = useState<AcquisitionOptions | null>(null)
  const [tasks, setTasks] = useState<AcquisitionTask[]>([])
  const [selected, setSelected] = useState<AcquisitionTask | null>(null)
  const [loading, setLoading] = useState(false)
  const [auto, setAuto] = useState(false)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [taskKind, setTaskKind] = useState<'sample' | 'evaporation'>('sample')
  const [taskName, setTaskName] = useState('S13 样品采集')
  const [profileId, setProfileId] = useState<number | null>(null)
  const [layoutId, setLayoutId] = useState<string>('default')
  const [methodKey, setMethodKey] = useState('')
  const [queueId, setQueueId] = useState('')
  const [queueItemId, setQueueItemId] = useState('')
  const [sampleName, setSampleName] = useState('')
  const [sampleKind, setSampleKind] = useState<'test' | 'normal' | 'standard' | 'blank' | 'preheat'>('test')
  const [storageMode, setStorageMode] = useState<'averaged' | 'full_interval'>('averaged')
  const [repeatCount, setRepeatCount] = useState(1)
  const [burnCount, setBurnCount] = useState(3)
  const [darkCount, setDarkCount] = useState(1)
  const [countdown, setCountdown] = useState(0)
  const [preExcitation, setPreExcitation] = useState(1)
  const [samplingPeriod, setSamplingPeriod] = useState(1)
  const [burnCycle, setBurnCycle] = useState(1)
  const [darkCycle, setDarkCycle] = useState(1)
  const [simulatorSample, setSimulatorSample] = useState(SAMPLE_OPTIONS[0])
  const [seed, setSeed] = useState(13)
  const [intervalLabel, setIntervalLabel] = useState('有效区间')
  const [intervalStart, setIntervalStart] = useState(0)
  const [intervalEnd, setIntervalEnd] = useState(1)
  const [renameValue, setRenameValue] = useState('')
  const [ccdIndex, setCcdIndex] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextOptions, nextTasks] = await Promise.all([api.acquisitionOptions(token), api.acquisitionTasks(token)])
      setOptions(nextOptions)
      setTasks(nextTasks)
      setProfileId((current) => current ?? nextOptions.profiles[0]?.id ?? null)
      setLayoutId((current) => current || String(nextOptions.layouts[0]?.id ?? 'default'))
      setMethodKey((current) => nextOptions.methods.some((item) => `${item.method_id}:${item.method_version}` === current)
        ? current
        : nextOptions.methods[0] ? `${nextOptions.methods[0].method_id}:${nextOptions.methods[0].method_version}` : '')
      setSelected((current) => current ? nextTasks.find((item) => item.id === current.id) ?? current : nextTasks[0] ?? null)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取样品采集配置')
    } finally {
      setLoading(false)
    }
  }, [onToast, token])

  useEffect(() => { void load() }, [load])

  const selectedNeedsPoints = selected?.last_event?.ccds.some((item) => !Array.isArray(item.points)) ?? false

  useEffect(() => {
    if (!selected || !selectedNeedsPoints) return
    let cancelled = false
    const taskId = selected.id
    void api.acquisitionTask(token, taskId, true).then((next) => {
      if (cancelled) return
      setSelected((current) => current?.id === taskId ? next : current)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
    }).catch((error) => {
      if (!cancelled) onToast(error instanceof Error ? error.message : '无法读取采集曲线')
    })
    return () => { cancelled = true }
  }, [onToast, selected, selectedNeedsPoints, token])

  const refreshSelected = useCallback(async () => {
    if (!selected) return
    try {
      const next = await api.acquisitionTask(token, selected.id, true)
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法刷新采集任务')
    }
  }, [onToast, selected, token])

  useEffect(() => {
    if (!auto || !selected || !['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats'].includes(selected.status)) return
    const timer = window.setInterval(() => {
      if (busyRef.current) return
      busyRef.current = true
      void api.stepAcquisitionTask(token, selected.id).then((next) => {
        setSelected(next)
        setTasks((current) => current.map((item) => item.id === next.id ? next : item))
        if (['completed', 'failed', 'stopped'].includes(next.status)) setAuto(false)
      }).catch((error) => {
        setAuto(false)
        onToast(error instanceof Error ? error.message : '连续采集失败')
      }).finally(() => { busyRef.current = false })
    }, Math.max(250, samplingPeriod * 1000))
    return () => window.clearInterval(timer)
  }, [auto, onToast, samplingPeriod, selected, token])

  const queue = options?.queues.find((item) => String(item.id) === queueId)
  const queueItem = queue?.items.find((item) => String(item.id) === queueItemId)
  const displayedRepeatCount = queueItem ? (queueItem.repeats || 1) : repeatCount
  const [methodId, methodVersion] = methodKey.split(':').map(Number)
  const selectedCcd = selected?.last_event?.ccds.find((item) => item.ccd_index === ccdIndex) ?? selected?.last_event?.ccds[0]
  const selectedPoints = selectedCcd?.points ?? EMPTY_POINTS
  const boundMethod = options?.methods.find((item) => item.method_id === selected?.method_id && item.method_version === selected?.method_version)
  const messageTone = selected?.messages.some((item) => item.level === 'error') ? 'error' : selected?.messages.some((item) => item.level === 'warning') ? 'warning' : selected?.messages.some((item) => item.level === 'success') ? 'success' : 'info'
  const curve = useMemo(() => lineGeometry(selectedPoints), [selectedPoints])
  const progressLabel = selected ? `${selected.progress.toFixed(1)}% · ${selected.completed_repeats}/${selected.repeat_count} 重复` : '--'

  const apply = async (action: 'start' | 'step' | 'pause' | 'resume' | 'stop') => {
    if (!selected) return
    if (action !== 'step' && action !== 'stop' && !canExecute) return onToast('当前账户没有采集执行权限')
    setBusy(true)
    try {
      const methods = {
        start: api.startAcquisitionTask,
        step: api.stepAcquisitionTask,
        pause: api.pauseAcquisitionTask,
        resume: api.resumeAcquisitionTask,
        stop: api.stopAcquisitionTask,
      }
      const next = await methods[action](token, selected.id)
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
      if (action === 'stop' || ['completed', 'failed', 'stopped'].includes(next.status)) setAuto(false)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '采集控制失败')
    } finally {
      setBusy(false)
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canWrite) return onToast('当前账户没有采集写入权限')
    if (taskKind === 'sample' && (!Number.isInteger(methodId) || methodId < 1 || !Number.isInteger(methodVersion) || methodVersion < 1)) return onToast('请选择已发布方法版本')
    setBusy(true)
    try {
      const next = await api.createAcquisitionTask(token, {
        task_kind: taskKind,
        name: taskName,
        device_profile_id: profileId,
        ccd_layout_id: layoutId,
        method_id: taskKind === 'sample' ? methodId : undefined,
        method_version: taskKind === 'sample' ? methodVersion : undefined,
        queue_id: queueId ? Number(queueId) : undefined,
        queue_item_id: queueItemId ? Number(queueItemId) : undefined,
        sample_name: sampleName,
        sample_kind: sampleKind,
        storage_mode: taskKind === 'evaporation' ? 'full_interval' : storageMode,
        repeat_count: displayedRepeatCount,
        burn_frame_count: burnCount,
        dark_frame_count: darkCount,
        countdown_seconds: countdown,
        pre_excitation_seconds: preExcitation,
        sampling_period_seconds: samplingPeriod,
        burn_cycle_seconds: burnCycle,
        dark_cycle_seconds: darkCycle,
        simulator_sample: simulatorSample,
        seed,
      })
      setTasks((current) => [next, ...current])
      setSelected(next)
      onToast('采集任务已创建')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '创建采集任务失败')
    } finally {
      setBusy(false)
    }
  }

  const markInterval = async () => {
    if (!selected || !canWrite) return
    if (!reportInvalidNumericInput(document.querySelector('.interval-form'))) return onToast('请先修正区间帧参数')
    try {
      const result = await api.markAcquisitionInterval(token, selected.id, { repeat_index: selected.current_repeat_index, label: intervalLabel, start_frame_index: intervalStart, end_frame_index: intervalEnd })
      void result
      await refreshSelected()
      onToast('蒸发区间已标记')
    } catch (error) { onToast(error instanceof Error ? error.message : '区间标记失败') }
  }

  const rename = async () => {
    const sample = selected?.samples.find((item) => item.status === 'completed')
    if (!selected || !sample || !renameValue.trim() || !canWrite) return
    try {
      const next = await api.renameAcquisitionSample(token, selected.id, sample.id, renameValue.trim())
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
      setRenameValue('')
      onToast('采集后名称已保存，数据哈希未改变')
    } catch (error) { onToast(error instanceof Error ? error.message : '采集后命名失败') }
  }

  return <div className="page-content sample-acquisition-page" data-testid="sample-acquisition-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S13 · SAMPLE ACQUISITION</span><h1>蒸发与样品采集</h1><p>连接样品队列，按旧版采集顺序保存原始帧、平均谱带或全时区间。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} />刷新</button></section>
    <div className="sample-acquisition-grid">
      <aside className="surface acquisition-task-list"><div className="surface-heading"><div><span className="section-kicker">TASKS</span><h2>采集任务 <span className="count-badge">{tasks.length}</span></h2></div><Activity size={17} /></div>{tasks.length === 0 ? <div className="empty-state">暂无采集任务</div> : <div className="acquisition-task-rows">{tasks.map((item) => { const metadata = `${item.task_kind === 'evaporation' ? '蒸发' : item.sample_name || '临时样品'} · ${stateLabel[item.status]}`; return <button key={item.id} className={selected?.id === item.id ? 'active' : ''} onClick={() => setSelected(item)}><span className={`task-state-dot ${item.status}`} /><span><strong title={item.name}>{item.name}</strong><small title={metadata}>{metadata}</small></span><Chevron item={item} /></button> })}</div>}</aside>
      <main className="sample-acquisition-main">
        <section className="surface acquisition-create"><div className="surface-heading"><div><span className="section-kicker">NEW ACQUISITION</span><h2>建立采集任务</h2></div><Flame size={17} /></div><form className="acquisition-form" onSubmit={create}><label className="field"><span>任务类型</span><select value={taskKind} onChange={(e) => setTaskKind(e.target.value as 'sample' | 'evaporation')} disabled={!canWrite || busy}><option value="sample">样品摄谱</option><option value="evaporation">蒸发摄谱</option></select></label><label className="field"><span>任务名称</span><input value={taskName} onChange={(e) => setTaskName(e.target.value)} disabled={!canWrite || busy} /></label><label className="field"><span>设备档案</span><select value={profileId ?? ''} onChange={(e) => setProfileId(Number(e.target.value))} disabled={!canWrite || busy}>{options?.profiles.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label className="field"><span>CCD 布局</span><select value={layoutId} onChange={(e) => setLayoutId(e.target.value)} disabled={!canWrite || busy}>{options?.layouts.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.points_per_ccd} 点</option>)}</select></label>{taskKind === 'sample' && <><label className="field"><span>已发布方法版本</span><select value={methodKey} onChange={(e) => setMethodKey(e.target.value)} disabled={!canWrite || busy || !options?.methods.length} required><option value="">{options?.methods.length ? '请选择方法版本' : '暂无已发布方法版本'}</option>{options?.methods.map((item) => <option value={`${item.method_id}:${item.method_version}`} key={`${item.method_id}:${item.method_version}`}>{item.name} · v{item.method_version}</option>)}</select></label><label className="field"><span>样品队列</span><select value={queueId} onChange={(e) => { setQueueId(e.target.value); setQueueItemId('') }} disabled={!canWrite || busy}><option value="">临时样号</option>{options?.queues.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>{queue && <label className="field"><span>预录样品</span><select value={queueItemId} onChange={(e) => setQueueItemId(e.target.value)} disabled={!canWrite || busy}><option value="">请选择队列项</option>{queue.items.filter((item) => !item.spectrum_hash).map((item) => <option value={item.id} key={item.id}>{item.pre_name || '空样'} · {item.repeats || 1} 次</option>)}</select></label>}{!queueId && <><label className="field"><span>临时样号</span><input value={sampleName} onChange={(e) => setSampleName(e.target.value)} placeholder="采集后也可命名" disabled={!canWrite || busy} /></label><label className="field"><span>样品类型</span><select value={sampleKind} onChange={(e) => setSampleKind(e.target.value as typeof sampleKind)} disabled={!canWrite || busy}><option value="test">试样</option><option value="normal">普通样</option><option value="standard">标准样</option><option value="blank">空样</option><option value="preheat">预热</option></select></label></>}</>}{taskKind === 'sample' && <label className="field"><span>保存模式</span><select value={storageMode} onChange={(e) => setStorageMode(e.target.value as typeof storageMode)} disabled={!canWrite || busy}><option value="averaged">平均值 float32</option><option value="full_interval">全时原始区间</option></select></label>}<label className="field"><span>燃烧帧</span><NumericInput min={1} max={255} value={burnCount} onValueChange={setBurnCount} disabled={!canWrite || busy} /></label><label className="field"><span>暗帧</span><NumericInput min={0} max={20} value={darkCount} onValueChange={setDarkCount} disabled={!canWrite || busy} /></label><label className="field"><span>重复次数{queueItem ? '（来自队列）' : ''}</span><NumericInput min={1} max={10} value={displayedRepeatCount} onValueChange={setRepeatCount} disabled={!canWrite || busy || Boolean(queueItem)} /></label><label className="field"><span>倒计时 / 预激发 (秒)</span><div className="field-pair"><NumericInput min={0} max={600} step={0.1} value={countdown} onValueChange={setCountdown} disabled={!canWrite || busy} /><NumericInput min={0} max={600} step={0.1} value={preExcitation} onValueChange={setPreExcitation} disabled={!canWrite || busy} /></div></label><label className="field"><span>采样周期 (秒)</span><NumericInput min={0.01} max={60} step={0.01} value={samplingPeriod} onValueChange={setSamplingPeriod} disabled={!canWrite || busy} /></label><label className="field"><span>模拟帧</span><select value={simulatorSample} onChange={(e) => setSimulatorSample(e.target.value)} disabled={!canWrite || busy}>{SAMPLE_OPTIONS.map((item) => <option key={item}>{item}</option>)}</select></label><label className="field"><span>种子</span><NumericInput min={0} max={2_147_483_647} value={seed} onValueChange={setSeed} disabled={!canWrite || busy} /></label><button className="primary-button acquisition-create-button" type="submit" disabled={!canWrite || busy || (taskKind === 'sample' && !methodKey) || (Boolean(queueId) && !queueItemId)}><TestTube2 size={15} />创建任务</button></form></section>
        <section className="surface acquisition-monitor">
          <div className="surface-heading">
            <div><span className="section-kicker">LIVE ACQUISITION</span><h2 title={selected?.name}>{selected?.name ?? '选择任务'} {selected && <span className={`state-chip ${selected.status}`}>{stateLabel[selected.status]}</span>}</h2></div>
            <div className="monitor-actions">
              <button className="primary-button" onClick={() => void apply('start')} disabled={!selected || busy || !canExecute || selected.status !== 'draft'}><PlayCircle size={15} />开始</button>
              <button className="secondary-button" onClick={() => setAuto((value) => !value)} disabled={!selected || busy || !canExecute || !['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats'].includes(selected.status)}><Waves size={15} />{auto ? '停止连续' : '连续采集'}</button>
              <button className="secondary-button" onClick={() => void apply('step')} disabled={!selected || busy || !canExecute}><Clock3 size={15} />单步</button>
              {selected?.status === 'paused'
                ? <button className="secondary-button" onClick={() => void apply('resume')} disabled={busy || !canExecute}><PlayCircle size={15} />继续</button>
                : <button className="secondary-button" onClick={() => void apply('pause')} disabled={!selected || busy || !canExecute || !['countdown', 'pre_excitation', 'burn', 'dark'].includes(selected.status)}><PauseCircle size={15} />暂停</button>}
              <button className="icon-button compact danger" title="停止" onClick={() => void apply('stop')} disabled={!selected || busy || !canExecute || ['completed', 'failed', 'stopped'].includes(selected.status)}><Square size={14} /></button>
            </div>
          </div>
          {selected ? <>
            <div className="acquisition-progress">
              <div><span>总进度</span><strong>{progressLabel}</strong></div>
              <div><span>当前阶段</span><strong title={selected.last_message || stateLabel[selected.status]}>{selected.last_message || stateLabel[selected.status]}</strong></div>
              <div><span>帧数</span><strong>{selected.burn_frames_captured}/{selected.burn_frame_count} + {selected.dark_frames_captured}/{selected.dark_frame_count}</strong></div>
            </div>
            <div className="acquisition-curve-toolbar">
              <label className="field compact-field"><span>CCD</span><select value={ccdIndex} onChange={(e) => setCcdIndex(Number(e.target.value))}>{selected.ccd_indices.map((item) => <option value={item} key={item}>CCD {item + 1}</option>)}</select></label>
              <CopyableCode value={selected.last_event?.details.sha256} visibleLength={18} empty="等待帧" className="curve-hash" />
            </div>
            <div className="acquisition-curve simple-chart-plot-host">
              <div className="simple-chart-plot"><svg viewBox="0 0 1000 260" preserveAspectRatio="none" role="img" aria-label={`CCD ${ccdIndex + 1} 样品采集曲线`}><g className="acquisition-curve-grid"><line x1="0" y1="18" x2="1000" y2="18" /><line x1="0" y1="130" x2="1000" y2="130" /><line x1="0" y1="248" x2="1000" y2="248" /></g><path d={curve.path} /></svg></div>
              {selectedCcd && <SimpleChartAxes xMin={1} xMax={selectedPoints.length || selectedCcd.points_count || selected.layout.points_per_ccd} yMin={curve.minimum} yMax={curve.maximum} xLabel="CCD 点位" yLabel="强度 (ADC)" />}
              {!selectedCcd && <div className="curve-empty"><Activity size={22} /><span>开始采集后显示实时 CCD 曲线</span></div>}
            </div>
            <div className="acquisition-facts"><div><span>方法版本</span><strong title={boundMethod ? `${boundMethod.name} · v${boundMethod.method_version}` : '未绑定'}>{boundMethod ? `${boundMethod.name} · v${boundMethod.method_version}` : '未绑定'}</strong></div><div><span>峰值 / 位置</span><strong>{selectedCcd ? `${selectedCcd.peak.toLocaleString('zh-CN')} / ${selectedCcd.peak_position + 1}` : '--'}</strong></div><div><span>虚拟时间</span><strong>{selected.last_event?.details.virtual_time_ms ? `${Number(selected.last_event.details.virtual_time_ms).toFixed(0)} ms` : '--'}</strong></div><div><span>原始帧</span><strong>{selected.samples.reduce((sum, item) => sum + item.bands.length, 0)} 个均值带</strong></div><div><span>结果</span><strong className={selected.status === 'completed' ? 'good' : ''}>{selected.result_sha256 ? '已收尾' : '未完成'}</strong></div></div>
          </> : <div className="empty-state monitor-empty"><Activity size={24} /><span>选择或创建采集任务</span></div>}
        </section>
        {selected && <section className="surface acquisition-detail-grid"><div><div className="surface-heading"><div><span className="section-kicker">INTERVAL MARKS</span><h2>蒸发区间</h2></div><Tag size={16} /></div><div className="interval-form"><label className="field"><span>名称</span><input value={intervalLabel} onChange={(e) => setIntervalLabel(e.target.value)} disabled={!canWrite} /></label><label className="field"><span>起止帧</span><div className="field-pair"><NumericInput min={0} max={255} value={intervalStart} onValueChange={setIntervalStart} disabled={!canWrite} /><NumericInput min={0} max={255} value={intervalEnd} onValueChange={setIntervalEnd} disabled={!canWrite} /></div></label><button className="secondary-button" onClick={() => void markInterval()} disabled={!canWrite || selected.burn_frames_captured === 0}><Tag size={15} />标记区间</button></div>{selected.intervals.length ? <div className="interval-list">{selected.intervals.map((item) => <div key={`${item.repeat_index}-${item.label}`}><strong>{item.label}</strong><span>第 {item.repeat_index + 1} 次 · 帧 {item.start_frame_index + 1}–{item.end_frame_index + 1}</span></div>)}</div> : <div className="empty-state compact-empty">暂无区间标记</div>}</div><div><div className="surface-heading"><div><span className="section-kicker">POST ACQUISITION</span><h2>采集后命名</h2></div><Save size={16} /></div><div className="rename-form"><input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} placeholder="完整采集后输入正式样号" disabled={!canWrite || selected.status !== 'completed'} /><button className="secondary-button" onClick={() => void rename()} disabled={!canWrite || selected.status !== 'completed' || !renameValue.trim()}><Save size={15} />保存名称</button></div><div className="sample-result-list">{selected.samples.map((item) => <div key={item.id}><span className={`task-state-dot ${item.status}`} /><strong>{item.sample_name || '空样 / 未命名'}</strong><small>{item.sample_kind} · {item.status === 'completed' ? `${item.bands.length} CCD 均值带` : stateLabel[item.status]}</small></div>)}</div></div></section>}
        {selected && <section className="surface acquisition-messages"><div className="surface-heading"><div><span className="section-kicker">ACQUISITION LOG</span><h2>全部采集消息 <span className="count-badge">{selected.messages.length}</span></h2></div><span className={`message-summary-icon ${messageTone}`}>{messageTone === 'error' || messageTone === 'warning' ? <AlertTriangle size={16} /> : messageTone === 'success' ? <CheckCircle2 size={16} /> : <ListChecks size={16} />}</span></div><div className="message-list">{[...selected.messages].reverse().map((item) => <div key={item.id} className={item.level}><span>{item.created_at.slice(11, 19)}</span><strong title={item.message}>{item.message}</strong><code title={item.code}>{item.code}</code></div>)}</div></section>}
      </main>
    </div>
  </div>
}

function Chevron({ item }: { item: AcquisitionTask }) {
  return <span className="task-progress">{item.progress.toFixed(0)}%</span>
}
