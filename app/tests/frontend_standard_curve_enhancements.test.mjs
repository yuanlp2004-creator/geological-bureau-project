import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildResidualSeries, canToggleCurvePoint, computeCurveKpis, findPreviousCurveSnapshot, formatCurveNumber, relativeErrorTier,
} from '../frontend/src/pages/analysis/standardCurveModel.ts'

const point = (point_index, overrides = {}) => ({
  point_index,
  name: `标准样 ${point_index}`,
  active: true,
  adjusted_intensity: 50 + point_index,
  standard_value: point_index,
  ...overrides,
})
const diagnostic = (item, relative_error_percent) => ({ ...item, relative_error_percent, residual: item.point_index / 2 })
const snapshot = (overrides = {}) => ({
  id: 2,
  line_id: 'zn',
  coordinate_type: 'normal',
  result_sha256: 'current',
  diagnostics: { correlation: 0.991234567, points: [] },
  ...overrides,
})

test('KPIs report six-place R, usable points and the magnitude of the largest active relative error', () => {
  const points = [
    point(0), point(1), point(2), point(3, { active: false }), point(4, { adjusted_intensity: null }), point(5),
  ]
  const shownSnapshot = snapshot({
    diagnostics: {
      correlation: 0.991234567,
      points: [
        diagnostic(points[0], null), diagnostic(points[1], -8.123), diagnostic(points[2], 5),
        diagnostic(points[3], 60), diagnostic(points[5], Infinity),
      ],
    },
  })
  const kpis = computeCurveKpis({ points, currentFit: true, shownSnapshot })
  assert.equal(formatCurveNumber(kpis.correlation, 6), '0.991235')
  assert.equal(`${kpis.activeCount}/${kpis.totalCount}`, '4/6')
  assert.equal(formatCurveNumber(kpis.maxRelativeErrorPercent, 2), '8.12')
  assert.equal(kpis.pendingFit, false)
})

test('a zero standard has no relative error and a pending fit hides stale diagnostics', () => {
  const points = [point(0)]
  const shownSnapshot = snapshot({ diagnostics: { correlation: null, points: [diagnostic(points[0], null)] } })
  const kpis = computeCurveKpis({ points, currentFit: true, shownSnapshot })
  assert.equal(kpis.maxRelativeErrorPercent, null)
  assert.equal(formatCurveNumber(kpis.maxRelativeErrorPercent, 2), '—')
  assert.equal(formatCurveNumber(kpis.correlation, 6), '—')

  const stale = snapshot({ diagnostics: { correlation: 0.99, points: [diagnostic(point(1), 8)] } })
  assert.deepEqual(computeCurveKpis({ points, currentFit: false, shownSnapshot: stale, previousSnapshot: shownSnapshot }), {
    correlation: null, deltaR: null, activeCount: 1, totalCount: 1, maxRelativeErrorPercent: null, pendingFit: true,
  })
  assert.equal(computeCurveKpis({
    points, currentFit: true, shownSnapshot: snapshot({ diagnostics: { correlation: 1, points: [diagnostic(point(1), 0)] } }),
  }).maxRelativeErrorPercent, 0)
})

test('ΔR compares distinct fits of the same line and coordinate, including recalculation drafts with the same ID', () => {
  const shownSnapshot = snapshot()
  const priorDiagnostics = { correlation: 0.98, points: [] }
  const previousSnapshot = snapshot({ id: 1, result_sha256: 'prior', diagnostics: priorDiagnostics })
  const delta = (previous, shown = shownSnapshot, currentFit = true) =>
    computeCurveKpis({ points: [], currentFit, shownSnapshot: shown, previousSnapshot: previous }).deltaR

  assert.equal(formatCurveNumber(delta(previousSnapshot), 6), '0.011235')
  assert.equal(formatCurveNumber(delta({ ...previousSnapshot, id: shownSnapshot.id }), 6), '0.011235')
  assert.equal(delta({ ...shownSnapshot }), null)
  assert.equal(delta(undefined), null)
  assert.equal(delta(previousSnapshot, shownSnapshot, false), null)
  assert.equal(delta({ ...previousSnapshot, line_id: 'ag' }), null)
  assert.equal(delta({ ...previousSnapshot, coordinate_type: 'logarithmic' }), null)
  assert.equal(delta(previousSnapshot, { ...shownSnapshot, coordinate_type: 'logarithmic' }), null)
  assert.equal(delta({ ...previousSnapshot, diagnostics: { ...priorDiagnostics, correlation: NaN } }), null)
  assert.equal(delta(previousSnapshot, { ...shownSnapshot, diagnostics: { ...priorDiagnostics, correlation: null } }), null)
  assert.equal(delta({ ...previousSnapshot, diagnostics: shownSnapshot.diagnostics }), 0)
})

