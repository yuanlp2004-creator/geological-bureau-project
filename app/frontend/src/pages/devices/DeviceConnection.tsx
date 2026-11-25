import { useCallback, useEffect, useRef, useState } from 'react'
import { Bluetooth, Cable, RefreshCw, Save, Unplug } from 'lucide-react'
import { api, type BluetoothDevice, type DeviceDiagnostics, type DeviceProfile } from '../../api'
import { openBluetoothSettings } from '../../platform/bluetooth'
import { BluetoothDevicePicker } from './BluetoothDevicePicker'
import { MotorConnection } from './MotorConnection'
import './device-connection.css'

type Props = {
  token: string; canWrite: boolean; canExecute: boolean; active: boolean; revision: number
  onSaved: () => void; onProfileChange: (profile: DeviceProfile) => void
  onConfigure: () => void; onToast: (message: string) => void
}

export function DeviceConnection({ token, canWrite, canExecute, active, revision, onSaved, onProfileChange, onConfigure, onToast }: Props) {
  const [devices, setDevices] = useState<BluetoothDevice[]>([])
  const [wiredPorts, setWiredPorts] = useState<number[]>([])
  const [profile, setProfile] = useState<DeviceProfile | null>(null)
  const [address, setAddress] = useState('')
  const [port, setPort] = useState('')
  const [diagnostics, setDiagnostics] = useState<DeviceDiagnostics['adapter'] | null>(null)
  const [captures, setCaptures] = useState<NonNullable<DeviceDiagnostics['active_captures']>>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const pending = useRef(false), refreshing = useRef(false), dirty = useRef(false)
  const deleted = useRef(new Set<string>())
  const selection = useRef({ address: '', port: '' })
  const device = devices.find(item => item.address === address)
  const ports = device?.ports ?? []
  const bound = Boolean(port && ports.some(item => item.device === port))
  const wiredCcd = profile?.transport === 'serial' && !address && wiredPorts.includes(profile.port)
  const changed = !wiredCcd && (profile?.transport !== 'serial' || port !== `COM${profile.port}`)
  const connected = Boolean(diagnostics?.connected || captures.length)
  const running = Boolean(captures.length || diagnostics?.connected && !['connected', 'error'].includes(diagnostics.state))
  const choose = (nextAddress: string, nextPort: string) => {
    selection.current = { address: nextAddress, port: nextPort }; setAddress(nextAddress); setPort(nextPort)
  }
  const load = useCallback(async () => {
    if (refreshing.current) return
    refreshing.current = true; setLoading(true)
    try {
      const [next, current, bluetooth, systemPorts] = await Promise.all([api.deviceDiagnostics(token), api.currentDeviceProfile(token), api.bluetoothDevices(token),
        api.devicePorts(token)])
      bluetooth.devices = bluetooth.devices.filter(item => !deleted.current.has(item.address))
      setDiagnostics(next.adapter); setCaptures(next.active_captures ?? []); setProfile(current); setDevices(bluetooth.devices)
      setWiredPorts(systemPorts.filter(item => !item.is_bluetooth).map(item => item.port))
      if (dirty.current) {
        const selected = bluetooth.devices.find(item => item.address === selection.current.address)
        choose(selected?.address ?? '', selected?.ports.some(item => item.device === selection.current.port) ? selection.current.port : '')
      } else {
        const selected = bluetooth.devices.find(item => current?.transport === 'serial' && item.ports.some(p => p.port === current.port))
        choose(selected?.address ?? '', selected ? `COM${current!.port}` : '')
      }
      if (current) onProfileChange(current)
      setError('')
    } catch (cause) { setDiagnostics(null); setError(cause instanceof Error ? cause.message : '读取Windows蓝牙设备失败') }
    finally { refreshing.current = false; setLoading(false) }
  }, [token, onProfileChange])
  useEffect(() => { if (active) void load() }, [active, revision, load])
  useEffect(() => {
    if (!active) return
    let cancelled = false, polling = false
    const timer = window.setInterval(() => {
      if (pending.current || refreshing.current || polling) return
      polling = true
      void Promise.all([api.deviceDiagnostics(token), api.bluetoothDevices(token)]).then(([next, bluetooth]) => {
        if (!cancelled) { setDiagnostics(next.adapter); setCaptures(next.active_captures ?? []); setDevices(bluetooth.devices.filter(item => !deleted.current.has(item.address))) }
      }).catch(cause => { if (!cancelled) { setDiagnostics(null); setError(cause instanceof Error ? cause.message : '读取连接状态失败') } })
        .finally(() => { polling = false })
    }, 3000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [active, token])
  const command = async (operation: () => Promise<void>) => {
    if (pending.current) return
    pending.current = true; setBusy(true); setError('')
    try { await operation() }
    catch (cause) { const message = cause instanceof Error ? cause.message : '设备操作失败'; await load(); setError(message); onToast(message) }
    finally { pending.current = false; setBusy(false) }
  }
  const save = () => command(async () => {
    if (!canWrite || !bound || !device || connected) return
    const saved = await api.selectDevicePort(token, 'serial', Number(port.slice(3)), device.address)
    setProfile(saved); onProfileChange(saved); dirty.current = false; onSaved(); onToast('蓝牙设备与COM口选择已保存，摄谱将使用此通讯口')
  })
  const remove = (item: BluetoothDevice) => command(async () => {
    if (!canWrite || connected) return
    await api.deleteBluetoothDevice(token, item.address)
    deleted.current.add(item.address)
    setDevices(items => items.filter(candidate => candidate.address !== item.address))
    if (selection.current.address === item.address) { dirty.current = false; choose('', '') }
  })
  const connect = () => command(async () => {
    if (!canExecute || !profile || changed || !(bound || wiredCcd) || connected) return
    if (wiredCcd) {
      const systemPorts = await api.devicePorts(token)
      if (!systemPorts.some(item => item.port === profile.port && !item.is_bluetooth))
        throw new Error('CCD 有线串口已变化，请刷新后重新选择')
    } else {
      const windows = await api.bluetoothDevices(token)
      if (!windows.devices.some(item => item.address === address && item.ports.some(p => p.device === port)))
        throw new Error('Windows蓝牙端口映射已变化，请刷新后重新选择')
    }
    const result = await api.connectDevice(token, profile.id); setDiagnostics(result.diagnostics)
    onToast('串口已打开，开始调试或摄谱后确认仪器响应')
  })
  const disconnect = () => command(async () => {
    if (!canExecute || running) return
    const result = await api.disconnectDevice(token); setDiagnostics(result.diagnostics); onToast('设备已断开')
  })
  const state = !diagnostics ? '状态未获取' : captures.length ? '摄谱正在使用串口' : diagnostics.state === 'error' ? '连接异常'
    : diagnostics.connected ? diagnostics.adapter === 'acq-simulator' ? '模拟设备已连接'
      : diagnostics.state === 'debugging' ? '正在采集 / 调试' : '串口已打开' : '未连接'
  return <section className="device-connection" data-testid="device-connection">
    <div className="surface connection-pairing"><div><h2><Bluetooth size={19} />Windows 蓝牙连接</h2>
      <p>选择 Windows 中已连接或已配对的设备，再选择它对应的 COM 口。</p></div>
      <div className="connection-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => void command(openBluetoothSettings)}><Bluetooth size={16} />打开 Windows 蓝牙设置</button>
        <button type="button" className="secondary-button" disabled={busy || loading} onClick={() => void load()}><RefreshCw size={16} />刷新设备与端口</button></div>
    </div>
    <div className="surface connection-controls"><div className="connection-heading"><h2>CCD 采集连接</h2><span className={`connection-state${connected ? ' connected' : ''}`} role="status">{state}</span></div>
      <fieldset disabled={busy || loading || connected || !canWrite} className="connection-fields">
        <div className="field"><span>Windows 蓝牙设备</span><BluetoothDevicePicker devices={devices} value={address}
          disabled={!canWrite || busy || loading || connected} onDelete={remove} onChange={value => {
            const selected = devices.find(item => item.address === value); dirty.current = true; choose(selected?.address ?? '', selected?.ports[0]?.device ?? '')
          }}/></div>
        <label className="field"><span>绑定 COM 口</span><select aria-label="绑定COM口" value={bound ? port : ''} disabled={!device || !ports.length} onChange={event => { dirty.current = true; choose(address, event.target.value) }}>
          <option value="">{device && !ports.length ? '此设备暂无传出 COM 口' : '请选择对应的 COM 口'}</option>
          {ports.map(item => <option key={item.device} value={item.device}>{item.device} · {item.description}</option>)}</select></label>
      </fieldset>
      {!devices.length && !loading && <p className="field-hint">未发现已连接或已配对的蓝牙设备。请打开 Windows 蓝牙设置完成配对，再刷新。</p>}
      {device && <p className="field-hint">Windows状态：{device.connected ? '已连接' : device.paired ? '已配对，未连接' : '已记录，未连接'}。{!device.connected && ports.length > 0 ? '打开对应COM口时建立串口连接。' : ''}</p>}
      {device && !ports.length && <p className="field-hint">Windows尚未给此设备分配传出COM口，或此设备不提供串口服务。请在Windows蓝牙设置的“更多蓝牙设置 → COM端口”中添加，再回到这里刷新。</p>}
      <div className="connection-actions"><button type="button" className="secondary-button" disabled={!canWrite || !bound || !changed || busy || loading || connected} onClick={() => void save()}><Save size={16} />保存绑定</button>
        <button type="button" className="primary-button" disabled={!canExecute || !profile?.enabled || changed || !(bound || wiredCcd) || !diagnostics || busy || loading || connected} onClick={() => void connect()}><Cable size={16} />连接设备</button>
        <button type="button" className="secondary-button" disabled={!canExecute || busy || !connected || running} onClick={() => void disconnect()}><Unplug size={16} />断开设备</button>
        <button type="button" className="secondary-button" disabled={busy} onClick={onConfigure}>更多设备参数</button></div>
      {bound && changed && <p className="field-hint">请先保存绑定，再连接设备。</p>}
      {wiredCcd && <p className="field-hint">当前 CCD 采集口为有线 COM{profile.port}。</p>}
      {profile?.transport === 'simulator' && <p className="field-hint">当前启用了模拟设备测试。可在设备参数中取消勾选，或在此保存真实蓝牙通讯口。</p>}
      {diagnostics?.connected && diagnostics.adapter !== 'acq-simulator' && <p className="field-hint">当前串口：{diagnostics.port}。{diagnostics.instrument_responded ? '本次连接已收到有效CCD数据。' : '尚未确认仪器响应，请进入调试对中或摄谱验证。'}</p>}
      {captures.map(item => <p className="field-hint" key={`${item.owner}-${item.task_id}`}>{item.port} · {item.owner} · 任务 {item.task_id}</p>)}
      {running && <p className="field-hint">请先在对应摄谱或调试页面停止任务，再断开设备。</p>}
      {(error || diagnostics?.last_error) && <p className="connection-error" role="alert">{error || diagnostics?.last_error?.message}</p>}
    </div>
    {profile?.transport === 'serial' && <MotorConnection key={profile.id} token={token} profile={profile} devices={devices}
      disabled={!canWrite || running} onToast={onToast} />}
    <p className="field-hint">蓝牙列表只显示 Windows 分配的传出 COM 口。有线 CCD 通讯口和模拟设备可在设备参数中选择。</p>
  </section>
}
