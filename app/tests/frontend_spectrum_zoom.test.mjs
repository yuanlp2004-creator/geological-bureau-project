import assert from 'node:assert/strict'
import test from 'node:test'
import { limitSpectrumRange, stepSpectrumRange, ZOOM_IN, ZOOM_OUT } from '../frontend/src/components/spectrumZoom.ts'

const full = { xMin: 1, xMax: 2049, yMin: -24, yMax: 1000 }

test('axis steps double from fit, preserve their anchors, and stop at 32× and 1×', () => {
  let view = full
  for (const zoom of [2, 4, 8, 16, 32, 32]) {
    view = stepSpectrumRange(stepSpectrumRange(view, full, 'x', ZOOM_IN), full, 'y', ZOOM_IN)
    assert.equal(view.xMax - view.xMin, 2048 / zoom)
    assert.equal((view.xMin + view.xMax) / 2, 1025)
    assert.equal(view.yMax - view.yMin, 1024 / zoom)
    assert.equal(view.yMin, -24)
  }
  for (let step = 0; step < 6; step++) {
    view = stepSpectrumRange(stepSpectrumRange(view, full, 'x', ZOOM_OUT), full, 'y', ZOOM_OUT)
  }
  assert.deepEqual(view, full)
})

test('a tiny selection stays visible at the cap even on a data boundary', () => {
  const view = limitSpectrumRange({ xMin: 2048, xMax: 2049, yMin: 480, yMax: 481 }, full)
  assert.deepEqual(view, { xMin: 1985, xMax: 2049, yMin: 464.5, yMax: 496.5 })
  assert.deepEqual(stepSpectrumRange(view, full, 'y', ZOOM_IN), view)
  assert.equal(stepSpectrumRange(view, full, 'y', ZOOM_OUT).yMin, view.yMin)
})
