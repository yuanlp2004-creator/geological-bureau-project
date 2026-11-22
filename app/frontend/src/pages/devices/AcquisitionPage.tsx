import { AdvancedSettings } from '../../components/AdvancedSettings'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Cable, PlayCircle, RefreshCw, Square, XCircle } from 'lucide-react'
import { api, type DeviceDiagnostics, type DeviceEvent } from '../../api'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { PageFileActions } from '../../components/PageFileActions'
import { AlignmentMonitor } from './AlignmentMonitor'
import { ensureCaptureConnection } from '../acquisition/captureConnection'

type AcquisitionPageProps = {
  token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void
  embedded?: boolean; revision?: number; actionsTarget?: HTMLElement | null; active?: boolean
  preferredProfileId?: number
}
const SAMPLE_OPTIONS = ['280-288.acq', '291-299.acq', '303-310.acq']

export function AcquisitionPage({ token, canExecute, onToast, revision = 0, actionsTarget, active = true, preferredProfileId }: AcquisitionPageProps) {
  const [diagnostics, setDiagnostics] = useState<DeviceDiagnostics | null>(null)
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null)
  const [event, setEvent] = useState<DeviceEvent | null>(null)
  const [lastFrame, setLastFrame] = useState<DeviceEvent | null>(null)
  const lastCcds = lastFrame?.ccds ?? []
  const [sample, setSample] = useState(SAMPLE_OPTIONS[0])
  const [seed, setSeed] = useState(11)
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [controlling, setControlling] = useState(false)
  const runningRef = useRef(false)
  const commandInFlight = useRef(false)
  const stepInFlight = useRef(false)
  const debugParameters = useRef<HTMLDivElement>(null)
  useEffect(() => { setLastFrame(null); setEvent(null) }, [selectedProfile])
  const remember = useCallback((next: DeviceEvent) => {
    setEvent(next)
    if (next.ccds.some(ccd => ccd.points?.length)) setLastFrame(next)
  }, [])
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [next, currentProfile] = await Promise.all([api.deviceDiagnostics(token), api.currentDeviceProfile(token)])
      setDiagnostics(next)
      const live = next.adapter.connected && next.adapter.state === 'debugging'
      setRunning(live); runningRef.current = live
      setEvent(current => current ? { ...current, state: next.adapter.state } : null)
      setSelectedProfile(next.adapter.connected ? next.adapter.profile_id ?? null : currentProfile?.id ?? null)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取设备诊断')
    } finally {
      setLoading(false)
    }
  }, [onToast, token, preferredProfileId])

  useEffect(() => {
    if (active) void load()
  }, [load, revision, active])
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      if (stepInFlight.current || !runningRef.current) return
      stepInFlight.current = true
      void api
        .stepDeviceDebug(token)
        .then((result) => {
          if (!runningRef.current) return
          remember(result.event)
          setDiagnostics((current) => (current ? { ...current, adapter: result.diagnostics } : current))
          if (result.event.event_type === 'fault') {
            runningRef.current = false
            setRunning(false)
            onToast('CCD 故障，调试已停止并保留诊断信息')
          }
        })
        .catch(async (error) => {
          if (!runningRef.current) return
          runningRef.current = false
          setRunning(false)
          await load()
          runningRef.current = false
          onToast(error instanceof Error ? error.message : '实时调试连接失败')
        })
        .finally(() => {
          stepInFlight.current = false
        })
    }, 850)
    return () => {
      window.clearInterval(timer)
      stepInFlight.current = false
    }
  }, [onToast, remember, running, token, load])

  const profile = diagnostics?.profiles.find((item) => item.id === selectedProfile)
  const connect = async () => {
    if (!canExecute) return onToast('当前账户没有设备执行权限')
    if (commandInFlight.current) return
    commandInFlight.current = true; setControlling(true)
    try {
      const profile = await api.currentDeviceProfile(token)
      setSelectedProfile(profile?.id ?? null)
      if (!profile) throw new Error('请先在设备参数中选择通讯口，或勾选模拟设备用于测试')
      await ensureCaptureConnection(token, profile.id, profile.transport, 'devices')
      const result = await api.connectDevice(token, profile.id)
      setDiagnostics((current) => (current ? { ...current, adapter: result.diagnostics } : current))
      remember(result.event)
      onToast(profile.transport === 'serial' ? '串口已打开，开始调试后确认仪器响应' : '模拟设备已连接')
    } catch (error) {
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
    commandInFlight.current = true; setControlling(true)
    try {
      const result = await api.startDeviceDebug(token, { sample, seed })
      remember(result.event)
      runningRef.current = true
      setRunning(true)
      setDiagnostics((current) => (current ? { ...current, adapter: result.diagnostics } : current))
      onToast('实时调试已开始，数据不会写入样品记录')
    } catch (error) {
      await load()
      onToast(error instanceof Error ? error.message : '无法启动实时调试')
    } finally {
      commandInFlight.current = false; setControlling(false)
    }
  }
  const stop = async () => {
    if (commandInFlight.current) return
    commandInFlight.current = true; setControlling(true)
    runningRef.current = false
    try {
      const result = await api.stopDeviceDebug(token)
      setRunning(false)
      remember(result.event)
      setDiagnostics((current) => (current ? { ...current, adapter: result.diagnostics } : current))
      onToast('调试已停止，未生成样品/谱图记录')
    } catch (error) {
      await load(); runningRef.current = false
      onToast(error instanceof Error ? error.message : '停止调试失败')
    } finally {
      commandInFlight.current = false; setControlling(false)
    }
  }
  const disconnect = async () => {
    if (commandInFlight.current) return
    commandInFlight.current = true; setControlling(true)
    runningRef.current = false
    try {
      const result = await api.disconnectDevice(token)
      setRunning(false)
      remember(result.event)
      setDiagnostics((current) => (current ? { ...current, adapter: result.diagnostics } : current))
      onToast('设备已断开')
    } catch (error) {
      await load()
      onToast(error instanceof Error ? error.message : '设备断开失败')
    } finally {
      commandInFlight.current = false; setControlling(false)
    }
  }
  const finish = async () => {
    if (!canExecute || commandInFlight.current) return
    commandInFlight.current = true; setControlling(true); runningRef.current = false
    try {
      if (running) { await api.stopDeviceDebug(token); setRunning(false) }
      const result = await api.disconnectDevice(token)
      remember(result.event)
      setDiagnostics(current => current ? { ...current, adapter: result.diagnostics } : current)
      onToast('调试已结束，设备已断开')
    } catch (error) { await load(); onToast(error instanceof Error ? error.message : '结束调试失败，请重试停止或断开') }
    finally { commandInFlight.current = false; setControlling(false) }
  }
  const indices = profile?.ccd_indices ?? lastCcds.map(item => item.ccd_index)
  return <div className="page-content acquisition-page refined-page remaining-page" data-testid="acquisition-page">
    <PageFileActions target={actionsTarget} hidden={!active}>
      <button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''}/>刷新诊断</button>
    </PageFileActions>
    <AlignmentMonitor key={`${profile?.id}:${indices.join(',')}`} indices={indices} ccds={lastCcds} profile={profile} active={active}
      canFinish={canExecute && !controlling && Boolean(running || diagnostics?.adapter.connected)} finish={finish}
      connection={<>
        <button className="secondary-button" onClick={() => void connect()} disabled={!canExecute || !profile || controlling || Boolean(diagnostics?.adapter.connected)}><Cable size={15}/>连接诊断</button>
        <button className="secondary-button" onClick={() => void start()} disabled={!canExecute || controlling || running || !diagnostics?.adapter.connected || diagnostics.adapter.state !== 'connected'}><PlayCircle size={15}/>开始</button>
        <button className="secondary-button" onClick={() => void stop()} disabled={!canExecute || controlling || !running}><Square size={15}/>停止</button>
        <button className="secondary-button" onClick={() => void disconnect()} disabled={!canExecute || controlling || !diagnostics?.adapter.connected}><XCircle size={15}/>断开</button>
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
