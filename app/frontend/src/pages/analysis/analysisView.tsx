
import type { AnalysisRun } from '../../api'
import type { AnalysisPageSnapshot, WorkbenchIdentity } from '../../stores/workbenchStore'

export type Props = WorkbenchIdentity & {
  token: string
  initialView: AnalysisView
  explicitInitialView: boolean
  navigationId: number
  onViewChange: (view: AnalysisView) => void
  canExecute: boolean
  canIntervene: boolean
  canQuality: boolean
  canCurve: boolean
  canPrint: boolean
  canSaveMethod?: boolean
  information?: { expanded: boolean; setExpanded: (value: boolean) => void }
  onCurrentRunChange?: (run: AnalysisRun) => void
  onToast: (message: string) => void
}

export type AnalysisView = AnalysisPageSnapshot['viewByRun'][number]

export const statusLabels: Record<string, string> = {
  draft: '草稿',
  running: '分析中',
  paused: '慢进待确认',
  completed: '已完成',
  cancelled: '已取消',
  failed: '失败'
}

export const active = new Set(['running', 'paused'])

