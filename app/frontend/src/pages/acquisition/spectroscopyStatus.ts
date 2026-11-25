export type SpectroscopyStatusTone = 'neutral' | 'ready' | 'running' | 'burn' | 'warning' | 'danger' | 'success'

const statuses = {
  idle: { label: '空闲', tone: 'neutral' },
  positioned: { label: '转角已定位', tone: 'ready' },
  positioning: { label: '正在定位转角', tone: 'running' },
  countdown: { label: '倒计时', tone: 'running' },
  pre_excitation: { label: '预热', tone: 'running' },
  burn: { label: '激发燃弧', tone: 'burn' },
  dark: { label: '暗电流', tone: 'running' },
  between_repeats: { label: '轮次之间', tone: 'warning' },
  awaiting_turn: { label: '等待人工切角', tone: 'warning' },
  paused: { label: '已暂停', tone: 'warning' },
  stopping: { label: '停止中', tone: 'warning' },
  failed: { label: '失败', tone: 'danger' },
  completed: { label: '已完成', tone: 'success' },
  stopped: { label: '已停止', tone: 'neutral' }
} satisfies Record<string, { label: string; tone: SpectroscopyStatusTone }>

export type SpectroscopyStatusKey = keyof typeof statuses
export type SpectroscopyStatus = { key: SpectroscopyStatusKey; label: string; tone: SpectroscopyStatusTone; detail?: string }
export type SpectroscopyStatusInput = {
  status?: string
  awaitingTurn?: boolean
  positioned?: boolean
  positioning?: boolean
  failureReason?: string | null
}

export function resolveSpectroscopyStatus({ status, awaitingTurn, positioned, positioning, failureReason }: SpectroscopyStatusInput): SpectroscopyStatus {
  let key: SpectroscopyStatusKey
  if (status === 'failed' || status === 'stopping' || status === 'completed' || status === 'stopped') key = status
  else if (status === 'paused') key = awaitingTurn ? 'awaiting_turn' : 'paused'
  else if (positioning) key = 'positioning'
  else if (status === 'draft' || status === 'ready' || !status) key = positioned ? 'positioned' : 'idle'
  else key = Object.prototype.hasOwnProperty.call(statuses, status) ? status as SpectroscopyStatusKey : 'idle'

  const detail = key === 'failed' ? failureReason || undefined
    : key === 'between_repeats' ? '等待人工点击试样摄谱以开始下一次重复' : undefined
  return { key, ...statuses[key], detail }
}

type CaptureTaskStatus = {
  id?: number
  status: string
  positioned?: boolean
  positioning?: boolean
  turns?: { positioned?: boolean; awaiting_turn?: boolean }
  last_event?: { details: Record<string, unknown> } | null
  last_message?: string
  failure_message?: string | null
  failure_code?: string | null
}

export function captureStatusInput(task?: CaptureTaskStatus | null): SpectroscopyStatusInput {
  return {
    status: task?.status,
    awaitingTurn: task?.turns?.awaiting_turn,
    positioned: task?.turns?.positioned ?? task?.positioned ?? Boolean(task?.last_event?.details.turn_position),
    positioning: task?.positioning ?? (task?.last_message === '正在定位转角'),
    failureReason: task?.failure_message || task?.failure_code
  }
}

const turnStatusPriority: readonly SpectroscopyStatusKey[] = [
  'stopping', 'positioning', 'countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats',
  'failed', 'awaiting_turn', 'paused', 'stopped', 'positioned'
]

export function captureTaskPresentation(
  task: CaptureTaskStatus & { capture_turns?: { id?: number; status: string; angle_deg: number }[] },
  details: string,
  relatedTasks: readonly CaptureTaskStatus[] = [],
) {
  const { status, capture_turns: turns } = task
  if (!turns?.length) return { status, badge: resolveSpectroscopyStatus(captureStatusInput(task)), details }

  const turnStatuses = turns.map(turn => {
    const member = turn.id === undefined || turn.id === task.id ? task : relatedTasks.find(item => item.id === turn.id)
    return resolveSpectroscopyStatus({ ...captureStatusInput(member), status: turn.status })
  })
  const completedCount = turnStatuses.filter(turn => turn.key === 'completed').length
  let priority: SpectroscopyStatus | undefined
  for (const key of turnStatusPriority) {
    priority = turnStatuses.find(turn => turn.key === key)
    if (priority) break
  }
  const badge = priority ?? (completedCount > 0 && completedCount < turns.length
    ? { key: 'idle', label: '待续采', tone: 'neutral' } as const
    : resolveSpectroscopyStatus({ status: completedCount === turns.length ? 'completed' : 'draft' }))
  return { status, badge, details: `${turns.map(turn => `${turn.angle_deg}°`).join(' / ')} · ${completedCount}/${turns.length} 转角完成` }
}
