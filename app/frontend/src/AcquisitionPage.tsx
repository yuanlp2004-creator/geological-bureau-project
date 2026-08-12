import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { Activity, Cable, CheckCircle2, Clock3, Crosshair, Gauge, PauseCircle, PlayCircle, Radio, RefreshCw, RotateCcw, SlidersHorizontal, Square, XCircle, ZoomIn, ZoomOut } from 'lucide-react'
import { api, type DeviceCcd, type DeviceDiagnostics, type DeviceEvent, type DeviceProfile } from './api'
import { SimpleChartAxes } from './SimpleChartAxes'
import './acquisition.css'

type AcquisitionPageProps = { token: string; canWrite: boolean; canExecute: boolean; onToast: (message: string) => void }

const SAMPLE_OPTIONS = ['280-288.acq', '291-299.acq', '303-310.acq']
const EMPTY_POINTS: number[] = []

type CurveGeometry = { path: string; min: number; span: number }

function curveY(value: number, min: number, span: number, yZoom: number): number {
  return Math.max(4, Math.min(252, 248 - ((value - min) / span * 218 * yZoom)))
}

function curveGeometry(points: number[], xZoom: number, yZoom: number): CurveGeometry {
  if (!points.length) return { path: '', min: 0, span: 1 }
  const stride = Math.max(1, Math.ceil(points.length / 720))
  const visible = points.map((value, pointIndex) => ({ value, pointIndex })).filter(({ pointIndex }) => pointIndex % stride === 0 || pointIndex === points.length - 1)
  const min = Math.min(...visible.map(({ value }) => value), 0)
  const sampledMax = Math.max(...visible.map(({ value }) => value), 1)
  const span = Math.max(sampledMax - min, 1)
  const width = 1000 * xZoom
  const path = visible.map(({ value, pointIndex }, index) => {
    const x = pointIndex / Math.max(points.length - 1, 1) * width
    return `${index ? 'L' : 'M'}${x.toFixed(2)},${curveY(value, min, span, yZoom).toFixed(2)}`
  }).join(' ')
  return { path, min, span }
}

function peakOf(ccd: DeviceCcd | undefined): string {
  return ccd ? `${ccd.peak.toLocaleString('zh-CN')} @ ${ccd.peak_position + 1}` : '--'
}

