import { useLayoutEffect, useSyncExternalStore } from 'react'
import { api } from '../api'
import { deviceStatusStore } from './deviceStatusStore'
import { createHardwareLockStore, type CaptureRecovery, type HardwareOperation } from './hardwareLockStoreCore'

export const hardwareLockStore = createHardwareLockStore({
  fetchDiagnostics: api.deviceDiagnostics,
  publishDiagnostics: diagnostics => deviceStatusStore.publish(diagnostics.adapter, diagnostics.active_captures?.length ?? 0),
  publishDiagnosticError: deviceStatusStore.publishError
})

export function useHardwareLock() {
  return useSyncExternalStore(hardwareLockStore.subscribe, hardwareLockStore.getSnapshot)
}

export function useHardwareStopRetry(owner: string, taskId?: number) {
  const { status } = useHardwareLock()
  return status === 'stop_unconfirmed' && hardwareLockStore.canRetryStop(owner, taskId)
}

export function useHardwareOwner(token: string, owner: string, active: boolean, recovery?: CaptureRecovery) {
  useLayoutEffect(() => {
    if (active) return () => hardwareLockStore.abandonOwner(token, owner, recovery)
  }, [token, owner, active, recovery])
}

export function acquireHardwareOperation(request: HardwareOperation, onBlocked: (reason: string) => void) {
  const result = hardwareLockStore.acquireOperation(request)
  if (result.ok) return result.token
  onBlocked(result.reason)
  return null
}
