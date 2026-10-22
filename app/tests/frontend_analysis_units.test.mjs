import assert from 'node:assert/strict'
import { test } from 'node:test'
import { convertLineUnit, formatAnalysisValue, unitScale } from '../frontend/src/components/analysisUnits.ts'

test('same mass fraction in three units and round trip retains standards and intensities', () => {
  const source = { unit: 'ug/g', decimal_places: 2, valid_range_min: 1, valid_range_max: 2000,
    standard_points: [{ value: 1000, original_intensity: 123 }] }
  const mg = convertLineUnit(source, 'mg/g'), percent = convertLineUnit(mg, '%')
  assert.equal(mg.standard_points[0].value, 1)
  assert.equal(percent.standard_points[0].value, 0.1)
  assert.equal(percent.valid_range_min, 0.0001)
  assert.equal(percent.decimal_places, 6)
  assert.equal(percent.standard_points[0].original_intensity, 123)
  assert.deepEqual(convertLineUnit(percent, 'ug/g'), source)
})

test('percent output retains tiny nonzero values and uses decimal rounding consistently', () => {
  assert.equal(formatAnalysisValue(0.0000000001, 10), '0.0000000001')
  assert.equal(Number(formatAnalysisValue(1e-12, 6)), 1e-12)
  assert.equal(formatAnalysisValue(1.005, 2), '1.01')
  assert.equal(formatAnalysisValue(-1.005, 2), '-1.01')
  assert.equal(formatAnalysisValue(0, 2), '0.00')
})

test('custom units are not treated as known conversion factors', () => {
  assert.equal(unitScale('constructor'), 1)
  assert.equal(unitScale('mg/kg'), 1)
})
