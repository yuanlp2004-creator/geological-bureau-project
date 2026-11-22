import assert from 'node:assert/strict'
import test from 'node:test'
import { alignmentStats, alignmentYRange, alignmentXRange, initialAlignmentViews, resetAlignmentView } from '../frontend/src/pages/devices/alignmentView.ts'
import { MAX_SPECTRUM_ZOOM } from '../frontend/src/components/spectrumZoom.ts'

test('legacy background display keeps raw peak/readout values and anchors vertical zoom at the baseline', () => {
  const points = [100, 300, 1600, 200]
  assert.deepEqual(alignmentYRange(points, true, 1), { min: 100, max: 1600 })
  assert.deepEqual(alignmentYRange(points, false, 1), { min: 0, max: 1600 })
  assert.deepEqual(alignmentYRange(points, true, 2), { min: 100, max: 850 })
  assert.deepEqual(alignmentStats(points), { min: 100, max: 1600, peakIndex: 2 })
  assert.deepEqual(points, [100, 300, 1600, 200])
})

test('weak, flat and absent CCD data keep finite drawable ranges', () => {
  assert.deepEqual(alignmentYRange([0, 30, 20], true, 1), { min: 0, max: 1000 })
  assert.deepEqual(alignmentYRange([2000, 2000], true, 1), { min: 2000, max: 2001 })
  assert.deepEqual(alignmentYRange([], true, 1), { min: 0, max: 1000 })
  assert.equal(alignmentStats([]), null)
})

test('pixel and physical CCD scales respect the same 32× fit limit at every display width', () => {
  const view = resetAlignmentView(0)
  const xRange = (patch, width = 513, ratio = 1, physicalPointPx = 2) =>
    alignmentXRange({ ...view, ...patch }, 2048, width, ratio, physicalPointPx, MAX_SPECTRUM_ZOOM)
  assert.equal(xRange({ scale: 1 }).span, 512)
  assert.equal(xRange({ scale: 4 }).span, 128)
  assert.equal(xRange({ scale: 1 }, 513, 2).span, 1024)
  assert.equal(xRange({ scale: 10 }, 513, 1, .5).span, 102.4)
  assert.equal(xRange({ scale: 10 }).span, 2047 / 32)
  assert.equal(xRange({ span: 1 }, 1000, 2).span, 2047 / 32)
  const range = xRange({ span: 128, start: 9999 })
  assert.equal(range.max, 2048)
})

test('installed CCDs initialize in device order and missing slots stay empty', () => {
  assert.deepEqual(initialAlignmentViews([0, 2, 5, 7]).map(view => view.ccd), [0, 2, 5])
  assert.deepEqual(initialAlignmentViews([4]).map(view => view.ccd), [4, null, null])
})
