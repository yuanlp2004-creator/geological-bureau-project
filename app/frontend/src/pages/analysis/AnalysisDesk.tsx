import { useEffect, useRef, useState } from 'react'
import { api, saveFile, type AcquisitionTask, type AnalysisRun, type SpectrumRecord } from '../../api'
import { getAnalysisSpectrum, printAnalysisSpectrum, previewDailyCalibration, saveDailyCalibration, type AnalysisRepeatDefaults, type AnalysisSampleNumber, type AnalysisSampleOption, type AnalysisSpectrum, type CalibrationPreview } from '../../api/analysis'
import { SpectrumInspector, type SpectrumViewRange } from '../../components/SpectrumInspector'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { LegacyViewingDesk } from '../../components/LegacyViewingDesk'
import { RowSelectionArrow } from '../../components/RowSelectionArrow'
import { SpectrumPointDetails } from '../../components/SpectrumPointDetails'
import { ViewerDialog } from '../spectra/ViewerDialog'
import { AnalysisSampleNamesDialog } from './AnalysisSampleNamesDialog'
import { AnalysisExposureControls, useAnalysisExposure } from './AnalysisExposure'
import { useFixedSpectrumView } from '../../components/useFixedSpectrumView'
import { spectralLineMenuGroups } from '../../components/spectrumMenu'
import type { SpectrumPlotMarker } from '../../components/SpectrumPlot'
import { ContextMenu, useContextMenu, type MenuGroup } from '../../components/ContextMenu'
import {
  acquisitionSourceKind, extractMethodStandardNames, resolveSampleSemanticRole, sampleRoleLabels, type SampleRoleEvidence,
} from '../../components/sampleSemanticRole'

type Props = {
  token: string; run: AnalysisRun | null; canSaveMethod: boolean; canPrint: boolean; canExecute: boolean
  busy: boolean; railCollapsed: boolean; paused: boolean
  revision: number
  sampleSources: AnalysisSampleOption[][]
  repeatDefaults?: AnalysisRepeatDefaults
  onSaveSampleNames: (ids: number[], numbering: AnalysisSampleNumber[] | null) => Promise<boolean>
  onShowRail: () => void; onReview: () => void
  onHideRail: () => void; onPrepare: () => void; onStart: () => void; onPause: () => void; onClose: () => void
  onToast: (message: string) => void; followSample?: boolean
  information?: { expanded: boolean; setExpanded: (value: boolean) => void }
}

