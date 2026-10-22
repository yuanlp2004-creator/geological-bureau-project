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

test('safe desktop reads can recover while sidecar starts', async () => {
  let calls = 0
  const { requestRaw } = transport(async () => {
    if (++calls === 1) throw new TypeError('not ready')
    return { ok: true }
  })
  assert.equal((await requestRaw('/health')).ok, true)
  assert.equal(calls, 2)
})

test('cancellation stops retries and an already cancelled command is never sent', async () => {
  const controller = new AbortController()
  let calls = 0
  const { requestRaw } = transport(async () => {
    calls++
    controller.abort()
    throw new TypeError('closed')
  })
  await assert.rejects(requestRaw('/health', { signal: controller.signal }), { name: 'AbortError' })
  await assert.rejects(requestRaw('/create', { method: 'POST', signal: controller.signal }), { name: 'AbortError' })
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