test('the analysis history selects the preceding same-coordinate fit of the same line', () => {
  const normal = snapshot({ id: 1 })
  const earlierLog = snapshot({ id: 2, coordinate_type: 'logarithmic' })
  const laterLog = snapshot({ id: 3, coordinate_type: 'logarithmic' })
  const otherLine = snapshot({ id: 4, line_id: 'ag' })
  const latestNormal = snapshot({ id: 5 })
  const history = [normal, earlierLog, laterLog, otherLine, latestNormal]
  assert.equal(findPreviousCurveSnapshot(history, latestNormal), normal)
  assert.equal(findPreviousCurveSnapshot(history, laterLog), earlierLog)
  assert.equal(findPreviousCurveSnapshot(history, earlierLog), undefined)
})

test('error tiers include their upper boundaries and reject missing/non-finite data', () => {
  for (const value of [null, undefined, NaN, Infinity, -Infinity]) assert.equal(relativeErrorTier(value), 'none')
  for (const value of [0, -5, 5]) assert.equal(relativeErrorTier(value), 'ok')
  for (const value of [5.001, -15, 15]) assert.equal(relativeErrorTier(value), 'warn')
  for (const value of [-15.001, 16]) assert.equal(relativeErrorTier(value), 'high')
})

test('residuals use relative error when available and keep missing points separate from numerical zero', () => {
  const points = [point(0), point(1), point(2, { active: false }), point(3, { adjusted_intensity: null })]
  const diagnostics = { points: [diagnostic(points[2], -7), diagnostic(points[0], null), diagnostic(points[1], 0)] }
  const { mode, series } = buildResidualSeries(points, diagnostics)
  assert.equal(mode, 'relative')
  assert.deepEqual(series, [
    { pointIndex: 0, name: '标准样 0', value: null, active: true, missingReason: 'zero-standard' },
    { pointIndex: 1, name: '标准样 1', value: 0, active: true, missingReason: null },
    { pointIndex: 2, name: '标准样 2', value: -7, active: false, missingReason: null },
    { pointIndex: 3, name: '标准样 3', value: null, active: true, missingReason: 'unavailable' },
  ])
})

test('residuals fall back to signed absolute residuals when all relative errors are unavailable', () => {
  const points = [point(0), point(1, { standard_value: 0 }), point(2)]
  const diagnostics = { points: [diagnostic(points[0], null), { ...diagnostic(points[1], null), residual: -0.75 }] }
  const { mode, series } = buildResidualSeries(points, diagnostics)
  assert.equal(mode, 'absolute')
  assert.deepEqual(series.map(({ value }) => value), [0, -0.75, null])
  assert.equal(series[2].missingReason, 'unavailable')
  assert.deepEqual(buildResidualSeries(points).series.map(({ value }) => value), [null, null, null])
})

test('legacy point toggles preserve four usable points and both profiles honor edit permission and intensity availability', () => {
  const active = point(1)
  const inactive = point(2, { active: false })
  assert.equal(canToggleCurvePoint(active, true, 'legacy_2_0_2', 5), true)
  assert.equal(canToggleCurvePoint(active, true, 'legacy_2_0_2', 4), false)
  assert.equal(canToggleCurvePoint(active, true, 'legacy_2_0_2', 3), false)
  assert.equal(canToggleCurvePoint(inactive, true, 'legacy_2_0_2', 4), true)
  assert.equal(canToggleCurvePoint(active, true, 'modern_v1', 4), true)
  for (const profile of ['legacy_2_0_2', 'modern_v1']) {
    assert.equal(canToggleCurvePoint(active, false, profile, 5), false)
    assert.equal(canToggleCurvePoint(point(2, { adjusted_intensity: null }), true, profile, 5), false)
    assert.equal(canToggleCurvePoint(undefined, true, profile, 5), false)
  }
})
