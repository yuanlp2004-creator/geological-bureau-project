import assert from 'node:assert/strict'
import test from 'node:test'
import { createShellLayoutStore, unreadAlerts } from '../frontend/src/stores/shellLayoutStoreCore.ts'

const layoutKey = id => `geospectrum:shell-layout:${id}`
const seenKey = id => `geospectrum:runtime-last-seen:${id}`
const expandedSidebar = { sidebarCollapsed: false, informationExpanded: false, focusMode: false }

function setup() {
  const entries = new Map()
  const storage = { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value) }
  return { storage, entries, store: createShellLayoutStore(storage) }
}

test('sidebar starts expanded and each account remembers its own manual layout', () => {
  const { store, storage, entries } = setup()
  store.startSession(1)
  assert.deepEqual(store.getSnapshot().view, expandedSidebar)
  store.toggleSidebar()
  store.setInformationExpanded(true)
  assert.deepEqual(JSON.parse(entries.get(layoutKey(1))), { sidebarCollapsed: true, informationExpanded: true })

  store.startSession(2)
  assert.deepEqual(store.getSnapshot().view, expandedSidebar)
  assert.equal(entries.has(layoutKey(2)), false)
  store.setInformationExpanded(true)
  assert.deepEqual(JSON.parse(entries.get(layoutKey(2))), { sidebarCollapsed: false, informationExpanded: true })

  const reopened = createShellLayoutStore(storage)
  reopened.startSession(1)
  assert.deepEqual(reopened.getSnapshot().view, { sidebarCollapsed: true, informationExpanded: true, focusMode: false })
  reopened.toggleSidebar()
  reopened.startSession(2)
  assert.deepEqual(reopened.getSnapshot().view, { ...expandedSidebar, informationExpanded: true })
})

test('the current layout key is the source of the saved drawer preference', () => {
  const { store, entries } = setup()
  entries.set('geospectrum:information-panel:1', JSON.stringify({ layoutVersion: 2, collapsed: false, height: 230 }))
  store.startSession(1)
  assert.equal(store.getSnapshot().view.informationExpanded, false)
  store.setInformationExpanded(true)
  store.startSession(2)
  assert.equal(store.getSnapshot().view.informationExpanded, false)
  store.startSession(1)
  assert.equal(store.getSnapshot().view.informationExpanded, true)
})

test('storage failures and corrupt preferences leave usable session state', () => {
  const unavailable = createShellLayoutStore({
    getItem() { throw new Error('storage is disabled') },
    setItem() { throw new Error('storage is full') }
  })
  unavailable.startSession(1)
  assert.deepEqual(unavailable.getSnapshot().view, expandedSidebar)
  unavailable.toggleSidebar()
  unavailable.setInformationExpanded(true)
  unavailable.markEventsSeen(1, 4)
  assert.equal(unavailable.getSnapshot().view.sidebarCollapsed, true)
  assert.equal(unavailable.getSnapshot().view.informationExpanded, true)
  assert.equal(unavailable.getSnapshot().lastSeenEventId, 4)

  const { store, entries } = setup()
  entries.set(layoutKey(1), 'invalid JSON')
  entries.set(seenKey(1), '-10')
  store.startSession(1)
  assert.deepEqual(store.getSnapshot().view, expandedSidebar)
  assert.equal(store.getSnapshot().lastSeenEventId, 0)
})

