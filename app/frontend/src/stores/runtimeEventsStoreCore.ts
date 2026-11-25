import type { RuntimeEvent } from '../api/system'

type Session = { token: string | null; userId: number; canRead: boolean }
type Timer = ReturnType<typeof setInterval>
type Dependencies = {
  fetchLogs: (token: string, query: string) => Promise<RuntimeEvent[]>
  clearLogs: (token: string) => Promise<unknown>
  setInterval: (callback: () => void, delay: number) => Timer
  clearInterval: (timer: Timer) => void
}

const emptyEvents: readonly RuntimeEvent[] = Object.freeze([])

export function runtimeEventsFingerprint(events: readonly RuntimeEvent[]): string {
  const first = events[0]
  const last = events.length > 0 ? events[events.length - 1] : undefined
  return `${first?.id ?? 0}:${last?.id ?? 0}:${events.length}:${first?.created_at ?? ''}`
}

export function createRuntimeEventsStore(dependencies: Dependencies) {
  const listeners = new Set<() => void>()
  let events = emptyEvents
  let fingerprint = runtimeEventsFingerprint(events)
  let session: (Session & { clearsInFlight: number; refreshAfterClear: boolean }) | null = null
  let timer: Timer | null = null
  let generation = 0
  let inFlight = false
  let refreshPending = false

  function publish(next: readonly RuntimeEvent[]) {
    const nextFingerprint = runtimeEventsFingerprint(next)
    if (nextFingerprint === fingerprint) return
    events = next
    fingerprint = nextFingerprint
    listeners.forEach(listener => listener())
  }

  function invalidateRequests() {
    generation++
    inFlight = false
    refreshPending = false
  }

  async function poll() {
    if (!session?.token || !session.canRead || session.clearsInFlight || inFlight) return
    const requestGeneration = generation
    inFlight = true
    try {
      const next = await dependencies.fetchLogs(session.token, '?limit=500')
      if (requestGeneration === generation) publish(next)
    } catch {
      // A failed read leaves the last successful snapshot visible.
    } finally {
      if (requestGeneration === generation) {
        inFlight = false
        if (refreshPending && !session?.clearsInFlight) {
          refreshPending = false
          void poll()
        }
      }
    }
  }

  async function refresh() {
    if (!session?.token || !session.canRead) return
    if (session.clearsInFlight) {
      session.refreshAfterClear = true
    } else if (inFlight) {
      refreshPending = true
    } else {
      refreshPending = false
      await poll()
    }
  }

  function stopSession() {
    session = null
    invalidateRequests()
    if (timer !== null) dependencies.clearInterval(timer)
    timer = null
    publish(emptyEvents)
  }

  function startSession(next: Session) {
    if (session && session.token === next.token && session.userId === next.userId && session.canRead === next.canRead) return
    stopSession()
    const active = { ...next, clearsInFlight: 0, refreshAfterClear: false }
    session = active
    if (active.token && active.canRead) {
      timer = dependencies.setInterval(() => {
        if (session === active) void poll()
      }, 1500)
    }
  }

  async function clearServerEvents(token: string) {
    const active = session?.token === token ? session : null
    if (active) active.clearsInFlight++
    try {
      await dependencies.clearLogs(token)
      if (active && session === active) {
        invalidateRequests()
        publish(emptyEvents)
      }
    } finally {
      if (active && session === active) {
        active.clearsInFlight--
        if (!active.clearsInFlight && (active.refreshAfterClear || refreshPending)) {
          active.refreshAfterClear = false
          void refresh()
        }
      }
    }
  }

  return {
    getSnapshot: () => events,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    startSession,
    stopSession,
    refresh,
    clearServerEvents
  }
}
