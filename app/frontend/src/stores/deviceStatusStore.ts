import { useSyncExternalStore } from 'react'
import { api } from '../api'
import { createDeviceStatusStore } from './deviceStatusStoreCore'

export const deviceStatusStore = createDeviceStatusStore({ fetchDiagnostics: api.deviceDiagnostics })

export function useDeviceStatus() {
  return useSyncExternalStore(deviceStatusStore.subscribe, deviceStatusStore.getSnapshot)
}
