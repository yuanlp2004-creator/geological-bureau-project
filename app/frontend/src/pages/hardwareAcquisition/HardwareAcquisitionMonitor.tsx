import type { HardwareTask } from '../../api'
import type { ReactNode } from 'react'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'
import { activeStates, anomalyText, decisionLabels, labels, terminalStates } from './hardwareView'

type Action = 'start' | 'step' | 'pause' | 'resume' | 'stop' | 'accept' | 'retry'
type Props = { selected: HardwareTask; control: (action: Action) => Promise<void>; busy: boolean; canExecute: boolean;
  auto: boolean; controlError: string; interventionNote: string; setInterventionNote: (note: string) => void; children?: ReactNode }

export function HardwareAcquisitionMonitor({ selected: task, control, busy, canExecute, auto, controlError,
  interventionNote, setInterventionNote, children }: Props) {
  const step = task.steps.find(item => item.order_index === task.current_step_index)
  const manual = task.execution_mode === 'manual'
  const decision = task.decisions[task.decisions.length - 1]
  const observed = (Array.isArray(decision?.observed) ? decision.observed : []) as Record<string, unknown>[]
  const measuredStep = task.steps.find(item => item.id === decision?.step_id)
  const config = task.plan.find(item => item.order_index === measuredStep?.order_index)
  const baseline = observed.find(item => item.baseline_monitored === true || (item.baseline_monitored === undefined
    && typeof item.baseline_intensity === 'number' && (config?.baseline_ccd_index == null || item.ccd_index === config.baseline_ccd_index)))
  const peak = observed.find(item => item.peak_monitored === true || (item.peak_monitored === undefined
    && typeof item.peak_position === 'number' && (config?.peak_ccd_index == null || item.ccd_index === config.peak_ccd_index)))
  const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value.toFixed(1) : '—'
  const detected = [...String(decision?.anomaly_kind ?? '').split(','),
    ...observed.flatMap(item => Array.isArray(item.detected) ? item.detected as string[] : [])]
  const health = (kinds: string[], monitored: Record<string, unknown> | undefined) => !monitored ? '待检测'
    : detected.some(kind => ['frame_fault', 'turn_timeout'].includes(kind)) ? '无法检测'
    : detected.some(kind => kinds.includes(kind)) ? '异常' : '正常'
  const latestAttempt = Math.max(0, ...task.frames.filter(frame => frame.step_id === step?.id).map(frame => Number(frame.attempt)))
  const pending = task.frames.some(frame => frame.step_id === step?.id && frame.attempt === latestAttempt && !frame.confirmed)
    && !task.frames.some(frame => frame.step_id === step?.id && frame.attempt === latestAttempt && frame.damaged)
  const active = activeStates.has(task.status)
  const disabled = busy || !canExecute
  return <aside className="hardware-monitor" aria-label="自动转角采集控制">
    <h2>摄谱窗口 <span className={`state-chip ${task.status}`}>{labels[task.status]}</span></h2>
    <div className="hardware-monitor-content">
    <fieldset className="hardware-task-summary"><legend>当前采集</legend>
      <label><span>样号</span><output aria-label="当前转角样号">{task.sample_name || '未命名'}</output></label>
      <label><span>{manual ? '转角' : '波段 / 转角'}</span><output aria-label="当前波段与转角">{step ? `${manual ? '' : `${step.wavelength_nm?.toFixed(2)} nm · `}${step.angle_deg.toFixed(2)}°` : '—'}</output></label>
      {manual && step && <label><span>已采集</span><output aria-label="当前采集时长">{(step.captured_seconds ?? 0).toFixed(1)} / {step.duration_seconds} 秒</output></label>}
    </fieldset>
    <fieldset className="hardware-command-area"><legend>采集控制</legend>
    <div className="hardware-command-buttons">
      <button type="button" title={task.status === 'draft' ? '开始采集' : '继续采集'}
        disabled={disabled || !(task.status === 'draft' || task.status === 'paused' || (active && !auto))}
        onClick={() => void control(task.status === 'draft' ? 'start' : task.status === 'paused' ? 'resume' : 'step')}>
        <SpectroscopyIcon name="capture" /><span>{task.status === 'draft' ? '开始采集' : '继续采集'}</span></button>
      <button type="button" title="暂停采集" disabled={disabled || !active} onClick={() => void control('pause')}>
        <SpectroscopyIcon name="pause" /><span>暂停采集</span></button>
      <button type="button" title="停止采集" disabled={disabled || task.status === 'draft' || terminalStates.has(task.status)} onClick={() => void control('stop')}>
        <SpectroscopyIcon name="stop" /><span>停止采集</span></button>
    </div>
    </fieldset>
    <fieldset className="hardware-health" aria-label="摄谱状态检测"><legend>摄谱状态
      {measuredStep && <small className="hardware-measured-band"> · 最近 {manual ? `${measuredStep.angle_deg.toFixed(2)}°` : `${measuredStep.wavelength_nm?.toFixed(2)} nm`}</small>}</legend>
      {manual && !task.method_id ? <p>未配置方法监测线</p> : <>
      <dl><div><dt>基线强度</dt><dd data-health="baseline-intensity">{health(['baseline_low', 'baseline_high'], baseline)} · {number(baseline?.baseline_intensity)}</dd></div>
        <div><dt>基线位置</dt><dd data-health="baseline-position">{health(['baseline_shift'], baseline)} · {number(baseline?.baseline_position)}</dd></div>
        <div><dt>峰位</dt><dd data-health="peak-position">{health(['peak_shift'], peak)} · {number(peak?.peak_position)}</dd></div></dl>
      {decision && <p className={String(decision.anomaly_kind) !== 'none' ? 'hardware-detection-warning' : ''} role="status">
        {anomalyText(decision.anomaly_kind)} · {decisionLabels[String(decision.decision)] ?? String(decision.decision)}</p>}
      </>}
    </fieldset>
    {task.status === 'manual_intervention' && <div className="hardware-alert manual" role="alert">
      <strong>请检查异常谱图</strong><input aria-label="异常处置说明" maxLength={300} placeholder="处置说明（可选）"
        disabled={disabled} value={interventionNote} onChange={e => setInterventionNote(e.target.value)} />
      <div className="intervention-actions"><button className="secondary-button" disabled={disabled || !pending} onClick={() => void control('accept')}>确认采用</button>
        <button className="secondary-button" disabled={disabled} onClick={() => void control('retry')}><SpectroscopyIcon name="capture" />重新采集</button></div>
    </div>}
    {task.status === 'deferred_external' && <p className="hardware-alert external" role="alert">转角协议尚未接入，未发送设备命令。</p>}
    {(task.status === 'safety_stopped' || task.status === 'failed') && <p className="hardware-alert danger" role="alert">
      {task.status === 'safety_stopped' ? '异常重采未通过，已安全停止。未确认数据不会进入结果。' : task.failure_message || '采集失败，请检查设备。'}</p>}
    {task.status === 'paused' && <p role="status">采集已暂停，点击“继续采集”恢复。</p>}
    {controlError && <p className="hardware-alert danger" role="alert">{controlError}</p>}
    {children}
    </div>
  </aside>
}
