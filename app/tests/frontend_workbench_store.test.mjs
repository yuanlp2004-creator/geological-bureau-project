import assert from 'node:assert/strict'
import test from 'node:test'
import { buildWorkbenchScopeKey, createWorkbenchStore, permissionScopeKey } from '../frontend/src/stores/workbenchStoreCore.ts'
import { captureStatusInput, captureTaskPresentation, resolveSpectroscopyStatus } from '../frontend/src/pages/acquisition/spectroscopyStatus.ts'

const snapshot = {
  fileGroup: 'task:8', sourceKind: 'sample', search: '样品', angleFilter: '30',
  selectedId: 'sample:1', overlayIds: ['sample:2'], priorityId: 'sample:2', multiMode: 'multi',
  showRecords: true, recordLocked: false, ccd: 1, line: 0, mode: 'mean', exposureStart: 2, exposureEnd: 5,
  manualZoomX: 4, zoomY: 2, panX: 0.5, panY: -0.5, tool: 'box', pixelMode: null,
  pointCoordinates: true, fixedView: true, followPoint: false, viewLine: 'Ni-1', locateValue: '2,123'
}
const scope = { userId: 1, permissionsKey: permissionScopeKey(['spectra.read']), page: 'spectra', methodVersionId: 3 }
const keyFor = (changes = {}) => buildWorkbenchScopeKey({ ...scope, ...changes })

test('permission keys encode sorted unique permission strings without delimiter collisions', () => {
  assert.equal(permissionScopeKey(['spectra.read', 'spectra.export', 'spectra.read']), '["spectra.export","spectra.read"]')
  assert.notEqual(permissionScopeKey(['spectra.read']), permissionScopeKey(['spectra.read', 'spectra.export']))
  assert.notEqual(permissionScopeKey(['a|b']), permissionScopeKey(['a', 'b']))
})

test('snapshots are isolated by user, permissions, viewer, and method version', () => {
  const store = createWorkbenchStore()
  const scopes = [
    keyFor(), keyFor({ userId: 2 }), keyFor({ permissionsKey: permissionScopeKey(['spectra.read', 'spectra.export']) }),
    keyFor({ page: 'evaporation' }), keyFor({ methodVersionId: 4 })
  ]
  assert.equal(new Set(scopes).size, scopes.length)
  scopes.forEach((key, index) => store.saveSpectrumSnapshot(key, { ...snapshot, selectedId: `sample:${index}` }))
  scopes.forEach((key, index) => assert.equal(store.peekSpectrumSnapshot(key).selectedId, `sample:${index}`))
})

test('peek preserves a snapshot and consume returns it only once', () => {
  const store = createWorkbenchStore()
  const key = keyFor()
  const overlayIds = [...snapshot.overlayIds]
  store.saveSpectrumSnapshot(key, { ...snapshot, overlayIds })
  overlayIds.push('sample:3')
  assert.throws(() => store.peekSpectrumSnapshot(key).overlayIds.push('sample:4'), TypeError)
  assert.deepEqual(store.peekSpectrumSnapshot(key), snapshot)
  assert.deepEqual(store.consumeSpectrumSnapshot(key), snapshot)
  assert.equal(store.consumeSpectrumSnapshot(key), null)
  assert.equal(store.peekSpectrumSnapshot(key), null)
})

test('session and global clearing invalidate only the corresponding snapshots and pending sessions', () => {
  const store = createWorkbenchStore()
  const keys = [keyFor(), keyFor({ page: 'evaporation' }), keyFor({ userId: 10 })]
  keys.forEach(key => store.saveSpectrumSnapshot(key, snapshot))
  const firstRevision = store.getSessionRevision(1)
  const otherRevision = store.getSessionRevision(10)
  store.clearSession(1)
  assert.deepEqual(keys.map(key => store.peekSpectrumSnapshot(key)), [null, null, snapshot])
  assert.notEqual(store.getSessionRevision(1), firstRevision)
  assert.equal(store.getSessionRevision(10), otherRevision)
  store.saveSpectrumSnapshot(keys[0], snapshot)
  const clearedRevision = store.getSessionRevision(1)
  store.clearAll()
  assert.ok(keys.every(key => store.peekSpectrumSnapshot(key) === null))
  assert.notEqual(store.getSessionRevision(1), clearedRevision)
  assert.notEqual(store.getSessionRevision(10), otherRevision)
})

