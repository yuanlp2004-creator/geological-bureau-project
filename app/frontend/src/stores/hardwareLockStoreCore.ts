import type { DeviceDiagnostics, DeviceOccupancy } from '../api/devices'

type Adapter = DeviceDiagnostics['adapter']
type Session = { token: string; userId: number; canRead: boolean }
export type HardwareStatus = 'idle' | 'connected_idle' | 'debugging' | 'turning' | 'capturing' | 'testing' | 'executing' | 'unknown' | 'stop_unconfirmed'
export type HardwareOperation = {
  owner: string
  kind: 'connect' | 'disconnect' | 'debug_start' | 'debug_stop' | 'finish' | 'turn' | 'test' | 'save' | 'remove'
    | 'capture_choose' | 'capture_create' | 'capture_start' | 'capture_preheat' | 'capture_pause' | 'capture_resume' | 'capture_stop'
  profileId?: number | null
  taskId?: number
}
export type OperationToken = Readonly<HardwareOperation>
export type CaptureActivity = { taskId: number; profileId: number; transport: string; state: string }
export type CaptureRecovery = { owner: string; read: () => Promise<CaptureActivity | null> }
type Receipt = {
  adapter?: Adapter
  profileId?: number | null
  turning?: boolean
  portReleased?: boolean
  capture?: CaptureActivity | null
}
type Occupancy = Omit<DeviceOccupancy, 'owner'> & { owner: string }
type Issue = { reason: string; stop?: { owner: string; taskId?: number } }
type LockSnapshot = {
  status: HardwareStatus
  profileId: number | null
  transport: string | null
  port: string | null
  activeOwner: string | null
  operation: OperationToken | null
}

const alignmentStops = new Set(['debug_stop', 'disconnect', 'finish'])
const captureControls = new Set(['capture_choose', 'capture_start', 'capture_pause', 'capture_resume', 'capture_stop'])
const stopErrors = new Set(['motor_stop_unconfirmed', 'serial_stop_unconfirmed', 'capture_stop_unconfirmed'])

