import { createContext, useContext, useLayoutEffect } from 'react'
import type { Page } from '../../navigation'

export const spectroscopyModes = [
  { page: 'dispersion', label: '色散摄谱', description: '采集、观察并保存色散谱图。' },
  { page: 'evaporation-acquisition', label: '蒸发摄谱', description: '采集、观察并保存蒸发全时数据。' },
  { page: 'sample-acquisition', label: '样品摄谱', description: '按分析方法、样号和重复规则采集样品，检查测量结果。' }
] as const

export type SpectroscopyMode = typeof spectroscopyModes[number]['page']
export function isSpectroscopyMode(page: Page): page is SpectroscopyMode {
  return spectroscopyModes.some((mode) => mode.page === page)
}

export const SpectroscopySession = createContext<((mode: SpectroscopyMode, reason: string | null) => void) | null>(null)

/** Only the presentation session is shared; each domain retains its own task and commands. */
export function useSpectroscopySession(mode: SpectroscopyMode, reason: string | null) {
  const report = useContext(SpectroscopySession)
  useLayoutEffect(() => {
    report?.(mode, reason)
    return () => report?.(mode, null)
  }, [report, mode, reason])
  return report !== null
}
