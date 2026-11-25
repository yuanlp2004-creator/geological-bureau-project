import assert from 'node:assert/strict'
import test from 'node:test'
import {
  MAX_SAMPLE_QUEUE_ITEMS, SAMPLE_QUEUE_ROWS, analysisSampleCapacityError, analysisSampleCommand,
  columnMajorPosition, commitSampleGridMove, incrementalSampleFill, isSampleComposition, nextSampleGridPosition,
  nextSampleName, rowMajorPosition, sampleTypingKey,
} from '../frontend/src/components/sampleGridFlow.ts'
import {
  acquisitionSourceKind, extractMethodStandardNames, resolveSampleSemanticRole,
} from '../frontend/src/components/sampleSemanticRole.ts'

const queuePosition = (row, column, start = 0) => columnMajorPosition({ row, column }, start, SAMPLE_QUEUE_ROWS)
const queueStep = (position, direction) => nextSampleGridPosition(position, direction, MAX_SAMPLE_QUEUE_ITEMS)

test('queue navigation stays column-major down a column, across columns and across pages', () => {
  const pageSize = 3 * SAMPLE_QUEUE_ROWS
  assert.equal(queueStep(queuePosition(3, 0), 1), queuePosition(4, 0))
  assert.equal(queueStep(queuePosition(19, 0), 1), queuePosition(0, 1))
  assert.equal(queueStep(queuePosition(19, 2), 1), queuePosition(0, 0, pageSize))
  assert.equal(queueStep(queuePosition(0, 1), -1), queuePosition(19, 0))
  assert.equal(queueStep(queuePosition(0, 0, pageSize), -1), queuePosition(19, 2))
  assert.equal(queueStep(0, -1), null)
  assert.equal(queueStep(MAX_SAMPLE_QUEUE_ITEMS - 1, 1), null)
  assert.equal(queueStep(MAX_SAMPLE_QUEUE_ITEMS - 1, -1), MAX_SAMPLE_QUEUE_ITEMS - 2)
})

test('queue advances only after the asynchronous commit and stays put on rejection', async () => {
  let position = 19
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  const saving = commitSampleGridMove(position, 1, MAX_SAMPLE_QUEUE_ITEMS, () => pending)
    .then(target => { position = target ?? position })
  assert.equal(position, 19)
  finish()
  await saving
  assert.equal(position, 20)
  const conflict = new Error('该样号已关联采集')
  await assert.rejects(commitSampleGridMove(position, -1, MAX_SAMPLE_QUEUE_ITEMS, async () => { throw conflict })
    .then(target => { position = target ?? position }), conflict)
  assert.equal(position, 20)
})

test('analysis navigation is row-major and bounds the first and last available band', () => {
  const position = (row, column) => rowMajorPosition({ row, column })
  const capacity = 13
  assert.equal(nextSampleGridPosition(position(0, 8), 1, capacity), position(0, 9))
  assert.equal(nextSampleGridPosition(position(0, 9), 1, capacity), position(1, 0))
  assert.equal(nextSampleGridPosition(position(1, 0), -1, capacity), position(0, 9))
  assert.equal(nextSampleGridPosition(0, -1, capacity), null)
  assert.equal(nextSampleGridPosition(capacity - 1, 1, capacity), null)
})

test('analysis capacity counts blank slots and prevents advancement on excess repeats', () => {
  const entries = [{ repeats: 3 }, { repeats: 0 }, { repeats: 2 }]
  assert.equal(analysisSampleCapacityError(entries, 6), '')
  const error = analysisSampleCapacityError(entries, 5)
  assert.match(error, /占用 6 条谱带，超过当前的 5 条/)
  const current = 1
  const target = error ? current : nextSampleGridPosition(current, 1, 5)
  assert.equal(target, current)
})

test('analysis name box retains comma insertion, slash deletion and dot saving', () => {
  assert.equal(analysisSampleCommand(' ,blank'), 'insert')
  assert.equal(analysisSampleCommand('/'), 'remove')
  assert.equal(analysisSampleCommand('.'), 'save')
  assert.equal(analysisSampleCommand('样品.001'), 'entry')
  assert.equal(analysisSampleCommand(''), 'entry')
})

