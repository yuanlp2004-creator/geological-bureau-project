export type Props = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void }

export const SAMPLE_OPTIONS = ['280-288.acq', '291-299.acq', '303-310.acq']

export const EMPTY_POINTS: number[] = []

export const stateLabel: Record<string, string> = {
  draft: '草稿',
  countdown: '倒计时',
  pre_excitation: '预激发',
  burn: '燃烧',
  dark: '暗帧',
  between_repeats: '等待下次摄谱',
  paused: '已暂停',
  stopping: '停止中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止'
}
