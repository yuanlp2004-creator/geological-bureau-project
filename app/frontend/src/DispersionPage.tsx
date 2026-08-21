import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, ArrowLeft, ArrowRight, Crosshair, PauseCircle, PlayCircle, Plus, RefreshCw, Save, SlidersHorizontal, Square, Trash2, Zap } from 'lucide-react'
import { api, type DispersionCalibrationVersion, type DispersionLine, type DispersionOptions, type DispersionTask, type MethodRecord } from './api'
import { CopyableCode } from './InformationDisplay'
import { NumericInput, reportInvalidNumericInput } from './NumericInput'
import { SimpleChartAxes } from './SimpleChartAxes'
import './dispersion.css'

type Props = {
  token: string
  canWrite: boolean
  canExecute: boolean
  onToast: (message: string) => void
}

const runningStates = new Set(['pre_excitation', 'burn', 'dark'])
const statusLabels: Record<string, string> = {
  draft: '待开始', pre_excitation: '预激发', burn: '燃烧采集', dark: '暗帧采集', paused: '已暂停',
  stopping: '收尾中', completed: '已完成', failed: '失败', stopped: '已停止',
}

type CurveGeometry = { path: string; minimum: number; maximum: number }

function curveGeometry(points: number[]): CurveGeometry {
  if (!points.length) return { path: '', minimum: 0, maximum: 1 }
  const stride = Math.max(1, Math.ceil(points.length / 800))
  const visible = points.filter((_, index) => index % stride === 0)
  const minimum = Math.min(...visible)
  const maximum = Math.max(...visible)
  const span = Math.max(maximum - minimum, 1)
  const path = visible.map((value, index) => {
    const x = index / Math.max(visible.length - 1, 1) * 1000
    const y = 248 - (value - minimum) / span * 224
    return `${index ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
  return { path, minimum, maximum }
}

type PositionMarker = {
  key: string
  kind: 'expected' | 'located'
  label: string
  position: number
  x: number
  labelY: number
}

function positionMarkers(lines: DispersionLine[], ccdIndex: number, pointsPerCcd: number): PositionMarker[] {
  if (pointsPerCcd <= 1) return []
  const markers: PositionMarker[] = []
  const markerDefinitions: Array<{ kind: PositionMarker['kind']; field: 'expected_position' | 'located_position'; label: string; labelY: number }> = [
    { kind: 'expected', field: 'expected_position', label: '预期', labelY: 38 },
    { kind: 'located', field: 'located_position', label: '实测', labelY: 62 },
  ]
  lines.filter((line) => line.ccd_index === ccdIndex).forEach((line) => {
    markerDefinitions.forEach((definition) => {
      const position = line[definition.field]
      if (position === null || !Number.isFinite(position)) return
      const bounded = Math.max(0, Math.min(pointsPerCcd - 1, position))
      markers.push({
        key: `${line.id}-${definition.kind}`,
        kind: definition.kind,
        label: `${line.element} ${line.wavelength_nm.toFixed(4)} nm · ${definition.label} ${position.toFixed(2)}`,
        position,
        x: bounded / (pointsPerCcd - 1) * 1000,
        labelY: definition.labelY,
      })
    })
  })
  return markers
}

function replaceLine(task: DispersionTask, line: DispersionLine): DispersionTask {
  return { ...task, lines: task.lines.map((item) => item.id === line.id ? line : item) }
}

export function DispersionPage({ token, canWrite, canExecute, onToast }: Props) {
  const [options, setOptions] = useState<DispersionOptions | null>(null)
  const [tasks, setTasks] = useState<DispersionTask[]>([])
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [active, setActive] = useState<DispersionTask | null>(null)
  const [profileId, setProfileId] = useState<number | null>(null)
  const [layoutId, setLayoutId] = useState<number | null>(null)
  const [frameCount, setFrameCount] = useState(3)
  const [darkFrameCount, setDarkFrameCount] = useState(1)
  const [selectedCcd, setSelectedCcd] = useState(0)
  const [element, setElement] = useState('Fe')
  const [wavelength, setWavelength] = useState(253.65)
  const [lineCcd, setLineCcd] = useState(0)
  const [calibrationName, setCalibrationName] = useState('S12 色散校准')
  const [bindMethodId, setBindMethodId] = useState<number | null>(null)
  const [autoRun, setAutoRun] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    try {
      const [nextOptions, nextTasks, nextMethods] = await Promise.all([
        api.dispersionOptions(token), api.dispersionTasks(token), api.methods(token),
      ])
      setOptions(nextOptions)
      setTasks(nextTasks)
      setActive((current) => current ? nextTasks.find((item) => item.id === current.id) ?? nextTasks[0] ?? null : nextTasks[0] ?? null)
      setMethods(nextMethods.filter((item) => item.current_version !== null && item.status !== 'deleted'))
      setProfileId((current) => current ?? nextOptions.device_profiles[0]?.id ?? null)
      setLayoutId((current) => current ?? nextOptions.ccd_layouts[0]?.id ?? null)
      setBindMethodId((current) => current ?? nextMethods.find((item) => item.current_version !== null)?.id ?? null)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取色散任务')
    } finally {
      setBusy(false)
    }
  }, [onToast, token])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!active || !active.ccd_indices.includes(selectedCcd)) setSelectedCcd(active?.ccd_indices[0] ?? 0)
    if (!active || !active.ccd_indices.includes(lineCcd)) setLineCcd(active?.ccd_indices[0] ?? 0)
  }, [active, lineCcd, selectedCcd])
  useEffect(() => {
    if (!autoRun || !active || !runningStates.has(active.status) || busy) return
    const timer = window.setTimeout(() => {
      setBusy(true)
      void api.stepDispersionTask(token, active.id).then((task) => {
        setActive(task)
        setTasks((current) => current.map((item) => item.id === task.id ? task : item))
        if (!runningStates.has(task.status)) setAutoRun(false)
      }).catch((error) => {
        setAutoRun(false)
        onToast(error instanceof Error ? error.message : '采集帧失败')
      }).finally(() => setBusy(false))
    }, 850)
    return () => window.clearTimeout(timer)
  }, [active, autoRun, busy, onToast, token])

  const currentCcd = active?.last_event?.ccds.find((item) => item.ccd_index === selectedCcd) ?? active?.last_event?.ccds[0]
  const curve = useMemo(() => curveGeometry(currentCcd?.points ?? []), [currentCcd?.points])
  const markers = useMemo(
    () => positionMarkers(active?.lines ?? [], selectedCcd, active?.layout.points_per_ccd ?? 0),
    [active?.layout.points_per_ccd, active?.lines, selectedCcd],
  )
  const latestCalibration = active?.calibrations[0] ?? null

  const createTask = async () => {
    if (!canWrite || profileId === null || layoutId === null) return
    if (!reportInvalidNumericInput(document.querySelector('.dispersion-number-grid'))) return onToast('请先修正采集帧参数')
    setBusy(true)
    try {
      const task = await api.createDispersionTask(token, {
        name: `色散采集 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`,
        device_profile_id: profileId, ccd_layout_id: layoutId, frame_count: frameCount,
        dark_frame_count: darkFrameCount, pre_excitation_seconds: 3, sampling_period_seconds: 1,
        residual_limit_points: 2, sample: '280-288.acq', seed: 12,
      })
      setTasks((current) => [task, ...current])
      setActive(task)
      onToast('色散采集任务已创建')
    } catch (error) { onToast(error instanceof Error ? error.message : '无法创建任务') }
    finally { setBusy(false) }
  }

  const applyTask = (task: DispersionTask) => {
    setActive(task)
    setTasks((current) => current.map((item) => item.id === task.id ? task : item))
  }

  const start = async () => {
    if (!active || !canExecute) return
    setBusy(true)
    try {
      const task = await api.startDispersionTask(token, active.id)
      applyTask(task)
      setAutoRun(true)
      onToast('色散采集已开始')
    } catch (error) { onToast(error instanceof Error ? error.message : '无法开始采集') }
    finally { setBusy(false) }
  }

  const pause = async () => {
    if (!active) return
    setAutoRun(false)
    try { applyTask(await api.pauseDispersionTask(token, active.id)); onToast('采集已暂停') }
    catch (error) { onToast(error instanceof Error ? error.message : '无法暂停') }
  }

  const resume = async () => {
    if (!active) return
    try { applyTask(await api.resumeDispersionTask(token, active.id)); setAutoRun(true); onToast('采集已继续') }
    catch (error) { onToast(error instanceof Error ? error.message : '无法继续') }
  }

  const stop = async () => {
    if (!active) return
    setAutoRun(false)
    try { applyTask(await api.stopDispersionTask(token, active.id)); onToast('采集已安全收尾') }
    catch (error) { onToast(error instanceof Error ? error.message : '无法停止') }
  }

  const step = async () => {
    if (!active || busy) return
    setBusy(true)
    try { applyTask(await api.stepDispersionTask(token, active.id)) }
    catch (error) { onToast(error instanceof Error ? error.message : '采集帧失败') }
    finally { setBusy(false) }
  }

  const addLine = async () => {
    if (!active || !canWrite) return
    if (!reportInvalidNumericInput(document.querySelector('.dispersion-line-form'))) return onToast('请先修正谱线波长')
    try {
      const line = await api.addDispersionLine(token, active.id, { element, wavelength_nm: wavelength, ccd_index: lineCcd })
      setActive({ ...active, lines: [...active.lines, line].sort((left, right) => left.wavelength_nm - right.wavelength_nm) })
      onToast('已知谱线已添加')
    } catch (error) { onToast(error instanceof Error ? error.message : '无法添加谱线') }
  }

  const updateLine = async (line: DispersionLine, action: 'locate' | 'short' | 'long' | 'save' | 'restore') => {
    if (!active) return
    try {
      const next = action === 'locate' ? await api.locateDispersionLine(token, active.id, line.id)
        : action === 'short' || action === 'long' ? await api.moveDispersionLine(token, active.id, line.id, action)
          : action === 'save' ? await api.saveDispersionLinePosition(token, active.id, line.id)
            : await api.restoreDispersionLinePosition(token, active.id, line.id)
      setActive(replaceLine(active, next))
    } catch (error) { onToast(error instanceof Error ? error.message : '谱线位置操作失败') }
  }

  const locateAll = async () => {
    if (!active) return
    try {
      const result = await api.locateAllDispersionLines(token, active.id)
      setActive({ ...active, lines: active.lines.map((line) => result.located.find((item) => item.id === line.id) ?? line) })
      onToast(result.all_succeeded ? '全部谱线定位完成' : `${result.errors.length} 条谱线定位失败`)
    } catch (error) { onToast(error instanceof Error ? error.message : '全部定位失败') }
  }

  const removeLine = async (lineId: number) => {
    if (!active) return
    try { await api.deleteDispersionLine(token, active.id, lineId); setActive({ ...active, lines: active.lines.filter((line) => line.id !== lineId) }) }
    catch (error) { onToast(error instanceof Error ? error.message : '删除谱线失败') }
  }

  const fit = async () => {
    if (!active) return
    try {
      const calibration = await api.fitDispersionCalibration(token, active.id, { name: calibrationName, degree: 2 })
      setActive({ ...active, calibrations: [calibration, ...active.calibrations] })
      onToast(calibration.publishable ? '拟合完成，可发布校准版本' : '拟合完成，但残差超过阈值')
    } catch (error) { onToast(error instanceof Error ? error.message : '拟合失败') }
  }

  const publish = async (calibration: DispersionCalibrationVersion) => {
    if (!active) return
    try {
      const published = await api.publishDispersionCalibration(token, calibration.id)
      setActive({ ...active, calibrations: active.calibrations.map((item) => item.id === published.id ? published : item) })
      onToast('不可变校准版本已发布')
    } catch (error) { onToast(error instanceof Error ? error.message : '校准版本不能发布') }
  }

  const bind = async () => {
    if (!latestCalibration || bindMethodId === null) return
    const method = methods.find((item) => item.id === bindMethodId)
    try {
      await api.bindDispersionCalibration(token, latestCalibration.id, bindMethodId, method?.current_version ?? undefined)
      onToast(`已绑定 ${method?.name ?? '方法'} 修订 v${method?.current_version ?? ''}`)
    } catch (error) { onToast(error instanceof Error ? error.message : '方法绑定失败') }
  }

  return <div className="page-content dispersion-page" data-testid="dispersion-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />DISPERSION ACQUISITION</span><h1>色散采集、校准与方法绑定</h1><p>用确定性 ACQ 帧完成燃烧/暗帧时序、已知谱线定位和不可变校准版本发布，不修改原始帧。</p></div><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />刷新</button></section>
    <div className="dispersion-shell">
      <aside className="surface dispersion-sidebar">
        <div className="surface-heading"><div><span className="section-kicker">TASK SETUP</span><h2>采集条件</h2></div><Zap size={17} /></div>
        <label className="field"><span>设备档案</span><select value={profileId ?? ''} onChange={(event) => setProfileId(Number(event.target.value))}>{options?.device_profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.transport}</option>)}</select></label>
        <label className="field"><span>CCD 布局</span><select value={layoutId ?? ''} onChange={(event) => setLayoutId(Number(event.target.value))}>{options?.ccd_layouts.map((layout) => <option key={layout.id} value={layout.id}>{layout.name} · {layout.frame_count}×{layout.ccds_per_frame}</option>)}</select></label>
        <div className="dispersion-number-grid"><label className="field"><span>燃烧帧</span><NumericInput min={1} max={255} value={frameCount} onValueChange={setFrameCount} /></label><label className="field"><span>暗帧</span><NumericInput min={0} max={20} value={darkFrameCount} onValueChange={setDarkFrameCount} /></label></div>
        <button className="primary-button full-button" onClick={() => void createTask()} disabled={!canWrite || busy || profileId === null || layoutId === null}><Plus size={15} />新建任务</button>
        <div className="dispersion-task-list"><span className="section-kicker">TASKS</span>{tasks.length === 0 ? <small>尚无色散任务</small> : tasks.map((task) => <button key={task.id} className={active?.id === task.id ? 'active' : ''} onClick={() => setActive(task)}><span className={`dispersion-state ${task.status}`} /> <strong title={task.name}>{task.name}</strong><small>{statusLabels[task.status]} · {task.burn_frames_captured}/{task.frame_count}</small></button>)}</div>
      </aside>
      <main className="dispersion-main">
        <section className="surface dispersion-run-panel">
          <div className="surface-heading"><div><span className="section-kicker">ACQUISITION STATE</span><h2>{active?.name ?? '选择或创建任务'}</h2></div>{active && <span className={`state-chip ${active.status}`}>{statusLabels[active.status]}</span>}</div>
          {active ? <><div className="dispersion-progress"><div><span>燃烧帧</span><strong>{active.burn_frames_captured} / {active.frame_count}</strong><progress max={active.frame_count} value={active.burn_frames_captured} /></div><div><span>暗帧</span><strong>{active.dark_frames_captured} / {active.dark_frame_count}</strong><progress max={Math.max(active.dark_frame_count, 1)} value={active.dark_frames_captured} /></div><div><span>CCD</span><strong>{active.ccd_indices.length} × {active.layout.points_per_ccd}</strong><small>原始帧只读保存</small></div></div>
            <div className="dispersion-controls"><button className="primary-button" onClick={() => void start()} disabled={!canExecute || active.status !== 'draft'}><PlayCircle size={15} />开始</button><button className="secondary-button" onClick={() => void pause()} disabled={!canExecute || !runningStates.has(active.status)}><PauseCircle size={15} />暂停</button><button className="secondary-button" onClick={() => void resume()} disabled={!canExecute || active.status !== 'paused'}><PlayCircle size={15} />继续</button><button className="secondary-button" onClick={() => void step()} disabled={!canExecute || !runningStates.has(active.status) || busy}><Activity size={15} />单帧</button><button className="secondary-button danger" onClick={() => void stop()} disabled={!canExecute || ![...runningStates, 'paused'].includes(active.status)}><Square size={14} />停止</button></div>
            <div className="dispersion-curve-toolbar"><label className="field compact-field"><span>当前 CCD</span><select value={selectedCcd} onChange={(event) => setSelectedCcd(Number(event.target.value))}>{active.ccd_indices.map((ccd) => <option value={ccd} key={ccd}>CCD {ccd + 1}</option>)}</select></label><span><Crosshair size={14} />峰值 {currentCcd ? `${currentCcd.peak} @ ${currentCcd.peak_position + 1}` : '--'}</span><div className="dispersion-marker-legend" aria-label="谱线位置图例"><span><i className="expected" />预期</span><span><i className="located" />实测</span></div><CopyableCode value={active.last_event?.details.sha256} visibleLength={16} empty="--" /></div>
            <div className="dispersion-curve simple-chart-plot-host">
              <div className="simple-chart-plot">
                <svg viewBox="0 0 1000 260" preserveAspectRatio="none" role="img" aria-label={`CCD ${selectedCcd + 1} 色散曲线与谱线定位`}><g className="dispersion-grid"><line x1="0" y1="24" x2="1000" y2="24" /><line x1="0" y1="136" x2="1000" y2="136" /><line x1="0" y1="248" x2="1000" y2="248" /></g><path className="dispersion-spectrum-line" d={curve.path} />{currentCcd && <g className="dispersion-position-markers">{markers.map((marker) => <g key={marker.key} className={`dispersion-position-marker ${marker.kind}`} data-marker-kind={marker.kind} data-marker-position={marker.position.toFixed(2)}><title>{marker.label}</title><line x1={marker.x} y1="24" x2={marker.x} y2="248" /><circle cx={marker.x} cy={marker.labelY - 5} r="5" /></g>)}</g>}</svg>
                {currentCcd && markers.length > 0 && <div className="dispersion-marker-label-layer" aria-hidden="true">{markers.map((marker) => {
                  const placeOnLeft = marker.x > 650
                  return <span key={marker.key} className={`dispersion-marker-label ${marker.kind} ${placeOnLeft ? 'align-end' : ''}`} style={{ left: `calc(${marker.x / 10}% ${placeOnLeft ? '-' : '+'} 11px)`, top: `${marker.labelY - 15}px` }}>{marker.label}</span>
                })}</div>}
                {currentCcd && markers.length === 0 && <span className="dispersion-marker-empty">当前 CCD 尚无已添加的定位谱线</span>}
              </div>
              {currentCcd && <SimpleChartAxes xMin={1} xMax={active.layout.points_per_ccd} yMin={curve.minimum} yMax={curve.maximum} xLabel="CCD 点位" yLabel="强度 (ADC)" />}
              {!currentCcd && <div className="dispersion-curve-empty"><Activity size={22} /><span>开始采集后显示实时 CCD 曲线</span></div>}
            </div>
          </> : <div className="dispersion-empty"><Activity size={28} /><p>配置设备档案和帧数后创建色散任务。</p></div>}
        </section>
        {active && <section className="surface dispersion-lines-panel">
          <div className="surface-heading"><div><span className="section-kicker">KNOWN LINES</span><h2>谱线定位与位置</h2></div><button className="secondary-button" onClick={() => void locateAll()} disabled={!canWrite || active.lines.length === 0 || active.burn_frames_captured === 0}><Crosshair size={15} />全部定位</button></div>
          <div className="dispersion-line-form"><label className="field"><span>元素</span><input value={element} onChange={(event) => setElement(event.target.value)} /></label><label className="field"><span>波长 (nm)</span><NumericInput min={0} step={0.0001} value={wavelength} onValueChange={setWavelength} /></label><label className="field"><span>CCD</span><select value={lineCcd} onChange={(event) => setLineCcd(Number(event.target.value))}>{active.ccd_indices.map((ccd) => <option key={ccd} value={ccd}>CCD {ccd + 1}</option>)}</select></label><button className="primary-button" onClick={() => void addLine()} disabled={!canWrite}><Plus size={15} />添加</button></div>
          <div className="dispersion-line-table"><table><thead><tr><th>谱线</th><th>CCD</th><th>预期位置</th><th>实测 / 保存</th><th>定位操作</th></tr></thead><tbody>{active.lines.length === 0 ? <tr><td colSpan={5} className="empty-cell">添加至少 3 条已知谱线后可拟合校准。</td></tr> : active.lines.map((line) => <tr key={line.id}><td><strong>{line.element}</strong><small>{line.wavelength_nm.toFixed(4)} nm</small></td><td>CCD {line.ccd_index + 1}</td><td>{line.expected_position?.toFixed(2) ?? '越界'}</td><td><strong>{line.located_position?.toFixed(2) ?? '--'}</strong><small>保存 {line.saved_position?.toFixed(2) ?? '--'}</small></td><td><div className="line-actions"><button title="定位" onClick={() => void updateLine(line, 'locate')} disabled={!canWrite || active.burn_frames_captured === 0}><Crosshair size={14} /></button><button title="向短波移动" onClick={() => void updateLine(line, 'short')} disabled={!canWrite}><ArrowLeft size={14} /></button><button title="向长波移动" onClick={() => void updateLine(line, 'long')} disabled={!canWrite}><ArrowRight size={14} /></button><button title="保存实测位置" onClick={() => void updateLine(line, 'save')} disabled={!canWrite || line.located_position === null}><Save size={14} /></button><button title="恢复保存位置" onClick={() => void updateLine(line, 'restore')} disabled={!canWrite || line.saved_position === null}><RefreshCw size={14} /></button><button title="删除谱线" onClick={() => void removeLine(line.id)} disabled={!canWrite}><Trash2 size={14} /></button></div></td></tr>)}</tbody></table></div>
        </section>}
        {active && <section className="surface dispersion-fit-panel">
          <div className="surface-heading"><div><span className="section-kicker">CALIBRATION VERSION</span><h2>拟合、发布与方法绑定</h2></div><SlidersHorizontal size={17} /></div>
          <div className="dispersion-fit-form"><label className="field"><span>校准名称</span><input value={calibrationName} onChange={(event) => setCalibrationName(event.target.value)} /></label><button className="primary-button" onClick={() => void fit()} disabled={!canWrite || active.lines.filter((line) => line.saved_position !== null || line.located_position !== null).length < 3}>二次拟合</button>{latestCalibration?.state === 'draft' && <button className="secondary-button" onClick={() => void publish(latestCalibration)} disabled={!canWrite || !latestCalibration.publishable}>发布版本</button>}</div>
          {latestCalibration ? <div className="calibration-result"><div><span>版本</span><strong title={`${latestCalibration.name} · v${latestCalibration.version}`}>{latestCalibration.name} · v{latestCalibration.version}</strong><small>{latestCalibration.state}</small></div><div><span>有效波段</span><strong>{latestCalibration.wavelength_min.toFixed(4)}–{latestCalibration.wavelength_max.toFixed(4)} nm</strong><small>{latestCalibration.point_count} 个定位点</small></div><div><span>残差</span><strong>RMS {latestCalibration.residual_rms.toFixed(4)}</strong><small>最大 {latestCalibration.residual_max.toFixed(4)} / 阈值 {latestCalibration.residual_limit_points}</small></div><div><span>系数</span><code title={latestCalibration.coefficients.map((value) => value.toExponential(4)).join(' · ')}>{latestCalibration.coefficients.map((value) => value.toExponential(4)).join(' · ')}</code></div></div> : <div className="dispersion-empty compact"><p>保存至少三个定位点后生成校准草稿。</p></div>}
          {latestCalibration?.state === 'published' && <div className="dispersion-bind"><label className="field"><span>绑定已发布方法修订</span><select value={bindMethodId ?? ''} onChange={(event) => setBindMethodId(Number(event.target.value))}>{methods.map((method) => <option value={method.id} key={method.id}>{method.name} · v{method.current_version}</option>)}</select></label><button className="primary-button" onClick={() => void bind()} disabled={!canWrite || bindMethodId === null}>绑定修订</button><small>绑定记录独立保存，不原地修改方法版本。</small></div>}
        </section>}
      </main>
    </div>
  </div>
}
