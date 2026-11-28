import { AdvancedSettings } from '../../components/AdvancedSettings'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Cable, PlayCircle, RefreshCw, Square, XCircle } from 'lucide-react'
import { api, type DeviceDiagnostics, type DeviceEvent } from '../../api'
import type { DeviceDebugTurn } from '../../api/devices'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { PageFileActions } from '../../components/PageFileActions'
import { acquireHardwareOperation, hardwareLockStore, useHardwareLock, useHardwareOwner } from '../../stores/hardwareLockStore'
import type { OperationToken } from '../../stores/hardwareLockStoreCore'
import { AlignmentMonitor } from './AlignmentMonitor'
import { ensureCaptureConnection } from '../acquisition/captureConnection'

type AcquisitionPageProps = {
  token: string; canExecute: boolean; onToast: (message: string) => void
  revision?: number; actionsTarget?: HTMLElement | null; active?: boolean
  preferredProfileId?: number
}
const SAMPLE_OPTIONS = ['280-288.acq', '291-299.acq', '303-310.acq']
const owner = 'alignment'

export function AcquisitionPage({ token, canExecute, onToast, revision = 0, actionsTarget, active = true,
  preferredProfileId }: AcquisitionPageProps) {
  useHardwareOwner(token, owner, active)
  const hardware = useHardwareLock()
  const stopUnconfirmed = hardware.status === 'stop_unconfirmed' && hardwareLockStore.canRetryStop(owner)
  const [diagnostics, setDiagnostics] = useState<DeviceDiagnostics | null>(null)
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null)
  const [event, setEvent] = useState<DeviceEvent | null>(null)
  const [observed, setObserved] = useState<{ profileId: number; frame: DeviceEvent } | null>(null)
  const lastFrame = observed && observed.profileId === selectedProfile ? observed.frame : null
  const lastCcds = lastFrame?.ccds ?? []
  const [sample, setSample] = useState(SAMPLE_OPTIONS[0])
  const [seed, setSeed] = useState(11)
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [controlling, setControlling] = useState(false)
  const [turn, setTurn] = useState<DeviceDebugTurn | null>(null)
  const [targetAngle, setTargetAngle] = useState<number | null>(null)
  const [switching, setSwitching] = useState(false)
  const runningRef = useRef(false)
  const profileRef = useRef<number | null>(null)
  const sessionRef = useRef<string | null>(null)
  const commandInFlight = useRef(false)
  const stepInFlight = useRef(false)
  const stepTimer = useRef<number | null>(null)
  const turnSnapshot = useRef<DeviceDebugTurn | null>(null)
  const switchInFlight = useRef(false)
  const turnRevision = useRef(0)
  const turnRead = useRef(0)
  const frameRevision = useRef(0)
  const diagnosticRead = useRef(0)
  const debugParameters = useRef<HTMLDivElement>(null)
  const clearStepTimer = () => {
    if (stepTimer.current !== null) window.clearInterval(stepTimer.current)
    stepTimer.current = null
  }
  const remember = useCallback((next: DeviceEvent, profileId?: number | null) => {
    setEvent(next)
    if (profileId != null && next.ccds.some(ccd => ccd.points?.length)) setObserved({ profileId, frame: next })
  }, [])
  const showTurn = useCallback((next: DeviceDebugTurn) => {
    if (next.profile_id !== profileRef.current) return
    const previous = turnSnapshot.current
    if (previous?.profile_id === next.profile_id
        && (next.current_angle_deg !== previous.current_angle_deg || next.moving && !previous.moving)) {
      frameRevision.current++
      setObserved(null)
    }
    turnSnapshot.current = next
    setTurn(next)
  }, [])
  const refreshTurn = useCallback(async () => {
    const read = ++turnRead.current
    try {
      const next = await api.deviceDebugTurn(token)
      if (read === turnRead.current) showTurn(next)
    } catch {
      if (read !== turnRead.current) return
      turnSnapshot.current = null
      setTurn(null)
    }
  }, [showTurn, token])
  const load = useCallback(async () => {
    const read = ++diagnosticRead.current
    setLoading(true)
    try {
      const [next, currentProfile] = await Promise.all([hardwareLockStore.reconcile(token), api.currentDeviceProfile(token)])
      if (!next || read !== diagnosticRead.current || hardwareLockStore.getSnapshot().operation) return
      setDiagnostics(next)
      const live = next.adapter.connected && next.adapter.state === 'debugging'
      setRunning(live); runningRef.current = live
      sessionRef.current = live ? next.adapter.session_id : null
      setEvent(current => current ? { ...current, state: next.adapter.state } : null)
      const profileId = next.adapter.connected && next.adapter.adapter !== 'acq-simulator'
        ? next.adapter.profile_id ?? null : currentProfile?.id ?? null
      if (profileId !== profileRef.current) {
        turnSnapshot.current = null
        setTurn(null)
        setTargetAngle(null)
      }
      profileRef.current = profileId
      setSelectedProfile(profileId)
      await refreshTurn()
    } catch (error) {
      if (read === diagnosticRead.current) onToast(error instanceof Error ? error.message : '无法读取设备诊断')
    } finally {
      if (read === diagnosticRead.current) setLoading(false)
    }
  }, [onToast, token, preferredProfileId, refreshTurn])

  useEffect(() => {
    if (active) void load()
    return () => { diagnosticRead.current++; frameRevision.current++; turnRead.current++ }
  }, [load, revision, active])
  useEffect(() => {
    if (!active || !turn?.moving || switching) return
    const timer = window.setTimeout(() => void load(), 650)
    return () => window.clearTimeout(timer)
  }, [active, load, switching, turn])
  useEffect(() => {
    if (!running || !active) return
    if (controlling) return
    stepTimer.current = window.setInterval(() => {
      if (stepInFlight.current || !runningRef.current || switchInFlight.current || turnSnapshot.current?.moving) return
      const hardware = hardwareLockStore.getSnapshot()
      if (hardware.operation || hardware.status !== 'debugging') return
      stepInFlight.current = true
      const observation = hardwareLockStore.observation(token)
      const profileId = profileRef.current
      const sessionId = sessionRef.current
      const frameVersion = frameRevision.current
      void api
        .stepDeviceDebug(token)
        .then((result) => {
          if (!runningRef.current || profileId !== profileRef.current || sessionId !== sessionRef.current || frameVersion !== frameRevision.current) return
          const confirmed = turnSnapshot.current?.current_angle_deg
          if (result.diagnostics.turning || (result.event.ccds.length > 0 && confirmed != null && result.event.details.angle_deg !== confirmed)) {
            void refreshTurn()
            return
          }
          sessionRef.current = result.session_id
          remember(result.event, result.diagnostics.profile_id ?? (result.diagnostics.adapter === 'acq-simulator' ? profileId : null))
          setDiagnostics((current) => (current ? { ...current, adapter: result.diagnostics } : current))
          if (result.event.event_type === 'fault') {
            runningRef.current = false
            setRunning(false)
            hardwareLockStore.observeFailure(token, observation, new Error('CCD 故障，调试已停止'))
            onToast('CCD 故障，调试已停止并保留诊断信息')
          }
        })
        .catch(async (error) => {
          if (!runningRef.current || frameVersion !== frameRevision.current) return
          runningRef.current = false
          setRunning(false)
          hardwareLockStore.observeFailure(token, observation, error)
          await load()
          onToast(error instanceof Error ? error.message : '实时调试连接失败')
        })
        .finally(() => {
          stepInFlight.current = false
        })
    }, 850)
    return clearStepTimer
  }, [active, controlling, onToast, remember, running, token, load, refreshTurn])

  const profile = diagnostics?.profiles.find((item) => item.id === selectedProfile)
  const activeTurn = turn?.profile_id === profile?.id ? turn : null
  const turning = switching || hardware.status === 'turning' || Boolean(activeTurn?.moving || diagnostics?.adapter.turning)
  const selectedAngle = targetAngle != null && activeTurn?.angles.includes(targetAngle) ? targetAngle : null
  const canChooseAngle = Boolean(canExecute && profile && diagnostics?.adapter.connected
    && ['connected', 'debugging'].includes(diagnostics.adapter.state) && activeTurn?.angles.length && !loading && !controlling && !turning)
  const switchTurn = async () => {
    if (!canChooseAngle || !profile || selectedAngle === null || selectedAngle === activeTurn?.current_angle_deg
        || commandInFlight.current || switchInFlight.current) return
    const operation = acquireHardwareOperation({ owner, kind: 'turn', profileId: profile.id }, onToast)
    if (!operation) return
    switchInFlight.current = true
    const request = ++turnRevision.current
    turnRead.current++
    frameRevision.current++
    setObserved(null)
    setSwitching(true)
    try {
      const next = await api.switchDeviceDebugTurn(token, profile.id, selectedAngle)
      if (hardwareLockStore.completeOperation(operation, { turning: next.moving })
        && request === turnRevision.current && profileRef.current === profile.id) {
        showTurn(next)
        setTargetAngle(null)
        if (!next.moving && next.current_angle_deg === selectedAngle) onToast(`转角 ${selectedAngle}° 已到位`)
      }
    } catch (error) {
      const current = hardwareLockStore.owns(operation)
      hardwareLockStore.failOperation(operation, error)
      if (current && request === turnRevision.current) {
        if (turnSnapshot.current?.profile_id === profile.id) showTurn({ ...turnSnapshot.current, current_angle_deg: null })
        onToast(error instanceof Error ? error.message : '切换转角失败')
      }
    } finally {
      if (!commandInFlight.current) await load()
      switchInFlight.current = false
      setSwitching(false)
    }
  }
  const applyReceipt = (operation: OperationToken, result: { diagnostics: DeviceDiagnostics['adapter']; event: DeviceEvent },
    profileId?: number | null) => {
    if (!hardwareLockStore.completeOperation(operation, { adapter: result.diagnostics, profileId })) return false
    setDiagnostics(current => current ? { ...current, adapter: result.diagnostics } : current)
    remember(result.event, profileId)
    return true
  }
  const connect = async () => {
    if (!canExecute) return onToast('当前账户没有设备执行权限')
    if (commandInFlight.current) return
    const operation = acquireHardwareOperation({ owner, kind: 'connect', profileId: profileRef.current }, onToast)
    if (!operation) return
    commandInFlight.current = true; setControlling(true)
    diagnosticRead.current++
    try {
      const profile = await api.currentDeviceProfile(token)
      if (!hardwareLockStore.owns(operation)) { hardwareLockStore.completeOperation(operation); return }
      profileRef.current = profile?.id ?? null
      setSelectedProfile(profile?.id ?? null)
      if (!profile) throw new Error('请先在设备参数中选择通讯口，或勾选模拟设备用于测试')
      setObserved(null)
      await ensureCaptureConnection(token, profile.id, profile.transport, 'devices')
      if (!hardwareLockStore.owns(operation)) { hardwareLockStore.completeOperation(operation); return }
      const result = await api.connectDevice(token, profile.id)
      if (!applyReceipt(operation, result, result.profile.id)) return
      await refreshTurn()
      onToast(profile.transport === 'serial' ? '串口已打开，开始调试后确认仪器响应' : '模拟设备已连接')
    } catch (error) {
      hardwareLockStore.failOperation(operation, error)
      await load()
      onToast(error instanceof Error ? error.message : '设备连接失败')
    } finally {
      commandInFlight.current = false; setControlling(false)
    }
  }
  const start = async () => {
    if (!canExecute) return onToast('当前账户没有设备执行权限')
    if (!reportInvalidNumericInput(debugParameters.current)) return onToast('请先修正调试参数')
    if (commandInFlight.current) return
    const operation = acquireHardwareOperation({ owner, kind: 'debug_start', profileId: profileRef.current }, onToast)
    if (!operation) return
    commandInFlight.current = true; setControlling(true)
    diagnosticRead.current++
    try {
      const result = await api.startDeviceDebug(token, { sample, seed })
      setObserved(null)
      if (!applyReceipt(operation, result, result.diagnostics.profile_id ?? (result.diagnostics.adapter === 'acq-simulator' ? profileRef.current : null))) return
      sessionRef.current = result.session_id
      runningRef.current = true
      setRunning(true)
      onToast('实时调试已开始，数据不会写入样品记录')
    } catch (error) {
      hardwareLockStore.failOperation(operation, error)
      await load()
      onToast(error instanceof Error ? error.message : '无法启动实时调试')
    } finally {
      commandInFlight.current = false; setControlling(false)
    }
  }
  const shutdown = async (kind: 'debug_stop' | 'disconnect' | 'finish') => {
    if (!canExecute || commandInFlight.current) return
    const operation = acquireHardwareOperation({ owner, kind, profileId: profileRef.current }, onToast)
    if (!operation) return
    commandInFlight.current = true; setControlling(true)
    clearStepTimer()
    runningRef.current = false
    setRunning(false)
    frameRevision.current++
    diagnosticRead.current++
    setLoading(false)
    turnRevision.current++
    turnRead.current++
    try {
      if (kind === 'debug_stop' || kind === 'finish' && (running || hardware.status === 'debugging' || turning || stopUnconfirmed)) {
        const stopped = await api.stopDeviceDebug(token)
        if (stopped.diagnostics.turning || ['debugging', 'error'].includes(stopped.diagnostics.state))
          throw new Error('停止调试结果尚未确认')
        if (kind === 'debug_stop') {
          if (!applyReceipt(operation, stopped)) return
          await refreshTurn()
          onToast('调试已停止，未生成样品/谱图记录')
          return
        }
        if (!hardwareLockStore.owns(operation)) { hardwareLockStore.completeOperation(operation); return }
      }
      const result = await api.disconnectDevice(token)
      if (result.diagnostics.connected || result.diagnostics.turning || result.diagnostics.state === 'error')
        throw new Error('设备断开结果尚未确认')
      if (!applyReceipt(operation, result)) return
      await refreshTurn()
      onToast(kind === 'finish' ? '调试已结束，设备已断开' : '设备已断开')
    } catch (error) {
      hardwareLockStore.failOperation(operation, error)
      await load()
      onToast(error instanceof Error ? error.message : '设备停机失败，请重试停止或断开')
    }
    finally { commandInFlight.current = false; setControlling(false) }
  }
  const indices = profile?.ccd_indices ?? lastCcds.map(item => item.ccd_index)
  return <div className="page-content acquisition-page refined-page remaining-page" data-testid="acquisition-page">
    <PageFileActions target={actionsTarget} hidden={!active}>
      <button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''}/>刷新诊断</button>
    </PageFileActions>
    <AlignmentMonitor key={`${profile?.id}:${indices.join(',')}`} indices={indices} frame={lastFrame} profile={profile} active={active}
      turnControl={<div className="alignment-turn-control">
        <select aria-label="目标转角" value={selectedAngle ?? ''} disabled={!canChooseAngle}
          onChange={event => setTargetAngle(event.target.value ? Number(event.target.value) : null)}>
          <option value="">{activeTurn?.angles.length ? '选转角' : '无可选转角'}</option>
          {activeTurn?.angles.map(angle => <option key={angle} value={angle}>{angle}°</option>)}
        </select>
        <button type="button" className="secondary-button" disabled={!canChooseAngle || selectedAngle === null || selectedAngle === activeTurn?.current_angle_deg}
          onClick={() => void switchTurn()}>切换转角</button>
        <span className="alignment-turn-status" aria-live="polite">{diagnostics?.adapter.connected && turning ? '正在切换转角' :
          diagnostics?.adapter.connected && activeTurn?.current_angle_deg != null ? `当前转角 ${activeTurn.current_angle_deg}°` : '当前转角 --'}</span>
      </div>}
      canFinish={canExecute && !controlling && Boolean(running || diagnostics?.adapter.connected || stopUnconfirmed)} finish={() => shutdown('finish')}
      connection={<>
        <button className="secondary-button" onClick={() => void connect()} disabled={!canExecute || !profile || controlling || turning || Boolean(diagnostics?.adapter.connected)}><Cable size={15}/>连接诊断</button>
        <button className="secondary-button" onClick={() => void start()} disabled={!canExecute || controlling || turning || running || !diagnostics?.adapter.connected || diagnostics.adapter.state !== 'connected'}><PlayCircle size={15}/>开始</button>
        <button className="secondary-button" onClick={() => void shutdown('debug_stop')} disabled={!canExecute || controlling || !(running || turning || stopUnconfirmed)}><Square size={15}/>停止</button>
        <button className="secondary-button" onClick={() => void shutdown('disconnect')} disabled={!canExecute || controlling || !(diagnostics?.adapter.connected || stopUnconfirmed)}><XCircle size={15}/>断开</button>
        <details className="alignment-settings"><summary>调试设置</summary><div ref={debugParameters} className="alignment-settings-content">
          <p>{profile?.transport === 'simulator' ? '模拟设备 · 仅用于软件验证' : '真实串口设备'}</p>
          {profile?.transport === 'simulator' && <AdvancedSettings title="模拟调试"><div className="device-debug-fields">
            <label className="field"><span>模拟样本</span><select value={sample} onChange={e => setSample(e.target.value)} disabled={running || controlling}>
              {SAMPLE_OPTIONS.map(item => <option key={item}>{item}</option>)}
            </select></label>
            <label className="field"><span>随机种子</span><NumericInput min={0} max={2_147_483_647} value={seed} onValueChange={setSeed} disabled={running || controlling}/></label>
          </div></AdvancedSettings>}
          {profile && <dl><div><dt>串口 / 波特率</dt><dd>COM {profile.port} / {profile.baud_rate.toLocaleString()}</dd></div>
            <div><dt>CCD 布局</dt><dd>{profile.frame_count} 组 × {profile.ccds_per_frame} / {profile.points_per_ccd} 点</dd></div>
            <div><dt>屏幕换算</dt><dd>{profile.screen_conversion.pixels_per_mm.toFixed(2)} px/mm</dd></div></dl>}
        </div></details>
      </>}
      footer={<>
        <span>状态：{diagnostics?.adapter.state ?? event?.state ?? '未连接'}</span>
        {event?.event_type === 'fault' && <span role="alert" className="alignment-error">{event.message} · {String(event.details.code ?? 'unknown')}</span>}
        <span>帧序：{lastFrame?.frame_index == null ? '--' : lastFrame.frame_index + 1}</span>
        <span title={lastFrame?.details.sha256}>帧哈希：{lastFrame?.details.sha256?.slice(0, 16) ?? '--'}</span>
        <span>0 样品 · 0 谱图</span>
      </>}/>
  </div>
}
