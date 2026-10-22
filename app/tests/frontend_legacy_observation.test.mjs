import assert from 'node:assert/strict'
import test from 'node:test'
import { nudgeStandardIntensity, parseCcdCoordinate, roundHalfEven } from '../frontend/src/components/legacyObservation.ts'

test('old blank-time conversion uses Delphi even rounding', () => {
  assert.equal(roundHalfEven(9 / 2), 4)
  assert.equal(roundHalfEven(11 / 2), 6)
  assert.equal(roundHalfEven(8 / 1), 8)
  assert.equal(roundHalfEven(8 / 2), 4)
})
test('CCD coordinates use one-based input and reject invalid coordinates', () => {
  assert.deepEqual(parseCcdCoordinate('2,123'), { ccd: 1, point: 122 })
  assert.deepEqual(parseCcdCoordinate('(2,123)'), { ccd: 1, point: 122 })
  assert.equal(parseCcdCoordinate('0,1'), null)
  assert.equal(parseCcdCoordinate('2,1.5'), null)
  assert.equal(parseCcdCoordinate('(2,123'), null)
})
test('ruler uses per-pixel transformed range rather than adding one or five', () => {
  assert.equal(nudgeStandardIntensity(10, [10, 100], false, 90, 1, 1), 11)
  assert.equal(nudgeStandardIntensity(10, [10, 100], false, 90, 5, 1), 15)
  assert.ok(Math.abs(nudgeStandardIntensity(1, [1, 100], true, 100, 1, 1) - 100 ** 0.01) < 1e-12)
  assert.equal(nudgeStandardIntensity(1, [1, 100], false, 1, 5, -1), 1)
})