export function AcquisitionPage({ token, canWrite, canExecute, onToast }: AcquisitionPageProps) {
  const [diagnostics, setDiagnostics] = useState<DeviceDiagnostics | null>(null)
  const [selectedProfile, setSelectedProfile] = useState<number | null>(null)
  const [event, setEvent] = useState<DeviceEvent | null>(null)
  const [ccdIndex, setCcdIndex] = useState(0)
  const [sample, setSample] = useState(SAMPLE_OPTIONS[0])
  const [seed, setSeed] = useState(11)
  const [running, setRunning] = useState(false)
  const [crosshair, setCrosshair] = useState(true)
  const [crosshairPoint, setCrosshairPoint] = useState<number | null>(null)
  const [xZoom, setXZoom] = useState(1)
  const [xOffset, setXOffset] = useState(0)
  const [yZoom, setYZoom] = useState(1)
  const [loading, setLoading] = useState(false)
  const stepInFlight = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await api.deviceDiagnostics(token)
      setDiagnostics(next)
      setSelectedProfile((current) => current ?? next.profiles[0]?.id ?? null)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取设备诊断')
    } finally {
      setLoading(false)
    }
  }, [onToast, token])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      if (stepInFlight.current) return
      stepInFlight.current = true
      void api.stepDeviceDebug(token).then((result) => {
        setEvent(result.event)
        setDiagnostics((current) => current ? { ...current, adapter: result.diagnostics } : current)
        if (result.event.event_type === 'fault') {
          setRunning(false)
          onToast('模拟 CCD 故障，调试已停止并保留诊断信息')
        }
      }).catch((error) => {
        setRunning(false)
        onToast(error instanceof Error ? error.message : '实时调试连接失败')
      }).finally(() => { stepInFlight.current = false })
    }, 850)
    return () => { window.clearInterval(timer); stepInFlight.current = false }
  }, [onToast, running, token])

  const profile = diagnostics?.profiles.find((item) => item.id === selectedProfile) ?? diagnostics?.profiles[0]
  const selectedCcd = event?.ccds.find((item) => item.ccd_index === ccdIndex) ?? event?.ccds[0]
  const selectedCcds = event?.ccds ?? []
  const selectedPoints = selectedCcd?.points ?? EMPTY_POINTS
  const conversion = profile?.screen_conversion
  const curve = useMemo(() => curveGeometry(selectedPoints, xZoom, yZoom), [selectedPoints, xZoom, yZoom])
  const maxXOffset = Math.max(0, 1000 * xZoom - 1000)
  const visiblePointStart = selectedPoints.length ? xOffset / Math.max(1000 * xZoom, 1) * (selectedPoints.length - 1) + 1 : 1
  const visiblePointEnd = selectedPoints.length ? Math.min(1, (xOffset + 1000) / Math.max(1000 * xZoom, 1)) * (selectedPoints.length - 1) + 1 : 1
  const visibleIntensityMin = curve.min
  const visibleIntensityMax = curve.min + curve.span / Math.max(yZoom, .0001)
  const crosshairDatum = crosshairPoint == null || !selectedCcd || selectedPoints[crosshairPoint] == null ? null : {
    ccd: selectedCcd.ccd_index,
    point: crosshairPoint,
    value: selectedPoints[crosshairPoint],
    x: crosshairPoint / Math.max(selectedPoints.length - 1, 1) * 1000 * xZoom,
    y: curveY(selectedPoints[crosshairPoint], curve.min, curve.span, yZoom),
  }

  const connect = async () => {
    if (!canExecute || !profile) return onToast('当前账户没有设备执行权限')
    try {
      const result = await api.connectDevice(token, profile.id)
      setDiagnostics((current) => current ? { ...current, adapter: result.diagnostics } : current)
      setEvent(result.event)
      onToast('模拟设备已连接')
    } catch (error) { onToast(error instanceof Error ? error.message : '设备连接失败') }
  }
  const start = async () => {
    if (!canExecute) return onToast('当前账户没有设备执行权限')
    try {
      const result = await api.startDeviceDebug(token, { sample, seed })
      setEvent(result.event)
      setRunning(true)
      setDiagnostics((current) => current ? { ...current, adapter: result.diagnostics } : current)
      onToast('实时调试已开始，数据不会写入样品记录')
    } catch (error) { onToast(error instanceof Error ? error.message : '无法启动实时调试') }
  }
  const stop = async () => {
    setRunning(false)
    try {
      const result = await api.stopDeviceDebug(token)
      setEvent(result.event)
      setDiagnostics((current) => current ? { ...current, adapter: result.diagnostics } : current)
      onToast('调试已停止，未生成样品/谱图记录')
    } catch (error) { onToast(error instanceof Error ? error.message : '停止调试失败') }
  }
  const disconnect = async () => {
    setRunning(false)
    try {
      const result = await api.disconnectDevice(token)
      setEvent(result.event)
      setDiagnostics((current) => current ? { ...current, adapter: result.diagnostics } : current)
      onToast('设备已断开')
    } catch (error) { onToast(error instanceof Error ? error.message : '设备断开失败') }
  }
  const onChartMove = (mouseEvent: MouseEvent<SVGSVGElement>) => {
    if (!crosshair || !selectedPoints.length) return
    const bounds = mouseEvent.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (mouseEvent.clientX - bounds.left) / bounds.width))
    const pointRatio = (xOffset + ratio * 1000) / Math.max(1000 * xZoom, 1)
    setCrosshairPoint(Math.round(Math.max(0, Math.min(1, pointRatio)) * (selectedPoints.length - 1)))
  }

  return <div className="page-content acquisition-page" data-testid="acquisition-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />DEVICE & REAL-TIME DEBUG</span><h1>设备与实时调试</h1><p>使用确定性 ACQ 模拟器观察 CCD 曲线、峰值和连接状态。调试流不会创建样品或谱图记录。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} />刷新诊断</button></section>
    <div className="acquisition-layout">
      <aside className="surface acquisition-sidebar">
        <div className="surface-heading"><div><span className="section-kicker">DEVICE PROFILE</span><h2>设备档案</h2></div><SlidersHorizontal size={17} /></div>
        <label className="field"><span>当前档案</span><select value={selectedProfile ?? ''} onChange={(e) => setSelectedProfile(Number(e.target.value))} disabled={!diagnostics?.profiles.length}>{diagnostics?.profiles.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        {profile && <div className="device-facts"><div><span>传输</span><strong>{profile.transport === 'simulator' ? 'ACQ 模拟器' : '串口设备'}</strong></div><div><span>串口 / 波特率</span><strong>COM {profile.port} / {profile.baud_rate.toLocaleString()}</strong></div><div><span>CCD 布局</span><strong>{profile.frame_count} 组 × {profile.ccds_per_frame} / {profile.points_per_ccd} 点</strong></div><div><span>保护时间</span><strong>{profile.protection_time_ms} ms</strong></div><div><span>屏幕换算</span><strong>{conversion ? `${conversion.pixels_per_mm.toFixed(2)} px/mm` : '--'}</strong></div></div>}
        <div className="device-actions"><button className="primary-button" onClick={() => void connect()} disabled={!canExecute || diagnostics?.adapter.connected}><Cable size={15} />连接诊断</button><button className="secondary-button" onClick={() => void disconnect()} disabled={!canExecute || !diagnostics?.adapter.connected}><XCircle size={15} />断开</button></div>
        <div className="diagnostic-state"><span className={`status-dot ${diagnostics?.adapter.connected ? 'online' : 'offline'}`} /><div><span>适配器状态</span><strong>{diagnostics?.adapter.state ?? 'unknown'}</strong></div><Radio size={15} /></div>
      </aside>
      <main className="surface acquisition-workbench">
        <div className="surface-heading"><div><span className="section-kicker">CCD STREAM</span><h2>实时曲线</h2></div><div className="debug-state"><span className={`state-chip ${event?.state ?? 'idle'}`}>{event?.state ?? 'idle'}</span>{event?.event_type === 'fault' ? <AlertIcon /> : event ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}</div></div>
        <div className="debug-toolbar"><label className="field compact-field"><span>模拟样本</span><select value={sample} onChange={(e) => setSample(e.target.value)} disabled={running}>{SAMPLE_OPTIONS.map((item) => <option key={item}>{item}</option>)}</select></label><label className="field compact-field"><span>随机种子</span><input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} disabled={running} /></label><label className="field compact-field"><span>CCD</span><select value={ccdIndex} onChange={(e) => { setCcdIndex(Number(e.target.value)); setCrosshairPoint(null) }}>{(profile?.ccd_indices ?? selectedCcds.map((item) => item.ccd_index)).map((item) => <option value={item} key={item}>CCD {item + 1}</option>)}</select></label><div className="debug-command"><button className="primary-button" onClick={() => void start()} disabled={!canExecute || running || !diagnostics?.adapter.connected}><PlayCircle size={15} />开始</button><button className="secondary-button" onClick={() => void stop()} disabled={!running}><Square size={14} />停止</button></div></div>
        <div className="curve-tools"><button className={`icon-button compact ${crosshair ? 'selected' : ''}`} title="十字线" aria-pressed={crosshair} onClick={() => { setCrosshair((value) => !value); setCrosshairPoint(null) }}><Crosshair size={15} /></button><button className="icon-button compact" title="横向放大" onClick={() => { setXZoom((value) => Math.min(4, value + .5)); setXOffset(0) }}><ZoomIn size={15} /></button><button className="icon-button compact" title="横向缩小" onClick={() => { setXZoom((value) => Math.max(.5, value - .5)); setXOffset(0) }}><ZoomOut size={15} /></button><button className="icon-button compact" title="还原视图" onClick={() => { setXZoom(1); setXOffset(0); setYZoom(1); setCrosshairPoint(null) }}><RotateCcw size={15} /></button><div className="zoom-presets" role="group" aria-label="横向缩放预设"><button onClick={() => { setXZoom(1); setXOffset(0) }}>适配</button><button onClick={() => { setXZoom(1); setXOffset(0) }}>100%</button><button onClick={() => { setXZoom(4); setXOffset(0) }}>400%</button></div><label className="range-control"><span>X {Math.round(xZoom * 100)}%</span><input type="range" min=".5" max="4" step=".5" value={xZoom} onChange={(e) => { setXZoom(Number(e.target.value)); setXOffset(0) }} /></label><label className="range-control"><span>Y {Math.round(yZoom * 100)}%</span><input type="range" min=".5" max="4" step=".5" value={yZoom} onChange={(e) => setYZoom(Number(e.target.value))} /></label>{maxXOffset > 0 && <label className="range-control"><span>滚动</span><input type="range" min="0" max={maxXOffset} step="10" value={xOffset} onChange={(e) => setXOffset(Number(e.target.value))} /></label>}</div>
        <div className="curve-frame simple-chart-plot-host" role="img" aria-label="CCD 实时曲线">
          <div className="simple-chart-plot"><svg onMouseMove={onChartMove} onMouseLeave={() => setCrosshairPoint(null)} viewBox={`${xOffset} 0 1000 260`} preserveAspectRatio="none"><g className="curve-grid"><line x1="0" y1="20" x2="1000" y2="20" /><line x1="0" y1="130" x2="1000" y2="130" /><line x1="0" y1="248" x2="1000" y2="248" /></g><path className="curve-path" d={curve.path} />{crosshair && crosshairDatum && <g data-testid="acquisition-crosshair"><line data-testid="acquisition-crosshair-x" className="curve-crosshair" x1={crosshairDatum.x} x2={crosshairDatum.x} y1="0" y2="260" /><line data-testid="acquisition-crosshair-y" className="curve-crosshair" x1={xOffset} x2={xOffset + 1000} y1={crosshairDatum.y} y2={crosshairDatum.y} /><circle className="curve-cursor" cx={crosshairDatum.x} cy={crosshairDatum.y} r="4" /></g>}</svg></div>
          {event && <SimpleChartAxes xMin={visiblePointStart} xMax={visiblePointEnd} yMin={visibleIntensityMin} yMax={visibleIntensityMax} xLabel="CCD 点位" yLabel="强度 (ADC)" />}
          {crosshair && crosshairDatum && <div className="curve-hover-readout" role="status" data-testid="acquisition-hover-readout"><span>CCD {crosshairDatum.ccd + 1}</span><strong>点 {crosshairDatum.point + 1}</strong><span>强度 {crosshairDatum.value.toLocaleString('zh-CN')}</span></div>}
          {!event && <div className="curve-empty"><Activity size={22} /><span>连接模拟设备后开始实时调试</span></div>}
        </div>
        <div className="curve-meta"><div><span>帧序</span><strong title={event?.frame_index == null ? '暂无帧' : `第 ${event.frame_index + 1} 帧`}>{event?.frame_index == null ? '--' : event.frame_index + 1}</strong></div><div><span>峰值 / 位置</span><strong title={peakOf(selectedCcd)}>{peakOf(selectedCcd)}</strong></div><div><span>帧哈希</span><code title={String(event?.details.sha256 ?? '暂无哈希')}>{event?.details.sha256?.slice(0, 16) ?? '--'}</code></div><div><span>记录写入</span><strong className="safe-result" title="0 样品 · 0 谱图">0 样品 · 0 谱图</strong></div></div>
        {event?.event_type === 'fault' && <div className="debug-error"><PauseCircle size={16} /><span>{event.message} · {String(event.details.code ?? 'unknown')}</span></div>}
      </main>
    </div>
  </div>
}

function AlertIcon() { return <PauseCircle size={16} className="warning-icon" /> }
