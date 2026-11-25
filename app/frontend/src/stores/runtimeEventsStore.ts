import { useSyncExternalStore } from 'react'
import { api } from '../api'
import { createRuntimeEventsStore } from './runtimeEventsStoreCore'

export { createRuntimeEventsStore, runtimeEventsFingerprint } from './runtimeEventsStoreCore'

export const runtimeEventsStore = createRuntimeEventsStore({
  fetchLogs: api.logs,
  clearLogs: api.clearLogs,
  setInterval: (callback, delay) => window.setInterval(callback, delay),
  clearInterval: timer => window.clearInterval(timer)
})

export function useRuntimeEvents() {
  return useSyncExternalStore(runtimeEventsStore.subscribe, runtimeEventsStore.getSnapshot)
}

export default runtimeEventsStore
