import assert from 'node:assert/strict'
import test from 'node:test'
import { createRuntimeEventsStore, runtimeEventsFingerprint } from '../frontend/src/stores/runtimeEventsStoreCore.ts'

const accountA = { token: 'token-a', userId: 1, canRead: true }
const accountB = { token: 'token-b', userId: 2, canRead: true }

function event(id) {
  return {
    id, category: 'analysis', severity: 'info', message: `event ${id}`,
    details: null, correlation_id: null, created_at: new Date(id * 1000).toISOString()
  }
}

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function setup() {
  const requests = []
  const clears = []
  const timers = new Map()
  let timerId = 0
  const store = createRuntimeEventsStore({
    fetchLogs(token, query) {
      const request = deferred()
      requests.push({ token, query, ...request })
      return request.promise
    },
    clearLogs(token) {
      const request = deferred()
      clears.push({ token, ...request })
      return request.promise
    },
    setInterval(callback, delay) {
      assert.equal(delay, 1500)
      const id = timerId++
      timers.set(id, callback)
      return id
    },
    clearInterval: id => timers.delete(id)
  })
  const notifications = []
  store.subscribe(() => notifications.push(store.getSnapshot()))

  function tick() {
    for (const callback of timers.values()) callback()
  }

  async function load(events) {
    const count = requests.length
    const done = store.refresh()
    assert.equal(requests.length, count + 1)
    requests[count].resolve(events)
    await done
  }

  return { store, requests, clears, timers, notifications, tick, load }
}

test('identical empty and populated fingerprints keep snapshot identity and send no notifications', async () => {
  const { store, notifications, load } = setup()
  store.startSession(accountA)
  const empty = store.getSnapshot()
  await load([])
  await load([])
  assert.strictEqual(store.getSnapshot(), empty)
  assert.deepEqual(notifications, [])
  assert.equal(runtimeEventsFingerprint(empty), '0:0:0:')

  const first = [event(2), event(1)]
  await load(first)
  assert.deepEqual(notifications, [first])
  notifications.length = 0
  await load([event(2), event(1)])
  await load([event(2), event(1)])
  assert.strictEqual(store.getSnapshot(), first)
  assert.deepEqual(notifications, [])
  assert.equal(runtimeEventsFingerprint(first), `2:1:2:${first[0].created_at}`)
})

test('interval ticks do not overlap a read and an old generation cannot overwrite a newer reply', async () => {
  const { store, requests, timers, notifications, tick, load } = setup()
  store.startSession(accountA)
  tick()
  const staleTimer = [...timers.values()][0]
  store.startSession({ ...accountA })
  tick()
  tick()
  assert.equal(timers.size, 1)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].query, '?limit=500')

  store.startSession({ ...accountA, token: 'renewed-token' })
  staleTimer()
  assert.equal(requests.length, 1)
  const current = [event(3)]
  await load(current)
  assert.equal(requests[1].token, 'renewed-token')
  requests[0].resolve([event(1)])
  await Promise.resolve()
  assert.strictEqual(store.getSnapshot(), current)
  assert.deepEqual(notifications, [current])
})

test('manual refreshes coalesce into one follow-up and polling skips both in-flight reads', async () => {
  const { store, requests, tick } = setup()
  store.startSession(accountA)
  tick()
  await store.refresh()
  await store.refresh()
  tick()
  assert.equal(requests.length, 1)
  requests[0].resolve([event(1)])
  await Promise.resolve()
  tick()
  assert.equal(requests.length, 2)
  const current = [event(2)]
  requests[1].resolve(current)
  await Promise.resolve()
  assert.strictEqual(store.getSnapshot(), current)
  assert.equal(requests.length, 2)
})

test('successful server clear blocks polls while pending and discards a pre-clear reply', async () => {
  const { store, requests, clears, notifications, tick, load } = setup()
  store.startSession(accountA)
  await load([event(1)])
  tick()
  const clearing = store.clearServerEvents(accountA.token)
  assert.equal(clears[0].token, accountA.token)
  tick()
  assert.equal(requests.length, 2)
  clears[0].resolve({ deleted: 1 })
  await clearing
  const empty = store.getSnapshot()
  assert.deepEqual(empty, [])
  assert.strictEqual(notifications[1], empty)

  requests[1].resolve([event(2), event(1)])
  await Promise.resolve()
  assert.strictEqual(store.getSnapshot(), empty)
  assert.equal(notifications.length, 2)
  await load([event(3)])
  assert.equal(store.getSnapshot()[0].id, 3)
})

