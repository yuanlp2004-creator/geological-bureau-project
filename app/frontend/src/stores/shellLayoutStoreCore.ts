import type { RuntimeEvent } from '../api/system'

type Layout = Readonly<{ sidebarCollapsed: boolean; informationExpanded: boolean }>
type ShellView = Layout & Readonly<{ focusMode: boolean }>
type ShellLayout = Readonly<{
  userId: number | null
  view: ShellView
  lastSeenEventId: number
}>
type EventSummary = { count: number; severity: 'warning' | 'error' | null; maxEventId: number }

export const initialShellLayout: ShellLayout = {
  userId: null, view: { sidebarCollapsed: false, informationExpanded: false, focusMode: false }, lastSeenEventId: 0
}

export function unreadAlerts(events: readonly Pick<RuntimeEvent, 'id' | 'severity'>[], lastSeenEventId: number): EventSummary {
  let count = 0
  let severity: EventSummary['severity'] = null
  let maxEventId = 0
  for (const event of events) {
    maxEventId = Math.max(maxEventId, event.id)
    if (event.id <= lastSeenEventId || (event.severity !== 'warning' && event.severity !== 'error')) continue
    count++
    if (severity !== 'error') severity = event.severity
  }
  return { count, severity, maxEventId }
}

const layoutKey = (userId: number) => `geospectrum:shell-layout:${userId}`
const seenKey = (userId: number) => `geospectrum:runtime-last-seen:${userId}`

export function createShellLayoutStore(storage?: Pick<Storage, 'getItem' | 'setItem'>) {
  const listeners = new Set<() => void>()
  let snapshot = initialShellLayout
  let beforeFocus: Layout | null = null

  function read(key: string): unknown {
    try { return JSON.parse(storage?.getItem(key) ?? 'null') } catch { return null }
  }

  function write(key: string, value: unknown) {
    try { storage?.setItem(key, JSON.stringify(value)) } catch { /* Keep the current session usable. */ }
  }

  function publish(next: ShellLayout) {
    snapshot = next
    listeners.forEach(listener => listener())
  }

  function updateLayout(layout: Layout) {
    const { userId, view: { focusMode } } = snapshot
    if (userId === null) return
    if (!focusMode) write(layoutKey(userId), layout)
    publish({ ...snapshot, view: { ...layout, focusMode } })
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    startSession(userId: number) {
      if (snapshot.userId === userId) return
      beforeFocus = null
      const saved = read(layoutKey(userId)) as Partial<Layout> | null
      const seen = read(seenKey(userId))
      publish({
        ...initialShellLayout,
        userId,
        view: {
          focusMode: false,
          sidebarCollapsed: saved?.sidebarCollapsed === true,
          informationExpanded: saved?.informationExpanded === true
        },
        lastSeenEventId: typeof seen === 'number' && Number.isSafeInteger(seen) && seen > 0 ? seen : 0
      })
    },
    stopSession() {
      beforeFocus = null
      if (snapshot.userId !== null) publish(initialShellLayout)
    },
    toggleSidebar() {
      const { focusMode, sidebarCollapsed, informationExpanded } = snapshot.view
      if (focusMode) return
      updateLayout({ sidebarCollapsed: !sidebarCollapsed, informationExpanded })
    },
    setInformationExpanded(expanded: boolean) {
      if (snapshot.view.informationExpanded === expanded) return
      updateLayout({ sidebarCollapsed: snapshot.view.sidebarCollapsed, informationExpanded: expanded })
    },
    toggleFocusMode() {
      if (snapshot.userId === null) return
      if (beforeFocus) {
        const restored = beforeFocus
        beforeFocus = null
        publish({ ...snapshot, view: { ...restored, focusMode: false } })
      } else {
        const { sidebarCollapsed, informationExpanded } = snapshot.view
        beforeFocus = { sidebarCollapsed, informationExpanded }
        publish({ ...snapshot, view: { sidebarCollapsed: true, informationExpanded: false, focusMode: true } })
      }
    },
    markEventsSeen(userId: number, maxEventId: number) {
      if (snapshot.userId !== userId || !Number.isSafeInteger(maxEventId) || maxEventId <= snapshot.lastSeenEventId) return
      write(seenKey(userId), maxEventId)
      publish({ ...snapshot, lastSeenEventId: maxEventId })
    }
  }
}