for (const sidebarCollapsed of [false, true]) {
  for (const informationExpanded of [false, true]) {
    test(`focus restores sidebarCollapsed=${sidebarCollapsed}, informationExpanded=${informationExpanded}`, () => {
      const { store, entries } = setup()
      store.startSession(1)
      if (sidebarCollapsed) store.toggleSidebar()
      store.setInformationExpanded(informationExpanded)
      const before = store.getSnapshot().view
      const saved = entries.get(layoutKey(1))

      store.toggleFocusMode()
      assert.deepEqual(store.getSnapshot().view, { sidebarCollapsed: true, informationExpanded: false, focusMode: true })
      assert.equal(entries.get(layoutKey(1)), saved)
      store.toggleFocusMode()
      assert.deepEqual(store.getSnapshot().view, before)

      store.toggleFocusMode()
      store.setInformationExpanded(true)
      assert.equal(store.getSnapshot().view.informationExpanded, true)
      store.toggleSidebar()
      assert.equal(store.getSnapshot().view.sidebarCollapsed, true)
      store.toggleFocusMode()
      assert.deepEqual(store.getSnapshot().view, before)
      assert.equal(entries.get(layoutKey(1)), saved)
    })
  }
}

test('focus is discarded on logout and account switch', () => {
  const { store } = setup()
  store.startSession(1)
  store.toggleSidebar()
  store.setInformationExpanded(true)
  store.toggleFocusMode()
  store.startSession(1)
  assert.equal(store.getSnapshot().view.focusMode, true)

  store.startSession(2)
  assert.deepEqual(store.getSnapshot().view, expandedSidebar)
  store.toggleFocusMode()
  store.stopSession()
  assert.equal(store.getSnapshot().userId, null)
  assert.deepEqual(store.getSnapshot().view, expandedSidebar)
  store.toggleFocusMode()
  assert.deepEqual(store.getSnapshot().view, expandedSidebar)

  store.startSession(1)
  assert.deepEqual(store.getSnapshot().view, { sidebarCollapsed: true, informationExpanded: true, focusMode: false })
})

test('unread counts use raw event IDs, select the highest severity and return the newest event ID', () => {
  const events = [
    { id: 8, severity: 'info' }, { id: 3, severity: 'error' }, { id: 7, severity: 'warning' },
    { id: 6, severity: 'warning' }, { id: 5, severity: 'success' }, { id: 4, severity: 'debug' }
  ]
  assert.deepEqual(unreadAlerts(events, 0), { count: 3, severity: 'error', maxEventId: 8 })
  assert.deepEqual(unreadAlerts(events, 3), { count: 2, severity: 'warning', maxEventId: 8 })
  assert.deepEqual(unreadAlerts(events, 8), { count: 0, severity: null, maxEventId: 8 })
  assert.deepEqual(unreadAlerts([], 8), { count: 0, severity: null, maxEventId: 0 })
})

test('reading advances the account watermark independently of layout, filtering and cleared snapshots', () => {
  const { store, entries } = setup()
  const events = [{ id: 7, severity: 'error' }, { id: 6, severity: 'info' }]
  store.startSession(1)
  store.setInformationExpanded(true)
  const layout = store.getSnapshot().view
  const summary = unreadAlerts(events, store.getSnapshot().lastSeenEventId)
  assert.equal(summary.count, 1)
  store.markEventsSeen(1, summary.maxEventId)
  assert.equal(store.getSnapshot().view, layout)
  assert.equal(unreadAlerts(events, store.getSnapshot().lastSeenEventId).count, 0)
  store.markEventsSeen(1, unreadAlerts([], 7).maxEventId)
  store.markEventsSeen(1, 6)
  assert.equal(store.getSnapshot().lastSeenEventId, 7)
  assert.equal(JSON.parse(entries.get(seenKey(1))), 7)
  assert.deepEqual(JSON.parse(entries.get(layoutKey(1))), { sidebarCollapsed: false, informationExpanded: true })

  store.startSession(2)
  store.markEventsSeen(1, 100)
  assert.equal(store.getSnapshot().lastSeenEventId, 0)
  assert.equal(unreadAlerts(events, 0).count, 1)
  store.markEventsSeen(2, 11)
  store.stopSession()
  store.startSession(1)
  assert.equal(store.getSnapshot().lastSeenEventId, 7)
  assert.equal(unreadAlerts([{ id: 8, severity: 'warning' }], 7).count, 1)
  store.startSession(2)
  assert.equal(store.getSnapshot().lastSeenEventId, 11)
})
