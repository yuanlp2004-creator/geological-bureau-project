
export type Props = { token: string; canWrite: boolean; canExecute: boolean; canSaveSample?: boolean;
  currentMethodId?: number; actionsTarget?: HTMLElement | null; onLockChange?: (reason: string | null) => void;
  onToast: (message: string) => void }

export const anomalyLabels: Record<string, string> = {
  baseline_low: '基线强度偏低', baseline_high: '基线强度偏高', baseline_shift: '基线位置偏移',
  peak_shift: '峰位偏移', frame_fault: '原始帧损坏', turn_timeout: '转角超时', none: '正常'
}
export const decisionLabels: Record<string, string> = {
  accept: '已确认', correct: '自动校正后重采', retry: '重新采集', manual: '等待人工处理', stop: '安全停止'
}
export const anomalyText = (value: unknown) => String(value ?? '').split(',').map(key => anomalyLabels[key] ?? key).join('、')

export const labels: Record<string, string> = {
  draft: '草稿',
  connecting: '连接中',
  connected: '已连接',
  pre_excitation: '预激发',
  turning: '转角中',
  collecting: '采集中',
  anomaly: '异常待处理',
  manual_intervention: '人工接管',
  paused: '已暂停',
  stopping: '安全停止中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
  safety_stopped: '安全停止',
  deferred_external: '外部依赖',
  pending: '待执行',
  retry_pending: '等待重试',
  confirmed: '已确认',
  manual: '人工处理'
}

export const terminalStates = new Set(['completed', 'failed', 'stopped', 'safety_stopped', 'deferred_external'])

export const activeStates = new Set(['pre_excitation', 'turning', 'collecting'])