export function createHardwareLockStore({ fetchDiagnostics, publishDiagnostics, publishDiagnosticError }: {
  fetchDiagnostics: (token: string) => Promise<DeviceDiagnostics>
  publishDiagnostics?: (diagnostics: DeviceDiagnostics) => void
  publishDiagnosticError?: (error: unknown) => void
}) {
  const listeners = new Set<() => void>()
  let session: Session | null = null
  let adapter: Adapter | null = null
  let occupancy: Occupancy | null = null
  let operation: OperationToken | null = null
  let abandoned: OperationToken | null = null
  let issue: Issue | null = null
  let recovery: CaptureRecovery | undefined
  let inFlight: { snapshot: LockSnapshot; result: Promise<DeviceDiagnostics | null> } | undefined

  function readSnapshot(): LockSnapshot {
    const capture = occupancy && occupancy.owner !== 'alignment' ? occupancy : null
    const state = occupancy?.state ?? adapter?.state
    const status: HardwareStatus = issue?.stop ? 'stop_unconfirmed' : issue ? 'unknown'
      : operation?.kind === 'turn' || state === 'turning' || adapter?.turning ? 'turning'
      : operation?.kind === 'test' || state === 'testing' ? 'testing'
      : state === 'stopping' || state === 'connecting' ? 'executing'
      : capture ? 'capturing'
      : state === 'debugging' ? 'debugging'
      : adapter?.connected ? 'connected_idle' : 'idle'
    return {
      status, operation,
      profileId: occupancy?.profile_id ?? (adapter?.connected ? adapter.profile_id : null) ?? operation?.profileId ?? null,
      port: occupancy?.port ?? (adapter?.connected ? adapter.port : null) ?? null,
      transport: occupancy?.transport ?? (adapter?.connected ? adapter.adapter === 'acq-simulator' ? 'simulator' : 'serial' : null),
      activeOwner: capture?.owner ?? (status === 'turning' || status === 'debugging' ? 'alignment' : null)
    }
  }

  let snapshot = readSnapshot()
  function publish() {
    snapshot = readSnapshot()
    listeners.forEach(listener => listener())
  }

  function reset(next: Session | null) {
    session = next
    adapter = occupancy = operation = abandoned = null
    recovery = inFlight = undefined
    issue = next?.canRead ? { reason: '正在核实设备状态' } : null
    publish()
  }

  function stopIssue(owner: string, taskId: number | null | undefined, reason: string) {
    issue = { reason, stop: { owner: taskId == null ? 'alignment' : owner, taskId: taskId ?? undefined } }
  }

  function setAdapter(next: Adapter, profileId?: number | null) {
    const previousId = adapter?.connected && adapter.adapter === next.adapter ? adapter.profile_id : undefined
    adapter = { ...next, profile_id: next.connected ? next.profile_id ?? profileId ?? previousId : undefined }
    if (next.last_error && stopErrors.has(next.last_error.code)) {
      if (!issue?.stop) stopIssue('alignment', undefined, next.last_error.message)
    } else if (next.connected && !['connected', 'debugging'].includes(next.state) && !next.turning && !issue) {
      issue = { reason: next.last_error?.message ?? '设备连接或停机状态需要核实' }
    }
  }

  function setCapture(owner: string, activity: CaptureActivity | null, taskId?: number) {
    if (occupancy && occupancy.owner !== 'alignment' &&
      (occupancy.owner !== owner || (occupancy.task_id !== taskId && occupancy.task_id !== activity?.taskId))) return
    if (activity) {
      const sameProfile = occupancy?.profile_id === activity.profileId
      occupancy = { owner, task_id: activity.taskId, profile_id: activity.profileId, transport: activity.transport,
        state: activity.state, port: sameProfile ? occupancy?.port ?? null : null }
    } else if (occupancy?.owner === owner) {
      occupancy = null
    }
  }

  function releasePort() {
    if (adapter) adapter = { ...adapter, connected: false, state: 'idle', turning: false, port: undefined, profile_id: undefined }
    if (occupancy?.owner === 'alignment') occupancy = null
  }

  function owns(token: OperationToken) {
    return token === operation
  }

  function blockedReason() {
    if (issue?.stop) return `停机未确认：${issue.reason}。请检查仪器并重试停止。`
    if (issue) return `设备状态待核实：${issue.reason}。请刷新设备状态后再试。`
    if (snapshot.status === 'turning') return '设备正在切换转角，请先完成切角或停止设备。'
    if (snapshot.status === 'debugging') return '设备正在调试，请先停止调试。'
    if (snapshot.status === 'capturing') return '摄谱尚未结束，请完成或停止摄谱后再试。'
    if (snapshot.status === 'testing') return '设备正在进行连接测试，请等待测试结束。'
    return operation || snapshot.status === 'executing' ? '设备操作尚未完成，请稍后再试。' : null
  }

  function canRetryStop(owner: string, taskId?: number) {
    const target = issue?.stop
    if (!target) return false
    if (owner === 'device-connection') return true
    if (target.owner === 'alignment') return owner === 'alignment'
    return target.owner === owner && target.taskId === taskId
  }

  function confirmsStop({ owner, kind, taskId }: HardwareOperation) {
    if (!canRetryStop(owner, taskId)) return false
    if (owner === 'device-connection') return kind === 'disconnect'
    return issue?.stop?.owner === 'alignment' ? alignmentStops.has(kind) : kind === 'capture_stop'
  }

  function acquireOperation(request: HardwareOperation): { ok: true; token: OperationToken } | { ok: false; reason: string } {
    if (!session) return { ok: false, reason: '当前登录会话已结束，请重新登录。' }
    const { owner, kind, taskId, profileId } = request
    const retry = confirmsStop(request)
    const sameTask = occupancy?.owner === owner && occupancy.task_id === taskId
    const stoppingAlignment = alignmentStops.has(kind) &&
      (owner === 'alignment' || owner === 'device-connection') &&
      (snapshot.status === 'turning' || adapter?.turning || abandoned?.kind === 'turn' || kind === 'disconnect') &&
      !issue?.stop && (!operation || !alignmentStops.has(operation.kind) && operation.kind !== 'capture_stop')
    const stoppingCapture = kind === 'capture_stop' && operation?.owner === owner &&
      operation.taskId === taskId && taskId !== undefined && operation.kind !== 'capture_stop' && !issue?.stop
    const interrupt = stoppingAlignment || stoppingCapture
    const controlsCapture = snapshot.status === 'capturing' && captureControls.has(kind) && sameTask
    const controlsDebug = snapshot.status === 'debugging' && owner === 'alignment' && (alignmentStops.has(kind) || kind === 'turn')
    const reason = blockedReason()
    if (reason && !interrupt && (operation || !retry && !controlsCapture && !controlsDebug)) return { ok: false, reason }
    if (snapshot.status === 'connected_idle' && profileId != null && snapshot.profileId != null
      && profileId !== snapshot.profileId && (kind === 'test' || kind.startsWith('capture_')))
      return { ok: false, reason: '当前连接的是其他设备档案，请先断开设备。' }
    const token = { ...request }
    operation = token
    publish()
    return { ok: true, token }
  }

  function reconcile(authToken: string): Promise<DeviceDiagnostics | null> {
    if (!session?.canRead || authToken !== session.token || operation) return Promise.resolve(null)
    if (inFlight?.snapshot === snapshot) return inFlight.result
    const requested = snapshot
    const captureRecovery = recovery
    const result = Promise.resolve().then(async () => {
      if (snapshot !== requested) return null
      try {
        const [diagnostics, recovered] = await Promise.all([fetchDiagnostics(authToken), captureRecovery?.read()])
        if (snapshot !== requested) return null
        if (!abandoned && !issue?.stop) issue = null
        const serverUse = diagnostics.ownership ?? diagnostics.active_captures?.[0]
        if (serverUse) occupancy = { ...serverUse, transport: serverUse.transport ?? 'serial' }
        else if (occupancy?.transport !== 'simulator' || occupancy.owner === 'alignment') occupancy = null
        if (occupancy?.state === 'stop_unconfirmed' && !issue?.stop)
          stopIssue(occupancy.owner, occupancy.task_id, occupancy.last_error?.message ?? '请检查仪器状态')
        setAdapter(diagnostics.adapter)
        if (!abandoned && captureRecovery) {
          if (!serverUse) setCapture(captureRecovery.owner, recovered ?? null, occupancy?.task_id ?? undefined)
          recovery = undefined
        }
        publish()
        publishDiagnostics?.(diagnostics)
        return diagnostics
      } catch (error) {
        if (snapshot === requested) {
          if (!issue?.stop) issue = { reason: error instanceof Error ? error.message : '无法读取设备诊断' }
          publish()
          publishDiagnosticError?.(error)
        }
        return null
      }
    }).finally(() => { if (inFlight?.result === result) inFlight = undefined })
    inFlight = { snapshot: requested, result }
    return result
  }

  function refresh() {
    if (session) void reconcile(session.token)
  }

  function markUnknown(reason: string, captureRecovery?: CaptureRecovery) {
    if (!session) return
    if (operation) abandoned = operation
    operation = null
    if (!issue?.stop) issue = { reason }
    recovery = captureRecovery ?? recovery
    publish()
  }

  function settleAbandoned(token: OperationToken) {
    if (token !== abandoned) return
    abandoned = null
    publish()
    refresh()
  }

  function completeOperation(token: OperationToken, receipt: Receipt = {}) {
    if (!owns(token)) { settleAbandoned(token); return false }
    operation = null
    const stopped = confirmsStop(token) && (receipt.adapter || receipt.capture === null)
    if (stopped) issue = null
    if (receipt.adapter) {
      if (occupancy?.owner === 'alignment' || token.kind === 'disconnect') occupancy = null
      if (alignmentStops.has(token.kind) && abandoned?.kind === 'turn') abandoned = null
      setAdapter(receipt.adapter, receipt.profileId)
    }
    if (receipt.turning !== undefined) {
      if (adapter) adapter = { ...adapter, turning: receipt.turning }
      if (occupancy?.owner === 'alignment' && !receipt.turning) occupancy = null
    }
    if (receipt.portReleased) releasePort()
    if (receipt.capture !== undefined) setCapture(token.owner, receipt.capture, token.taskId)
    publish()
    if (adapter && (receipt.adapter || receipt.portReleased)) publishDiagnostics?.({ adapter, profiles: [] })
    if (issue || token.kind === 'capture_create' || token.kind === 'disconnect') refresh()
    return true
  }

  function markFailure(error: unknown, target?: HardwareOperation, captureRecovery?: CaptureRecovery) {
    const failure = error as { code?: string; message?: string; details?: { reason?: string } } | null
    const reason = failure?.message || '设备操作结果尚未确认'
    if (!issue?.stop && (stopErrors.has(failure?.code ?? '') || stopErrors.has(failure?.details?.reason ?? ''))) {
      const owner = (target?.kind === 'disconnect' ? occupancy?.owner : target?.owner)
        ?? captureRecovery?.owner ?? 'alignment'
      const taskId = target?.taskId ?? (occupancy?.owner === owner ? occupancy.task_id : null)
      stopIssue(owner, taskId, reason)
    }
    markUnknown(reason, captureRecovery)
    refresh()
  }

  function failOperation(token: OperationToken, error: unknown, captureRecovery?: CaptureRecovery) {
    if (!owns(token)) { settleAbandoned(token); return }
    const status = (error as { status?: number } | null)?.status
    if (!status || status === 409 || status >= 500 || alignmentStops.has(token.kind)
      || token.kind === 'capture_stop' || token.kind === 'capture_pause') {
      operation = null
      markFailure(error, token, captureRecovery)
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
      if (session?.token !== authToken || (operation?.owner ?? snapshot.activeOwner) !== owner) return
      markUnknown('硬件页面已离开，正在核实未结束的操作', captureRecovery)
      refresh()
    },
    observation(authToken: string) {
      return session?.token === authToken ? snapshot : null
    },
    recordPortReleased(token: OperationToken, releasedProfileId: number) {
      if (!owns(token) || !adapter?.connected || (snapshot.profileId != null && snapshot.profileId !== releasedProfileId)) return
      releasePort()
      publish()
      publishDiagnostics?.({ adapter, profiles: [] })
    },
    observeFailure(authToken: string, observation: LockSnapshot | null, error: unknown, captureRecovery?: CaptureRecovery) {
      if (observation === snapshot && !operation && session?.token === authToken)
        markFailure(error, undefined, captureRecovery)
    },
    observeCapture(observation: LockSnapshot | null, owner: string, activity: CaptureActivity | null, taskId?: number) {
      if (observation !== snapshot || operation || issue) return
      if (!activity && occupancy?.owner === owner && (taskId === undefined || taskId === occupancy.task_id)) {
        if (occupancy.transport === 'serial') { refresh(); return }
        taskId = occupancy.task_id ?? undefined
      }
      if (activity?.taskId === occupancy?.task_id && activity?.state === occupancy?.state) return
      const previous = occupancy
      setCapture(owner, activity, taskId)
      if (occupancy !== previous) publish()
    }
  }
}
