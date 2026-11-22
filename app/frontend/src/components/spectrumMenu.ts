import type { MenuGroup, MenuItem } from './ContextMenu'
import { MAX_SPECTRUM_ZOOM, ZOOM_IN, ZOOM_OUT, type SpectrumAxis, type SpectrumViewRange } from './spectrumZoom'

export type CcdNavigation = { current: number; indices: number[]; choose: (ccd: number) => void; labels?: Record<number, string> }

export function zoomMenuItems(axis: SpectrumAxis, zoom: (axis: SpectrumAxis, factor: number) => void,
  canEnlarge: boolean, canShrink: boolean): MenuGroup {
  const label = axis === 'x' ? '横向' : '纵向'
  return [
    { label: `${label}放大`, disabled: !canEnlarge, run: () => zoom(axis, ZOOM_IN) },
    { label: `${label}缩小`, disabled: !canShrink, run: () => zoom(axis, ZOOM_OUT) }
  ]
}

export function spectrumMenuGroups(navigation: CcdNavigation | undefined, view: SpectrumViewRange, full: SpectrumViewRange,
  zoom: (axis: SpectrumAxis, factor: number) => void, fixed: MenuItem, extras: MenuGroup = []): MenuGroup[] {
  const index = navigation?.indices.indexOf(navigation.current) ?? -1
  const xZoom = (full.xMax - full.xMin) / (view.xMax - view.xMin)
  const yZoom = (full.yMax - full.yMin) / (view.yMax - view.yMin)
  return [
    navigation ? [
      { label: '上一 CCD', disabled: index <= 0, run: () => navigation.choose(navigation.indices[index - 1]) },
      { label: '下一 CCD', disabled: index < 0 || index >= navigation.indices.length - 1, run: () => navigation.choose(navigation.indices[index + 1]) }
    ] : [],
    [...zoomMenuItems('x', zoom, xZoom < MAX_SPECTRUM_ZOOM - 1e-6, xZoom > 1 + 1e-6),
      ...zoomMenuItems('y', zoom, yZoom < MAX_SPECTRUM_ZOOM - 1e-6, yZoom > 1 + 1e-6)],
    [fixed, ...extras]
  ]
}

export function spectralLineMenuGroups<T>(lines: T[], current: T, choose: (line: T) => void, priority: MenuItem, editing: MenuGroup = [], positions: MenuGroup = []): MenuGroup[] {
  const index = lines.indexOf(current)
  return [[
    { label: '上一谱线', disabled: index <= 0, run: () => choose(lines[index - 1]) },
    { label: '下一谱线', disabled: index < 0 || index >= lines.length - 1, run: () => choose(lines[index + 1]) },
    priority, ...editing
  ], positions]
}
