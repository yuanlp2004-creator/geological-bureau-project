import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Activity, Beaker, CheckCircle2, ChevronRight, FileCheck2, Lightbulb, PlayCircle, RefreshCw, RotateCcw, ShieldAlert, Square, SquareTerminal } from 'lucide-react'
import { api, type MercuryOptions, type MercurySession } from './api'
import { CopyableCode } from './InformationDisplay'
import { SimpleChartAxes } from './SimpleChartAxes'
import './mercury-calibration.css'

type Props = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void }

const labels: Record<string, string> = {
  draft: '草稿', stabilizing: '稳定中', acquiring: '采集中', ready: '待应用', applied: '已应用', rolled_back: '已回滚',
  stopped: '已停止', safe_off: '安全关闭', deferred_external: '外部依赖', pending: '待定位', located: '已定位', not_found: '未找到',
}
const activeStates = new Set(['stabilizing', 'acquiring'])
const terminalStates = new Set(['applied', 'rolled_back', 'stopped', 'safe_off', 'deferred_external'])

export function MercuryCalibrationPage({ token, canWrite, canExecute, onToast }: Props) {
  const [options, setOptions] = useState<MercuryOptions | null>(null)
  const [sessions, setSessions] = useState<MercurySession[]>([])
  const [selected, setSelected] = useState<MercurySession | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [auto, setAuto] = useState(false)
  const [name, setName] = useState('S15 汞灯光学校准')
  const [profileId, setProfileId] = useState<number | null>(null)
  const [layoutId, setLayoutId] = useState('default')
  const [lineIds, setLineIds] = useState<number[]>([])
  const [stabilizationFrames, setStabilizationFrames] = useState(2)
  const [offset, setOffset] = useState(6)
  const [fault, setFault] = useState('none')
  const [ccdIndex, setCcdIndex] = useState<number | null>(null)

  const update = useCallback((next: MercurySession) => {
    setSelected(next)
    setSessions((current) => current.some((item) => item.id === next.id) ? current.map((item) => item.id === next.id ? next : item) : [next, ...current])
    setCcdIndex((current) => current ?? next.layout.ccd_indices[0] ?? null)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextOptions, nextSessions] = await Promise.all([api.mercuryCalibrationOptions(token), api.mercuryCalibrationSessions(token)])
      setOptions(nextOptions); setSessions(nextSessions)
      setProfileId((value) => value ?? nextOptions.profiles[0]?.id ?? null)
      setLayoutId((value) => value !== 'default' ? value : String(nextOptions.layouts[0]?.id ?? 'default'))
      setLineIds((value) => value.length ? value : nextOptions.reference_lines.slice(0, 4).map((line) => line.id))
      if (nextSessions.length) {
        const detail = await api.mercuryCalibrationSession(token, nextSessions[0].id, true)
        update(detail)
      }
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取汞灯校准数据') }
    finally { setLoading(false) }
  }, [onToast, token, update])

  useEffect(() => { void load() }, [load])

  const choose = async (session: MercurySession) => {
    try { update(await api.mercuryCalibrationSession(token, session.id, true)) }
    catch (error) { onToast(error instanceof Error ? error.message : '无法读取校准会话') }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canWrite) return onToast('当前账户没有汞灯校准写入权限')
    if (lineIds.length < 2) return onToast('请至少选择两条汞谱线')
    setBusy(true)
    try {
      const next = await api.createMercuryCalibrationSession(token, { name, device_profile_id: profileId, ccd_layout_id: layoutId, line_ids: lineIds, stabilization_frames: stabilizationFrames, simulator_offset_points: offset, simulator_seed: 15, simulator_fault: fault })
      update(next); onToast('汞灯校准会话已建立，选线与校准前版本已锁定')
    } catch (error) { onToast(error instanceof Error ? error.message : '创建汞灯校准会话失败') }
    finally { setBusy(false) }
  }

  const run = async (action: 'start' | 'step' | 'stop' | 'apply' | 'rollback') => {
    if (!selected) return
    if ((action === 'apply' || action === 'rollback') && !canWrite) return onToast('当前账户没有应用校准版本的权限')
    if (action !== 'apply' && action !== 'rollback' && !canExecute) return onToast('当前账户没有汞灯调试执行权限')
    setBusy(true)
    try {
      const methods = { start: api.startMercuryCalibrationSession, step: api.stepMercuryCalibrationSession, stop: api.stopMercuryCalibrationSession, apply: api.applyMercuryCalibrationSession, rollback: api.rollbackMercuryCalibrationSession }
      const next = await methods[action](token, selected.id)
      update(next)
      if (terminalStates.has(next.status) || next.status === 'ready') setAuto(false)
      if (action === 'apply') onToast('光学调整版本已应用，校准前版本仍可回滚')
      if (action === 'rollback') onToast('已恢复校准前光学调整版本')
    } catch (error) { setAuto(false); onToast(error instanceof Error ? error.message : '校准控制操作失败') }
    finally { setBusy(false) }
  }

  const advance = useCallback(async () => {
    if (!selected || busyRef.current || !activeStates.has(selected.status)) return
    busyRef.current = true
    try {
      const next = await api.stepMercuryCalibrationSession(token, selected.id)
      update(next)
      if (!activeStates.has(next.status)) setAuto(false)
    } catch (error) { setAuto(false); onToast(error instanceof Error ? error.message : '自动推进失败') }
    finally { busyRef.current = false }
  }, [onToast, selected, token, update])

  useEffect(() => {
    if (!auto || !selected || !activeStates.has(selected.status)) return
    const timer = window.setInterval(() => { void advance() }, 500)
    return () => window.clearInterval(timer)
  }, [advance, auto, selected])

  const selectedProfile = options?.profiles.find((profile) => profile.id === profileId)
  const curves = selected?.last_event?.ccds ?? []
  const curve = curves.find((item) => item.ccd_index === ccdIndex) ?? curves[0]
  const curveRange = useMemo(() => {
    const points = curve?.points ?? []
    return points.length ? { minimum: Math.min(...points), maximum: Math.max(...points) } : { minimum: 0, maximum: 1 }
  }, [curve])
  const curvePath = useMemo(() => {
    const points = curve?.points ?? []
    if (!points.length) return ''
    const maximum = Math.max(1, ...points)
    const stride = Math.max(1, Math.ceil(points.length / 600))
    return points.filter((_, index) => index % stride === 0 || index === points.length - 1).map((value, index, sampled) => `${index ? 'L' : 'M'}${(index / Math.max(1, sampled.length - 1)) * 900},${250 - value / maximum * 225}`).join(' ')
  }, [curve])

  return <div className="page-content mercury-page" data-testid="mercury-calibration-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S15 · MERCURY OPTICAL ALIGNMENT</span><h1>汞灯调试与光学校准</h1><p>以权威汞线定位峰位，计算光学偏移建议；结果独立于色散方法版本。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} />刷新</button></section>
    <div className="mercury-layout">
      <aside className="surface mercury-session-list"><div className="surface-heading"><div><span className="section-kicker">SESSIONS</span><h2>校准会话 <span className="count-badge">{sessions.length}</span></h2></div><Lightbulb size={17} /></div><div className="mercury-session-rows">{sessions.map((session) => { const metadata = `${session.transport === 'simulator' ? '合成汞谱' : '真实串口'} · ${labels[session.status]}`; return <button key={session.id} className={selected?.id === session.id ? 'active' : ''} onClick={() => void choose(session)}><span className={`task-state-dot ${session.status}`} /><span><strong title={session.name}>{session.name}</strong><small title={metadata}>{metadata}</small></span><ChevronRight size={14} /></button> })}</div>{!sessions.length && <div className="empty-state compact-empty">暂无汞灯校准会话</div>}</aside>
      <main className="mercury-main">
        <section className="surface mercury-create"><div className="surface-heading"><div><span className="section-kicker">LINE SELECTION</span><h2>选择汞线与设备</h2></div><Beaker size={17} /></div><form onSubmit={create}><div className="mercury-form"><label className="field"><span>会话名称</span><input value={name} onChange={(event) => setName(event.target.value)} disabled={!canWrite || busy} /></label><label className="field"><span>设备档案</span><select value={profileId ?? ''} onChange={(event) => setProfileId(Number(event.target.value))} disabled={!canWrite || busy}>{options?.profiles.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.transport === 'simulator' ? '合成谱' : '串口'}</option>)}</select></label><label className="field"><span>CCD 布局</span><select value={layoutId} onChange={(event) => setLayoutId(event.target.value)} disabled={!canWrite || busy}>{options?.layouts.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.points_per_ccd} 点</option>)}</select></label><label className="field"><span>稳定帧数</span><input type="number" min="1" max="20" value={stabilizationFrames} onChange={(event) => setStabilizationFrames(Number(event.target.value))} disabled={!canWrite || busy} /></label><label className="field"><span>模拟峰偏移（点）</span><input type="number" min="-100" max="100" step="0.5" value={offset} onChange={(event) => setOffset(Number(event.target.value))} disabled={!canWrite || busy} /></label><label className="field"><span>故障脚本</span><select value={fault} onChange={(event) => setFault(event.target.value)} disabled={!canWrite || busy}><option value="none">无</option><option value="switch_failure">谱源启动失败</option><option value="stability_failure">稳定失败</option><option value="capture_failure">采集失败</option></select></label></div><div className="mercury-line-selector">{options?.reference_lines.map((line) => <label key={line.id} className={lineIds.includes(line.id) ? 'selected' : ''}><input type="checkbox" checked={lineIds.includes(line.id)} onChange={() => setLineIds((current) => current.includes(line.id) ? current.filter((id) => id !== line.id) : [...current, line.id])} disabled={!canWrite || busy} /><strong>{line.wavelength_nm.toFixed(4)} nm</strong><small>Hg I · 强度 {line.relative_intensity}</small></label>)}</div><button className="primary-button" type="submit" disabled={!canWrite || busy || !profileId || lineIds.length < 2}><Lightbulb size={15} />建立校准会话</button></form>{selectedProfile?.transport === 'serial' && <div className="surface-note warning-note"><ShieldAlert size={16} /><span>{options?.protocol_notice} 启动仅登记外部依赖。</span></div>}</section>
        <section className="surface mercury-monitor"><div className="surface-heading"><div><span className="section-kicker">SESSION CONTROL</span><h2>{selected?.name ?? '选择一个会话'} {selected && <span className={`state-chip ${selected.status}`}>{labels[selected.status]}</span>}</h2></div><div className="mercury-actions"><button className="primary-button" onClick={() => void run('start')} disabled={!selected || busy || !canExecute || selected.status !== 'draft'}><PlayCircle size={15} />启动</button><button className="secondary-button" onClick={() => setAuto((value) => !value)} disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}><Activity size={15} />{auto ? '停止自动' : '自动推进'}</button><button className="secondary-button" onClick={() => void run('step')} disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}><ChevronRight size={15} />单步</button><button className="secondary-button" onClick={() => void run('apply')} disabled={!selected || busy || !canWrite || selected.status !== 'ready'}><CheckCircle2 size={15} />应用建议</button><button className="secondary-button" onClick={() => void run('rollback')} disabled={!selected || busy || !canWrite || selected.status !== 'applied'}><RotateCcw size={15} />回滚</button><button className="icon-button compact danger" title="安全停止" onClick={() => void run('stop')} disabled={!selected || busy || !canExecute || terminalStates.has(selected.status)}><Square size={14} /></button></div></div>{selected ? <><div className="mercury-metrics"><div><span>稳定进度</span><strong>{selected.stabilized_frames}/{selected.stabilization_frames}</strong></div><div><span>校准前版本</span><strong>v{selected.before_version.version} · {selected.before_version.offset_points.toFixed(3)} 点</strong></div><div><span>建议校正</span><strong>{selected.analysis ? `${selected.analysis.suggestion_points.toFixed(3)} 点` : '--'}</strong></div><div><span>残差 RMS</span><strong className={selected.analysis?.within_tolerance ? 'good' : ''}>{selected.analysis ? `${selected.analysis.before_rms.toFixed(3)} → ${selected.analysis.after_rms.toFixed(3)}` : '--'}</strong></div><div><span>安全态</span><strong className={selected.safe_off ? 'good' : ''}>{selected.safe_off ? '已关闭' : '模拟谱源活动'}</strong></div></div>{selected.status === 'deferred_external' && <div className="mercury-alert external"><ShieldAlert size={17} /><span>真实汞灯协议、抓包和现场硬件缺失；没有生成或发送命令字节。</span></div>}{selected.status === 'safe_off' && <div className="mercury-alert danger"><ShieldAlert size={17} /><span>{selected.failure_message || '异常已触发安全关闭，未应用校准。'}</span></div>}<div className="mercury-last-message">{selected.last_message || '等待操作'}</div></> : <div className="empty-state monitor-empty"><Lightbulb size={24} /><span>建立或选择会话后开始调试</span></div>}</section>
        {selected && <section className="surface mercury-spectrum"><div className="surface-heading"><div><span className="section-kicker">LIVE SPECTRUM</span><h2>实时汞谱</h2></div><label className="inline-select">CCD <select value={ccdIndex ?? ''} onChange={(event) => setCcdIndex(Number(event.target.value))}>{selected.layout.ccd_indices.map((index) => <option key={index} value={index}>{index}</option>)}</select></label></div><div className="mercury-plot simple-chart-plot-host">{curvePath ? <><div className="simple-chart-plot"><svg viewBox="0 0 900 270" role="img" aria-label={`CCD ${curve?.ccd_index} 汞谱`}><path className="grid-line" d="M0 250H900 M0 137.5H900 M0 25H900" /><path className="spectrum-line" d={curvePath} /></svg></div><SimpleChartAxes xMin={1} xMax={curve?.points?.length ?? selected.layout.points_per_ccd} yMin={curveRange.minimum} yMax={curveRange.maximum} xLabel="CCD 点位" yLabel="强度 (ADC)" /></> : <div className="empty-state compact-empty">推进到稳定帧后显示光谱</div>}</div></section>}
        {selected && <section className="surface mercury-lines"><div className="surface-heading"><div><span className="section-kicker">PEAK COMPARISON</span><h2>汞线峰位与校正前后</h2></div><Activity size={16} /></div><div className="mercury-table-wrap"><table><thead><tr><th>汞线</th><th>CCD</th><th>期望位置</th><th>实测位置</th><th>校正前偏移</th><th>校正后偏移</th><th>状态</th></tr></thead><tbody>{selected.lines.map((line) => <tr key={line.id}><td><strong>{line.wavelength_nm.toFixed(4)} nm</strong></td><td>{line.expected_ccd_index}</td><td>{line.expected_position.toFixed(3)}</td><td>{line.observed_position?.toFixed(3) ?? '--'}</td><td>{line.offset_points?.toFixed(3) ?? '--'}</td><td>{line.after_offset_points?.toFixed(3) ?? '--'}</td><td><span className={`state-chip ${line.state}`}>{labels[line.state]}</span></td></tr>)}</tbody></table></div></section>}
        {selected && <section className="mercury-evidence"><section className="surface"><div className="surface-heading"><div><span className="section-kicker">VERSION EVIDENCE</span><h2>版本与完整性</h2></div><FileCheck2 size={16} /></div><dl><dt>活动版本</dt><dd>v{selected.active_version.version}</dd><dt>候选版本</dt><dd>{selected.candidate_version ? `v${selected.candidate_version.version}` : '--'}</dd><dt>候选快照</dt><dd><CopyableCode value={selected.candidate_version?.snapshot_sha256} visibleLength={18} empty="--" /></dd><dt>原始帧</dt><dd>{selected.frames.length}</dd></dl></section><section className="surface"><div className="surface-heading"><div><span className="section-kicker">TRACE</span><h2>全部调试与安全轨迹 <span className="count-badge">{selected.traces.length}</span></h2></div><SquareTerminal size={16} /></div><div className="mercury-traces">{[...selected.traces].reverse().map((trace, index) => <div key={index}><span>{String(trace.kind)}</span><strong title={String(trace.name)}>{String(trace.name)}</strong><CopyableCode value={String(trace.payload_sha256 ?? '')} visibleLength={12} empty="—" /><small title={String(trace.safe_state ?? '')}>{String(trace.safe_state ?? '')}</small></div>)}{!selected.traces.length && <div className="empty-state compact-empty">暂无轨迹</div>}</div></section></section>}
      </main>
    </div>
  </div>
}
