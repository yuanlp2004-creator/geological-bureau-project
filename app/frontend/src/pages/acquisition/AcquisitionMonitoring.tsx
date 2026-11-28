import { useState, type FormEvent } from 'react'
import type { AcquisitionIntervention, AcquisitionMonitoring as Monitoring } from '../../api/acquisition'

const statusLabels: Record<Monitoring['state']['status'], string> = {
  pending: '等待燃烧帧',
  unmonitored: '未监测',
  normal: '正常',
  alert: '异常告警',
  retrying: '正在重采',
  manual: '等待人工接管',
  accepted: '已人工接受',
  safety_stopped: '已安全停机',
  stop_unconfirmed: '仪器停止未确认',
}

const actions = [
  { action: 'retry', label: '继续重采' },
  { action: 'accept', label: '接受当前帧' },
  { action: 'stop', label: '安全停机' },
] as const

export function interventionRequest(state: Monitoring['state'], enabled: boolean, reason: string, action: string) {
  const command = actions.find(item => item.action === action)
  if (!enabled || !state.awaiting_intervention || !reason.trim() || !command
    || command.action === 'accept' && !state.can_accept) return null
  return { action: command.action, reason: reason.trim() }
}

export function AcquisitionMonitoring({ monitoring, enabled, intervene }: {
  monitoring: Monitoring
  enabled: boolean
  intervene: (decision: AcquisitionIntervention) => Promise<void>
}) {
  const { state } = monitoring
  const [reason, setReason] = useState('')
  const blocked = state.accept_blocked_reason
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const action = ((event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null)?.value
    const request = interventionRequest(state, enabled, reason, action ?? '')
    if (request) void intervene(request)
  }
  return <section className="capture-monitoring" aria-label="电弧与峰位监测" data-monitoring-state={state.status}>
    <div className="capture-monitoring-summary" role="status">
      <strong>电弧与峰位监测 · {statusLabels[state.status]}</strong>
      {Boolean(monitoring.retry_limit || state.retry_count) && <span>已重采 {state.retry_count} 次</span>}
      {state.last_summary && <span className="capture-monitoring-detail">{state.last_summary}</span>}
      {state.status === 'unmonitored' && <span>当前转角没有可用的标定监测线</span>}
    </div>
    {state.awaiting_intervention && <form className="capture-monitoring-actions" onSubmit={submit}>
      {blocked && <span className="capture-monitoring-detail" role="alert">{blocked}</span>}
      <label>处理原因 <input value={reason} onChange={event => setReason(event.target.value)}
        required maxLength={200} disabled={!enabled} /></label>
      <div role="group" aria-label="人工接管操作">
        {actions.map(({ action, label }) => <button key={action} type="submit" value={action}
          disabled={!interventionRequest(state, enabled, reason, action)}
          title={action === 'accept' ? blocked ?? undefined : undefined}>{label}</button>)}
      </div>
    </form>}
  </section>
}
