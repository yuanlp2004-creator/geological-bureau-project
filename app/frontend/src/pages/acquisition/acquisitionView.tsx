import { type AcquisitionTask } from '../../api'

export type Props = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void }

export const SAMPLE_OPTIONS = ['280-288.acq', '291-299.acq', '303-310.acq']

export type CurveGeometry = { path: string; minimum: number; maximum: number }

export const EMPTY_POINTS: number[] = []

export function lineGeometry(points: number[]): CurveGeometry {
  if (!points.length) return { path: '', minimum: 0, maximum: 1 }
  const stride = Math.max(1, Math.ceil(points.length / 720))
  const visible = points.filter((_, index) => index % stride === 0)
  const max = Math.max(...visible, 1)
  const min = Math.min(...visible, 0)
  const span = Math.max(max - min, 1)
  const path = visible
    .map((value, index) => {
      const x = (index / Math.max(visible.length - 1, 1)) * 1000
      const y = 244 - ((value - min) / span) * 220
      return `${index ? 'L' : 'M'}${x.toFixed(2)},${Math.max(4, Math.min(248, y)).toFixed(2)}`
    })
    .join(' ')
  return { path, minimum: min, maximum: max }
}

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

export function Chevron({ item }: { item: AcquisitionTask }) {
  return <span className="task-progress">{item.progress.toFixed(0)}%</span>
}
