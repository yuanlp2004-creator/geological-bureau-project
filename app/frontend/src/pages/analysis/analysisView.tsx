
import type { AnalysisRun } from '../../api'

export type Props = {
  token: string
  initialView: AnalysisView
  onViewChange: (view: AnalysisView) => void
  canExecute: boolean
  canIntervene: boolean
  canQuality: boolean
  canCurve: boolean
  canPrint: boolean
  canSaveMethod?: boolean
  onCurrentRunChange?: (run: AnalysisRun) => void
  onToast: (message: string) => void
}

export type AnalysisView = 'raw' | 'quality' | 'curve' | 'standards' | 'samples'

export const statusLabels: Record<string, string> = {
  draft: '草稿',
  running: '分析中',
  paused: '慢进待确认',
  completed: '已完成',
  cancelled: '已取消',
  failed: '失败'
}

export const active = new Set(['running', 'paused'])

