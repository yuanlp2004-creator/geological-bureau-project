import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Activity, AlertTriangle, CheckCircle2, ChevronRight, ClipboardList, PauseCircle, PlayCircle, RefreshCw, RotateCcw, ShieldAlert, Square, SquareTerminal, Wrench } from 'lucide-react'
import { api, type HardwareOptions, type HardwareTask } from './api'
import { CopyableCode } from './InformationDisplay'
import { NumericInput } from './NumericInput'
import './hardware-acquisition.css'

type Props = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void }

const labels: Record<string, string> = {
  draft: '草稿', connecting: '连接中', connected: '已连接', pre_excitation: '预激发', turning: '转角中', collecting: '采集中',
  anomaly: '异常待处理', manual_intervention: '人工接管', paused: '已暂停', stopping: '安全停止中', completed: '已完成', failed: '失败',
  stopped: '已停止', safety_stopped: '安全停止', deferred_external: '外部依赖', pending: '待执行', retry_pending: '等待重试', confirmed: '已确认', manual: '人工处理',
}

const defaultTurns = JSON.stringify([
  { angle_deg: 10, wavelength_nm: 250, priority: 0, key_band: false, expected_peak_position: 1024 },
  { angle_deg: 20, wavelength_nm: 280, priority: 1, key_band: true, expected_peak_position: 1024 },
  { angle_deg: 30, wavelength_nm: 310, priority: 0, key_band: false, expected_peak_position: 1024 },
], null, 2)

const terminalStates = new Set(['completed', 'failed', 'stopped', 'safety_stopped', 'deferred_external'])
const activeStates = new Set(['pre_excitation', 'turning', 'collecting'])

