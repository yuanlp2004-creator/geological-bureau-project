import assert from 'node:assert/strict'
import test from 'node:test'
import { createHardwareLockStore } from '../frontend/src/stores/hardwareLockStoreCore.ts'

const alice = { token: 'alice', userId: 1, canRead: true }
const bob = { token: 'bob', userId: 2, canRead: true }
const idle = { adapter: 'acq-simulator', state: 'idle', connected: false, session_id: null, contract: {} }
const connected = { ...idle, adapter: 'legacy-ccd-serial', state: 'connected', connected: true, profile_id: 7, port: 'COM12' }
const debugging = { ...connected, state: 'debugging' }
const turning = { ...debugging, turning: true }
const serialCapture = { task_id: 21, owner: '色散摄谱', profile_id: 7, port: 'COM12', state: 'burn' }

function diagnostics(adapter = idle, active_captures = []) {
  return { adapter, active_captures, profiles: [] }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function setup() {
  const reads = []
  const published = []
  const store = createHardwareLockStore({
    fetchDiagnostics(token) {
      const read = deferred()
      reads.push({ token, ...read })
      return read.promise
    },
    publishDiagnostics: next => published.push(next)
  })
  return { store, reads, published }
}

async function answer(reads, pending, next = diagnostics()) {
  await Promise.resolve()
  assert.ok(reads.length > 0)
  reads[reads.length - 1].resolve(next)
  return pending
}

function acquire(store, owner, kind, profileId = 7, taskId) {
  const result = store.acquireOperation({ owner, kind, profileId, taskId })
  assert.equal(result.ok, true, result.reason)
  return result.token
}

function reject(store, owner, kind, profileId = 7, taskId) {
  const result = store.acquireOperation({ owner, kind, profileId, taskId })
  assert.equal(result.ok, false)
  assert.ok(result.reason)
}

test('takes the UI operation synchronously before the first await across hardware hosts', async () => {
  const { store, reads } = setup()
  await answer(reads, store.startSession(alice))
  const response = deferred()
  const pending = (async () => {
    const token = acquire(store, 'alignment', 'connect')
    await response.promise
    store.completeOperation(token, { adapter: connected })
  })()
  assert.equal(store.getSnapshot().operation.owner, 'alignment')
  reject(store, 'alignment', 'connect')
  reject(store, 'device-connection', 'connect')
  reject(store, 'dispersion', 'capture_start')
  assert.ok(store.blockedReason())
  response.resolve()
  await pending
  assert.equal(store.getSnapshot().status, 'connected_idle')
  assert.equal(store.getSnapshot().operation, null)
  assert.equal(store.blockedReason(), null)
})

test('requires the current ID and generation and discards a read started before an operation receipt', async () => {
  const { store, reads, published } = setup()
  await answer(reads, store.startSession(alice))
  const staleRead = store.reconcile(alice.token)
  await Promise.resolve()
  const token = acquire(store, 'alignment', 'connect')
  assert.equal(store.completeOperation({ ...token, id: token.id + 1 }), false)
  assert.equal(store.completeOperation({ ...token, generation: token.generation - 1 }), false)
  assert.equal(store.getSnapshot().operation, token)
  assert.equal(store.completeOperation(token, { adapter: connected }), true)
  assert.equal(await answer(reads, staleRead, diagnostics(debugging)), null)
  const next = acquire(store, 'device-parameters', 'test')
  assert.equal(store.completeOperation(token, { adapter: idle }), false)
  assert.equal(store.getSnapshot().operation, next)
  assert.deepEqual(published.map(item => item.adapter.state), ['idle', 'connected'])
})

test('allows same-profile idle handoff, then arbitrates testing, debugging and capturing in both directions', async () => {
  const { store, reads } = setup()
  await answer(reads, store.startSession(alice), diagnostics(connected))
  assert.equal(store.blockedReason(), null)
  for (const owner of ['dispersion', 'sample-acquisition', 'evaporation-acquisition']) {
    reject(store, owner, 'capture_start', 9)
    const operation = acquire(store, owner, 'capture_choose')
    assert.equal(store.completeOperation(operation), true)
  }
  reject(store, 'device-parameters', 'test', 9)
  const testing = acquire(store, 'device-parameters', 'test')
  assert.equal(store.getSnapshot().status, 'testing')
  reject(store, 'alignment', 'debug_start')
  reject(store, 'dispersion', 'capture_start')
  store.completeOperation(testing)
  store.completeOperation(acquire(store, 'alignment', 'debug_start'), { adapter: debugging })
  reject(store, 'dispersion', 'capture_start')
  reject(store, 'device-parameters', 'test')
  store.completeOperation(acquire(store, 'alignment', 'debug_stop'), { adapter: connected })
  const start = acquire(store, 'dispersion', 'capture_start', 7, 21)
  store.completeOperation(start, { portReleased: true,
    capture: { taskId: 21, profileId: 7, transport: 'serial', state: 'burn' } })
  assert.equal(store.getSnapshot().status, 'capturing')
  reject(store, 'alignment', 'debug_start')
  reject(store, 'device-parameters', 'test')
  reject(store, 'sample-acquisition', 'capture_stop', 7, 21)
  reject(store, 'dispersion', 'capture_stop', 7, 22)
  store.completeOperation(acquire(store, 'dispersion', 'capture_stop', 7, 21), { capture: null })
  assert.equal(store.getSnapshot().status, 'idle')
})

test('stop, disconnect and finish each preempt turning without releasing the emergency command on late turn receipt', async () => {
  for (const kind of ['debug_stop', 'disconnect', 'finish']) {
    const { store, reads } = setup()
    await answer(reads, store.startSession(alice), diagnostics(debugging))
    const turn = acquire(store, 'alignment', 'turn')
    reject(store, 'dispersion', 'capture_start')
    reject(store, 'device-parameters', 'test')
    const stop = acquire(store, 'alignment', kind)
    reject(store, 'alignment', 'disconnect')
    assert.equal(store.completeOperation(turn, { turning: false }), false)
    assert.equal(store.getSnapshot().operation, stop)
    store.completeOperation(stop, { adapter: kind === 'debug_stop' ? connected : idle })
    assert.equal(store.getSnapshot().status, kind === 'debug_stop' ? 'connected_idle' : 'idle')
  }
  const { store, reads } = setup()
  await answer(reads, store.startSession(alice), diagnostics(turning))
  assert.equal(store.getSnapshot().status, 'turning')
  acquire(store, 'alignment', 'disconnect')
})

test('unmount retains unknown through diagnostic reads until an abandoned request settles', async () => {
  const { store, reads } = setup()
  await answer(reads, store.startSession(alice))
  const token = acquire(store, 'alignment', 'connect')
  store.abandonOwner(alice.token, 'device-connection')
  assert.equal(store.getSnapshot().operation, token)
  store.abandonOwner(alice.token, 'alignment')
  assert.equal(store.getSnapshot().status, 'unknown')
  reject(store, 'device-parameters', 'test')
  await answer(reads, store.reconcile(alice.token))
  assert.equal(store.getSnapshot().status, 'unknown')
  assert.equal(store.completeOperation(token, { adapter: connected }), false)
  assert.equal(store.getSnapshot().status, 'unknown')
  await answer(reads, store.reconcile(alice.token), diagnostics(connected))
  assert.equal(store.getSnapshot().status, 'connected_idle')
})

test('timeout and busy conflict request one reconciliation and follow active_captures and adapter state', async () => {
  const { store, reads, published } = setup()
  await answer(reads, store.startSession(alice))
  const operation = acquire(store, 'alignment', 'connect')
  store.failOperation(operation, Object.assign(new Error('响应超时'), { status: 0 }))
  assert.equal(store.getSnapshot().status, 'unknown')
  reject(store, 'dispersion', 'capture_start')
  const first = store.reconcile(alice.token)
  assert.equal(first, store.reconcile(alice.token))
  await answer(reads, first, diagnostics(connected))
  assert.equal(store.getSnapshot().status, 'connected_idle')
  const testConnection = acquire(store, 'device-parameters', 'test')
  store.failOperation(testConnection, Object.assign(new Error('服务端设备忙'), { status: 409, code: 'device_busy' }))
  assert.equal(store.getSnapshot().status, 'unknown')
  await answer(reads, store.reconcile(alice.token), diagnostics(idle, [serialCapture]))
  assert.deepEqual(published[2].active_captures, [serialCapture])
  assert.equal(store.getSnapshot().status, 'capturing')
  assert.equal(store.getSnapshot().port, 'COM12')
  assert.equal(store.getSnapshot().profileId, 7)
  reject(store, 'alignment', 'connect')
  await answer(reads, store.reconcile(alice.token), diagnostics(debugging))
  assert.equal(store.getSnapshot().status, 'debugging')
  await answer(reads, store.reconcile(alice.token), diagnostics())
  assert.equal(store.getSnapshot().status, 'idle')
  assert.equal(reads.length, 5)
})

test('uncertain capture control also checks the task list for simulator and paused sessions', async () => {
  const { store, reads } = setup()
  await answer(reads, store.startSession(alice))
  const start = acquire(store, 'sample-acquisition', 'capture_start', 8, 41)
  const activity = { taskId: 41, profileId: 8, transport: 'simulator', state: 'paused' }
  const recovery = { owner: 'sample-acquisition', read: async () => activity }
  store.failOperation(start, new Error('网络连接中断'), recovery)
  assert.equal(store.getSnapshot().status, 'unknown')
  await answer(reads, store.reconcile(alice.token))
  assert.equal(store.getSnapshot().status, 'capturing')
  assert.equal(store.getSnapshot().activeOwner, 'sample-acquisition')
  await answer(reads, store.reconcile(alice.token))
  assert.equal(store.getSnapshot().status, 'capturing')
  store.abandonOwner(alice.token, 'sample-acquisition', { ...recovery, read: async () => null })
  assert.equal(store.getSnapshot().status, 'unknown')
  await answer(reads, store.reconcile(alice.token))
  assert.equal(store.getSnapshot().status, 'idle')
})

test('failed diagnostics keep unknown and a later authorized refresh restores state', async () => {
  const { store, reads } = setup()
  const first = store.startSession(alice)
  await Promise.resolve()
  reads[0].reject(new Error('诊断请求断开'))
  assert.equal(await first, null)
  assert.equal(store.getSnapshot().status, 'unknown')
  reject(store, 'device-connection', 'connect')
  await answer(reads, store.reconcile(alice.token))
  assert.equal(store.getSnapshot().status, 'idle')
})

test('idle diagnostics alone cannot confirm a reported motor stop failure, but a successful stop can', async () => {
  const { store, reads } = setup()
  await answer(reads, store.startSession(alice), diagnostics(debugging))
  const stop = acquire(store, 'alignment', 'debug_stop')
  store.failOperation(stop, Object.assign(new Error('电机未确认停止'), { status: 409, code: 'motor_stop_unconfirmed' }))
  await answer(reads, store.reconcile(alice.token), diagnostics(connected))
  assert.equal(store.getSnapshot().status, 'unknown')
  reject(store, 'dispersion', 'capture_start')
  reject(store, 'device-parameters', 'test')
  store.completeOperation(acquire(store, 'alignment', 'debug_stop'), { adapter: connected })
  assert.equal(store.getSnapshot().status, 'connected_idle')
})

test('logout and account changes isolate diagnostics, operations and late receipts', async () => {
  const { store, reads, published } = setup()
  await answer(reads, store.startSession(alice), diagnostics(connected))
  const aliceOperation = acquire(store, 'alignment', 'connect')
  store.abandonOwner(alice.token, 'alignment')
  await Promise.resolve()
  const aliceRead = reads[1]
  store.stopSession()
  assert.equal(store.getSnapshot().status, 'idle')
  assert.equal(store.getSnapshot().profileId, null)
  reject(store, 'alignment', 'connect')
  await answer(reads, store.startSession(bob))
  const bobOperation = acquire(store, 'device-parameters', 'test')
  aliceRead.resolve(diagnostics(debugging))
  await Promise.resolve()
  assert.equal(await store.reconcile(alice.token), null)
  assert.equal(store.completeOperation(aliceOperation, { adapter: connected }), false)
  assert.equal(store.getSnapshot().operation, bobOperation)
  assert.equal(store.getSnapshot().status, 'testing')
  assert.equal(published.length, 2)
  assert.equal(store.completeOperation(bobOperation), true)
})
