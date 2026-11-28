import {
  type DispersionLine
} from '../../api'

export type Props = {
  token: string
  canWrite: boolean
  canExecute: boolean
  onToast: (message: string) => void
}

export const runningStates = new Set(['pre_excitation', 'burn', 'dark'])

export const statusLabels: Record<string, string> = {
  draft: '待开始',
  pre_excitation: '预激发',
  burn: '燃烧采集',
  dark: '暗帧采集',
  paused: '已暂停',
  stopping: '收尾中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止'
}

export type PositionMarker = {
  key: string
  kind: 'expected' | 'located'
  label: string
  position: number
  x: number
  labelY: number
  select?: () => void
}

export function positionMarkers(lines: DispersionLine[], ccdIndex: number, pointsPerCcd: number, select?: (id: number) => void): PositionMarker[] {
  if (pointsPerCcd <= 1) return []
  const markers: PositionMarker[] = []
  const markerDefinitions: Array<{
    kind: PositionMarker['kind']
    field: 'expected_position' | 'located_position'
    label: string
    labelY: number
  }> = [
      { kind: 'expected', field: 'expected_position', label: '预期', labelY: 38 },
      { kind: 'located', field: 'located_position', label: '实测', labelY: 62 }
    ]
  lines
    .filter((line) => line.ccd_index === ccdIndex)
    .forEach((line) => {
      markerDefinitions.forEach((definition) => {
        const position = line[definition.field]
        if (position === null || !Number.isFinite(position)) return
        const bounded = Math.max(0, Math.min(pointsPerCcd - 1, position))
        markers.push({
          key: `${line.id}-${definition.kind}`,
          kind: definition.kind,
          label: `${line.element} ${line.wavelength_nm > 0 ? `${line.wavelength_nm.toFixed(4)} nm` : '待填波长'} · ${definition.label} ${position.toFixed(2)}`,
          select: select ? () => select(line.id) : undefined,
          position,
          x: (bounded / (pointsPerCcd - 1)) * 1000,
          labelY: definition.labelY
        })
      })
    })
  return markers
}
