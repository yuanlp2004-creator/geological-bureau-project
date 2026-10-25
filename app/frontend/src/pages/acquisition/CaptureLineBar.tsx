import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { MethodVersion } from '../../api/methods'

export type CaptureLineChoice = { id: string; label: string; wavelength: number; exposure?: string }
export function CaptureLineBar({ lines = [], value = '', choose, disabled = false, unavailable = '当前没有可选择的谱线', defaultExposure = '' }:
  { lines?: CaptureLineChoice[]; value?: string; choose?: (id: string) => void; disabled?: boolean; unavailable?: string; defaultExposure?: string }) {
  const line = lines.find(item => item.id === value)
  return <div className="spectroscopy-line-bar" aria-label="谱线与曝光区间">
    <label><span>选择谱线:</span><select aria-label="选择谱线" value={value} disabled={disabled || !lines.length} title={!lines.length ? unavailable : '查看当前任务谱线'}
      onChange={event => choose?.(event.target.value)}>
      <option value="" />
      {lines.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select></label>
    <label><span>定位谱线:</span><input aria-label="定位谱线" title="当前谱线波长（nm），只读观察" readOnly value={line?.wavelength ?? ''} /></label>
    <label><span>曝光区间:</span><input aria-label="曝光区间" title="当前任务方法版本规定的帧区间；修改条件请回到方法参数" readOnly value={line?.exposure ?? defaultExposure} /></label>
  </div>
}

export function SampleCaptureLineBar({ token, canReadMethods, methodId, version, frames }:
  { token: string; canReadMethods: boolean; methodId: number | null; version: number | null; frames: number }) {
  const [snapshot, setSnapshot] = useState<{ key: string; value: MethodVersion } | null>(null)
  const [lineId, setLineId] = useState('')
  const [error, setError] = useState('')
  const key = `${token}:${methodId}:${version}`
  useEffect(() => {
    setSnapshot(null); setLineId(''); setError('')
    if (!canReadMethods || !methodId || !version) return
    let cancelled = false
    void api.methodVersions(token, methodId).then(versions => {
      if (cancelled) return
      const value = versions.find(item => item.version === version && item.state === 'published')
      if (value) setSnapshot({ key, value })
      else setError('当前任务的方法版本不可用')
    }).catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : '读取任务谱线失败') })
    return () => { cancelled = true }
  }, [key, canReadMethods])
  const lines = snapshot?.key === key ? snapshot.value.lines.map(line => ({ id: line.id,
    label: `${line.element} ${line.wavelength_nm}`, wavelength: line.actual_wavelength_nm ?? line.wavelength_nm,
    exposure: `${line.exposure_start_frame ?? 1}-${line.exposure_end_frame ?? frames}` })) : []
  return <CaptureLineBar lines={lines} value={lineId} choose={setLineId} defaultExposure={frames ? `1-${frames}` : ''}
    unavailable={error || (!canReadMethods ? '当前账户没有方法读取权限' : '等待当前任务的方法谱线')} />
}
