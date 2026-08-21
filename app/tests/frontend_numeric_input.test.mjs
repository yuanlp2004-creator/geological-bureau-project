import assert from 'node:assert/strict'
import test from 'node:test'

import { COMPLETE_NUMBER, PARTIAL_NUMBER, validateNumericText } from '../frontend/src/numericInputModel.ts'

test('required blank stays blank and is not coerced to zero', () => {
  assert.deepEqual(validateNumericText('', { required: true }), { value: null, message: '此项为必填项' })
  assert.deepEqual(validateNumericText('', { required: false }), { value: null, message: null })
})

test('intermediate numeric editing states remain editable', () => {
  for (const text of ['', '-', '.', '-.', '2.', '2e', '2e-']) assert.equal(PARTIAL_NUMBER.test(text), true)
  for (const text of ['-', '.', '-.', '2e', '2e-']) assert.equal(COMPLETE_NUMBER.test(text), false)
  assert.deepEqual(validateNumericText('25', { required: true }), { value: 25, message: null })
})

test('explicit zero follows the field minimum', () => {
  assert.deepEqual(validateNumericText('0', { min: 0 }), { value: 0, message: null })
  assert.equal(validateNumericText('0', { min: 1 }).message, '数值不能小于 1')
})

test('min, max and step use the same contract as the UI', () => {
  assert.deepEqual(validateNumericText('1', { min: 0.01, max: 60, step: 0.01 }), { value: 1, message: null })
  assert.equal(validateNumericText('61', { min: 0.01, max: 60, step: 0.01 }).message, '数值不能大于 60')
  assert.equal(validateNumericText('1.05', { min: 0, step: 0.1 }).message, '请输入符合步进 0.1 的数值')
  assert.deepEqual(validateNumericText('-0.5', { min: -100, max: 100, step: 0.5 }), { value: -0.5, message: null })
})
