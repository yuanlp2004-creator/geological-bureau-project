import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Activity, AlertTriangle, Check, CheckCircle2, Copy, Database, FileText, PauseCircle, PlayCircle, Plus, Printer, RefreshCw, Save, ShieldCheck, SlidersHorizontal, Trash2, X } from 'lucide-react'
import { api, type AngleExposure, type AuthUser, type CurrentMethodState, type MethodConditions, type MethodOptions, type MethodRecord } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { NumericInput as EmptyableNumberInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { NumberField } from './NumberField'
import { SpectralLinesPanel } from './SpectralLinesPanel'
import { MethodPrintPanel } from './MethodPrintPanel'

export function MethodsPage({ token, currentUser, currentMethod, initialSection, onViewChange, onCurrentMethodChange, onToast }: { token: string; currentUser: AuthUser; currentMethod: CurrentMethodState | null; initialSection: string | null; onViewChange: (view: string) => void; onCurrentMethodChange: (method: CurrentMethodState) => void; onToast: (message: string) => void }) {
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [options, setOptions] = useState<MethodOptions | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  const [draftWorkType, setDraftWorkType] = useState('routine')
  const [conditions, setConditions] = useState<MethodConditions | null>(null)
  const [composer, setComposer] = useState<'create' | 'copy' | null>(null)
  const [composerName, setComposerName] = useState('')
  const [editorSection, setEditorSection] = useState<'conditions' | 'lines' | 'print'>('conditions')
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const canWrite = currentUser.permissions.includes('methods.write')

  useEffect(() => {
    if (initialSection === 'lines') setEditorSection('lines')
    else if (initialSection === 'print-settings' || initialSection === 'print-preview') setEditorSection('print')
    else setEditorSection('conditions')
  }, [initialSection])

  const load = useCallback(async () => {
    try {
      const [nextMethods, nextOptions, nextCurrent] = await Promise.all([api.methods(token), api.methodOptions(token), api.currentMethod(token)])
      setMethods(nextMethods)
      setOptions(nextOptions)
      setSelectedId((previous) => nextMethods.some((item) => item.id === previous) ? previous : (nextCurrent.method_id ?? nextMethods[0]?.id ?? null))
      onCurrentMethodChange(nextCurrent)
      setLoadError(null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法读取方法数据')
    }
  }, [onCurrentMethodChange, token])

  useEffect(() => { void load() }, [load])
  const selected = methods.find((item) => item.id === selectedId) ?? null
  const selectedVersion = selected?.version ?? null
  const issues = selectedVersion?.validation_errors ?? []

  useEffect(() => {
    if (!selected?.version) return
    setDraftName(selected.name)
    setDraftDescription(selected.description)
    setDraftWorkType(selected.work_type)
    setConditions(structuredClone(selected.version.conditions))
  }, [selected])

  const setCondition = <K extends keyof MethodConditions>(key: K, value: MethodConditions[K]) => {
    setConditions((previous) => previous ? { ...previous, [key]: value } : previous)
  }
  const hasIssue = (field: string) => issues.some((issue) => issue.field === field || issue.field.startsWith(`${field}.`) || issue.field.startsWith(`${field}[`))
  const notifyError = (error: unknown, fallback: string) => onToast(error instanceof Error ? error.message : fallback)

  const runAction = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await action()
      await load()
      onToast(success)
    } catch (error) {
      notifyError(error, '方法操作失败')
    } finally {
      setBusy(false)
    }
  }

  const saveDraft = () => {
    if (!selected || !conditions) return
    if (!reportInvalidNumericInput(document.querySelector('.methods-page'))) return onToast('请先修正方法中的无效数值')
    void runAction(() => api.updateMethod(token, selected.id, { name: draftName, description: draftDescription, work_type: draftWorkType, conditions }), '方法草稿已保存；已发布版本未改变')
  }

  const submitComposer = (event: FormEvent) => {
    event.preventDefault()
    if (!composerName.trim()) return
    const action = composer === 'copy' && selected ? api.copyMethod(token, selected.id, composerName) : api.createMethod(token, { name: composerName })
    setBusy(true)
    void action.then(async (created) => {
      setComposer(null)
      setComposerName('')
      await load()
      setSelectedId(created.id)
      onToast(composer === 'copy' ? '方法副本已创建' : '新方法草稿已创建')
    }).catch((error) => notifyError(error, '创建方法失败')).finally(() => setBusy(false))
  }

  const currentLayout = options?.ccd_layouts.find((item) => item.id === Number(conditions?.ccd_layout_id) || item.name === String(conditions?.ccd_layout_id))
  const matchingCalibrations = options?.dispersion_calibrations.filter((item) => item.ccd_layout_id === currentLayout?.id) ?? []
  const currentCalibration = matchingCalibrations.find((item) => item.id === Number(conditions?.dispersion_calibration_id) || item.name === String(conditions?.dispersion_calibration_id))

  const changeLayout = (layoutId: number) => {
    const layout = options?.ccd_layouts.find((item) => item.id === layoutId)
    const calibration = options?.dispersion_calibrations.find((item) => item.ccd_layout_id === layoutId && item.enabled)
    if (!layout) return
    setConditions((previous) => previous ? { ...previous, ccd_layout_id: layoutId, selected_ccds: [...layout.ccd_indices], dispersion_calibration_id: calibration?.id ?? previous.dispersion_calibration_id } : previous)
  }

  const toggleCcd = (ccdIndex: number) => {
    if (!conditions) return
    const selectedCcds = conditions.selected_ccds.includes(ccdIndex) ? conditions.selected_ccds.filter((item) => item !== ccdIndex) : [...conditions.selected_ccds, ccdIndex].sort((a, b) => a - b)
    setCondition('selected_ccds', selectedCcds)
  }

  const updateAngle = (index: number, patch: Partial<AngleExposure>) => {
    if (!conditions) return
    setCondition('angle_exposures', conditions.angle_exposures.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  }

  const removeAngle = (index: number) => {
    if (!conditions || conditions.angle_exposures.length === 1) return
    setCondition('angle_exposures', conditions.angle_exposures.filter((_, itemIndex) => itemIndex !== index))
  }

  const addAngle = () => {
    if (!conditions) return
    const previousAngle = conditions.angle_exposures[conditions.angle_exposures.length - 1]?.angle_deg ?? -10
    setCondition('angle_exposures', [...conditions.angle_exposures, { angle_deg: previousAngle + 10, storage_mode: 'averaged', start_frame: 1, end_frame: Math.max(2, conditions.frame_count) }])
  }

  return <div className="page-content methods-page refined-page" data-testid="methods-page" data-navigation-view={initialSection ?? 'lifecycle'}>
    <section className="surface method-action-bar method-context-bar">
      <div className="method-context-main">
        <div className="method-picker"><h1>方法管理</h1><select aria-label="选择编辑方法" title={selected?.name} value={selectedId ?? ''} onChange={(event) => setSelectedId(Number(event.target.value))} disabled={busy || methods.length === 0}>{methods.length === 0 && <option value="">暂无方法</option>}{methods.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_current ? ' · 当前运行' : ''}{item.status === 'paused' ? ' · 已暂停' : ''}</option>)}</select></div>
        {selected && <div className="method-context-status"><span className={`version-chip ${selectedVersion?.state}`}>v{selectedVersion?.version} · {selectedVersion?.state === 'published' ? '已发布' : '草稿'}</span>{selected.is_current && <span className="current-chip">当前运行</span>}{selected.status !== 'active' && <span className="issue-chip">{selected.status === 'paused' ? '已暂停' : '已删除'}</span>}{issues.length > 0 && <span className="issue-chip"><AlertTriangle size={13} />{issues.length} 项待修正</span>}<details className="method-version-details"><summary>版本信息</summary><div><span>工作类型：{selected.work_type}</span><span>已发布版本：{selected.current_version ? `v${selected.current_version}` : '—'}</span><span>最新内容摘要：<CopyableCode value={selectedVersion?.content_sha256} visibleLength={10} /></span><small>修改保存为草稿，已发布版本保留。</small></div></details></div>}
      </div>
      <div className="method-context-actions"><div className="method-actions">{canWrite && selected && <><button className="secondary-button" onClick={() => { setComposer('copy'); setComposerName(`${selected.name}-副本`) }} disabled={busy}><Copy size={15} />复制</button><button className="secondary-button" onClick={saveDraft} disabled={busy || selected.status === 'deleted'}><Save size={15} />保存草稿</button><button className="primary-button" onClick={() => void runAction(() => api.publishMethod(token, selected.id), '有效草稿已发布为不可变版本')} disabled={busy || selectedVersion?.state !== 'draft' || issues.length > 0}><CheckCircle2 size={15} />发布</button>{selected.published_version && !selected.is_current && selected.status === 'active' && <button className="primary-button" onClick={() => void runAction(() => api.openMethod(token, selected.id), '当前运行方法已切换')} disabled={busy}><PlayCircle size={15} />设为当前</button>}{selected.status === 'active' && <button className="icon-button" title="暂停方法" onClick={() => void runAction(() => api.pauseMethod(token, selected.id), '方法已暂停')} disabled={busy}><PauseCircle size={15} /></button>}{selected.status === 'paused' && <button className="icon-button" title="恢复方法" onClick={() => void runAction(() => api.resumeMethod(token, selected.id), '方法已恢复')} disabled={busy}><PlayCircle size={15} /></button>}<button className="icon-button danger" title="软删除方法" onClick={() => { if (window.confirm(`确认删除方法“${selected.name}”？历史版本仍会保留。`)) void runAction(() => api.deleteMethod(token, selected.id), '方法已软删除') }} disabled={busy}><Trash2 size={15} /></button></>}</div><div className="method-library-actions"><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={16} />刷新</button>{canWrite && <button className="primary-button" onClick={() => { setComposer('create'); setComposerName('') }}><Plus size={16} />新建方法</button>}</div></div>
    </section>
    {loadError && <div className="auth-error"><AlertTriangle size={15} />{loadError}</div>}
    {composer && <form className="surface method-composer" onSubmit={submitComposer}><div><span className="section-kicker">{composer === 'copy' ? '复制方法' : '新建方法'}</span><strong>{composer === 'copy' ? `复制“${selected?.name ?? ''}”` : '创建方法草稿'}</strong></div><label className="field"><span>新方法名称</span><input autoFocus maxLength={20} value={composerName} onChange={(event) => setComposerName(event.target.value)} placeholder="GB18030 不超过 20 字节" required /></label><button className="primary-button" disabled={busy}><Check size={15} />确认</button><button type="button" className="icon-button" title="取消" onClick={() => setComposer(null)}><X size={15} /></button></form>}
    <div className="method-workbench">

      <main className="method-editor">
        {!selected || !conditions ? <section className="surface method-empty"><SlidersHorizontal size={30} /><h2>选择或新建方法</h2><p>方法条件、版本状态和运行操作会显示在这里。</p></section> : <>

          <div className="method-editor-tabs" role="tablist"><button className={editorSection === 'conditions' ? 'active' : ''} onClick={() => { setEditorSection('conditions'); onViewChange('conditions') }}>方法管理与参数</button><button className={editorSection === 'lines' ? 'active' : ''} onClick={() => { setEditorSection('lines'); onViewChange('lines') }}>分析谱线 <span>{selectedVersion?.lines?.length ?? 1}</span></button><button className={editorSection === 'print' ? 'active' : ''} onClick={() => { setEditorSection('print'); onViewChange('print-preview') }}><Printer size={13} />预览与打印</button></div>
          {editorSection === 'conditions' && <>
          {issues.length > 0 && <section className="surface method-issues"><div><AlertTriangle size={17} /><strong>草稿尚不能发布</strong><span>错误已随草稿保留，不影响当前有效版本。</span></div><ul>{issues.map((issue, index) => <li key={`${issue.field}-${index}`}><code>{issue.field}</code><span>{issue.message}</span></li>)}</ul></section>}
          <section className="surface method-section"><div className="surface-heading"><div><h2>基本信息</h2></div><FileText size={17} /></div><div className="method-field-grid"><label className="field"><span>方法名称</span><input value={draftName} onChange={(event) => setDraftName(event.target.value)} disabled={!canWrite} /><small>{new TextEncoder().encode(draftName).length} UTF-8 字节；保存时按 GB18030 验证 20 字节边界</small></label><label className="field"><span>工作类型</span><input value={draftWorkType} onChange={(event) => setDraftWorkType(event.target.value)} disabled={!canWrite} /></label><label className="field span-2"><span>说明</span><textarea rows={2} value={draftDescription} onChange={(event) => setDraftDescription(event.target.value)} disabled={!canWrite} /></label></div></section>
          <section className={`surface method-section ${hasIssue('selected_ccds') || hasIssue('reference_wavelength_nm') || hasIssue('actual_reference_wavelength_nm') ? 'has-errors' : ''}`}><div className="surface-heading"><div><h2>CCD 布局与参考线</h2></div><Database size={17} /></div><div className="method-field-grid"><label className="field"><span>CCD 布局</span><select value={String(currentLayout?.id ?? '')} onChange={(event) => changeLayout(Number(event.target.value))} disabled={!canWrite}>{options?.ccd_layouts.map((layout) => <option key={layout.id} value={layout.id}>{layout.name} · {layout.frame_count}×{layout.ccds_per_frame}</option>)}</select></label><label className="field"><span>色散标定</span><select value={String(currentCalibration?.id ?? '')} onChange={(event) => setCondition('dispersion_calibration_id', Number(event.target.value))} disabled={!canWrite}>{matchingCalibrations.map((calibration) => <option key={calibration.id} value={calibration.id}>{calibration.name}</option>)}</select></label><div className="field span-2"><span>启用 CCD</span><div className="ccd-selector">{currentLayout?.ccd_indices.map((index, itemIndex) => <label key={index} className={conditions.selected_ccds.includes(index) ? 'selected' : ''}><input type="checkbox" checked={conditions.selected_ccds.includes(index)} onChange={() => toggleCcd(index)} disabled={!canWrite} /><strong>{currentLayout.ccd_labels[itemIndex] ?? `CCD ${index}`}</strong><small>索引 {index}</small></label>)}</div></div><label className="field"><span>参考波长 (nm)</span><EmptyableNumberInput step="0.0001" value={conditions.reference_wavelength_nm} onValueChange={(value) => setCondition('reference_wavelength_nm', value)} disabled={!canWrite} /></label><label className="field"><span>实际参考波长 (nm)</span><EmptyableNumberInput step="0.0001" value={conditions.actual_reference_wavelength_nm} onValueChange={(value) => setCondition('actual_reference_wavelength_nm', value)} disabled={!canWrite} /></label><label className="field"><span>参考线宽（点）</span><EmptyableNumberInput min="11" max="50" value={conditions.reference_width_points} onValueChange={(value) => setCondition('reference_width_points', value)} disabled={!canWrite} /></label><label className="field"><span>分析单位</span><select value={conditions.analysis_unit} onChange={(event) => setCondition('analysis_unit', event.target.value as MethodConditions['analysis_unit'])} disabled={!canWrite}><option value="ug/g">ug/g</option><option value="mg/g">mg/g</option><option value="%">%</option></select></label></div>{currentCalibration && <div className="ccd-ranges">{currentCalibration.ccd_ranges.map((range) => <div key={range.ccd_index} className={conditions.selected_ccds.includes(range.ccd_index) ? 'active' : ''}><strong>CCD {range.ccd_index}</strong><span>{range.safe_start_nm.toFixed(3)} — {range.safe_end_nm.toFixed(3)} nm</span></div>)}</div>}</section>
          <section className={`surface method-section ${hasIssue('frame_count') || hasIssue('dark_frame_count') ? 'has-errors' : ''}`}><div className="surface-heading"><div><h2>激发与采集</h2></div><Activity size={17} /></div><div className="numeric-grid"><NumberField label="预激发 (s)" value={conditions.pre_excitation_seconds} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('pre_excitation_seconds', value)} /><NumberField label="采样周期 (s)" value={conditions.sampling_period_seconds} min={1} max={2} disabled={!canWrite} onChange={(value) => setCondition('sampling_period_seconds', value)} /><NumberField label="采集帧数" value={conditions.frame_count} min={1} max={255} disabled={!canWrite} onChange={(value) => setCondition('frame_count', value)} /><NumberField label="暗帧数" value={conditions.dark_frame_count} min={0} max={20} disabled={!canWrite} onChange={(value) => setCondition('dark_frame_count', value)} /></div></section>
          <section className={`surface method-section ${hasIssue('sample_repeats') || hasIssue('maximum_id_deviation') || hasIssue('rsd_threshold') ? 'has-errors' : ''}`}><div className="surface-heading"><div><h2>重复测量与质量阈值</h2></div><ShieldCheck size={17} /></div><div className="numeric-grid"><NumberField label="样品重复次数" value={conditions.sample_repeats} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('sample_repeats', value)} /><NumberField label="标样重复次数" value={conditions.standard_repeats} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('standard_repeats', value)} /><NumberField label="控制样重复次数" value={conditions.control_repeats} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('control_repeats', value)} /><NumberField label="最大 ID 偏差" value={conditions.maximum_id_deviation} min={0} max={20} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('maximum_id_deviation', value)} /><NumberField label="RSD 阈值" value={conditions.rsd_threshold} min={0} max={20} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('rsd_threshold', value)} /><NumberField label="校准阈值" value={conditions.calibration_threshold} min={0} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('calibration_threshold', value)} /><NumberField label="质控阈值" value={conditions.qc_threshold} min={0} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('qc_threshold', value)} /><NumberField label="异常阈值" value={conditions.abnormal_threshold} min={0} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('abnormal_threshold', value)} /><label className="field"><span>标准样品</span><input value={conditions.standard_sample_name} onChange={(event) => setCondition('standard_sample_name', event.target.value)} disabled={!canWrite} /></label><label className="toggle-row compact-toggle"><input type="checkbox" checked={conditions.rsd_enabled} onChange={(event) => setCondition('rsd_enabled', event.target.checked)} disabled={!canWrite} /><span><strong>启用 RSD 检查</strong><small>按阈值标记重复性异常</small></span></label></div></section>
          <section className={`surface method-section ${hasIssue('angle_exposures') ? 'has-errors' : ''}`}><div className="surface-heading"><div><h2>分角度存储区间</h2></div>{canWrite && <button className="secondary-button" onClick={addAngle}><Plus size={15} />添加角度</button>}</div><div className="angle-table-wrap"><table className="angle-table"><thead><tr><th>角度 (°)</th><th>存储模式</th><th>起始帧</th><th>结束帧</th><th>范围规则</th><th /></tr></thead><tbody>{conditions.angle_exposures.map((angle, index) => <tr key={`${angle.angle_deg}-${index}`}><td><EmptyableNumberInput step="0.1" value={angle.angle_deg} onValueChange={(value) => updateAngle(index, { angle_deg: value })} disabled={!canWrite} /></td><td><select value={angle.storage_mode} onChange={(event) => updateAngle(index, { storage_mode: event.target.value as AngleExposure['storage_mode'] })} disabled={!canWrite}>{options?.storage_modes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></td><td><EmptyableNumberInput min="1" max={conditions.frame_count} value={angle.start_frame} onValueChange={(value) => updateAngle(index, { start_frame: value })} disabled={!canWrite} /></td><td><EmptyableNumberInput min="1" max={conditions.frame_count} value={angle.end_frame} onValueChange={(value) => updateAngle(index, { end_frame: value })} disabled={!canWrite} /></td><td><span className="rule-note">{angle.storage_mode === 'full_interval' ? '至少 2 帧，完整保存' : '区间求均值后保存'}</span></td><td>{canWrite && <button className="icon-button compact danger" title="移除此角度" onClick={() => removeAngle(index)} disabled={conditions.angle_exposures.length === 1}><Trash2 size={14} /></button>}</td></tr>)}</tbody></table></div></section>
          {canWrite && <div className="method-save-footer"><span>{selected.is_current ? `当前运行引用已发布 v${currentMethod?.version}` : '编辑内容只会生成新草稿版本'}</span><button className="primary-button" onClick={saveDraft} disabled={busy}><Save size={16} />保存方法草稿</button></div>}
          </>}
          {editorSection === 'lines' && <SpectralLinesPanel methodId={selected.id} token={token} canWrite={canWrite} onChanged={load} onToast={onToast} />}
          {editorSection === 'print' && <MethodPrintPanel methodId={selected.id} methodName={selected.name} version={selectedVersion?.version ?? null} token={token} canWrite={canWrite} onToast={onToast} />}
        </>}
      </main>
    </div>
  </div>
}
