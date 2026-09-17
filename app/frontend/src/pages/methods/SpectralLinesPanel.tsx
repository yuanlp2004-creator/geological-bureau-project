import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Clock3, Info, Plus, Save, SlidersHorizontal, Trash2, CircleX } from 'lucide-react'
import { api, type LineDetectability, type MethodLineCollection, type SpectralLine, type SpectralLineInput, type SpectralLineOptions } from '../../api'
import { NumericInput as EmptyableNumberInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { NumberField } from './NumberField'

const lineTypeLabel: Record<SpectralLineInput['line_type'], string> = {
  baseline: '参考基线',
  analysis: '分析线',
  internal_standard: '内标线',
  positioning: '定位线',
}

const defaultLine = (): SpectralLineInput => ({
  line_type: 'analysis', element: 'Fe', wavelength_nm: 254, actual_wavelength_nm: 254,
  enabled: true, critical_band: false, priority: 0, background_line_id: 'reference-baseline',
  alignment_line_id: null, internal_standard_mode: 'none', internal_standard_line_id: null,
  scan_width_points: 9, background_offset_points: 0, peak_mode: 'max_single_point', peak_width_points: 1,
  fit_mode: 'linear', coordinate_type: 'normal', unit: 'ug/g', value_kind: 'content',
  decimal_places: 2, lower_peak: 300, minimum_peak_ratio: 1.5, valid_range_min: 0,
  valid_range_max: 1000, over_limit_tolerance_percent: 0,
  standard_points: [1, 2, 3, 4].map((value) => ({ name: `S${value}`, value, active: true })),
})

function lineToInput(line: SpectralLine): SpectralLineInput {
  const { id: _id, order: _order, reference_baseline: _reference, detectability: _detectability, ...input } = line
  return structuredClone(input)
}

export function SpectralLinesPanel({ methodId, token, canWrite, onChanged, onToast }: { methodId: number; token: string; canWrite: boolean; onChanged: () => Promise<void>; onToast: (message: string) => void }) {
  const [listCollapsed, setListCollapsed] = useState(false)
  const [collection, setCollection] = useState<MethodLineCollection | null>(null)
  const [options, setOptions] = useState<SpectralLineOptions | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<SpectralLineInput>(defaultLine)
  const [creating, setCreating] = useState(false)
  const [detectability, setDetectability] = useState<LineDetectability | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadLines = useCallback(async () => {
    try {
      const [nextCollection, nextOptions] = await Promise.all([
        api.methodLines(token, methodId), api.spectralLineOptions(token),
      ])
      setCollection(nextCollection)
      setOptions(nextOptions)
      setSelectedId((previous) => nextCollection.lines.some((line) => line.id === previous) ? previous : nextCollection.lines[0]?.id ?? null)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取谱线')
    }
  }, [methodId, token])

  useEffect(() => { void loadLines() }, [loadLines])
  useEffect(() => {
    setCreating(false)
    setSelectedId(null)
  }, [methodId])

  const selected = collection?.lines.find((line) => line.id === selectedId) ?? null
  useEffect(() => {
    if (creating || !selected) return
    setDraft(lineToInput(selected))
    setDetectability(selected.detectability ?? null)
  }, [creating, selected])

  useEffect(() => {
    if (!Number.isFinite(draft.wavelength_nm)) return
    let active = true
    const timer = window.setTimeout(() => {
      void api.detectLine(token, methodId, {
        wavelength_nm: draft.wavelength_nm,
        actual_wavelength_nm: draft.actual_wavelength_nm,
        scan_width_points: draft.scan_width_points,
      }).then((result) => { if (active) setDetectability(result) }).catch(() => { if (active) setDetectability(null) })
    }, 220)
    return () => { active = false; window.clearTimeout(timer) }
  }, [draft.actual_wavelength_nm, draft.scan_width_points, draft.wavelength_nm, methodId, token])

  const updateDraft = <K extends keyof SpectralLineInput>(key: K, value: SpectralLineInput[K]) => setDraft((previous) => ({ ...previous, [key]: value }))
  const edit = (line: SpectralLine) => { setCreating(false); setSelectedId(line.id); setDraft(lineToInput(line)); setDetectability(line.detectability ?? null) }
  const beginCreate = () => { setCreating(true); setSelectedId(null); setDraft(defaultLine()); setDetectability(null) }

  const mutate = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await action()
      await Promise.all([loadLines(), onChanged()])
      onToast(success)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '谱线操作失败')
    } finally {
      setBusy(false)
    }
  }

  const save = () => {
    if (!canWrite || selected?.line_type === 'baseline') return
    if (!reportInvalidNumericInput(document.querySelector('.spectral-editor-surface'))) return onToast('请先修正谱线中的无效数值')
    const action = creating
      ? api.createLine(token, methodId, draft)
      : selectedId ? api.updateLine(token, methodId, selectedId, draft) : Promise.reject(new Error('请选择谱线'))
    void mutate(() => action, creating ? '谱线已添加到新草稿版本' : '谱线已更新，已发布版本未改变')
    setCreating(false)
  }

  const toggle = (line: SpectralLine) => {
    const input = lineToInput(line)
    input.enabled = !input.enabled
    void mutate(() => api.updateLine(token, methodId, line.id, input), input.enabled ? '谱线已启用' : '谱线已停用')
  }

  const remove = (line: SpectralLine) => {
    if (!window.confirm(`确认删除 ${line.element} ${line.wavelength_nm.toFixed(4)} nm？`)) return
    void mutate(() => api.deleteLine(token, methodId, line.id), '谱线已删除')
  }

  const reorder = (ordered: SpectralLine[], success: string) => {
    void mutate(() => api.reorderLines(token, methodId, ordered.map((line) => line.id)), success)
  }

  const movable = collection?.lines.filter((line) => line.line_type !== 'baseline') ?? []
  const sortBy = (key: 'element' | 'wavelength_nm') => reorder(
    [...movable].sort((left, right) => key === 'element' ? left.element.localeCompare(right.element) || left.wavelength_nm - right.wavelength_nm : left.wavelength_nm - right.wavelength_nm),
    key === 'element' ? '已按元素排序' : '已按波长排序',
  )
  const move = (line: SpectralLine, offset: number) => {
    const index = movable.findIndex((item) => item.id === line.id)
    const target = index + offset
    if (index < 0 || target < 0 || target >= movable.length) return
    const ordered = [...movable]
    ;[ordered[index], ordered[target]] = [ordered[target], ordered[index]]
    reorder(ordered, '谱线顺序已更新')
  }

  const setLineType = (lineType: SpectralLineInput['line_type']) => setDraft((previous) => ({
    ...previous,
    line_type: lineType,
    standard_points: lineType === 'analysis' ? (previous.standard_points.length >= 4 ? previous.standard_points : defaultLine().standard_points) : [],
    internal_standard_mode: lineType === 'analysis' ? previous.internal_standard_mode : 'none',
    internal_standard_line_id: lineType === 'analysis' ? previous.internal_standard_line_id : null,
  }))

  const backgroundLines = collection?.lines.filter((line) => line.line_type === 'baseline' && line.enabled) ?? []
  const alignmentLines = collection?.lines.filter((line) => ['positioning', 'internal_standard'].includes(line.line_type) && line.enabled && line.id !== selectedId) ?? []
  const internalLines = collection?.lines.filter((line) => line.line_type === 'internal_standard' && line.enabled && line.id !== selectedId) ?? []
  const isBaseline = !creating && selected?.line_type === 'baseline'

  return <div className={`spectral-workbench ${listCollapsed ? 'list-collapsed' : ''}`} data-testid="spectral-lines-panel">
    {error && <div className="auth-error"><AlertTriangle size={15} />{error}</div>}
    <section className="surface spectral-list-surface" id="method-spectral-list" hidden={listCollapsed}>
      <div className="surface-heading spectral-heading"><div><h2>谱线清单 <span className="count-badge">{collection?.lines.length ?? 0}/300</span></h2></div>{canWrite && <button className="primary-button" onClick={beginCreate} disabled={busy}><Plus size={15} />添加谱线</button>}</div>
      <div className="spectral-sortbar"><span>排序</span><button onClick={() => sortBy('element')} disabled={!canWrite || busy || movable.length < 2}>按元素</button><button onClick={() => sortBy('wavelength_nm')} disabled={!canWrite || busy || movable.length < 2}>按波长</button></div>
      <div className="spectral-line-list">{collection?.lines.map((line) => <button key={line.id} className={`spectral-line-card ${line.id === selectedId && !creating ? 'active' : ''} ${line.enabled ? '' : 'disabled'}`} onClick={() => edit(line)}>
        <span className={`line-type-mark ${line.line_type}`} />
        <span className="line-main"><strong title={`${line.element} ${line.wavelength_nm.toFixed(4)} nm`}>{line.element} <b>{line.wavelength_nm.toFixed(4)}</b> nm</strong><small title={`${lineTypeLabel[line.line_type]} · ${line.detectability?.detectable ? `${line.detectability.ccd_label} / 角度位 ${line.detectability.angle_slot}` : line.detectability?.message}`}>{lineTypeLabel[line.line_type]} · {line.detectability?.detectable ? `${line.detectability.ccd_label} / 角度位 ${line.detectability.angle_slot}` : line.detectability?.message}</small></span>
        <span className="line-badges">{line.reference_baseline && <i>基线</i>}{line.critical_band && <i className="critical">关键</i>}{line.priority > 0 && <i>P{line.priority}</i>}{!line.enabled && <i className="off">停用</i>}</span>
      </button>)}</div>
    </section>

    <section className="surface spectral-editor-surface">
      <div className="surface-heading"><button className="secondary-button spectral-list-toggle" aria-controls="method-spectral-list" aria-expanded={!listCollapsed} onClick={() => setListCollapsed(!listCollapsed)}><SlidersHorizontal size={14} />{listCollapsed ? '展开谱线清单' : '收起清单'}</button><div><h2>{creating ? '添加谱线' : selected ? `${selected.element} ${selected.wavelength_nm.toFixed(4)} nm` : '选择谱线'}</h2></div>{selected && !isBaseline && canWrite && <div className="line-toolbar"><button className="icon-button compact" title="上移" onClick={() => move(selected, -1)} disabled={busy || movable[0]?.id === selected.id}>↑</button><button className="icon-button compact" title="下移" onClick={() => move(selected, 1)} disabled={busy || movable[movable.length - 1]?.id === selected.id}>↓</button><button className="icon-button compact" title={selected.enabled ? '停用' : '启用'} onClick={() => toggle(selected)} disabled={busy}>{selected.enabled ? '●' : '○'}</button><button className="icon-button compact danger" title="删除" onClick={() => remove(selected)} disabled={busy}><Trash2 size={14} /></button></div>}</div>
      {!selected && !creating ? <div className="method-empty compact"><SlidersHorizontal size={25} /><p>选择一条谱线查看完整参数。</p></div> : <>
        {isBaseline && <div className="baseline-notice"><Info size={16} /><span>参考基线全方法唯一，波长、实际波长、线宽和单位由“方法条件”维护。</span></div>}
        <div className="spectral-form-grid">
          <label className="field"><span>谱线类型</span><select value={draft.line_type} onChange={(event) => setLineType(event.target.value as SpectralLineInput['line_type'])} disabled={!canWrite || isBaseline}><option value="analysis">分析线</option><option value="internal_standard">内标线</option><option value="positioning">定位线</option>{isBaseline && <option value="baseline">参考基线</option>}</select></label>
          <label className="field"><span>元素</span><select value={draft.element} onChange={(event) => updateDraft('element', event.target.value)} disabled={!canWrite || isBaseline}>{options?.element_symbols.map((element) => <option key={element}>{element}</option>)}</select></label>
          <NumberField label="理论波长 (nm)" value={draft.wavelength_nm} min={160} max={800} step={0.0001} disabled={!canWrite || isBaseline} onChange={(value) => setDraft((previous) => ({ ...previous, wavelength_nm: value, actual_wavelength_nm: previous.actual_wavelength_nm === previous.wavelength_nm ? value : previous.actual_wavelength_nm }))} />
          <NumberField label="实际波长 (nm)" value={draft.actual_wavelength_nm ?? draft.wavelength_nm} min={160} max={800} step={0.0001} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('actual_wavelength_nm', value)} />
        </div>
        <div className={`detectability-card ${detectability == null ? 'checking' : detectability.detectable ? 'detectable' : 'undetectable'}`}><span className="detect-icon">{detectability?.detectable ? <CheckCircle2 size={18} /> : detectability ? <CircleX size={18} /> : <Clock3 size={18} />}</span><div><strong>{detectability?.detectable ? '当前条件可检测' : detectability ? '当前条件不可检测' : '正在检查检测条件'}</strong><span>{detectability?.detectable ? `${detectability.ccd_label} · 点位 ${detectability.point_index} · 角度位 ${detectability.angle_slot}${detectability.angle_deg == null ? '' : ` (${detectability.angle_deg}°)`}` : detectability?.message ?? '正在计算 CCD 落点…'}</span></div><code>{detectability?.reason_code ?? 'checking'}</code></div>
        <div className="spectral-toggle-grid"><label><input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft('enabled', event.target.checked)} disabled={!canWrite || isBaseline} /><span><strong>启用谱线</strong><small>停用后不参与后续分析</small></span></label><label><input type="checkbox" checked={draft.critical_band} onChange={(event) => updateDraft('critical_band', event.target.checked)} disabled={!canWrite || isBaseline} /><span><strong>关键波段</strong><small>随方法版本固化</small></span></label><NumberField label="优先级" value={draft.priority} min={0} max={100} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('priority', value)} /></div>

        <div className="spectral-section-title"><strong>引用与内标</strong></div>
        <div className="spectral-form-grid">
          <label className="field"><span>背景线</span><select value={draft.background_line_id ?? ''} onChange={(event) => updateDraft('background_line_id', event.target.value || null)} disabled={!canWrite || isBaseline}><option value="">不引用</option>{backgroundLines.map((line) => <option key={line.id} value={line.id}>{line.element} {line.wavelength_nm.toFixed(4)}</option>)}</select></label>
          <label className="field"><span>定位参考</span><select value={draft.alignment_line_id ?? ''} onChange={(event) => updateDraft('alignment_line_id', event.target.value || null)} disabled={!canWrite || isBaseline}><option value="">不引用</option>{alignmentLines.map((line) => <option key={line.id} value={line.id}>{lineTypeLabel[line.line_type]} · {line.element} {line.wavelength_nm.toFixed(4)}</option>)}</select></label>
          <label className="field"><span>内标方式</span><select value={draft.internal_standard_mode} onChange={(event) => updateDraft('internal_standard_mode', event.target.value as SpectralLineInput['internal_standard_mode'])} disabled={!canWrite || isBaseline || draft.line_type !== 'analysis'}><option value="none">无内标</option><option value="background">背景内标</option><option value="line">普通内标线</option></select></label>
          <label className="field"><span>内标线引用</span><select value={draft.internal_standard_line_id ?? ''} onChange={(event) => updateDraft('internal_standard_line_id', event.target.value || null)} disabled={!canWrite || isBaseline || draft.internal_standard_mode !== 'line'}><option value="">请选择</option>{internalLines.map((line) => <option key={line.id} value={line.id}>{line.element} {line.wavelength_nm.toFixed(4)}</option>)}</select></label>
        </div>

        <div className="spectral-section-title"><strong>峰值、拟合与结果规则</strong></div>
        <div className="spectral-form-grid dense">
          <NumberField label="扫描宽度（点）" value={draft.scan_width_points} min={5} max={31} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('scan_width_points', value)} />
          <NumberField label="背景偏移（点）" value={draft.background_offset_points} min={-100} max={100} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('background_offset_points', value)} />
          <label className="field"><span>峰值方式</span><select value={draft.peak_mode} onChange={(event) => setDraft((previous) => ({ ...previous, peak_mode: event.target.value as SpectralLineInput['peak_mode'], peak_width_points: event.target.value === 'max_single_point' ? 1 : Math.max(3, previous.peak_width_points | 1) }))} disabled={!canWrite || isBaseline}><option value="max_single_point">最大值</option><option value="gaussian">高斯曲线</option></select></label>
          <NumberField label="计算点数" value={draft.peak_width_points} min={1} max={9} step={draft.peak_mode === 'gaussian' ? 2 : 1} disabled={!canWrite || isBaseline || draft.peak_mode === 'max_single_point'} onChange={(value) => updateDraft('peak_width_points', value)} />
          <label className="field"><span>拟合方式</span><select value={draft.fit_mode} onChange={(event) => updateDraft('fit_mode', event.target.value as SpectralLineInput['fit_mode'])} disabled={!canWrite || isBaseline}><option value="linear">直线函数</option><option value="quadratic">二次曲线</option><option value="cubic">三次曲线</option><option value="spline">样条函数</option></select></label>
          <label className="field"><span>拟合坐标</span><select value={draft.coordinate_type} onChange={(event) => updateDraft('coordinate_type', event.target.value as SpectralLineInput['coordinate_type'])} disabled={!canWrite || isBaseline}><option value="normal">普通坐标</option><option value="logarithmic">对数坐标</option></select></label>
          <label className="field"><span>单位</span><select value={draft.unit} onChange={(event) => updateDraft('unit', event.target.value as SpectralLineInput['unit'])} disabled={!canWrite || isBaseline}><option value="ug/g">ug/g</option><option value="mg/g">mg/g</option><option value="%">%</option></select></label>
          <label className="field"><span>数值类型</span><select value={draft.value_kind} onChange={(event) => updateDraft('value_kind', event.target.value as SpectralLineInput['value_kind'])} disabled={!canWrite || isBaseline}><option value="content">含量</option><option value="concentration">浓度</option></select></label>
          <NumberField label="小数位" value={draft.decimal_places} min={0} max={6} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('decimal_places', value)} />
          <NumberField label="低峰阈值" value={draft.lower_peak} min={100} max={600} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('lower_peak', value)} />
          <NumberField label="最小峰侧比" value={draft.minimum_peak_ratio} min={1.1} max={2.5} step={0.1} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('minimum_peak_ratio', value)} />
          <NumberField label="有效下限" value={draft.valid_range_min} min={0} max={9999999} step={0.01} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('valid_range_min', value)} />
          <NumberField label="有效上限" value={draft.valid_range_max} min={0} max={9999999} step={0.01} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('valid_range_max', value)} />
          <NumberField label="超限容差 (%)" value={draft.over_limit_tolerance_percent} min={0} max={100} step={0.1} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('over_limit_tolerance_percent', value)} />
        </div>

        {draft.line_type === 'analysis' && <><div className="spectral-section-title"><strong>标准点 <i>{draft.standard_points.length}/50</i></strong>{canWrite && <button className="secondary-button compact" onClick={() => updateDraft('standard_points', [...draft.standard_points, { name: `S${draft.standard_points.length + 1}`, value: draft.standard_points.length + 1, active: true }])} disabled={isBaseline || draft.standard_points.length >= 50}><Plus size={14} />添加</button>}</div><div className="standard-points-wrap"><table className="standard-points-table"><thead><tr><th>启用</th><th>名称</th><th>含量 / 浓度</th><th /></tr></thead><tbody>{draft.standard_points.map((point, index) => <tr key={index}><td><input type="checkbox" checked={point.active} onChange={(event) => updateDraft('standard_points', draft.standard_points.map((item, itemIndex) => itemIndex === index ? { ...item, active: event.target.checked } : item))} disabled={!canWrite || isBaseline} /></td><td><input value={point.name} maxLength={50} onChange={(event) => updateDraft('standard_points', draft.standard_points.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} disabled={!canWrite || isBaseline} /></td><td><EmptyableNumberInput min="0.00000099" max="9999999" step="any" value={point.value} onValueChange={(value) => updateDraft('standard_points', draft.standard_points.map((item, itemIndex) => itemIndex === index ? { ...item, value } : item))} disabled={!canWrite || isBaseline} /></td><td><button className="icon-button compact danger" title="删除标准点" onClick={() => updateDraft('standard_points', draft.standard_points.filter((_, itemIndex) => itemIndex !== index))} disabled={!canWrite || isBaseline || draft.standard_points.length <= 4}><Trash2 size={13} /></button></td></tr>)}</tbody></table></div></>}
        {canWrite && !isBaseline && <div className="spectral-savebar"><span>保存会校验全部引用，成功后生成新草稿版本。</span><button className="primary-button" onClick={save} disabled={busy || !detectability?.detectable}><Save size={15} />{creating ? '添加谱线' : '保存谱线'}</button></div>}
      </>}
    </section>
  </div>
}
