
export type Props = { token: string; canWrite: boolean; canExecute: boolean; canSaveSample?: boolean; onToast: (message: string) => void }

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

export const defaultTurns = JSON.stringify(
  [
    { angle_deg: 10, wavelength_nm: 250, priority: 0, key_band: false, expected_peak_position: 1024 },
    { angle_deg: 20, wavelength_nm: 280, priority: 1, key_band: true, expected_peak_position: 1024 },
    { angle_deg: 30, wavelength_nm: 310, priority: 0, key_band: false, expected_peak_position: 1024 }
  ],
  null,
  2
)

export const terminalStates = new Set(['completed', 'failed', 'stopped', 'safety_stopped', 'deferred_external'])

export const activeStates = new Set(['pre_excitation', 'turning', 'collecting'])