test('the spectroscopy status distinguishes all capture phases and terminal states', () => {
  const cases = [
    [{ status: 'draft' }, 'idle', '空闲', 'neutral'],
    [{ status: 'draft', positioned: true }, 'positioned', '转角已定位', 'ready'],
    [{ status: 'ready', positioned: true }, 'positioned', '转角已定位', 'ready'],
    [{ status: 'pre_excitation', positioning: true }, 'positioning', '正在定位转角', 'running'],
    [{ status: 'countdown' }, 'countdown', '倒计时', 'running'],
    [{ status: 'pre_excitation' }, 'pre_excitation', '预热', 'running'],
    [{ status: 'burn', positioned: true }, 'burn', '激发燃弧', 'burn'],
    [{ status: 'dark' }, 'dark', '暗电流', 'running'],
    [{ status: 'between_repeats' }, 'between_repeats', '轮次之间', 'warning'],
    [{ status: 'paused', awaitingTurn: true }, 'awaiting_turn', '等待人工切角', 'warning'],
    [{ status: 'paused', awaitingTurn: false }, 'paused', '已暂停', 'warning'],
    [{ status: 'stopping', positioning: true }, 'stopping', '停止中', 'warning'],
    [{ status: 'failed', positioning: true }, 'failed', '失败', 'danger'],
    [{ status: 'completed' }, 'completed', '已完成', 'success'],
    [{ status: 'stopped' }, 'stopped', '已停止', 'neutral']
  ]
  for (const [input, key, label, tone] of cases) {
    const actual = resolveSpectroscopyStatus(input)
    assert.deepEqual([actual.key, actual.label, actual.tone], [key, label, tone])
  }
  assert.equal(resolveSpectroscopyStatus({ status: 'failed', failureReason: '设备超时' }).detail, '设备超时')
  assert.match(resolveSpectroscopyStatus({ status: 'between_repeats' }).detail, /人工点击/)
})

test('task rows expose concrete capture phases and the available hardware status', () => {
  const phases = ['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats', 'stopping', 'completed', 'stopped', 'failed']
  const labels = phases.map(status => captureTaskPresentation({ status }, '任务信息').badge.label)
  assert.equal(new Set(labels).size, phases.length)
  assert.equal(captureTaskPresentation({ status: 'paused', turns: { awaiting_turn: true } }, '任务信息').badge.label, '等待人工切角')
  assert.equal(captureTaskPresentation({ status: 'draft', turns: { positioned: true } }, '任务信息').badge.label, '转角已定位')
  assert.equal(resolveSpectroscopyStatus(captureStatusInput({
    status: 'draft', last_event: { details: { turn_position: { angle_deg: 30 } } }
  })).key, 'positioned')
  assert.equal(resolveSpectroscopyStatus(captureStatusInput({ status: 'pre_excitation', last_message: '正在定位转角' })).key, 'positioning')
})

test('multi-angle rows preserve completion counts and surface the active or failed angle', () => {
  const task = { id: 1, status: 'completed', capture_turns: [
    { id: 1, status: 'completed', angle_deg: 30 },
    { id: 2, status: 'draft', angle_deg: 45 }
  ] }
  const present = (status, metadata = {}) => captureTaskPresentation({
    ...task, capture_turns: [task.capture_turns[0], { ...task.capture_turns[1], status }]
  }, '', [{ id: 2, status, ...metadata }])
  assert.equal(present('draft').badge.label, '待续采')
  assert.equal(present('draft').details, '30° / 45° · 1/2 转角完成')
  assert.equal(present('burn').badge.key, 'burn')
  assert.equal(present('between_repeats').badge.key, 'between_repeats')
  assert.equal(present('paused', { turns: { awaiting_turn: true } }).badge.key, 'awaiting_turn')
  assert.equal(present('failed', { failure_message: '转角超时' }).badge.detail, '转角超时')
  assert.equal(present('completed').badge.key, 'completed')
  assert.match(present('completed').details, /2\/2 转角完成/)
})
