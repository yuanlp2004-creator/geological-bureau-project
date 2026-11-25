import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
import { createThemeStore, resolveTheme } from '../frontend/src/stores/themeStoreCore.ts'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const ts = require('typescript')
const chartSource = readFileSync(new URL('../frontend/src/components/SimpleChartAxes.tsx', import.meta.url), 'utf8')
const chartCode = ts.transpileModule(chartSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX }
}).outputText
const chartAxes = {}
vm.runInNewContext(chartCode, { exports: chartAxes, require })

const keyA = 'geospectrum:theme:1'
const keyB = 'geospectrum:theme:2'

function setup(initialStorage = new Map()) {
  const applied = []
  const store = createThemeStore({
    storage: {
      getItem: key => initialStorage.get(key) ?? null,
      setItem: (key, value) => initialStorage.set(key, value)
    },
    applyTheme: theme => applied.push(theme)
  })
  return { store, applied, storage: initialStorage }
}

test('the auth screens start and stay light without an active account', () => {
  const { store, applied, storage } = setup(new Map([[keyA, 'dark']]))
  assert.equal(store.getSnapshot(), 'light')
  assert.deepEqual(applied, ['light'])
  store.setSettingsTheme('dark')
  store.toggleTheme()
  assert.equal(store.getSnapshot(), 'light')
  assert.deepEqual([...storage], [[keyA, 'dark']])
  store.activateUser(2)
  assert.equal(store.getSnapshot(), 'light')
})

test('activation ignores damaged values and each toggle persists to the account key', () => {
  const { store, applied, storage } = setup(new Map([[keyA, 'DARK']]))
  store.activateUser(1)
  assert.equal(store.getSnapshot(), 'light')
  store.toggleTheme()
  assert.equal(store.getSnapshot(), 'dark')
  assert.equal(applied[applied.length - 1], 'dark')
  assert.equal(storage.get(keyA), 'dark')
  store.toggleTheme()
  assert.equal(store.getSnapshot(), 'light')
  assert.deepEqual([...storage], [[keyA, 'light']])
})

test('sign-out clears the current theme and each account synchronously restores its own preference', () => {
  const { store, applied, storage } = setup(new Map([[keyB, 'light']]))
  store.activateUser(1)
  store.toggleTheme()
  assert.equal(store.getSnapshot(), 'dark')
  store.deactivate()
  assert.equal(store.getSnapshot(), 'light')
  store.activateUser(2)
  assert.equal(store.getSnapshot(), 'light')
  assert.deepEqual([...storage], [[keyB, 'light'], [keyA, 'dark']])
  store.activateUser(1)
  assert.equal(store.getSnapshot(), 'dark')
  assert.deepEqual(applied, ['light', 'light', 'dark', 'light', 'light', 'dark'])
})

test('settings dark applies only as a session fallback without a valid local preference', () => {
  const { store, storage } = setup()
  store.activateUser(1)
  store.setSettingsTheme('dark')
  assert.equal(store.getSnapshot(), 'dark')
  assert.equal(storage.size, 0)
  store.activateUser(2)
  assert.equal(store.getSnapshot(), 'light')
  store.setSettingsTheme('unknown')
  assert.equal(store.getSnapshot(), 'light')
  assert.equal(resolveTheme(null, null), 'light')
})

test('a manual preference takes priority over later GET settings and notifies only on changes', () => {
  const { store, applied, storage } = setup()
  store.activateUser(1)
  const notifications = []
  const unsubscribe = store.subscribe(() => {
    assert.equal(applied[applied.length - 1], store.getSnapshot())
    notifications.push(store.getSnapshot())
  })
  store.toggleTheme()
  store.setSettingsTheme('light')
  assert.equal(store.getSnapshot(), 'dark')
  assert.equal(storage.get(keyA), 'dark')
  store.toggleTheme()
  store.setSettingsTheme('dark')
  assert.equal(store.getSnapshot(), 'light')
  assert.equal(storage.get(keyA), 'light')
  unsubscribe()
  store.toggleTheme()
  assert.deepEqual(notifications, ['dark', 'light'])
})

test('storage access failures preserve the current session and reset cleanly at sign-out', () => {
  const store = createThemeStore({
    storage: {
      getItem() { throw new Error('Storage blocked') },
      setItem() { throw new Error('Storage blocked') }
    },
    applyTheme() {}
  })
  store.activateUser(1)
  assert.equal(store.getSnapshot(), 'light')
  store.toggleTheme()
  store.setSettingsTheme('light')
  assert.equal(store.getSnapshot(), 'dark')
  store.deactivate()
  store.activateUser(1)
  assert.equal(store.getSnapshot(), 'light')
})

test('integer and fractional axes normalize negative zero in labels and tick values', () => {
  const { formatIntegerTick, formatFractionalTick, integerAxisTicks, fractionalTicks } = chartAxes
  assert.equal(formatIntegerTick(-0), '0')
  assert.equal(formatIntegerTick(-0.2), '0')
  assert.equal(formatFractionalTick(-0), '0')
  assert.equal(formatFractionalTick(-1e-7), '-1.00e-7')

  for (const ticks of [
    integerAxisTicks(-100, 15000), integerAxisTicks(-0.2, 0.2), integerAxisTicks(-0, -0),
    fractionalTicks(-0.5, 0.5), fractionalTicks(-0.01, 1), fractionalTicks(-0, -0)
  ]) {
    assert.ok(ticks.some(tick => Object.is(tick, 0)))
    assert.ok(ticks.every(tick => !Object.is(tick, -0)))
  }
})
