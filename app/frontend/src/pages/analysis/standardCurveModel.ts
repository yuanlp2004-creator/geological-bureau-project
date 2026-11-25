import type { AnalysisCurvePoint, AnalysisCurveSnapshot, AnalysisRun } from '../../api/analysis'

type CurveDiagnostics = AnalysisCurveSnapshot['diagnostics']

const finiteNumber = (value: number | null | undefined): value is number =>
  value != null && Number.isFinite(value)

export const formatCurveNumber = (value: number | null | undefined, digits: number) =>
  finiteNumber(value) ? value.toFixed(digits) : '—'

export function computeCurveKpis({ points, currentFit, shownSnapshot, previousSnapshot }: {
  points: readonly AnalysisCurvePoint[]
  currentFit: boolean
  shownSnapshot?: AnalysisCurveSnapshot
  previousSnapshot?: AnalysisCurveSnapshot
}) {
  const diagnostics = currentFit ? shownSnapshot?.diagnostics : undefined
  const correlation = diagnostics?.correlation ?? null
  const previousCorrelation = previousSnapshot?.diagnostics?.correlation
  const comparable = currentFit && shownSnapshot && previousSnapshot
    && shownSnapshot.line_id === previousSnapshot.line_id
    && shownSnapshot.coordinate_type === previousSnapshot.coordinate_type
    && (shownSnapshot.id !== previousSnapshot.id || shownSnapshot.result_sha256 !== previousSnapshot.result_sha256)

  let maxRelativeErrorPercent: number | null = null
  for (const { active, relative_error_percent: error } of diagnostics?.points ?? []) {
    if (active && finiteNumber(error)) {
      maxRelativeErrorPercent = Math.max(maxRelativeErrorPercent ?? 0, Math.abs(error))
    }
  }

  return {
    correlation,
    deltaR: comparable && finiteNumber(correlation) && finiteNumber(previousCorrelation)
      ? correlation - previousCorrelation
      : null,
    activeCount: points.filter((item) => item.active && item.adjusted_intensity != null).length,
    totalCount: points.length,
    maxRelativeErrorPercent,
    pendingFit: !currentFit,
  }
}

export function findPreviousCurveSnapshot(snapshots: readonly AnalysisCurveSnapshot[], shown?: AnalysisCurveSnapshot) {
  if (!shown) return undefined
  const shownIndex = snapshots.findIndex((snapshot) => snapshot.id === shown.id)
  for (let index = shownIndex - 1; index >= 0; index--) {
    const snapshot = snapshots[index]
    if (snapshot.line_id === shown.line_id && snapshot.coordinate_type === shown.coordinate_type) return snapshot
  }
  return undefined
}

export function canToggleCurvePoint(
  point: AnalysisCurvePoint | undefined,
  canEdit: boolean,
  profile: AnalysisRun['calculation_profile'],
  activeCount: number,
) {
  return canEdit && point?.adjusted_intensity != null
    && !(profile === 'legacy_2_0_2' && point.active && activeCount <= 4)
}

export function relativeErrorTier(value: number | null | undefined): 'none' | 'ok' | 'warn' | 'high' {
  if (!finiteNumber(value)) return 'none'
  const magnitude = Math.abs(value)
  if (magnitude <= 5) return 'ok'
  return magnitude <= 15 ? 'warn' : 'high'
}

export function buildResidualSeries(points: readonly AnalysisCurvePoint[], diagnostics?: CurveDiagnostics | null) {
  const rows = diagnostics?.points ?? []
  const mode = rows.some((row) => finiteNumber(row.relative_error_percent)) ? 'relative' : 'absolute'
  const byIndex = new Map(rows.map((row) => [row.point_index, row]))
  const series = points.map((point) => {
    const row = byIndex.get(point.point_index)
    const candidate = mode === 'relative' ? row?.relative_error_percent : row?.residual
    const value = finiteNumber(candidate) ? candidate : null
    let missingReason: 'zero-standard' | 'unavailable' | null = null
    if (value === null) {
      missingReason = mode === 'relative' && row?.standard_value === 0 ? 'zero-standard' : 'unavailable'
    }
    return { pointIndex: point.point_index, name: point.name, value, active: point.active, missingReason }
  })
  return { mode, series }
}
