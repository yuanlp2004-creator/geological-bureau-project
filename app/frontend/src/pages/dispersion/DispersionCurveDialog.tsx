import { useEffect, useRef, useState } from 'react'
import { api, type DispersionTask, type DispersionCalibrationVersion } from '../../api'
import { SpectroscopyTaskDialog } from '../acquisition/SpectroscopyTaskDialog'
import './dispersion-curve-dialog.css'

type Props = {
  active: DispersionTask; token: string; canWrite: boolean; busy: boolean; gapLimits: [number, number]
  curves: DispersionCalibrationVersion[]
  change: (work: (id: number) => Promise<unknown>, message?: string) => Promise<DispersionTask | undefined> | undefined
  onClose: () => void
}

const displayWavelength = (value: number) => value <= 0 ? '' : Number(value.toFixed(4)) === value ? value.toFixed(4) : String(value)

/** FmWstc: compact toolbar, six-column editable wavelength grid, calculation results. */
export function DispersionCurveDialog({ active, token, canWrite, busy, gapLimits, curves, change, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [drafts, setDrafts] = useState<Record<number, string>>(() => Object.fromEntries(active.lines.map(line => [line.id, displayWavelength(line.wavelength_nm)])))
  const [gap, setGap] = useState(-1)
  const [increment, setIncrement] = useState(1)
  const [fittedId, setFittedId] = useState<number | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState(active.name)
  const [error, setError] = useState('')
  const previousFocus = useRef<Element | null>(null)
  useEffect(() => {
    previousFocus.current = document.activeElement
    dialog.current?.showModal()
    return () => { dialog.current?.close(); if (previousFocus.current instanceof HTMLElement) previousFocus.current.focus() }
  }, [])
  const fit = active.calibrations.find(item => item.id === fittedId)
  const current = fit?.inputs_current !== false ? fit : undefined
  const results = current?.legacy_results
  const rows = active.legacy_lines ?? []
  const gapValue = gap < 0 ? null : Math.round((active.layout.gap_points[gap] ?? 0) * active.layout.point_width_um)
  const enabled = canWrite && !busy
  const names = Array.from(new Set([...active.calibrations, ...curves].filter(curve=>curve.state === 'published' && !curve.archived).map(curve=>curve.name)))
  const located = rows.filter(row => row.measured_step != null)
  const valid = located.filter(row => Number(drafts[row.line_id]) >= 160 && Number(drafts[row.line_id]) <= 800)
  const wavelengths = valid.map(row => Number(drafts[row.line_id])).sort((a, b) => a - b)
  const positions = valid.map(row => row.measured_step!).sort((a, b) => a - b)
  const duplicate = wavelengths.some((value, index) => index > 0 && value - wavelengths[index - 1] <= 0.01)
    || positions.some((value, index) => index > 0 && value - positions[index - 1] <= 1e-7)
  const fitIssue = valid.length !== located.length ? '请填写已定位谱线的有效已知波长。'
    : valid.length < 4 || valid.length > 8 ? `有效定位点 ${valid.length} 个，拟合需要 4–8 个，通常使用 6 个。`
    : duplicate ? '有效定位点的波长与测量步数须各不相同。' : ''
  const persist = async () => {
    let task = active
    for (const line of active.lines) {
      if (!located.some(row => row.line_id === line.id)) continue
      const value = Number(drafts[line.id])
      if (!Number.isFinite(value) || value < 160 || value > 800) { setError('请填写160–800 nm范围内的已知波长'); return }
      if (value !== line.wavelength_nm) {
        const updated = await change(id => api.updateDispersionWavelength(token, id, line.id, value, true))
        if (!updated) return
        task = updated
      }
    }
    return task
  }
  const commitOne = async (id: number) => {
    const line = active.lines.find(line => line.id === id), value = Number(drafts[id])
    if (!line || !enabled) return
    if (value === line.wavelength_nm) { setDrafts(values => ({ ...values, [id]: displayWavelength(value) })); return }
    if (!Number.isFinite(value) || value < 160 || value > 800) {
      setError('请输入160–800 nm范围内的已知波长，已还原原值')
      setDrafts(values=>({...values,[id]:displayWavelength(line.wavelength_nm)}));return
    }
    const updated = await change(taskId => api.updateDispersionWavelength(token, taskId, id, value, true))
    if (updated) { setError(''); setDrafts(values => Number(values[id]) === value ? { ...values, [id]: displayWavelength(value) } : values) }
    else setDrafts(values=>({...values,[id]:displayWavelength(line.wavelength_nm)}))
  }
  const calculate = async () => {
    setError('')
    if (!await persist()) return
    const updated = await change(id => api.fitDispersionCalibration(token, id, { degree: 2, use_legacy_limit: true }))
    if (updated) {
      const nextFit = updated.calibrations.find(item => item.state === 'draft' && !active.calibrations.some(prior => prior.id === item.id))
      if (!nextFit) return
      setFittedId(nextFit.id)
      if (!nextFit.publishable && nextFit.inputs_current !== false) setError('步数误差达到或超过允许值，请检查输入数据后重新拟合。')
    }
  }
  const save = async () => {
    if (!current || !name.trim() || !await persist()) return
    const updated = await change(() => api.saveDispersionCurve(token, current.id, name.trim()), '色散曲线已保存，可在方法参数中选用')
    if (updated) onClose()
  }
  const stepGap = async (direction: number) => {
    if (gapValue === null) return
    const value = Math.max(gapLimits[0], Math.min(gapLimits[1], gapValue + direction * increment))
    if (value === gapValue) return
    await change(id => api.updateDispersionGap(token, id, gap, value, true), 'CCD间隔已更新，测量步数已重算，请重新拟合')
  }
  const fixed = (value: number | null | undefined, digits = 1) => value == null ? '' : value.toFixed(digits)
  return <>
    <dialog ref={dialog} className="dispersion-curve-dialog" aria-label="色散曲线" onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
      <header><h2>色散曲线</h2><button type="button" aria-label="关闭色散曲线" disabled={busy} onClick={onClose}>×</button></header>
      <div className="dispersion-legacy-toolbar" role="toolbar" aria-label="色散曲线操作">
        <div className="dispersion-legacy-settings">
        <label>CCD区间<select aria-label="CCD区间" value={gap} disabled={!enabled} onChange={event => setGap(Number(event.target.value))}>
          <option value={-1}>选择区间</option>{active.layout.gap_points.map((_, index) => <option key={index} value={index}>CCD: [{index + 1},{index + 2}]</option>)}
        </select></label>
        <div className="dispersion-gap-field"><span>间隔</span><div className="dispersion-gap-spin"><input aria-label="CCD间隔（μm）" readOnly value={gapValue ?? ''} placeholder="—" disabled={!enabled || gap < 0} />
          <div><button type="button" aria-label="增大CCD间隔" disabled={!enabled || gapValue === null || gapValue >= gapLimits[1]} onClick={() => void stepGap(1)}>▴</button>
            <button type="button" aria-label="减小CCD间隔" disabled={!enabled || gapValue === null || gapValue <= gapLimits[0]} onClick={() => void stepGap(-1)}>▾</button></div>
        </div><span className="dispersion-unit">μm</span></div>
        <label>标尺<select aria-label="标尺（μm）" value={increment} disabled={!enabled} onChange={event => setIncrement(Number(event.target.value))}>
          {[1, 5, 10].map(value => <option key={value} value={value}>{value}</option>)}
        </select><span className="dispersion-unit">μm</span></label>
        </div>
        <div className="dispersion-legacy-actions">
        <button type="button" disabled={!enabled || Boolean(fitIssue)} title={fitIssue || '使用当前有效定位点拟合'} onMouseDown={event => event.preventDefault()} onClick={() => void calculate()}>拟合曲线</button>
        <button type="button" className="dispersion-save-button" disabled={!enabled || Boolean(fitIssue) || !current?.publishable || !results || active.lines.some(line => located.some(row => row.line_id === line.id) && Number(drafts[line.id]) !== line.wavelength_nm)} onMouseDown={event => event.preventDefault()} onClick={() => setSaveOpen(true)}>保存曲线</button>
        <button type="button" disabled={busy} onClick={onClose}>退出</button>
        </div>
      </div>
      <div className="dispersion-legacy-body">
        <section className="dispersion-legacy-lines"><h3>谱线列表<span>{valid.length} 个有效定位点 / {rows.length} 条谱线 · 波长 nm</span></h3>
          <div className="dispersion-legacy-table"><table><thead><tr>
            {['序号','谱线波长','谱线位置','测量步数','校正步数','步数误差'].map(label => <th key={label}>{label}</th>)}
          </tr></thead><tbody>{rows.map((row, index) => {
            const calculated = results?.rows.find(item => item.line_id === row.line_id)
            return <tr key={row.line_id}><td>{index + 1}</td><td><input aria-label={`谱线${index + 1}波长（nm）`} inputMode="decimal" value={drafts[row.line_id] ?? ''} disabled={!canWrite}
              onChange={event => {setDrafts(values => ({...values, [row.line_id]: event.target.value})); setError('')}}
              onBlur={() => void commitOne(row.line_id)} onKeyDown={async event => {if (event.key === 'Enter') {event.preventDefault(); await commitOne(row.line_id); dialog.current?.querySelector<HTMLInputElement>(`input[aria-label="谱线${index + 2}波长（nm）"]`)?.focus()}}} /></td>
              <td>{row.point_index == null ? '' : `(${row.ccd_index + 1},${row.point_index + 1})`}</td><td>{fixed(row.measured_step)}</td>
              <td>{fixed(calculated?.predicted_position)}</td><td>{fixed(calculated?.step_error)}</td></tr>
          })}</tbody></table></div>
        </section>
        <section className="dispersion-legacy-results"><h3>计算结果<span>{results ? '已拟合' : fit ? '需重新拟合' : '待拟合'}</span></h3><dl>
          <div><dt>截距</dt><dd>{fixed(results?.intercept, 1) || '—'}</dd></div>
          <div><dt>一次系数</dt><dd>{fixed(results?.linear_coefficient, 5) || '—'}</dd></div>
          <div><dt>二次系数</dt><dd>{fixed(results?.quadratic_coefficient, 7) || '—'}</dd></div>
          <div><dt>每步波长</dt><dd>{fixed(results?.wave_per_step, 5) || '—'}</dd></div>
          <div><dt>波长范围</dt><dd>{results?.wavelength_range.map(value => fixed(value, 4)).join(' – ') || '—'}</dd></div>
          <div><dt>步数范围</dt><dd>{results?.step_range.map(value => fixed(value)).join(' – ') || '—'}</dd></div>
        </dl></section>
      </div>
      {fit && !current && <p className="dispersion-legacy-note" role="status">谱线或CCD间隔已改变，请重新拟合。</p>}
      {fitIssue && <p className="dispersion-legacy-note" role="status">{fitIssue}</p>}
      {error && <p className="dispersion-legacy-error" role="alert">{error}</p>}
    </dialog>
    <SpectroscopyTaskDialog open={saveOpen} title="保存色散曲线" busy={busy} onCancel={() => setSaveOpen(false)}
      actions={<button type="button" disabled={!enabled || !name.trim()} onMouseDown={event => event.preventDefault()} onClick={() => void save()}>保存</button>}>
      <label className="field"><span>已有色散曲线</span><select aria-label="选择已有色散曲线" size={Math.max(2,Math.min(5,names.length+1))} value={names.includes(name)?name:''} disabled={busy} onChange={event=>setName(event.target.value)}>
        <option value="">新建曲线</option>{names.map(value=><option key={value} value={value}>{value}</option>)}
      </select></label>
      <label className="field"><span>曲线名称</span><input aria-label="色散曲线名称" maxLength={120} value={name} disabled={busy} onChange={event => setName(event.target.value)} /></label>
      <p className="field-help">同名曲线保留原版本，本次保存为新版本。</p>
    </SpectroscopyTaskDialog>
  </>
}
