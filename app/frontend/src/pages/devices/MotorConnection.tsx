import { useEffect, useState, type FormEvent } from 'react'
import { api, type BluetoothDevice, type DeviceProfile } from '../../api'
import type { MotorPositionEvidence } from '../../api/devices'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'

type Angle = { method: number | null; motor: number | null; evidence?: MotorPositionEvidence }

export function MotorConnection({ token, profile, devices, disabled, onToast }: {
  token: string; profile: DeviceProfile; devices: BluetoothDevice[]; disabled: boolean; onToast: (message: string) => void
}) {
  const [selection, setSelection] = useState('')
  const [servicePort, setServicePort] = useState<number | null>(8790)
  const [calibration, setCalibration] = useState('')
  const [angles, setAngles] = useState<Angle[]>([{ method: null, motor: null }])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [loadedProfileId, setLoadedProfileId] = useState<number>()
  const ports = devices.flatMap(device => device.ports.filter(port => port.port !== profile.port)
    .map(port => ({ value: `${device.address}:${port.port}`, label: `${device.name} · ${port.device}` })))
  useEffect(() => {
    let current = true
    setLoading(true)
    setLoadedProfileId(undefined)
    setError('')
    void api.motorBinding(token, profile.id).then(binding => {
      if (!current) return
      setSelection(binding ? `${binding.bluetooth_address.toUpperCase()}:${binding.motor_port}` : '')
      setServicePort(binding?.api_port ?? 8790)
      setCalibration(binding?.calibration_id ?? '')
      setAngles(binding?.angles.map(angle => ({ method: angle.method_angle_deg, motor: angle.motor_angle_deg,
        evidence: angle.evidence ?? undefined })) ?? [{ method: null, motor: null }])
      setLoadedProfileId(profile.id)
    }).catch(cause => { if (current) setError(cause instanceof Error ? cause.message : '读取转角电机绑定失败') })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [token, profile.id])
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (disabled || !ports.some(port => port.value === selection) || !calibration.trim() || saving || loadedProfileId !== profile.id
        || !reportInvalidNumericInput(event.currentTarget)) return
    const complete = angles.flatMap(row => row.method !== null && row.motor !== null
      ? [{ method_angle_deg: row.method, motor_angle_deg: row.motor, evidence: row.evidence }] : [])
    if (servicePort === null || complete.length !== angles.length) {
      setError('请填写本机电机服务端口及每行的两个转角')
      return
    }
    const [address, number] = selection.split(':')
    setSaving(true)
    setError('')
    try {
      await api.saveMotorBinding(token, profile.id, {
        bluetooth_address: address, motor_port: Number(number), api_port: servicePort, calibration_id: calibration,
        angles: complete,
      })
      onToast('CCD 与转角电机的双口绑定已保存')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '保存转角电机绑定失败') }
    finally { setSaving(false) }
  }
  const edit = (index: number, field: 'method' | 'motor', value: number | null) =>
    setAngles(current => current.map((angle, i) => i === index
      ? { ...angle, [field]: value, evidence: field === 'method' && value !== angle.evidence?.target_angle_deg ? undefined : angle.evidence }
      : angle))
  return <form className="surface connection-controls" onSubmit={save} aria-label="转角电机绑定">
    <div className="connection-heading"><h2>转角电机</h2><span>CCD 采集口 COM{profile.port}</span></div>
    <p className="field-hint">选择独立的蓝牙电机 COM 口，并录入实测确认的转角对应关系。</p>
    <fieldset className="connection-fields" disabled={disabled || loading || saving || loadedProfileId !== profile.id}>
      <label className="field"><span>电机蓝牙 COM 口</span><select required value={ports.some(port => port.value === selection) ? selection : ''} onChange={event => setSelection(event.target.value)}>
        <option value="">{ports.length ? '请选择电机传出 COM 口' : '暂无独立的蓝牙传出 COM 口'}</option>
        {ports.map(port => <option key={port.value} value={port.value}>{port.label}</option>)}
      </select></label>
      <label className="field"><span>本机电机服务端口</span><NumericInput min={1} max={65535} required={false} value={servicePort} onValueChange={setServicePort} /></label>
      <label className="field"><span>现场标定编号</span><input required maxLength={200} value={calibration} onChange={event => setCalibration(event.target.value)} /></label>
    </fieldset>
    <fieldset className="connection-fields motor-angle-fields" disabled={disabled || loading || saving || loadedProfileId !== profile.id}>
      {angles.map((angle, index) => <div className="connection-fields motor-angle-row" key={index}>
        <label className="field"><span>方法转角（°）</span><NumericInput min={0} max={360} step="any" required={false} value={angle.method} onValueChange={value => edit(index, 'method', value)} /></label>
        <label className="field"><span>电机坐标（°）</span><NumericInput step="any" required={false} value={angle.motor} onValueChange={value => edit(index, 'motor', value)} /></label>
        <button type="button" className="secondary-button" disabled={angles.length === 1} onClick={() => setAngles(current => current.filter((_, i) => i !== index))}>移除此转角</button>
      </div>)}
      <div className="connection-actions">
        <button type="button" className="secondary-button" disabled={angles.length >= 64} onClick={() => setAngles(current => [...current, { method: null, motor: null }])}>添加转角</button>
        <button type="submit" className="primary-button" disabled={!selection || !ports.some(port => port.value === selection)}>保存电机绑定</button>
      </div>
    </fieldset>
    {error && <p className="connection-error" role="alert">{error}</p>}
  </form>
}
