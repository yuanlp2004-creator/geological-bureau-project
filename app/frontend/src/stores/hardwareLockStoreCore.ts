import type { DeviceDiagnostics } from '../api/devices'

type Adapter = DeviceDiagnostics['adapter']
type ActiveCapture = NonNullable<DeviceDiagnostics['active_captures']>[number]
type Session = { token: string; userId: number; canRead: boolean }
export type HardwareStatus = 'idle' | 'connected_idle' | 'debugging' | 'turning' | 'capturing' | 'testing' | 'unknown'
export type HardwareOperation = {
  owner: string
  kind: 'connect' | 'disconnect' | 'debug_start' | 'debug_stop' | 'finish' | 'turn' | 'test' | 'save' | 'remove'
    | 'capture_choose' | 'capture_create' | 'capture_start' | 'capture_preheat' | 'capture_pause' | 'capture_resume' | 'capture_stop'
  profileId?: number | null
  taskId?: number
}
export type OperationToken = Readonly<HardwareOperation & { id: number; generation: number }>
export type CaptureActivity = {
  taskId: number
  profileId: number
  transport: string
  state: string
}
export type CaptureRecovery = { owner: string; read: () => Promise<CaptureActivity | null> }
type Receipt = {
  adapter?: Adapter
  profileId?: number | null
  turning?: boolean
  portReleased?: boolean
  capture?: CaptureActivity | null
}
type LockSnapshot = Readonly<{
  status: HardwareStatus
  profileId: number | null
  transport: string | null
  port: string | null
  activeCaptures: readonly ActiveCapture[]
  activeOwner: string | null
  unknownReason: string | null
  operation: OperationToken | null
  generation: number
}>

const emergency = new Set(['debug_stop', 'disconnect', 'finish'])
const captureControl = new Set(['capture_choose', 'capture_start', 'capture_pause', 'capture_resume', 'capture_stop'])
const unconfirmedStops = new Set(['motor_stop_unconfirmed', 'serial_stop_unconfirmed', 'capture_stop_unconfirmed'])

function matchesCaptureOwner(serverOwner: string, owner: string) {
  return serverOwner === owner || serverOwner === '色散摄谱' && owner === 'dispersion'
    || serverOwner === '样品 / 蒸发摄谱' && (owner === 'sample-acquisition' || owner === 'evaporation-acquisition')
}

