import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { api, type CcdLayoutOption, type DevicePort, type DeviceProfile, type Settings } from '../../api'
import { ConnectionPortSelect, connectionValue } from './ConnectionPortSelect'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { PageFileActions } from '../../components/PageFileActions'
import { SectionHeading } from '../../components/SectionHeading'
import { acquireHardwareOperation, hardwareLockStore, useHardwareOwner } from '../../stores/hardwareLockStore'

const owner = 'device-parameters'

export function DeviceParameters({ token, canWrite, canExecute, canWriteScreen, canReadLayouts, settings, onSettingsChange, onSaved, onProfileChange, onToast, actionsTarget, active = true, revision = 0, handoffPurpose }: {
  token: string; canWrite: boolean; canExecute: boolean; canWriteScreen: boolean; canReadLayouts: boolean
  settings: Settings | null; onSettingsChange: (settings: Settings) => void
  onSaved: () => void; onToast: (message: string) => void; actionsTarget?: HTMLElement | null; active?: boolean
  onProfileChange?: (profile: DeviceProfile) => void
  revision?: number
  handoffPurpose?: 'acquisition' | 'dispersion' | 'hardware-acquisition'
}) {
  useHardwareOwner(token, owner, active)
  const [profiles, setProfiles] = useState<DeviceProfile[]>([])
  const [ports, setPorts] = useState<DevicePort[]>([])
  const [draft, setDraft] = useState<DeviceProfile | null>(null)
  const [currentProfileId, setCurrentProfileId] = useState<number | null>(null)
  const [slots, setSlots] = useState('')
  const [layouts, setLayouts] = useState<CcdLayoutOption[]>([])
  const [serviceMode, setServiceMode] = useState(false)
  const [screenWidth, setScreenWidth] = useState(settings?.display.screen_width_mm ?? 409.2)
  const [busy, setBusy] = useState(false)
  const [testMessage, setTestMessage] = useState('')
  const inFlight = useRef(false)
  const dirty = useRef(false)
  const screenDirty = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  const formId = useId()
  const lastSerialPort = useRef<string>('')
  const lastSerialProfileId = useRef<number | null>(null)
  const select = (profile: DeviceProfile) => { dirty.current = false; setTestMessage(''); setDraft(profile); setSlots(profile.ccd_indices.map(index => index + 1).join(', ')); onProfileChange?.(profile) }
  const choosePort = async (value: string, restorePrevious = false) => {
    if (!canWrite || busy || inFlight.current) return
    if (!value) return
    if (dirty.current || screenDirty.current) return onToast('请先保存当前设备参数，再切换通讯口')
    const operation = acquireHardwareOperation({ owner, kind: 'save' }, onToast)
    if (!operation) return
    inFlight.current = true; setBusy(true)
    try {
      const previous = restorePrevious ? profiles.find(item => item.id === lastSerialProfileId.current && item.enabled && item.transport === 'serial' && connectionValue(item) === value) : null
      const current = previous ? await api.selectDeviceProfile(token, previous.id)
        : await api.selectDevicePort(token, value === 'simulator' ? 'simulator' : 'serial', value === 'simulator' ? undefined : Number(value.slice(3)))
      if (!hardwareLockStore.owns(operation)) return
      if (current.transport === 'serial') { lastSerialPort.current = connectionValue(current); lastSerialProfileId.current = current.id }
      const next = await api.deviceProfiles(token)
      if (!hardwareLockStore.owns(operation)) return
      setProfiles(next); setCurrentProfileId(current.id); select(current); onSaved()
    }
    catch (error) {
      hardwareLockStore.failOperation(operation, error)
      onToast(error instanceof Error ? error.message : '选择设备失败')
    }
    finally { hardwareLockStore.completeOperation(operation); inFlight.current = false; setBusy(false) }
  }
  const load = useCallback(async () => {
    try { const [next, current, available] = await Promise.all([api.deviceProfiles(token), api.currentDeviceProfile(token), api.devicePorts(token)]); setPorts(available); setProfiles(next); setCurrentProfileId(current?.id ?? null); const profile = next.find(item => item.id === current?.id) ?? next[0]; if (profile) select(profile)
      if (current?.transport === 'serial') { lastSerialPort.current = connectionValue(current); lastSerialProfileId.current = current.id }
      else if (!lastSerialPort.current) { const serial = next.find(item => item.enabled && item.transport === 'serial'); lastSerialPort.current = serial ? connectionValue(serial) : available[0]?.device ?? ''; lastSerialProfileId.current = serial?.id ?? null }
    }
    catch (error) { onToast(error instanceof Error ? error.message : '读取设备参数失败') }
  }, [token, onToast, onProfileChange])
  useEffect(() => { void load() }, [load, revision])
  useEffect(() => {
    if (!screenDirty.current) setScreenWidth(settings?.display.screen_width_mm ?? 409.2)
  }, [settings])
  useEffect(() => {
    if (!canReadLayouts) return
    let cancelled = false
    void api.methodOptions(token).then(result => { if (!cancelled) setLayouts(result.ccd_layouts) })
      .catch(error => { if (!cancelled) onToast(error instanceof Error ? error.message : '读取CCD规格失败') })
    return () => { cancelled = true }
  }, [token, canReadLayouts, onToast])
  const screenPixels = Math.round(window.screen.width * window.devicePixelRatio) || settings?.display.screen_resolution_px || 1920
  const save = async () => {
    if (!draft || !canWrite || inFlight.current) return
    if (!currentProfileId) return onToast('请先选择通讯口，或勾选模拟设备用于测试')
    if (form.current?.querySelector('[data-numeric-input]:invalid:not(:disabled)')) {
      requestAnimationFrame(() => reportInvalidNumericInput(form.current))
      return onToast('请先修正设备参数中的无效数值')
    }
    const indices = slots.trim().split(/[,，\s]+/).map(value => Number(value) - 1)
    const volume = draft.frame_count * draft.ccds_per_frame
    if (!slots.trim() || indices.some(index => !Number.isInteger(index) || index < 0 || index >= volume) || new Set(indices).size !== indices.length)
      return onToast(`CCD 安装插槽须为 1–${volume} 之间不重复的整数`)
    const operation = acquireHardwareOperation({ owner, kind: 'save', profileId: draft.id }, onToast)
    if (!operation) return
    inFlight.current = true; setBusy(true)
    try {
      const saved = await api.updateDeviceProfile(token, draft.id, { name: draft.name, transport: draft.transport,
        port: draft.port, baud_rate: draft.baud_rate, ccd_indices: indices,
        ...(canWriteScreen ? { screen_width_mm: screenWidth, screen_resolution_px: Math.min(16000, screenPixels) } : {}) })
      if (!hardwareLockStore.owns(operation)) return
      await api.selectDeviceProfile(token, saved.id)
      if (!hardwareLockStore.owns(operation)) return
      setCurrentProfileId(saved.id)
      setProfiles(current => current.map(item => item.id === saved.id ? saved : item))
      if (canWriteScreen) {
        try {
          const current = await api.settings(token)
          if (!hardwareLockStore.owns(operation)) return
          const savedSettings = await api.saveSettings(token, { display: { ...current.display,
            screen_width_mm: screenWidth, screen_resolution_px: Math.min(16000, screenPixels) } })
          if (!hardwareLockStore.owns(operation)) return
          screenDirty.current = false; onSettingsChange(savedSettings)
        } catch (error) {
          onSaved()
          throw new Error(`通讯参数已保存，屏幕参数保存失败，请重试：${error instanceof Error ? error.message : '未知错误'}`)
        }
      }
      select(saved)
      onSaved(); onToast('设备参数已保存，重新连接设备后使用新参数')
    } catch (error) {
      hardwareLockStore.failOperation(operation, error)
      onToast(error instanceof Error ? error.message : '保存设备参数失败')
    }
    finally { hardwareLockStore.completeOperation(operation); inFlight.current = false; setBusy(false) }
  }
  const testConnection = async () => {
    if (!draft || !canExecute || inFlight.current) return
    if (dirty.current || screenDirty.current) return onToast('请先保存设备参数，再进行连接测试')
    const handoff = hardwareLockStore.getSnapshot().status === 'connected_idle' ? handoffPurpose : undefined
    const operation = acquireHardwareOperation({ owner, kind: 'test', profileId: draft.id }, onToast)
    if (!operation) return
    inFlight.current = true; setBusy(true)
    setTestMessage(draft.transport === 'serial' ? '正在执行一次短采集，等待有效CCD响应…' : '正在测试模拟设备…')
    try {
      const result = await api.testDeviceConnection(token, draft.id, handoff)
      if (!result.passed) throw new Error('连接测试未通过')
      if (result.connected) throw new Error('连接测试结束后串口状态仍需核实')
      if (!hardwareLockStore.completeOperation(operation, { portReleased: Boolean(handoff) })) return
      const message = draft.transport === 'serial' ? '连接测试通过：已收到有效CCD数据，测试结束后串口已关闭' : '模拟设备连接测试通过'
      setTestMessage(message); onToast(message)
    } catch (error) {
      hardwareLockStore.failOperation(operation, error)
      const message = error instanceof Error ? error.message : '连接测试失败'
      setTestMessage(message); onToast(message)
    }
    finally { inFlight.current = false; setBusy(false) }
  }
  if (!draft) return <section className="surface device-parameter-form"><p>暂无设备档案</p><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />重新读取</button></section>
  const matchingLayouts = layouts.filter(layout => layout.frame_count === draft.frame_count && layout.ccds_per_frame === draft.ccds_per_frame
    && layout.points_per_ccd === draft.points_per_ccd && layout.point_width_um === draft.point_width_um
    && layout.ccd_indices.join(',') === draft.ccd_indices.join(','))
  const driftValues = [...new Set(matchingLayouts.map(layout => layout.allow_drift_um))]
  return <form id={formId} ref={form} noValidate className="surface device-parameter-form device-parameter-cards" onSubmit={event => { event.preventDefault(); void save() }}
    onKeyDown={event => { if (canWrite && event.ctrlKey && event.altKey && event.key.toLowerCase() === 'w') { event.preventDefault(); setServiceMode(true) } }}>
    <PageFileActions target={actionsTarget} hidden={!active}>
      <button type="button" className="secondary-button" disabled={busy} onClick={() => {
        const saved = profiles.find(item => item.id === draft.id); if (saved) select(saved)
        screenDirty.current = false; setScreenWidth(settings?.display.screen_width_mm ?? 409.2)
      }}>还原参数</button>
      <button type="submit" form={formId} className="primary-button" disabled={!canWrite || busy}><Save size={15} />保存设备参数</button>
    </PageFileActions>
    <div className="legacy-device-parameters">
      <section className="surface legacy-parameter-card legacy-computer-parameters" aria-label="电脑设置">
        <div className="surface-heading"><SectionHeading title="电脑设置" /></div>
        <div className="legacy-parameter-content">
        <fieldset className="legacy-parameter-group" disabled={busy}>
          <legend>通讯参数</legend>
          <div className="legacy-communication-row"><ConnectionPortSelect value={currentProfileId ? draft.transport === 'serial' ? connectionValue(draft) : lastSerialPort.current : ''} ports={ports}
            savedPorts={profiles.filter(item => item.transport === 'serial').map(item => item.port)} disabled={!canWrite || busy || draft.transport === 'simulator' && Boolean(currentProfileId)}
            onChange={value => void choosePort(value)} />
            <label className="checkbox-row"><input type="checkbox" checked={Boolean(currentProfileId && draft.transport === 'simulator')} disabled={!canWrite || busy}
              onChange={event => { if (!event.target.checked && !lastSerialPort.current) return onToast('请先刷新端口，选择真实设备的通讯口'); void choosePort(event.target.checked ? 'simulator' : lastSerialPort.current, !event.target.checked) }} />模拟设备（用于测试）</label>
            <button type="button" className="secondary-button" onClick={() => void api.devicePorts(token).then(available => { if (!lastSerialPort.current) lastSerialPort.current = available[0]?.device ?? ''; setPorts(available) }).catch(error => onToast(error.message))}>刷新端口</button>
            <button type="button" className="secondary-button" disabled={!canExecute || !currentProfileId} onClick={() => void testConnection()}>连接测试</button></div>
          {draft.transport === 'simulator' && currentProfileId && <p className="field-hint">当前使用模拟器，曲线为模拟数据，不连接真实仪器。</p>}
          {draft.transport === 'serial' && <p className="field-hint">连接测试会按旧版执行一次短采集；收到有效CCD数据后才通过。</p>}
          {testMessage && <p className="field-hint" role="status">{testMessage}</p>}
          {draft.transport === 'serial' && <details className="legacy-communication-options"><summary>通信速率</summary>
            <label className="field legacy-parameter-row"><span>波特率</span><select disabled={!canWrite} value={draft.baud_rate} onChange={event => { dirty.current = true; setDraft({ ...draft, baud_rate: Number(event.target.value) }) }}>
              {Array.from(new Set([draft.baud_rate, 460800, 921600])).sort((a, b) => a - b).map(value => <option key={value} value={value}>{value}</option>)}
            </select></label></details>}
        </fieldset>
        <fieldset className="legacy-parameter-group" disabled={!canWrite || !canWriteScreen || busy}>
          <legend>屏幕参数</legend>
          <label className="field legacy-parameter-row"><span>当前分辨率（μm/点）</span><input readOnly value={(screenWidth * 1000 / screenPixels).toFixed(1)} /></label>
          <label className="field legacy-parameter-row"><span>屏幕宽度（cm）</span><NumericInput min={25.4} max={122.76} step="any" value={Number((screenWidth / 10).toFixed(4))}
            onValueChange={value => { screenDirty.current = true; setScreenWidth(value * 10) }} /></label>
        </fieldset>
        </div>
      </section>
      <section className="surface legacy-parameter-card" aria-label="CCD设置">
        <div className="surface-heading"><SectionHeading title="CCD设置" /></div>
        <fieldset className="legacy-parameter-content legacy-ccd-parameters" disabled={!canWrite || busy} onChange={() => { dirty.current = true }}>
        <div className="legacy-ccd-capacity"><label className="field legacy-parameter-row"><span>CCD容量</span><input readOnly value={draft.frame_count * draft.ccds_per_frame} /></label>
          <label className="checkbox-row"><input type="checkbox" disabled checked={draft.mirror} readOnly />镜像CCD</label></div>
        <label className="field legacy-parameter-row"><span>CCD点数</span><input readOnly value={draft.points_per_ccd} /></label>
        <label className="field legacy-parameter-row"><span>CCD点宽（μm）</span><input readOnly value={draft.point_width_um.toFixed(1)} /></label>
        <label className="field legacy-parameter-row"><span>尾首间隔（μm）</span><input readOnly value={settings?.analysis?.dispersion_nominal_gap_um ?? '未读取'} /></label>
        <label className="field legacy-parameter-row"><span>安装插槽</span><input required readOnly={!serviceMode} value={slots} onChange={event => setSlots(event.target.value)} /></label>
        <label className="field legacy-parameter-row"><span>允许漂移（μm）</span><input readOnly value={driftValues.length === 1 ? driftValues[0] : driftValues.length ? '按方法布局' : '未匹配布局'} /></label>
        </fieldset>
      </section>
    </div>
  </form>
}