test('failed server clear preserves the snapshot and releases the queued manual refresh', async () => {
  const { store, requests, clears, notifications, tick, load } = setup()
  store.startSession(accountA)
  const first = [event(1)]
  await load(first)
  const clearing = store.clearServerEvents(accountA.token)
  const error = new Error('clear failed')
  const failure = assert.rejects(clearing, error)
  tick()
  await store.refresh()
  assert.equal(requests.length, 1)
  clears[0].reject(error)
  await failure
  assert.strictEqual(store.getSnapshot(), first)
  assert.deepEqual(notifications, [first])
  assert.equal(requests.length, 2)
  requests[1].resolve([event(2), ...first])
  await Promise.resolve()
  assert.equal(store.getSnapshot()[0].id, 2)
})

test('a 500-row rollover with unchanged length updates the fingerprint and notifies', async () => {
  const { store, notifications, load } = setup()
  store.startSession(accountA)
  const first = Array.from({ length: 500 }, (_, index) => event(index + 1))
  const next = [...first.slice(1), event(501)]
  assert.equal(first.length, next.length)
  assert.notEqual(runtimeEventsFingerprint(first), runtimeEventsFingerprint(next))
  await load(first)
  await load(next)
  assert.strictEqual(store.getSnapshot(), next)
  assert.deepEqual(notifications, [first, next])
})

test('503 and network failures preserve the successful snapshot and polling recovers', async () => {
  const { store, requests, notifications, tick, load } = setup()
  store.startSession(accountA)
  const first = [event(1)]
  await load(first)
  const errors = [Object.assign(new Error('unavailable'), { status: 503 }), new TypeError('network error')]
  for (const [index, error] of errors.entries()) {
    tick()
    requests[index + 1].reject(error)
    await Promise.resolve()
    assert.strictEqual(store.getSnapshot(), first)
    assert.deepEqual(notifications, [first])
  }
  tick()
  const next = [event(2), event(1)]
  requests[3].resolve(next)
  await Promise.resolve()
  assert.strictEqual(store.getSnapshot(), next)
  assert.deepEqual(notifications, [first, next])
})

test('logout clears the snapshot and late reads or clears from A cannot affect B', async () => {
  const { store, requests, clears, timers, notifications, tick, load } = setup()
  store.startSession(accountA)
  const first = [event(1)]
  await load(first)
  tick()
  await store.refresh()
  const clearing = store.clearServerEvents(accountA.token)
  store.stopSession()
  assert.equal(timers.size, 0)
  assert.deepEqual(store.getSnapshot(), [])
  await store.refresh()
  assert.equal(requests.length, 2)

  store.startSession(accountB)
  const current = [event(3)]
  await load(current)
  assert.equal(requests[2].token, accountB.token)
  requests[1].reject(new Error('late read failure'))
  clears[0].resolve({ deleted: 1 })
  await clearing
  assert.strictEqual(store.getSnapshot(), current)
  assert.equal(requests.length, 3)
  assert.deepEqual(notifications, [first, [], current])
})

test('missing token or read permission prevents requests and downgrade invalidates a pending reply', async () => {
  const { store, requests, timers, notifications, tick, load } = setup()
  const denied = { ...accountA, canRead: false }
  for (const session of [denied, { ...accountA, token: null }]) {
    store.startSession(session)
    tick()
    await store.refresh()
    assert.equal(timers.size, 0)
    assert.equal(requests.length, 0)
  }

  store.startSession(accountA)
  const first = [event(1)]
  await load(first)
  tick()
  store.startSession(denied)
  assert.equal(timers.size, 0)
  assert.deepEqual(store.getSnapshot(), [])
  requests[1].resolve([event(2)])
  await store.refresh()
  tick()
  assert.equal(requests.length, 2)
  assert.deepEqual(store.getSnapshot(), [])
  assert.deepEqual(notifications, [first, []])
})
