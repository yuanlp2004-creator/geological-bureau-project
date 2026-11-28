import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../frontend/src/api/client.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
}).outputText

function transport(fetch, { desktop = true, timeout = false, onTimer } = {}) {
  const exports = {}
  vm.runInNewContext(code, {
    exports,
    require: () => ({
      desktopRuntime: async () => (desktop ? { api_base: 'http://localhost', process_key: 'test' } : null)
    }),
    fetch,
    AbortController,
    DOMException,
    Error,
    window: { setTimeout: (fn, ms) => { onTimer?.(ms); return setTimeout(fn, timeout && ms === 8000 ? 1 : ms) }, clearTimeout }
  })
  return exports
}

test('a command whose response is lost is sent only once', async () => {
  let writes = 0
  const { requestRaw } = transport(async () => {
    writes++
    throw new TypeError('response lost after commit')
  })
  await assert.rejects(requestRaw('/create', { method: 'POST' }), { code: 'request_outcome_unknown' })
  assert.equal(writes, 1)
})

test('desktop startup callers share one probe and retry while sidecar starts', async () => {
  let calls = 0
  const { ensureBackendReady } = transport(async (url) => {
    assert.equal(url, 'http://localhost/health')
    if (++calls === 1) throw new TypeError('not ready')
    return { ok: true }
  })
  await Promise.all([ensureBackendReady(), ensureBackendReady()])
  assert.equal(calls, 2)
  await ensureBackendReady()
  assert.equal(calls, 2)
})

test('cancellation stops retries and an already cancelled command is never sent', async () => {
  const controller = new AbortController()
  const sent = []
  const { ensureBackendReady, requestRaw } = transport(async (_url, { signal }) => {
    sent.push(signal)
    throw new TypeError('offline')
  }, {
    onTimer: ms => {
      if (ms === 100) queueMicrotask(() => controller.abort())
    }
  })
  await assert.rejects(ensureBackendReady(controller.signal), { name: 'AbortError' })
  await assert.rejects(requestRaw('/create', { method: 'POST', signal: controller.signal }), { name: 'AbortError' })
  assert.equal(sent.length, 1)
  assert.equal(sent[0].aborted, true)
})

test('cancelling one startup caller leaves the shared probe running for the other', async () => {
  const controller = new AbortController()
  let calls = 0
  const { ensureBackendReady } = transport(async (_url, { signal }) => {
    if (++calls === 1) {
      controller.abort()
      throw new TypeError('not ready')
    }
    assert.equal(signal.aborted, false)
    return { ok: true }
  })
  const cancelled = ensureBackendReady(controller.signal)
  const waiting = ensureBackendReady()
  await assert.rejects(cancelled, { name: 'AbortError' })
  await waiting
  assert.equal(calls, 2)
})

test('desktop reads fail once on network loss and only explicit reconnection restarts the wait', async () => {
  let online = false
  const sent = [], timers = []
  const { ensureBackendReady, requestRaw, resetBackendReady } = transport(async (url, { method = 'GET' }) => {
    sent.push([url, method])
    if (!online) throw new TypeError('offline')
    return { ok: true }
  }, {
    onTimer: ms => {
      timers.push(ms)
      if (ms === 100) online = true
    }
  })
  await assert.rejects(requestRaw('/data'), { message: 'offline' })
  assert.deepEqual(timers, [8000])
  await ensureBackendReady()
  online = false
  sent.length = 0
  timers.length = 0
  await assert.rejects(requestRaw('/data'), { message: 'offline' })
  await assert.rejects(requestRaw('/health', { method: 'HEAD' }), { message: 'offline' })
  await ensureBackendReady()
  assert.deepEqual(sent, [['http://localhost/data', 'GET'], ['http://localhost/health', 'HEAD']])
  assert.deepEqual(timers, [8000, 8000])

  resetBackendReady()
  await ensureBackendReady()
  assert.deepEqual(sent.slice(2), [['http://localhost/health', 'GET'], ['http://localhost/health', 'GET']])
  assert.deepEqual(timers.slice(2), [8000, 100])
})

test('a desktop HTTP error establishes connectivity and browser startup does not probe', async () => {
  let calls = 0
  const desktop = transport(async () => {
    calls++
    return { ok: false, status: 401, text: async () => '{"detail":"unauthorized"}' }
  })
  await assert.rejects(desktop.requestRaw('/auth/me'), { status: 401 })
  await desktop.ensureBackendReady()
  const browser = transport(async () => { calls++ }, { desktop: false })
  await browser.ensureBackendReady()
  assert.equal(calls, 1)
})

test('a hanging command times out without being resubmitted', async () => {
  let calls = 0
  const { requestRaw } = transport(
    (_url, { signal }) =>
      new Promise((_resolve, reject) => {
        calls++
        signal.addEventListener('abort', () => reject(signal.reason), { once: true })
      }),
    { timeout: true }
  )
  await assert.rejects(requestRaw('/step', { method: 'POST' }), { code: 'request_outcome_unknown' })
  assert.equal(calls, 1)
})


test('Windows printing can wait for its dialog without retrying or leaking transport options', async () => {
  const timers = [], sent = []
  const { requestRaw } = transport(async (_url, init) => { sent.push(init); return { ok: true } },
    { onTimer: value => timers.push(value) })
  await requestRaw('/print', { method: 'POST', timeoutMs: 300000 })
  await requestRaw('/health')
  assert.deepEqual(timers, [300000, 8000])
  assert.equal(sent.length, 2)
  assert.ok(sent.every(init => !Object.hasOwn(init, 'timeoutMs')))
})
