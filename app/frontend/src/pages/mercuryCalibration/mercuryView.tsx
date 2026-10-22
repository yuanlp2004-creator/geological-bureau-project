
export type Props = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void; embedded?: boolean; actionsTarget?: HTMLElement | null; active?: boolean }

export const labels: Record<string, string> = {
  draft: '草稿',
  stabilizing: '稳定中',
  acquiring: '采集中',
  ready: '待应用',
  applied: '已应用',
  rolled_back: '已回滚',
  stopped: '已停止',
  safe_off: '安全关闭',
  deferred_external: '外部依赖',
  pending: '待定位',
  located: '已定位',
  not_found: '未找到'
}

export const activeStates = new Set(['stabilizing', 'acquiring'])

export const terminalStates = new Set(['applied', 'rolled_back', 'stopped', 'safe_off', 'deferred_external'])
