/** Old operator gestures, with one-based CCD/point input and Delphi banker's rounding. */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value), fraction = value - floor
  return Math.abs(fraction - 0.5) < 1e-10 ? floor + (floor % 2) : Math.round(value)
}

export function parseCcdCoordinate(text: string): { ccd: number; point: number } | null {
  const trimmed = text.trim()
  const body = trimmed.startsWith('(') && trimmed.endsWith(')') ? trimmed.slice(1, -1) : trimmed
  const match = body.match(/^\s*(\d+)\s*,\s*(\d+)\s*$/)
  if (!match) return null
  const ccd = Number(match[1]), point = Number(match[2])
  return ccd >= 1 && point >= 1 ? { ccd: ccd - 1, point: point - 1 } : null
}

export function nudgeStandardIntensity(value: number, intensities: number[], logarithmic: boolean,
  plotHeight: number, ruler: 1 | 5, direction: -1 | 1): number {
  const transform = (v: number) => logarithmic ? Math.log(v) : v
  const values = intensities.filter((v) => Number.isFinite(v) && (!logarithmic || v > 0)).map(transform)
  if (!values.length || !Number.isFinite(value) || (logarithmic && value <= 0)) return value
  const step = (Math.max(...values) - Math.min(...values)) / Math.max(1, plotHeight)
  const moved = transform(value) + step * ruler * direction
  const result = logarithmic ? Math.exp(moved) : moved
  return Number.isFinite(result) && result > 0 ? result : value
}
