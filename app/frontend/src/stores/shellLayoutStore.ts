import { useSyncExternalStore } from 'react'
import { createShellLayoutStore, initialShellLayout } from './shellLayoutStoreCore'

export const shellLayoutStore = createShellLayoutStore({
  getItem: key => window.localStorage.getItem(key),
  setItem: (key, value) => window.localStorage.setItem(key, value)
})

function layoutForUser(userId: number) {
  const snapshot = shellLayoutStore.getSnapshot()
  return snapshot.userId === userId ? snapshot : initialShellLayout
}

export function useShellLayout(userId: number) {
  return useSyncExternalStore(shellLayoutStore.subscribe, () => layoutForUser(userId).view)
}

export function useLastSeenEventId(userId: number) {
  return useSyncExternalStore(shellLayoutStore.subscribe, () => layoutForUser(userId).lastSeenEventId)
}