// FmViewSingle/FmDockAwareSam: retain the original two tool rows and sample table.
export function AnalysisDesk(p: Props) {
  const { token, run, onToast } = p
  const fixed = useFixedSpectrumView()
  const emptyMenu = useContextMenu<null>()
  const [sample, setSample] = useState(0), [ccd, setCcd] = useState(0)
  const [turnIndex, setTurnIndex] = useState<number | undefined>()
  const [lineId, setLineId] = useState<string | null>(null), [wave, setWave] = useState('')
  const [data, setData] = useState<AnalysisSpectrum | null>(null)
  const [source, setSource] = useState<SpectrumRecord | null>(null), [task, setTask] = useState<AcquisitionTask | null>(null)
  const [managementTaskIds, setManagementTaskIds] = useState<ReadonlySet<number>>(() => new Set())
  const [methodStandardNames, setMethodStandardNames] = useState<ReadonlySet<string>>(() => new Set())
  const [error, setError] = useState(''), [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false)
  const [recordLocked, setRecordLocked] = useState(false), [focus, setFocus] = useState<number | null>(null), [picked, setPicked] = useState<number | null>(null)
  const [dialog, setDialog] = useState<'calibration' | 'point' | 'names' | null>(null), [calibration, setCalibration] = useState<CalibrationPreview | null>(null)
  const [measuredPositions, setMeasuredPositions] = useState<Record<string, number>>({})
  const [restoredLines, setRestoredLines] = useState<string[]>([])
  const [positionSample, setPositionSample] = useState(0)
  const [priority, setPriority] = useState(true)
  const [focusRevision, setFocusRevision] = useState(0)
  const [scope, setScope] = useState<'reference' | 'all'>('all'), [mode, setMode] = useState<'measured' | 'stored' | 'theoretical'>('measured')
  const [calibrating, setCalibrating] = useState(false), [printing, setPrinting] = useState(false)
  const generation = useRef(0)
  const active = run?.samples.find(item => item.position === sample)
  const running = run?.status === 'running' && !p.paused
  const navigationLocked = running || p.busy
  const sampleNavigationLocked = recordLocked || navigationLocked
  const sourcesById = new Map(p.sampleSources.flatMap(group => group.map(item => [item.id, item] as const)))
  const numbering = run?.input_snapshot?.sample_numbering
  const recordIds = numbering?.source_sample_ids ?? run?.samples.map(item => item.acquisition_sample_id) ?? []
  const qcManagementPositions = new Set(numbering ? [] : run?.quality?.latest_snapshot?.groups
    .filter(group => group.management_sample === true).flatMap(group => group.members.map(member => member.sample_position)))
  const samplePositionById = new Map(run?.samples.map(item => [item.acquisition_sample_id, item.position]))
  const roleEvidenceFor = (id: number): SampleRoleEvidence => {
    const origin = sourcesById.get(id)
    const taskId = origin?.acquisition_task_id ?? (active?.acquisition_sample_id === id ? source?.task_id : undefined)
    const position = samplePositionById.get(id)
    return {
      explicitManagementTask: taskId != null && managementTaskIds.has(taskId),
      qualityManagementSample: position !== undefined && qcManagementPositions.has(position),
      sourceKind: acquisitionSourceKind(origin),
      sampleNumbering: !!numbering,
    }
  }
  const groupNumbers = new Map<number, number>()
  const initialEntries: AnalysisSampleNumber[] = []
  let previousTask: number | undefined
  let validSamples = 0
  for (const item of run?.samples ?? []) {
    const frozenPosition = run?.input_snapshot?.samples?.[item.position]?.sample_group_position
    if (numbering && frozenPosition !== undefined) {
      groupNumbers.set(item.position, numbering.entries.slice(0, frozenPosition + 1).filter(entry => entry.repeats > 0).length)
      continue
    }
    const taskId = sourcesById.get(item.acquisition_sample_id)?.acquisition_task_id
    const previous = initialEntries[initialEntries.length - 1]
    if (taskId !== undefined && taskId === previousTask && item.sample_name && previous?.name === item.sample_name) previous.repeats++
    else {
      initialEntries.push({ name: item.sample_name, repeats: item.sample_name ? 1 : 0 })
      if (item.sample_name) validSamples++
    }
    previousTask = taskId
    groupNumbers.set(item.position, validSamples)
  }
  const inputNames = () => setDialog('names')
  const namesDisabled = !run || !p.canExecute || p.busy || ['running', 'paused'].includes(run.status)
  useEffect(() => {
    let live = true
    setMethodStandardNames(new Set())
    if (run) void api.methodLines(token, run.method_id, run.method_version)
      .then(({ lines }) => { if (live) setMethodStandardNames(extractMethodStandardNames(lines)) })
      .catch(() => {})
    return () => { live = false }
  }, [token, run?.method_id, run?.method_version])
  useEffect(() => {
    if (p.followSample && run && ['running', 'paused'].includes(run.status) && !recordLocked) {
      if (!priority && run.current_sample_position !== sample) setLineId(null)
      setSample(run.current_sample_position)
    }
  }, [run?.current_sample_position, run?.status, p.followSample, recordLocked, priority, sample])
  const viewLinePosition = (line: AnalysisSpectrum['lines'][number]) => {
    if (positionSample === sample && measuredPositions[line.id] !== undefined) return measuredPositions[line.id]
    if (positionSample === sample && restoredLines.includes(line.id)) return line.point
    return run?.line_results.find(item => item.sample_position === sample && item.line_id === line.id)?.peak_position ?? line.point
  }
  useEffect(() => {
    const ticket = ++generation.current
    setData(null); setSource(null); setTask(null); setError(''); setFocus(null); setPicked(null); setDialog(null)
    if (!run || !active) return
    setLoading(true)
    void getAnalysisSpectrum(token, run.id, sample, lineId).then(next => {
      if (ticket !== generation.current) return
      setData(next)
      const line = next.lines.find(item => item.id === lineId)
      setTurnIndex(line?.turn_index ?? next.bands[0]?.turn_index)
      setCcd(current => line?.ccd_index ?? (next.bands.some(band => band.ccd_index === current) ? current : next.bands[0]?.ccd_index ?? 0))
      if (line) setFocus(viewLinePosition(line))
    }).catch(failure => { if (ticket === generation.current) setError(failure instanceof Error ? failure.message : '谱图读取失败') })
      .finally(() => { if (ticket === generation.current) setLoading(false) })
    return () => { generation.current++ }
  }, [token, run?.id, active?.id, sample, lineId, refresh, p.revision])
  useEffect(() => { setCalibration(null); setPositionSample(sample); setMeasuredPositions({}); setRestoredLines([]) }, [token, run?.id, sample])
  useEffect(() => {
    let live = true
    setSource(null); setTask(null)
    if (!active || !data) return
    const slot = data.bands.findIndex(item => item.ccd_index === ccd && item.turn_index === turnIndex)
    if (slot < 0) return
    void api.spectrum(token, `sample:${active.acquisition_sample_id}`, { ccd: slot, detail: 'summary' }).then(record => {
      if (!live) return
      setSource(record)
      if (record.task_id) void api.acquisitionTask(token, record.task_id).then(next => {
        if (!live) return
        setTask(next)
        if (next.excitation_condition.management_sample === true) {
          setManagementTaskIds(ids => ids.has(next.id) ? ids : new Set([...ids, next.id]))
        }
      }).catch(() => {})
    }).catch(() => {}) // Metadata is optional; intensities always come from the verified analysis snapshot.
    return () => { live = false }
  }, [token, active?.acquisition_sample_id, data, ccd, turnIndex])
  const bandPosition = data?.bands.findIndex(item => item.ccd_index === ccd && item.turn_index === turnIndex) ?? -1
  const observation = useAnalysisExposure(token, run?.id, sample, lineId, bandPosition, data)
  const pointDetails = run && active && bandPosition >= 0 && observation.count > 0 ? {
    token, recordId: `sample:${active.acquisition_sample_id}`, ccd, onToast, canOutput: p.canPrint,
    analysis: { runId: run.id, samplePosition: sample, bandPosition }
  } : undefined
  const band = observation.band
  const bandLabel = band?.angle_deg !== undefined ? `${band.angle_deg}° · CCD ${ccd + 1}` : `CCD ${ccd + 1}`
  const points = band?.mean_points ?? []
  const chooseSample = (position: number) => { if (!sampleNavigationLocked) { setSample(position); if (!priority) setLineId(null); setWave('') } }
  const locate = () => {
    const value = Number(wave), calibrated = band?.wavelengths_nm?.map((wavelength_nm, point_index) => ({ wavelength_nm, point_index })) ?? []
    if (!wave.trim() || !Number.isFinite(value) || !calibrated.length || value < Math.min(...calibrated.map(item => item.wavelength_nm!)) || value > Math.max(...calibrated.map(item => item.wavelength_nm!)))
      return onToast('请输入当前 CCD 已标定范围内的有效波长')
    const nearest = calibrated.reduce((best, item) => Math.abs(item.wavelength_nm! - value) < Math.abs(best.wavelength_nm! - value) ? item : best)
    setFocus(nearest.point_index); setPicked(nearest.point_index)
  }
  const correct = async (nextScope: 'reference' | 'all') => {
    if (!run || calibrating) return
    const ticket = generation.current
    setScope(nextScope); setCalibrating(true)
    try {
      const next = await previewDailyCalibration(token, run.id, sample)
      if (ticket === generation.current) {
        const positions = next.positions.filter(row => nextScope === 'all' || row.line_type === 'baseline')
        if (!positions.length || positions.some(row => !row.found)) return onToast('未找到有效峰，原位置保持')
        setCalibration(next)
        setMeasuredPositions(current => ({ ...current, ...Object.fromEntries(positions.map(row => [row.line_id, row.measured_point])) }))
        const position = positions.find(row => row.line_id === lineId) ?? positions[0]
        setCcd(position.ccd_index); setTurnIndex(position.turn_index); setFocus(position.measured_point); setPicked(position.measured_point)
        onToast(nextScope === 'reference' ? '参考线已校正' : '谱线已校正')
      }
    }
    catch (failure) { if (ticket === generation.current) onToast(failure instanceof Error ? failure.message : '校线预览失败') }
    finally { setCalibrating(false) }
  }
  const saveCalibration = async (saveMode = mode, saveScope = scope, measuredIds?: string[]) => {
    if (!run || !p.canSaveMethod || !calibration || calibrating || navigationLocked) return
    const ticket = generation.current
    setCalibrating(true)
    try {
      const next = await saveDailyCalibration(token, run.id, sample, saveMode, saveScope, measuredIds)
      if (ticket === generation.current) onToast(`位置已保存为方法草稿 v${next.latest_version}，请在方法页审核并保存`)
    } catch (failure) { if (ticket === generation.current) onToast(failure instanceof Error ? failure.message : '位置保存失败') }
    finally { setCalibrating(false) }
  }
  const lines = data?.lines ?? []
  const chooseLine = (line: AnalysisSpectrum['lines'][number], position = viewLinePosition(line)) => {
    setLineId(line.id); setWave(''); setFocus(position); setFocusRevision(value => value + 1)
  }
  const markers: SpectrumPlotMarker[] = lines.filter(line => line.ccd_index === ccd && (line.turn_index ?? 0) === (turnIndex ?? 0))
    .map(line => ({ key: line.id, kind: 'located', position: viewLinePosition(line) + 1,
      label: `${line.element} ${line.wavelength_nm.toFixed(4)} nm`, selected: line.id === lineId,
      select: navigationLocked ? undefined : () => chooseLine(line) }))
  const lineMenu = (id: string) => {
    const line = lines.find(item => item.id === id)
    if (!line) return undefined
    const measuredIds = Object.keys(measuredPositions)
    return spectralLineMenuGroups(navigationLocked ? [line] : lines, line, chooseLine,
      { label: '优先显示', checked: priority, run: () => setPriority(value => !value) }, [], [
        { label: '还原实际位置', disabled: navigationLocked, run: () => {
          setMeasuredPositions(current => Object.fromEntries(Object.entries(current).filter(([key]) => key !== id)))
          setRestoredLines(current => current.includes(id) ? current : [...current, id])
          chooseLine(line, line.point)
        } },
        { label: '还原全部位置', disabled: navigationLocked, run: () => {
          setMeasuredPositions({}); setRestoredLines(lines.map(item => item.id)); chooseLine(line, line.point)
        } },
        { label: '保存全部位置', disabled: !p.canSaveMethod || navigationLocked || calibrating || !measuredIds.length,
          run: () => void saveCalibration('measured', 'all', measuredIds) }
      ])
  }
  const print = async (range: SpectrumViewRange) => {
    if (!run || !active || !points.length || !p.canPrint || printing) return
    setPrinting(true)
    try {
      const blob = await printAnalysisSpectrum(token, run.id, sample, { ccd, band_position: bandPosition, line_id: lineId,
        exposure_start: observation.interval?.[0], exposure_end: observation.interval?.[1],
        x_min: range.xMin, x_max: range.xMax, y_min: range.yMin, y_max: range.yMax })
      const path = await saveFile(blob, `样品分析-${active.sample_name}-CCD${ccd + 1}.pdf`)
      onToast(path ? `谱图 PDF 已保存：${path}` : '已取消保存')
    } catch (failure) { onToast(failure instanceof Error ? failure.message : '打印失败') }
    finally { setPrinting(false) }
  }
  const analysisMenu: MenuGroup[] = [[
    { label: '建立分析运行', disabled: p.busy || running, run: p.onPrepare },
    { label: '曲线与分析结果', disabled: !run || p.busy, run: p.onReview },
    { label: '重新读取谱图', disabled: p.busy, run: () => setRefresh(value => value + 1) },
    ...(p.railCollapsed ? [{ label: '显示样品列表', run: p.onShowRail }] : [])
  ], [
    { label: '校线结果', disabled: !calibration, run: () => setDialog('calibration') },
    ...(pointDetails ? [{ label: '点位明细', disabled: picked == null, run: () => setDialog('point') }] : [])
  ]]
  const extras = [
    ...(p.information ? [{ label: '显示信息', checked: p.information.expanded, run: () => p.information?.setExpanded(!p.information.expanded) }] : []),
    { label: '分析操作', children: analysisMenu }
  ]
  return <LegacyViewingDesk>
    <div className="legacy-view-top analysis-desk-top" role="toolbar" aria-label="样品分析工具">
      <label>选择谱线:<select aria-label="选择分析谱线" value={lineId ?? ''} disabled={!data?.lines.length || navigationLocked} onChange={event => { setLineId(event.target.value || null); setWave('') }}>
        <option value="" />{data?.lines.map(line => <option key={line.id} value={line.id}>{line.element} {line.wavelength_nm.toFixed(4)}</option>)}
      </select></label>
      <label>定位谱线:<input aria-label="定位分析谱线" value={wave} disabled={!points.length || navigationLocked} onChange={event => setWave(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); locate() } }} /></label>
      {observation.count > 0 && <AnalysisExposureControls key={`${sample}:${bandPosition}:${lineId}:${refresh}`}
        count={observation.count} initial={data?.exposure_interval} busy={observation.busy} disabled={navigationLocked}
        active={Boolean(observation.interval)} onApply={observation.apply} onReset={observation.reset} />}
      <span className="legacy-toolbar-separator" />
      <SpectroscopyToolButton icon="sample-input" label="录入样品编号" disabled={namesDisabled} onClick={inputNames} />
      <SpectroscopyToolButton icon="reference-correction" label="校参考线" disabled={!points.length || running || p.busy || calibrating} onClick={() => void correct('reference')} />
      <SpectroscopyToolButton icon="line-correction" label="校正谱线" disabled={!points.length || running || p.busy || calibrating} onClick={() => void correct('all')} />
      <SpectroscopyToolButton icon="measure" label={p.paused || run?.status === 'paused' ? '继续测量' : '开始测量'} disabled={!p.canExecute || p.busy || !run || run.samples.some(item => !item.sample_name.trim()) || !['draft', 'running', 'paused'].includes(run.status)} onClick={p.onStart} />
      <SpectroscopyToolButton icon="pause" label="暂停测量" disabled={!p.canExecute || !running} onClick={p.onPause} />
      <span className="legacy-toolbar-separator" />
      <SpectroscopyToolButton icon="close" label={run && ['running', 'paused'].includes(run.status) ? '停止测量并关闭' : '关闭样品分析'} disabled={p.busy && !running} onClick={p.onClose} />
    </div>
    <div className={`legacy-view-body analysis-desk-body${p.railCollapsed ? ' left-hidden' : ''}`}>
      {!p.railCollapsed && <aside className="legacy-view-rail analysis-sample-rail">
        <header><h2>{source?.storage_mode === 'full_interval' ? '全时样品' : '均值样品'}</h2><button aria-label="隐藏样品列表" onClick={p.onHideRail}>×</button></header>
        <div className="legacy-record-toolbar" role="toolbar" aria-label="分析样品列表操作">
          <SpectroscopyToolButton icon="sample-list-input" label="录入列表样品编号" disabled={namesDisabled} onClick={inputNames} />
          <SpectroscopyToolButton icon="sample-list-clear" label="清除样品编号" disabled={namesDisabled || !run?.samples.some(item => item.sample_name)}
            onClick={() => { if (run) void p.onSaveSampleNames(recordIds, null) }} />
          <SpectroscopyToolButton icon={recordLocked ? 'record-unlock' : 'record-lock'} label={recordLocked ? '解锁谱带记录' : '锁定谱带记录'} aria-pressed={recordLocked} disabled={!active || running} onClick={() => setRecordLocked(value => !value)} />
        </div>
        <div className="legacy-view-table-wrap"><table className="legacy-view-table"><colgroup><col style={{ width: 18 }} /><col style={{ width: 54 }} /><col /><col style={{ width: 65 }} /></colgroup>
          <thead><tr><th className="row-indicator" /><th>记录号</th><th>样品编号</th><th>样品序号</th></tr></thead>
          <tbody>{run?.samples.map(item => {
            const role = resolveSampleSemanticRole({ name: item.sample_name, methodStandardNames, ...roleEvidenceFor(item.acquisition_sample_id) })
            return <tr key={item.id} aria-selected={sample === item.position} data-sample-role={role} onClick={() => chooseSample(item.position)}>
              <td className="row-indicator">{sample === item.position && <RowSelectionArrow />}</td><td>{item.position + 1}</td>
              <td><button disabled={sampleNavigationLocked}
                title={role === 'neutral' ? item.sample_name : `${item.sample_name} · ${sampleRoleLabels[role]}`}>{item.sample_name}</button></td>
              <td>{item.sample_name ? groupNumbers.get(item.position) : '?'}</td>
            </tr>
          })}</tbody>
        </table></div>
        <div className="legacy-view-footer">{source?.measure_time?.replace('T', ' ').slice(0, 19) || '测量时间未记录'}</div>
      </aside>}
      <section className="legacy-view-center analysis-desk-spectrum" aria-label="分析完整谱图" tabIndex={points.length ? undefined : 0}
        onContextMenu={event => { if (!points.length) emptyMenu.open(event, null) }}>
        {!points.length && emptyMenu.target && <ContextMenu target={emptyMenu.target} close={emptyMenu.close} label="样品分析操作" groups={analysisMenu} />}
        {error && <div role="alert" className="analysis-desk-error">{error}<button onClick={() => setRefresh(value => value + 1)}>重新读取谱图</button></div>}
        {observation.error && <p role="alert" className="analysis-desk-error">{observation.error}</p>}
        <SpectrumInspector key={`${run?.id}:${sample}:${bandPosition}:${lineId}:${refresh}:${observation.interval?.join('-') ?? ''}`} fitPlot iconToolbar panOnStripOnly
          legacyTitle={`记录号：[${sample + 1}]  样品编号：[${active?.sample_name ?? ''}]  ${bandLabel}${observation.interval ? `  临时曝光：[${observation.interval.join('-')}]` : ''}`}
          points={points} pointOrigin={1} wavelengths={band?.wavelengths_nm} label={`分析样品 ${active?.sample_name ?? ''} CCD ${ccd + 1}`}
          focusPoint={focus} focusRevision={focusRevision} markers={markers} onPick={setPicked} onPrint={range => void print(range)}
          context={{ fixed, scope: `${run?.id}:${turnIndex}:${ccd}`, extras: () => extras, lineMenu, pointDetails }}
          printDisabledReason={!p.canPrint ? '需要分析打印权限' : printing || observation.busy ? '正在准备谱图' : undefined}
          physicalScale={task ? { pointWidthUm: task.layout.point_width_um, screenWidthMm: task.profile.screen_width_mm, screenResolutionPx: task.profile.screen_resolution_px } : undefined}
          ccdNavigation={{ current: bandPosition, indices: navigationLocked ? [bandPosition] : data?.bands.map((_, index) => index) ?? [],
            labels: Object.fromEntries(data?.bands.map((item, index) => [index, `${item.angle_deg === undefined ? '' : `${item.angle_deg}° · `}CCD ${item.ccd_index + 1}`]) ?? []),
            choose: value => { const next = data?.bands[value]; if (next) { setCcd(next.ccd_index); setTurnIndex(next.turn_index) }; setFocus(null); setPicked(null); setWave('') } }}
          bandNavigation={{ previous: () => chooseSample(sample - 1), next: () => chooseSample(sample + 1), canPrevious: !sampleNavigationLocked && sample > 0,
            canNext: !sampleNavigationLocked && Boolean(run && sample < run.samples.length - 1) }}
          emptyText={loading ? '正在读取分析谱图…' : error ? '谱图读取失败，请重试' : '打开样品文件或建立分析运行后显示谱图'} />
      </section>
    </div>
    {dialog === 'names' && run && <AnalysisSampleNamesDialog token={token}
      initialEntries={numbering?.entries ?? (validSamples ? initialEntries : [])} repeatDefaults={p.repeatDefaults}
      methodStandardNames={methodStandardNames} bandEvidence={recordIds.map(roleEvidenceFor)}
      capacity={recordIds.length} busy={namesDisabled} onSave={entries => p.onSaveSampleNames(recordIds, entries)}
      onClose={() => setDialog(null)} />}
    {dialog === 'calibration' && <ViewerDialog title={scope === 'reference' ? '校参考线' : '校正谱线'} onClose={() => setDialog(null)}>
      {calibrating && <p role="status">正在处理谱线位置…</p>}
      <div className="viewer-dialog-fields"><label>位置来源<select value={mode} onChange={event => setMode(event.target.value as typeof mode)}><option value="measured">本次实测位置</option><option value="stored">还原原方法保存位置</option><option value="theoretical">复位理论位置</option></select></label></div>
      {calibration && <div className="table-scroll"><table><thead><tr><th>谱线</th><th>理论 (nm)</th><th>原保存 (nm)</th><th>实测 (nm)</th><th>寻峰</th></tr></thead><tbody>
        {calibration.positions.filter(row => scope === 'all' || row.line_type === 'baseline').map(row => <tr key={row.line_id}><td>{row.element}</td><td>{row.theoretical_wavelength_nm.toFixed(5)}</td><td>{row.stored_wavelength_nm.toFixed(5)}</td><td>{row.measured_wavelength_nm.toFixed(5)}</td><td>{row.found ? '有效峰' : '未找到有效峰'}</td></tr>)}
      </tbody></table></div>}
      <div className="viewer-dialog-actions"><button className="primary-button" disabled={!p.canSaveMethod || calibrating || !calibration || (mode === 'measured' && calibration.positions.filter(row => scope === 'all' || row.line_type === 'baseline').some(row => !row.found))} onClick={() => void saveCalibration()}>保存位置为方法草稿</button><button className="secondary-button" onClick={() => setDialog(null)}>关闭</button></div>
    </ViewerDialog>}
    {dialog === 'point' && pointDetails && picked != null && <ViewerDialog title="谱图点位明细" onClose={() => setDialog(null)}>
      <SpectrumPointDetails {...pointDetails} point={picked} />
    </ViewerDialog>}
  </LegacyViewingDesk>
}