export function HardwareAcquisitionPage({ token, canWrite, canExecute, onToast }: Props) {
  const [options, setOptions] = useState<HardwareOptions | null>(null)
  const [tasks, setTasks] = useState<HardwareTask[]>([])
  const [selected, setSelected] = useState<HardwareTask | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [auto, setAuto] = useState(false)
  const [name, setName] = useState('S14 自动转角任务')
  const [profileId, setProfileId] = useState<number | null>(null)
  const [layoutId, setLayoutId] = useState<string>('default')
  const [strategy, setStrategy] = useState<'short_to_long' | 'key_first'>('short_to_long')
  const [policy, setPolicy] = useState<'retry_then_stop' | 'manual'>('retry_then_stop')
  const [retryLimit, setRetryLimit] = useState(1)
  const [sample, setSample] = useState('280-288.acq')
  const [seed, setSeed] = useState(14)
  const [turns, setTurns] = useState(defaultTurns)
  const [anomalies, setAnomalies] = useState('[]')
  const [interventionNote, setInterventionNote] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextOptions, nextTasks] = await Promise.all([api.hardwareAcquisitionOptions(token), api.hardwareAcquisitionTasks(token)])
      setOptions(nextOptions)
      setTasks(nextTasks)
      setProfileId((current) => current ?? nextOptions.profiles[0]?.id ?? null)
      setLayoutId((current) => current !== 'default' ? current : String(nextOptions.layouts[0]?.id ?? 'default'))
      setSelected((current) => current ? nextTasks.find((item) => item.id === current.id) ?? current : nextTasks[0] ?? null)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取自动转角配置')
    } finally {
      setLoading(false)
    }
  }, [onToast, token])

  useEffect(() => { void load() }, [load])

  const refreshSelected = useCallback(async () => {
    if (!selected) return
    try {
      const next = await api.hardwareAcquisitionTask(token, selected.id)
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法刷新硬件任务')
    }
  }, [onToast, selected, token])

  const advance = useCallback(async () => {
    if (!selected || busyRef.current || !activeStates.has(selected.status)) return
    busyRef.current = true
    try {
      const next = await api.stepHardwareAcquisitionTask(token, selected.id)
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
      if (terminalStates.has(next.status) || next.status === 'manual_intervention') setAuto(false)
    } catch (error) {
      setAuto(false)
      onToast(error instanceof Error ? error.message : '自动转角推进失败')
    } finally {
      busyRef.current = false
    }
  }, [onToast, selected, token])

  useEffect(() => {
    if (!auto || !selected || !activeStates.has(selected.status)) return
    const timer = window.setInterval(() => { void advance() }, 450)
    return () => window.clearInterval(timer)
  }, [advance, auto, selected])

  const apply = async (action: 'start' | 'step' | 'pause' | 'resume' | 'stop') => {
    if (!selected) return
    if (action !== 'step' && !canExecute) { onToast('当前账户没有硬件执行权限'); return }
    setBusy(true)
    try {
      const methods = { start: api.startHardwareAcquisitionTask, step: api.stepHardwareAcquisitionTask, pause: api.pauseHardwareAcquisitionTask, resume: api.resumeHardwareAcquisitionTask, stop: api.stopHardwareAcquisitionTask }
      const next = await methods[action](token, selected.id)
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
      if (terminalStates.has(next.status) || next.status === 'manual_intervention' || action === 'stop') setAuto(false)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '硬件任务控制失败')
    } finally {
      setBusy(false)
    }
  }

  const intervene = async (action: 'accept' | 'retry' | 'stop') => {
    if (!selected || !canExecute) return onToast('当前账户没有硬件执行权限')
    setBusy(true)
    try {
      const next = await api.interveneHardwareAcquisitionTask(token, selected.id, action, interventionNote.trim())
      setSelected(next)
      setTasks((current) => current.map((item) => item.id === next.id ? next : item))
      setInterventionNote('')
      onToast(action === 'accept' ? '人工确认已记录' : action === 'retry' ? '人工重试已排程' : '任务已安全停止')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '人工接管操作失败')
    } finally {
      setBusy(false)
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canWrite) return onToast('当前账户没有硬件任务写入权限')
    let turnPayload: unknown
    let anomalyPayload: unknown
    try {
      turnPayload = JSON.parse(turns)
      anomalyPayload = JSON.parse(anomalies)
      if (!Array.isArray(turnPayload) || !turnPayload.length || !Array.isArray(anomalyPayload)) throw new Error('转角计划和异常脚本必须是数组')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '转角 JSON 无法解析')
      return
    }
    setBusy(true)
    try {
      const next = await api.createHardwareAcquisitionTask(token, { name, device_profile_id: profileId, ccd_layout_id: layoutId, strategy, anomaly_policy: policy, retry_limit: retryLimit, sample_name: sample, simulator_sample: sample, seed, turns: turnPayload, simulator_anomalies: anomalyPayload })
      setTasks((current) => [next, ...current])
      setSelected(next)
      onToast('自动转角任务已创建，计划顺序已锁定')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '创建自动转角任务失败')
    } finally {
      setBusy(false)
    }
  }

  const currentStep = selected?.steps.find((step) => step.order_index === selected.current_step_index)
  const selectedProfile = options?.profiles.find((profile) => profile.id === profileId)
  const latestDecision = selected?.decisions[selected.decisions.length - 1]
  const latestTrace = selected?.traces[selected.traces.length - 1]
  const isExternal = selected?.status === 'deferred_external'

  return <div className="page-content hardware-page" data-testid="hardware-acquisition-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S14 · HARDWARE TURN CONTROL</span><h1>真实设备与自动转角</h1><p>按短波到长波执行转角计划，保留 CCD 原始帧、命令追踪和异常处置决定。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} />刷新</button></section>
    <div className="hardware-layout">
      <aside className="surface hardware-task-list"><div className="surface-heading"><div><span className="section-kicker">TASKS</span><h2>转角任务 <span className="count-badge">{tasks.length}</span></h2></div><RotateCcw size={17} /></div>{tasks.length ? <div className="hardware-task-rows">{tasks.map((task) => { const metadata = `${task.transport === 'serial' ? '真实串口' : '确定性模拟器'} · ${labels[task.status] ?? task.status}`; return <button key={task.id} className={selected?.id === task.id ? 'active' : ''} onClick={() => setSelected(task)}><span className={`task-state-dot ${task.status}`} /><span><strong title={task.name}>{task.name}</strong><small title={metadata}>{metadata}</small></span><ChevronRight size={14} /></button> })}</div> : <div className="empty-state compact-empty">暂无自动转角任务</div>}</aside>
      <main className="hardware-main">
        <section className="surface hardware-create"><div className="surface-heading"><div><span className="section-kicker">NEW TURN TASK</span><h2>建立转角与采集计划</h2></div><ClipboardList size={17} /></div><form className="hardware-form" onSubmit={create}><label className="field"><span>任务名称</span><input value={name} onChange={(event) => setName(event.target.value)} disabled={!canWrite || busy} /></label><label className="field"><span>设备档案</span><select value={profileId ?? ''} onChange={(event) => setProfileId(Number(event.target.value))} disabled={!canWrite || busy}>{options?.profiles.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.transport === 'simulator' ? '模拟器' : '串口'}</option>)}</select></label><label className="field"><span>CCD 布局</span><select value={layoutId} onChange={(event) => setLayoutId(event.target.value)} disabled={!canWrite || busy}>{options?.layouts.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.name)} · {String(item.points_per_ccd)} 点</option>)}</select></label><label className="field"><span>执行策略</span><select value={strategy} onChange={(event) => setStrategy(event.target.value as typeof strategy)} disabled={!canWrite || busy}><option value="short_to_long">短波 → 长波</option><option value="key_first">关键波段优先</option></select></label><label className="field"><span>异常策略</span><select value={policy} onChange={(event) => setPolicy(event.target.value as typeof policy)} disabled={!canWrite || busy}><option value="retry_then_stop">有限重试后停止</option><option value="manual">转人工接管</option></select></label><label className="field"><span>重试上限</span><NumericInput min={0} max={5} value={retryLimit} onValueChange={setRetryLimit} disabled={!canWrite || busy} /></label><label className="field"><span>模拟样品</span><input value={sample} onChange={(event) => setSample(event.target.value)} disabled={!canWrite || busy} /></label><label className="field"><span>随机种子</span><NumericInput min={0} max={2_147_483_647} value={seed} onValueChange={setSeed} disabled={!canWrite || busy} /></label><label className="field span-2"><span>转角计划 JSON</span><textarea rows={7} value={turns} onChange={(event) => setTurns(event.target.value)} disabled={!canWrite || busy} spellCheck={false} /></label><label className="field span-2"><span>模拟异常脚本 JSON</span><textarea rows={7} value={anomalies} onChange={(event) => setAnomalies(event.target.value)} disabled={!canWrite || busy} spellCheck={false} placeholder='[{"step_index":0,"kind":"peak_shift","count":1}]' /></label><button className="primary-button hardware-create-button" type="submit" disabled={!canWrite || busy || !profileId}><RotateCcw size={15} />创建任务</button></form>{selectedProfile?.transport === 'serial' && <div className="surface-note warning-note"><ShieldAlert size={16} /><span>该档案是真实串口。当前缺少已确认的转角协议，启动只会记录 `deferred_external`，不会发送猜测命令字节。</span></div>}</section>
        <section className="surface hardware-monitor">
          <div className="surface-heading">
            <div><span className="section-kicker">LIVE CONTROL</span><h2 title={selected?.name}>{selected?.name ?? '选择一个任务'} {selected && <span className={`state-chip ${selected.status}`}>{labels[selected.status] ?? selected.status}</span>}</h2></div>
            <div className="hardware-actions"><button className="primary-button" onClick={() => void apply('start')} disabled={!selected || busy || !canExecute || selected.status !== 'draft'}><PlayCircle size={15} />启动</button><button className="secondary-button" onClick={() => setAuto((value) => !value)} disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}><Activity size={15} />{auto ? '停止自动推进' : '自动推进'}</button><button className="secondary-button" onClick={() => void apply('step')} disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}><ChevronRight size={15} />单步</button><button className="icon-button compact" title="暂停" onClick={() => void apply('pause')} disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}><PauseCircle size={16} /></button><button className="icon-button compact danger" title="安全停止" onClick={() => void apply('stop')} disabled={!selected || busy || !canExecute || terminalStates.has(selected.status)}><Square size={14} /></button></div>
          </div>
          {selected ? <>
            <div className="hardware-progress">
              <div><span>总进度</span><strong>{selected.progress.toFixed(1)}%</strong></div>
              <div><span>当前计划步</span><strong>{currentStep ? `${currentStep.wavelength_nm.toFixed(2)} nm · ${currentStep.angle_deg.toFixed(2)}°` : '--'}</strong></div>
              <div><span>连接状态</span><strong>{selected.transport === 'serial' ? '协议闸门' : selected.adapter_session_id ? '模拟器已连接' : '未连接'}</strong></div>
              <div><span>原始结果</span><CopyableCode value={selected.result_sha256} visibleLength={18} empty="--" className={selected.result_sha256 ? 'good' : ''} /></div>
            </div>
            {isExternal && <div className="hardware-alert external"><ShieldAlert size={17} /><span>真实硬件协议或现场记录缺失，任务已延后；没有发送命令字节。</span></div>}
            {selected.status === 'safety_stopped' && <div className="hardware-alert danger"><AlertTriangle size={17} /><span>{selected.failure_message || '异常超过边界，任务已进入安全状态。未确认帧已隔离。'}</span></div>}
            {selected.status === 'manual_intervention' && <div className="hardware-alert manual"><Wrench size={17} /><div><strong>需要人工接管</strong><small>检查当前帧后选择接受、重试或停止；损坏帧不能被接受。</small><div className="intervention-actions"><input value={interventionNote} onChange={(event) => setInterventionNote(event.target.value)} placeholder="处置说明（可选）" disabled={busy} /><button className="secondary-button" onClick={() => void intervene('accept')} disabled={busy}><CheckCircle2 size={14} />接受</button><button className="secondary-button" onClick={() => void intervene('retry')} disabled={busy}><RotateCcw size={14} />重试</button><button className="icon-button danger" title="安全停止" onClick={() => void intervene('stop')} disabled={busy}><Square size={14} /></button></div></div></div>}
            {selected.status === 'paused' && <div className="hardware-alert"><PauseCircle size={17} /><span>任务暂停在“{labels[selected.paused_from ?? 'turning']}”，恢复后从该阶段继续。</span><button className="secondary-button" onClick={() => void apply('resume')} disabled={busy || !canExecute}><PlayCircle size={14} />恢复</button></div>}
            <div className="hardware-facts"><span>最后消息</span><strong title={selected.last_message || '--'}>{selected.last_message || '--'}</strong><span>追踪事件</span><strong>{selected.traces.length}</strong><span>处置决定</span><strong>{selected.decisions.length}</strong><span>CCD 原始帧</span><strong>{selected.frames.length}</strong></div>
          </> : <div className="empty-state monitor-empty"><RotateCcw size={24} /><span>创建或选择任务后开始转角</span></div>}
        </section>
        {selected && <section className="surface hardware-plan"><div className="surface-heading"><div><span className="section-kicker">ORDERED TURN PLAN</span><h2>转角顺序与波段</h2></div><ClipboardList size={16} /></div><div className="hardware-table-wrap"><table className="hardware-table"><thead><tr><th>序号</th><th>波长</th><th>角度</th><th>优先级</th><th>波段</th><th>状态</th><th>重试</th></tr></thead><tbody>{selected.steps.map((step) => <tr key={step.id} className={step.order_index === selected.current_step_index ? 'current' : ''}><td>{step.order_index + 1}</td><td><strong>{step.wavelength_nm.toFixed(2)} nm</strong></td><td>{step.angle_deg.toFixed(2)}°</td><td>{step.priority}</td><td>{step.key_band ? <span className="key-band">关键</span> : '普通'}</td><td><span className={`state-chip ${step.status}`}>{labels[step.status] ?? step.status}</span></td><td>{step.retry_count}/{selected.retry_limit}</td></tr>)}</tbody></table></div></section>}
        {selected && <section className="hardware-evidence-grid"><section className="surface"><div className="surface-heading"><div><span className="section-kicker">COMMUNICATION TRACE</span><h2>全部命令与响应 <span className="count-badge">{selected.traces.length}</span></h2></div><SquareTerminal size={16} /></div><div className="evidence-list">{[...selected.traces].reverse().map((trace, index) => <div className="evidence-row" key={`${String(trace.sequence_no)}-${index}`}><span className={`trace-kind ${String(trace.direction)}`}>{String(trace.kind)}</span><strong title={String(trace.name)}>{String(trace.name)}</strong><CopyableCode value={String(trace.payload_sha256 || '')} visibleLength={12} empty="—" /><small title={String(trace.safe_state || '')}>{String(trace.safe_state || '')}</small></div>)}{!selected.traces.length && <div className="empty-state compact-empty">暂无追踪记录</div>}</div></section><section className="surface"><div className="surface-heading"><div><span className="section-kicker">DECISIONS</span><h2>全部异常处置 <span className="count-badge">{selected.decisions.length}</span></h2></div><ShieldAlert size={16} /></div><div className="evidence-list">{[...selected.decisions].reverse().map((decision, index) => <div className="evidence-row" key={`${String(decision.id)}-${index}`}><span className={`trace-kind ${String(decision.decision)}`}>{String(decision.decision)}</span><strong title={String(decision.anomaly_kind || 'none')}>{String(decision.anomaly_kind || 'none')}</strong><small title={String(decision.reason || '')}>{String(decision.reason || '')}</small></div>)}{!selected.decisions.length && <div className="empty-state compact-empty">暂无处置决定</div>}</div></section></section>}
        {selected && latestTrace && <div className="hardware-footer-note"><Activity size={14} />最近事件：{String(latestTrace.name)} · {String(latestDecision?.reason || selected.last_message || '')}</div>}
      </main>
    </div>
  </div>
}
