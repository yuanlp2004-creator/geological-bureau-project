import assert from 'node:assert/strict'
import test from 'node:test'
import { createDeviceStatusStore } from '../frontend/src/stores/deviceStatusStoreCore.ts'

const alice = { token: 'alice', userId: 1, canRead: true }
const bob = { token: 'bob', userId: 2, canRead: true }
const simulator = { adapter: 'acq-simulator', state: 'connected', session_id: 'sim', connected: true, contract: {} }
const serial = { ...simulator, adapter: 'legacy-ccd-serial', port: 'COM12', state: 'debugging' }
const diagnostics = (adapter) => ({ adapter, profiles: [] })

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function setup() {
  const requests = []
  const store = createDeviceStatusStore({
    fetchDiagnostics(token) {
      const response = deferred()
      requests.push({ token, ...response })
      return response.promise
    }
  })
  return { store, requests }
}

test('devices.read gates session startup, manual refresh and publishing', async () => {
  const { store, requests } = setup()
  await store.startSession({ ...alice, canRead: false })
  await store.refresh()
  store.publish(serial, 1)
  assert.equal(requests.length, 0)
  assert.equal(store.getSessionGeneration(alice.token), null)
  assert.deepEqual(store.getSnapshot(), {
    status: 'unauthorized', connected: false, stateLabel: '未授权', transport: null, port: null,
    activeCapturesCount: 0, lastError: null, generation: 1, updatedAt: null
  })
})

test('initial diagnostics and concurrent refreshes share one active request', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  assert.equal(store.getSnapshot().status, 'loading')
  assert.equal(store.refresh(), initial)
  assert.equal(store.refresh(), initial)
  await Promise.resolve()
  assert.deepEqual(requests.map(request => request.token), ['alice'])
  requests[0].resolve(diagnostics(simulator))
  await initial
  const ready = store.getSnapshot()
  assert.equal(ready.status, 'ready')
  assert.equal(ready.transport, 'simulator')
  assert.equal(ready.connected, true)
  const next = store.refresh()
  await Promise.resolve()
  assert.equal(requests.length, 2)
  requests[1].resolve(diagnostics(serial))
  await next
  assert.equal(store.getSnapshot().port, 12)
})

test('a stopped session clears its snapshot and discards pending diagnostics and receipts', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  const oldGeneration = store.getSessionGeneration(alice.token)
  await Promise.resolve()
  store.publish(serial, 1, oldGeneration)
  store.stopSession()
  const loggedOut = store.getSnapshot()
  assert.equal(loggedOut.status, 'idle')
  assert.ok(loggedOut.generation > oldGeneration)
  assert.equal(loggedOut.updatedAt, null)
  assert.equal(loggedOut.connected, false)
  assert.equal(loggedOut.port, null)
  assert.equal(loggedOut.activeCapturesCount, 0)
  store.publish(serial, 1, oldGeneration)
  requests[0].resolve(diagnostics(simulator))
  await initial
  assert.equal(store.getSnapshot(), loggedOut)
})

test('old account responses cannot replace a new account snapshot or clear its in-flight request', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  const oldGeneration = store.getSessionGeneration(alice.token)
  await Promise.resolve()
  const switched = store.startSession(bob)
  assert.equal(store.getSessionGeneration(alice.token), null)
  assert.ok(store.getSessionGeneration(bob.token) > oldGeneration)
  await Promise.resolve()
  assert.deepEqual(requests.map(request => request.token), ['alice', 'bob'])
  requests[0].resolve(diagnostics(serial))
  await initial
  store.publish(serial, 1, oldGeneration)
  assert.equal(store.getSnapshot().status, 'loading')
  assert.equal(store.refresh(), switched)
  requests[1].resolve(diagnostics(simulator))
  await switched
  assert.equal(store.getSnapshot().transport, 'simulator')
})

test('permission downgrade discards old errors and receipts even when the token stays the same', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  const oldGeneration = store.getSessionGeneration(alice.token)
  await Promise.resolve()
  await store.startSession({ ...alice, canRead: false })
  const denied = store.getSnapshot()
  assert.equal(denied.status, 'unauthorized')
  assert.ok(denied.generation > oldGeneration)
  store.publish(serial, 1, oldGeneration)
  requests[0].reject(new Error('previous session diagnostic failure'))
  await initial
  await store.refresh()
  assert.equal(requests.length, 1)
  assert.equal(store.getSnapshot(), denied)
})

test('publish updates the read-only snapshot without a request and supersedes an older read', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  await Promise.resolve()
  const observed = []
  const unsubscribe = store.subscribe(() => observed.push(store.getSnapshot()))
  store.publish(serial, 2)
  const published = store.getSnapshot()
  assert.equal(published.status, 'ready')
  assert.equal(published.stateLabel, '摄谱进行中')
  assert.equal(published.transport, 'serial')
  assert.equal(published.port, 12)
  assert.equal(published.activeCapturesCount, 2)
  assert.equal(typeof published.updatedAt, 'number')
  assert.deepEqual(observed, [published])
  requests[0].resolve(diagnostics(simulator))
  await initial
  assert.equal(store.getSnapshot(), published)
  unsubscribe()
  store.publish({ ...serial, connected: false, state: 'error', last_error: { code: 'closed', message: '串口已断开' } }, 0)
  assert.equal(store.getSnapshot().lastError, '串口已断开')
  assert.equal(store.getSnapshot().connected, false)
  assert.equal(observed.length, 1)
  assert.equal(requests.length, 1)
})

test('503 diagnostics failure is contained and a manual refresh can recover', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  await Promise.resolve()
  requests[0].reject(Object.assign(new Error('HTTP 503: 设备服务暂时不可用'), { status: 503 }))
  await initial
  assert.equal(store.getSnapshot().status, 'error')
  assert.equal(store.getSnapshot().lastError, 'HTTP 503: 设备服务暂时不可用')
  assert.equal(store.getSnapshot().updatedAt, null)
  const retry = store.refresh()
  await Promise.resolve()
  requests[1].resolve({
    ...diagnostics(serial), active_captures: [{ task_id: 1, owner: 'capture', port: 'COM12', state: 'running' }]
  })
  await retry
  assert.equal(requests.length, 2)
  assert.equal(store.getSnapshot().status, 'ready')
  assert.equal(store.getSnapshot().activeCapturesCount, 1)
  assert.equal(store.getSnapshot().lastError, null)
})

test('a session replaced before its deferred initial read starts makes no stale request', async () => {
  const { store, requests } = setup()
  const initial = store.startSession(alice)
  store.stopSession()
  const replayed = store.startSession(alice)
  await initial
  assert.deepEqual(requests.map(request => request.token), ['alice'])
  requests[0].resolve(diagnostics(simulator))
  await replayed
  assert.equal(store.getSnapshot().status, 'ready')
})
