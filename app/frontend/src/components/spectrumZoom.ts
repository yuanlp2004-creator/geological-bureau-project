export const MAX_SPECTRUM_ZOOM = 32
export const ZOOM_IN = 0.5
export const ZOOM_OUT = 2

export type SpectrumAxis = 'x' | 'y'
export type SpectrumViewRange = { xMin: number; xMax: number; yMin: number; yMax: number }

export function clampSpectrumZoom(zoom: number) {
  return Math.max(1, Math.min(MAX_SPECTRUM_ZOOM, zoom))
}

export function limitSpectrumAxis(low: number, high: number, fullLow: number, fullHigh: number, anchor = 0.5) {
  const fullSpan = fullHigh - fullLow
  const span = fullSpan / clampSpectrumZoom(fullSpan / (high - low))
  if (span === fullSpan) return [fullLow, fullHigh] as const
  const start = Math.max(fullLow, Math.min(fullHigh - span, low + (high - low - span) * anchor))
  return [start, start + span] as const
}

export function limitSpectrumRange(view: SpectrumViewRange, full: SpectrumViewRange): SpectrumViewRange {
  const [xMin, xMax] = limitSpectrumAxis(view.xMin, view.xMax, full.xMin, full.xMax)
  const [yMin, yMax] = limitSpectrumAxis(view.yMin, view.yMax, full.yMin, full.yMax)
  return { xMin, xMax, yMin, yMax }
}

export function stepSpectrumRange(view: SpectrumViewRange, full: SpectrumViewRange, axis: SpectrumAxis, factor: number): SpectrumViewRange {
  if (axis === 'x') {
    const inset = (view.xMax - view.xMin) * (1 - factor) / 2
    const [xMin, xMax] = limitSpectrumAxis(view.xMin + inset, view.xMax - inset, full.xMin, full.xMax)
    return { ...view, xMin, xMax }
  }
  const [yMin, yMax] = limitSpectrumAxis(view.yMin, view.yMin + (view.yMax - view.yMin) * factor, full.yMin, full.yMax, 0)
  return { ...view, yMin, yMax }
}
