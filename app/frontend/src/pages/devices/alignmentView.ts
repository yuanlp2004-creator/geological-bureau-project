export type AlignmentView = {
  ccd: number | null
  start: number
  span: number | null
  scale: 1 | 4 | 10 | null
  zoomY: number
  tool: 'crosshair' | 'box'
}

export function initialAlignmentViews(indices: number[]): AlignmentView[] {
  return Array.from({ length: 3 }, (_, index) => resetAlignmentView(indices[index] ?? null))
}

export function resetAlignmentView(ccd: number | null): AlignmentView {
  return { ccd, start: 1, span: null, scale: null, zoomY: 1, tool: 'crosshair' }
}

export function alignmentStats(points: number[]) {
  if (!points.length) return null
  let min = points[0], max = points[0], peakIndex = 0
  points.forEach((value, index) => {
    min = Math.min(min, value)
    if (value > max) { max = value; peakIndex = index }
  })
  return { min, max, peakIndex }
}

// FmDebug.UpdateAllIens/GetCurveCursorYPos: background removal changes the display
// floor to the measured minimum. Raw intensities and peak readouts stay unchanged.
export function alignmentYRange(points: number[], subtractBackground: boolean, zoomY: number) {
  const stats = alignmentStats(points)
  const min = subtractBackground ? stats?.min ?? 0 : 0
  const max = Math.max(1000, stats?.max ?? 0, min + 1)
  return { min, max: min + (max - min) / zoomY }
}

export function alignmentXRange(view: AlignmentView, count: number, width: number, pixelRatio: number, physicalPointPx: number, maxZoom: number) {
  const full = Math.max(1, count - 1)
  const minimum = full / maxZoom
  const density = view.scale === 10 ? physicalPointPx * 10 : view.scale
  const desired = density && density > 0 ? (width - 1) * pixelRatio / density : view.span ?? full
  const span = Math.max(minimum, Math.min(full, desired))
  const min = Math.max(1, Math.min(count - span, view.start))
  return { min, max: min + span, span, minimum, full }
}