test('typing recognizes printable characters and both native IME signals', () => {
  const key = { key: '样', keyCode: 0, isComposing: false, ctrlKey: false, metaKey: false, altKey: false }
  assert.equal(sampleTypingKey(key), '样')
  assert.equal(sampleTypingKey({ ...key, key: 'Process' }), '')
  assert.equal(sampleTypingKey({ ...key, key: 'Unidentified', keyCode: 229 }), '')
  assert.equal(sampleTypingKey({ ...key, key: 'd', ctrlKey: true }), undefined)
  assert.equal(isSampleComposition({ ...key, key: 'Enter' }, true), true)
  assert.equal(isSampleComposition({ ...key, key: 'Tab', isComposing: true }), true)
  assert.equal(isSampleComposition({ ...key, key: 'Enter', keyCode: 229 }), true)
  assert.equal(isSampleComposition({ ...key, key: 'Enter' }), false)
})

test('Ctrl+D fills the next slot or selected positions in host order with leading zeros', () => {
  assert.deepEqual(incrementalSampleFill([19], 1000, () => ' 样009 '), [{ position: 20, name: '样010' }])
  const queue = [queuePosition(1, 1), queuePosition(0, 0), queuePosition(1, 0), queuePosition(0, 1)]
  assert.deepEqual(incrementalSampleFill(queue, 1000, () => 'A001'), [
    { position: 1, name: 'A002' }, { position: 20, name: 'A003' }, { position: 21, name: 'A004' },
  ])
  const analysis = [rowMajorPosition({ row: 1, column: 2 }), rowMajorPosition({ row: 0, column: 2 })]
  assert.deepEqual(incrementalSampleFill(analysis, 20, () => '0009'), [{ position: 12, name: '0010' }])
  assert.throws(() => incrementalSampleFill([12], 13, () => 'A01'), /超出表格边界/)
})

test('Ctrl+D rejects the whole target range when a later target is acquired', () => {
  const items = [{}, {}, { spectrum_hash: 'verified' }]
  assert.throws(() => incrementalSampleFill([0, 1, 2], 1000, () => 'A001', items), /第 3 项已关联采集，整批样号未保存/)
  assert.throws(() => incrementalSampleFill([1], 1000, () => 'A002', items), /已关联采集/)
})

test('Ctrl+D rejects an absent numeric suffix instead of generating empty writes', () => {
  assert.equal(nextSampleName('地质样'), '')
  assert.throws(() => incrementalSampleFill([0], 1000, () => '地质样'), /须以数字结尾/)
  assert.throws(() => incrementalSampleFill([0, 1, 2], 1000, () => ''), /须以数字结尾/)
})

test('D13-4 is neutral in a normal queue and a numbered analysis with a derived QC flag', () => {
  const ordinary = { name: 'D13-4' }
  assert.equal(resolveSampleSemanticRole(ordinary), 'neutral')
  assert.equal(resolveSampleSemanticRole({ ...ordinary, sampleNumbering: true, qualityManagementSample: true }), 'neutral')
  assert.equal(resolveSampleSemanticRole({ ...ordinary, sampleNumbering: true, sourceKind: 'standard' }), 'neutral')
  assert.equal(resolveSampleSemanticRole({ ...ordinary, qualityManagementSample: true }), 'control')
  assert.equal(resolveSampleSemanticRole({ ...ordinary, explicitManagementTask: true }), 'control')
  assert.equal(resolveSampleSemanticRole({ ...ordinary, sampleNumbering: true, explicitManagementTask: true }), 'control')
})

test('only valid method entries and independently sourced standards are marked as standard', () => {
  const methodStandardNames = extractMethodStandardNames([
    { standard_points: [{ name: ' S1 ', value: 0, active: true }, { name: 'S2', value: 2, active: false }] },
    { standard_points: [{ name: 'S1', value: 3, active: true }, { name: 'S3', value: NaN, active: true }, { name: ' ', value: 1, active: true }] },
    {},
  ])
  assert.deepEqual([...methodStandardNames], ['S1'])
  assert.equal(resolveSampleSemanticRole({ name: ' S1 ', methodStandardNames, sampleNumbering: true }), 'standard')
  assert.equal(resolveSampleSemanticRole({ name: 'S99', methodStandardNames }), 'neutral')
  assert.equal(resolveSampleSemanticRole({ name: 'S99', methodStandardNames,
    sourceKind: acquisitionSourceKind({ sample_kind: 'standard', sample_name: 'S99' }) }), 'neutral')
  assert.equal(resolveSampleSemanticRole({ name: 'CRM-4',
    sourceKind: acquisitionSourceKind({ sample_kind: 'standard', sample_name: 'CRM-4' }) }), 'standard')
  assert.equal(resolveSampleSemanticRole({ name: 'S1', methodStandardNames, explicitManagementTask: true }), 'control')
})