export function createHardwareLockStore({ fetchDiagnostics, publishDiagnostics, publishDiagnosticError }: {
  fetchDiagnostics: (token: string) => Promise<DeviceDiagnostics>
  publishDiagnostics?: (diagnostics: DeviceDiagnostics) => void
  publishDiagnosticError?: (error: unknown) => void
}) {
  const listeners = new Set<() => void>()
  let session: Session | null = null
  let adapter: Adapter | null = null
  let profileId: number | null = null
  let profiles: DeviceDiagnostics['profiles'] = []
  let serverCaptures: readonly ActiveCapture[] = []
  let capture: (CaptureActivity & { owner: string }) | null = null
  let unknownReason: string | null = null
  let operation: OperationToken | null = null
  let abandoned: OperationToken | null = null
  let recovery: CaptureRecovery | undefined
  let unconfirmedStop: { owner: string; kind: 'alignment' | 'capture'; taskId?: number; reason: string } | null = null
  let revision = 0
  let generation = 0
  let nextId = 0
  let inFlight: { revision: number; result: Promise<DeviceDiagnostics | null> } | null = null

  function readSnapshot(): LockSnapshot {
    const currentCapture = capture
    const captureProfile = profiles.find(item => item.id === currentCapture?.profileId)
    const capturePort = captureProfile?.transport === 'serial' ? `COM${captureProfile.port}` : ''
    const activeCaptures = currentCapture && !serverCaptures.some(item => item.task_id === currentCapture.taskId
      && matchesCaptureOwner(item.owner, currentCapture.owner))
      ? [...serverCaptures, { task_id: currentCapture.taskId, owner: currentCapture.owner, port: capturePort, state: currentCapture.state }]
      : serverCaptures
    const status: HardwareStatus = unknownReason ? 'unknown'
      : operation?.kind === 'test' ? 'testing'
      : operation?.kind === 'turn' ? 'turning'
      : activeCaptures.length ? 'capturing'
      : adapter?.turning ? 'turning'
      : adapter?.state === 'debugging' ? 'debugging'
      : adapter?.connected ? 'connected_idle' : 'idle'
    const port = activeCaptures[0]?.port || (adapter?.connected ? adapter.port ?? null : null)
    return {
      status, operation, generation, unknownReason, activeCaptures, port,
      profileId: capture?.profileId ?? serverCaptures[0]?.profile_id ?? profileId ?? operation?.profileId ?? null,
      transport: serverCaptures.length ? 'serial' : capture?.transport
        ?? (adapter?.connected ? adapter.adapter === 'acq-simulator' ? 'simulator' : 'serial' : null),
      activeOwner: capture?.owner ?? (serverCaptures[0]?.owner === '色散摄谱' ? 'dispersion' : serverCaptures[0]?.owner)
        ?? (operation?.kind === 'test' || operation?.kind === 'turn' ? operation.owner
          : adapter?.turning || adapter?.state === 'debugging' ? 'alignment' : null)
    }
  }

  let snapshot = readSnapshot()
  function publish() {
    revision++
    snapshot = readSnapshot()
    listeners.forEach(listener => listener())
  }

  function reset(next: Session | null) {
    session = next
    operation = abandoned = null
    capture = adapter = null
    profileId = null
    profiles = []
    serverCaptures = []
    recovery = undefined
    unconfirmedStop = null
    inFlight = null
    unknownReason = next?.canRead ? '正在核实设备状态' : null
    generation++
    publish()
  }

  function setAdapter(next: Adapter, knownProfileId?: number | null) {
    profileId = next.connected ? next.profile_id ?? knownProfileId
      ?? (adapter?.connected && adapter.adapter === next.adapter ? profileId : null) : null
    adapter = next
    if (next.last_error && unconfirmedStops.has(next.last_error.code)) {
      unconfirmedStop = { owner: 'alignment', kind: 'alignment', reason: next.last_error.message }
      unknownReason = unconfirmedStop.reason
    } else if (next.connected && !['connected', 'debugging'].includes(next.state) && !next.turning) {
      unknownReason = next.last_error?.message || '设备连接或停机状态需要核实'
    }
  }

  function setCapture(owner: string, activity: CaptureActivity | null) {
    if (activity) capture = { ...activity, owner }
    else if (capture?.owner === owner) capture = null
  }

  function forgetServerCapture(owner: string, taskId?: number) {
    serverCaptures = serverCaptures.filter(item => !(item.task_id === taskId && matchesCaptureOwner(item.owner, owner)))
  }

  function releasePort() {
    if (adapter) adapter = { ...adapter, connected: false, state: 'idle', turning: false, port: undefined }
    profileId = null
  }

  function publishAdapter() {
    if (adapter) publishDiagnostics?.({ adapter, profiles, active_captures: [...serverCaptures] })
  }

  function owns(token: OperationToken) {
    return token.id === operation?.id && token.generation === generation
  }

  function blockedReason() {
    if (unknownReason) return `设备状态待核实：${unknownReason}。请刷新设备状态后再试。`
    if (snapshot.status === 'turning') return '设备正在切换转角，请先完成切角或停止设备。'
    if (snapshot.status === 'debugging') return '设备正在调试，请先停止调试。'
    if (snapshot.status === 'capturing') return '摄谱尚未结束，请完成或停止摄谱后再试。'
    if (snapshot.status === 'testing') return '设备正在进行连接测试，请等待测试结束。'
    return operation ? '设备操作尚未完成，请稍后再试。' : null
  }

  function canRetryStop(owner: string, taskId?: number) {
    if (!unconfirmedStop) return false
    return unconfirmedStop.kind === 'alignment' ? owner === 'alignment' || owner === unconfirmedStop.owner
      : owner === unconfirmedStop.owner && taskId === unconfirmedStop.taskId
  }

  function confirmsStop({ owner, kind, taskId }: HardwareOperation) {
    return unconfirmedStop && canRetryStop(owner, taskId)
      && (unconfirmedStop.kind === 'alignment' ? emergency.has(kind) : kind === 'capture_stop')
  }

  function acquireOperation(request: HardwareOperation): { ok: true; token: OperationToken } | { ok: false; reason: string } {
    if (!session) return { ok: false, reason: '当前登录会话已结束，请重新登录。' }
    const { owner, kind } = request
    const stoppingTurn = emergency.has(kind) && (snapshot.status === 'turning' || adapter?.turning === true || abandoned?.kind === 'turn')
      && (!operation || !emergency.has(operation.kind))
    if (operation && !stoppingTurn) return { ok: false, reason: blockedReason()! }
    const sameCapture = capture ? capture.owner === owner && capture.taskId === request.taskId
      : serverCaptures.some(item => item.task_id === request.taskId && matchesCaptureOwner(item.owner, owner))
    const controlsCapture = snapshot.status === 'capturing' && captureControl.has(kind) && sameCapture
    const controlsDebug = snapshot.status === 'debugging' && owner === 'alignment' && (emergency.has(kind) || kind === 'turn')
    const reason = blockedReason()
    if (reason && !stoppingTurn && !controlsCapture && !controlsDebug && !confirmsStop(request)) return { ok: false, reason }
    if (snapshot.status === 'connected_idle' && request.profileId != null && profileId != null
      && request.profileId !== profileId && (kind === 'test' || kind.startsWith('capture_')))
      return { ok: false, reason: '当前连接的是其他设备档案，请先断开设备。' }
    const token = Object.freeze({ ...request, id: ++nextId, generation })
    operation = token
    publish()
    return { ok: true, token }
  }

  function reconcile(authToken: string): Promise<DeviceDiagnostics | null> {
    if (!session?.canRead || authToken !== session.token || operation) return Promise.resolve(null)
    if (inFlight?.revision === revision) return inFlight.result
    const requested = revision
    const recoverCapture = recovery
    const result = Promise.resolve().then(async () => {
      if (revision !== requested) return null
      try {
        const [diagnostics, activity] = await Promise.all([fetchDiagnostics(authToken), recoverCapture?.read()])
        if (revision !== requested) return null
        if (!abandoned) {
          unknownReason = unconfirmedStop?.reason ?? null
          recovery = undefined
        }
        profiles = diagnostics.profiles
        const simulators = profiles.filter(item => item.enabled && item.transport === 'simulator')
        setAdapter(diagnostics.adapter, simulators.length === 1 ? simulators[0].id : undefined)
        serverCaptures = diagnostics.active_captures ?? []
        if (recoverCapture && !abandoned) setCapture(recoverCapture.owner, activity ?? null)
        publish()
        publishDiagnostics?.(diagnostics)
        return diagnostics
      } catch (error) {
        if (revision === requested) {
          unknownReason = error instanceof Error ? error.message : '无法读取设备诊断'
          publish()
          publishDiagnosticError?.(error)
        }
        return null
      }
    }).finally(() => { if (inFlight?.result === result) inFlight = null })
    inFlight = { revision: requested, result }
    return result
  }

  function markUnknown(reason: string, captureRecovery?: CaptureRecovery) {
    if (!session) return
    if (operation) abandoned = operation
    operation = null
    unknownReason = reason
    recovery = captureRecovery ?? recovery
    generation++
    publish()
  }

  function settleAbandoned(token: OperationToken) {
    if (token.id !== abandoned?.id || token.generation !== abandoned.generation) return
    abandoned = null
    publish()
    if (session) void reconcile(session.token)
  }

  function completeOperation(token: OperationToken, receipt: Receipt = {}) {
    if (!owns(token)) { settleAbandoned(token); return false }
    operation = null
    if ((receipt.adapter || receipt.capture === null) && confirmsStop(token)) {
      unconfirmedStop = null
      unknownReason = null
    }
    if (emergency.has(token.kind) && receipt.adapter && abandoned?.kind === 'turn') abandoned = null
    if (receipt.adapter) setAdapter(receipt.adapter, receipt.profileId)
    if (receipt.turning !== undefined && adapter) adapter = { ...adapter, turning: receipt.turning }
    if (receipt.capture !== undefined) {
      // A task receipt supersedes diagnostics for that task, but preserves other owners' reservations.
      const taskId = capture?.owner === token.owner ? capture.taskId : token.taskId
      forgetServerCapture(token.owner, taskId)
      setCapture(token.owner, receipt.capture)
    }
    if (receipt.portReleased) releasePort()
    publish()
    if (receipt.adapter || receipt.portReleased) publishAdapter()
    if (unknownReason && session) void reconcile(session.token)
    return true
  }

  function failOperation(token: OperationToken, error: unknown, captureRecovery?: CaptureRecovery) {
    if (!owns(token)) { settleAbandoned(token); return }
    const failure = error as { status?: number; code?: string; message?: string; details?: { reason?: string } } | null
    const status = failure?.status
    if (status === undefined || status === 0 || status === 409 || status >= 500
      || emergency.has(token.kind) || token.kind === 'capture_stop' || token.kind === 'capture_pause'
      || failure?.code === 'device_busy') {
      const reason = failure?.message || '设备操作结果尚未确认'
      if (unconfirmedStops.has(failure?.code ?? '') || unconfirmedStops.has(failure?.details?.reason ?? '')) {
        unconfirmedStop = { owner: token.owner, kind: token.kind.startsWith('capture_') ? 'capture' : 'alignment',
          taskId: token.taskId, reason }
      }
      operation = null
      markUnknown(reason, captureRecovery)
      if (session) void reconcile(session.token)
    } else completeOperation(token)
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    startSession(next: Session) {
      reset(next)
      return reconcile(next.token)
    },
    stopSession: () => reset(null),
    blockedReason,
    canRetryStop,
    acquireOperation,
    owns,
    completeOperation,
    failOperation,
    markUnknown,
    reconcile,
    abandonOwner(authToken: string, owner: string, captureRecovery?: CaptureRecovery) {
      if (session?.token !== authToken) return
      if (operation?.owner !== owner && snapshot.activeOwner !== owner) return
      if (operation && operation.owner !== owner) return
      markUnknown('硬件页面已离开，正在核实未结束的操作', captureRecovery)
      void reconcile(authToken)
    },
    observation(authToken: string) {
      return session?.token === authToken ? revision : null
    },
    recordPortReleased(token: OperationToken, releasedProfileId: number) {
      if (!owns(token) || !(adapter?.connected && (profileId === null || profileId === releasedProfileId))) return
      releasePort()
      publish()
      publishAdapter()
    },
    observeFailure(authToken: string, observation: number | null, error: unknown, captureRecovery?: CaptureRecovery) {
      if (observation !== revision || operation || session?.token !== authToken) return
      markUnknown(error instanceof Error ? error.message : '设备状态尚未确认', captureRecovery)
      void reconcile(authToken)
    },
    observeCapture(observation: number | null, owner: string, activity: CaptureActivity | null, taskId?: number) {
      if (observation !== revision || operation || unknownReason) return
      if (activity && capture && capture.owner !== owner) return
      if (!activity) {
        const count = serverCaptures.length
        if (taskId !== undefined) forgetServerCapture(owner, taskId)
        const matches = capture?.owner === owner && (taskId === undefined || capture.taskId === taskId)
        if (!matches && count === serverCaptures.length) return
        if (matches) setCapture(owner, null)
        publish()
        return
      }
      if (activity && capture?.taskId === activity.taskId && capture.state === activity.state) return
      setCapture(owner, activity)
      publish()
    }
  }
}
