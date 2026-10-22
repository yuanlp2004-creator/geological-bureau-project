import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { api, type DeviceProfile } from '../../api'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { PageFileActions } from '../../components/PageFileActions'
import { SectionHeading } from '../../components/SectionHeading'

export function DeviceParameters({ token, canWrite, onSaved, onToast, actionsTarget, active = true }: {
  token: string; canWrite: boolean; onSaved: () => void; onToast: (message: string) => void; actionsTarget?: HTMLElement | null; active?: boolean
}) {
  const [profiles, setProfiles] = useState<DeviceProfile[]>([])
  const [draft, setDraft] = useState<DeviceProfile | null>(null)
  const [slots, setSlots] = useState('')
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)
  const dirty = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  const formId = useId()
  const select = (profile: DeviceProfile) => { dirty.current = false; setDraft(profile); setSlots(profile.ccd_indices.map(index => index + 1).join(', ')) }
  const load = useCallback(async () => {
    try { const next = await api.deviceProfiles(token); setProfiles(next); if (next[0]) select(next[0]) }
    catch (error) { onToast(error instanceof Error ? error.message : '读取设备参数失败') }
  }, [token, onToast])
  useEffect(() => { void load() }, [load])
  const save = async () => {
    if (!draft || !canWrite || inFlight.current) return
    if (!reportInvalidNumericInput(form.current)) return onToast('请先修正设备参数中的无效数值')
    const indices = slots.trim().split(/[,，\s]+/).map(value => Number(value) - 1)
    const volume = draft.frame_count * draft.ccds_per_frame
    if (!slots.trim() || indices.some(index => !Number.isInteger(index) || index < 0 || index >= volume) || new Set(indices).size !== indices.length)
      return onToast(`CCD 安装插槽须为 1–${volume} 之间不重复的整数`)
    inFlight.current = true; setBusy(true)
    try {
      const saved = await api.updateDeviceProfile(token, draft.id, { name: draft.name, transport: draft.transport,
        port: draft.port, baud_rate: draft.baud_rate, ccd_indices: indices, point_width_um: draft.point_width_um,
        protection_time_ms: draft.protection_time_ms, mirror: draft.mirror, enabled: draft.enabled })
      setProfiles(current => current.map(item => item.id === saved.id ? saved : item)); select(saved)
      onSaved(); onToast('设备参数已保存，重新连接设备后使用新参数')
    } catch (error) { onToast(error instanceof Error ? error.message : '保存设备参数失败') }
    finally { inFlight.current = false; setBusy(false) }
  }
  if (!draft) return <section className="surface device-parameter-form"><div className="surface-heading"><SectionHeading title="设备参数" /></div><p>暂无设备档案</p><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />重新读取</button></section>
  return <form id={formId} ref={form} className="surface device-parameter-form" onSubmit={event => { event.preventDefault(); void save() }}>
    <PageFileActions target={actionsTarget} hidden={!active}>
      <button type="button" className="secondary-button" disabled={busy} onClick={() => { const saved = profiles.find(item => item.id === draft.id); if (saved) select(saved) }}>还原参数</button>
      <button type="submit" form={formId} className="primary-button" disabled={!canWrite || busy}><Save size={15} />保存设备参数</button>
    </PageFileActions>
    <div className="surface-heading"><SectionHeading title="设备参数" /></div>
    <label className="field device-profile-select"><span>设备档案</span><select value={draft.id} disabled={busy}
      onChange={event => { if (dirty.current) return onToast('请先保存当前设备参数，再切换设备档案'); const next = profiles.find(item => item.id === Number(event.target.value)); if (next) select(next) }}>
      {profiles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    <fieldset disabled={!canWrite || busy} onChange={() => { dirty.current = true }}><div className="device-parameter-grid">
      <label className="field"><span>档案名称</span><input required maxLength={100} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
      <label className="field"><span>设备类型</span><select value={draft.transport} onChange={event => setDraft({ ...draft, transport: event.target.value as DeviceProfile['transport'] })}><option value="simulator">模拟设备</option><option value="serial">串口设备</option></select></label>
      <label className="field"><span>串口号 COM</span><NumericInput min={1} max={256} step={1} value={draft.port} onValueChange={value => setDraft({ ...draft, port: value })} /></label>
      <label className="field"><span>波特率</span><select value={draft.baud_rate} onChange={event => setDraft({ ...draft, baud_rate: Number(event.target.value) })}>{[9600,19200,38400,57600,115200,230400,460800,921600].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="field"><span>CCD 安装插槽</span><input required value={slots} onChange={event => setSlots(event.target.value)} /></label>
      <label className="field"><span>CCD 点宽 (μm)</span><NumericInput min={0.001} max={1000} step="any" value={draft.point_width_um} onValueChange={value => setDraft({ ...draft, point_width_um: value })} /></label>
      <label className="field"><span>保护时间 (ms)</span><NumericInput min={0} max={60000} step="any" value={draft.protection_time_ms} onValueChange={value => setDraft({ ...draft, protection_time_ms: value })} /></label>
    </div><div className="settings-analysis-options">
      <label className="checkbox-row"><input type="checkbox" checked={draft.mirror} onChange={event => setDraft({ ...draft, mirror: event.target.checked })} />CCD 镜像</label>
      <label className="checkbox-row"><input type="checkbox" checked={draft.enabled} onChange={event => setDraft({ ...draft, enabled: event.target.checked })} />启用设备档案</label>
    </div></fieldset>
    <p className="settings-effect-note">CCD 容量：{draft.frame_count} 组 × {draft.ccds_per_frame} CCD；每片 {draft.points_per_ccd} 点。安装插槽从 1 开始，以逗号分隔。</p>
  </form>
}
