import type { DeviceDiagnostics } from '../api/devices'

type Session = { token: string; userId: number; canRead: boolean }
type Adapter = DeviceDiagnostics['adapter']

export type DeviceStatus = Readonly<{
  status: 'idle' | 'loading' | 'ready' | 'error' | 'unauthorized'
  connected: boolean
  stateLabel: string
  transport: string | null
  port: number | null
  activeCapturesCount: number
  lastError: string | null
  generation: number
  updatedAt: number | null
}>

function emptyStatus(generation: number, status: 'idle' | 'unauthorized' = 'idle'): DeviceStatus {
  return {
    status, generation, connected: false, transport: null, port: null, activeCapturesCount: 0,
    stateLabel: status === 'unauthorized' ? '未授权' : '状态未获取', lastError: null, updatedAt: null
  }
}

export function createDeviceStatusStore({ fetchDiagnostics }: {
  fetchDiagnostics: (token: string) => Promise<DeviceDiagnostics>
}) {
  const listeners = new Set<() => void>()
  let snapshot = emptyStatus(0)
  let session: Session | null = null
  let inFlight: Promise<void> | null = null

  function setSnapshot(next: DeviceStatus) {
    snapshot = next
    listeners.forEach(listener => listener())
  }

  function publish(adapter: Adapter, activeCapturesCount = snapshot.activeCapturesCount,
    generation: number | null = snapshot.generation) {
    if (!session?.canRead || generation !== snapshot.generation) return
    const portText = /^COM(\d+)$/i.exec(adapter.port ?? '')
    const transport = adapter.adapter === 'acq-simulator' ? 'simulator'
      : adapter.adapter === 'legacy-ccd-serial' || portText ? 'serial' : null
    const stateLabel = adapter.state === 'error' ? '连接异常'
      : activeCapturesCount > 0 ? '摄谱进行中'
      : adapter.connected ? (adapter.state === 'debugging' ? '调试中' : '已连接') : '未连接'
    setSnapshot({
      status: 'ready', generation, connected: adapter.connected, stateLabel, transport,
      port: portText ? Number(portText[1]) : null, activeCapturesCount,
      lastError: adapter.last_error?.message ?? null, updatedAt: Date.now()
    })
  }

  function publishError(error: unknown) {
    if (!session?.canRead) return
    setSnapshot({ ...snapshot, status: 'error', stateLabel: '诊断读取失败',
      lastError: error instanceof Error ? error.message : '无法读取设备诊断' })
  }

  function refresh(): Promise<void> {
    if (!session?.canRead) return Promise.resolve()
    if (inFlight) return inFlight
    const { token } = session
    const loading: DeviceStatus = { ...snapshot, status: 'loading', stateLabel: '正在读取诊断', lastError: null }
    // Defer the request so a session stopped in the same turn never reaches the API.
    const request = Promise.resolve().then(async () => {
      if (loading.generation !== snapshot.generation) return
      try {
        const next = await fetchDiagnostics(token)
        // A newer operation receipt takes precedence over an in-flight read.
        if (snapshot === loading) publish(next.adapter, next.active_captures?.length ?? 0, loading.generation)
      } catch (error) {
        if (snapshot === loading) publishError(error)
      } finally {
        if (loading.generation === snapshot.generation) inFlight = null
      }
    })
    inFlight = request
    setSnapshot(loading)
    return request
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    getSessionGeneration(token: string) {
      return session?.canRead && session.token === token ? snapshot.generation : null
    },
    startSession(next: Session, refreshOnStart = true) {
      session = { ...next, canRead: next.canRead === true }
      inFlight = null
      setSnapshot(emptyStatus(snapshot.generation + 1, session.canRead ? 'idle' : 'unauthorized'))
      return refreshOnStart ? refresh() : Promise.resolve()
    },
    stopSession() {
      session = null
      inFlight = null
      setSnapshot(emptyStatus(snapshot.generation + 1))
    },
    refresh,
    publish,
    publishError
  }
}
