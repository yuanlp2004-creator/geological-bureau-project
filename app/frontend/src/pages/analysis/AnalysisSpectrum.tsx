import { useEffect, useRef, useState } from 'react'
import { getAnalysisSpectrum, type AnalysisRun, type AnalysisSpectrum as SpectrumData } from '../../api/analysis'
import { previewDailyCalibration, saveDailyCalibration, type CalibrationPreview } from '../../api/analysis'
import { SpectrumPlot, type SpectrumPlotCursor } from '../../components/SpectrumPlot'
import { limitSpectrumRange, stepSpectrumRange, ZOOM_IN, ZOOM_OUT, type SpectrumAxis } from '../../components/spectrumZoom'
import { NumericInput } from '../../components/NumericInput'
import { SpectrumPointDetails } from '../../components/SpectrumPointDetails'
import { AnalysisExposureControls, useAnalysisExposure } from './AnalysisExposure'

// 复用谱图绘制，读取当前分析样品的完整固化谱带，支持任意点和双轴缩放。
export function AnalysisSpectrum({ token, run, canSaveMethod = false, onToast = () => {},preferences }: { token: string; run: AnalysisRun; canSaveMethod?: boolean; onToast?: (message: string) => void;
  preferences?:{look_band:boolean;cmt_band_mean:boolean} }) {
  const [sample, setSample] = useState(0)
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null)
  useEffect(() => { setSelectedLineId(null) }, [token, run.id])
  const [data, setData] = useState<SpectrumData | null>(null)
  const [ccd, setCcd] = useState(0)
  const [turnIndex, setTurnIndex] = useState<number | undefined>()
  const [error, setError] = useState('')
  const [point, setPoint] = useState(1)
  const [range, setRange] = useState({ xMin: 1, xMax: 2048, yMin: 0, yMax: 1 })
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [locked, setLocked] = useState(false)
  const [focus, setFocus] = useState<{ ccd: number; point: number } | null>(null)
  const [calibration, setCalibration] = useState<CalibrationPreview | null>(null)
  const [positionMode, setPositionMode] = useState<'measured' | 'theoretical' | 'stored'>('measured')
  const [scope, setScope] = useState<'reference' | 'all'>('all')
  useEffect(() => {if(preferences?.look_band && ['running','paused'].includes(run.status))setSample(Math.max(0,Math.min(run.samples.length-1,run.current_sample_position)))},[run.current_sample_position,run.status,run.samples.length,preferences?.look_band])
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  useEffect(() => { generation.current++; setCalibration(null); return () => { generation.current++ } }, [token, run.id, sample])
  const previewCalibration = async () => {
    const current = generation.current
    setBusy(true)
    try {
      const next = await previewDailyCalibration(token, run.id, sample)
      if (current === generation.current) { setCalibration(next); setError('') }
    } catch (failure) { if (current === generation.current) setError(failure instanceof Error ? failure.message : '校线预览失败') }
    finally { setBusy(false) }
  }
  const saveCalibration = async () => {
    const current = generation.current
    setBusy(true)
    try {
      const next = await saveDailyCalibration(token, run.id, sample, positionMode, scope)
      if (current === generation.current) onToast(`位置已保存为方法草稿 v${next.latest_version}，请在方法页审核并发布`)
    } catch (failure) { if (current === generation.current) setError(failure instanceof Error ? failure.message : '位置保存失败') }
    finally { setBusy(false) }
  }
  // 切换身份或样品时撤销旧响应，避免用另一份谱带显示点值。
  useEffect(() => {
    let live = true
    setData(null)
    setError('')
    setFocus(null)
    getAnalysisSpectrum(token, run.id, sample, selectedLineId).then(
      // 成功响应只归属当前样品。
      next => { if (live) {
        setData(next)
        const line = next.lines.find((item) => item.id === selectedLineId)
        setCcd(line?.ccd_index ?? next.bands[0]?.ccd_index ?? 0)
        setTurnIndex(line?.turn_index ?? next.bands[0]?.turn_index)
        if (line) {
          const result = run.line_results.find((item) => item.sample_position === sample && item.line_id === line.id)
          setFocus({ ccd: line.ccd_index, point: result?.peak_position ?? line.point })
        }
      } },
      // 失败信息只归属当前请求。
      failure => { if (live) setError(failure instanceof Error ? failure.message : '谱图读取失败') }
    )
    // 取消过期响应回写。
    return () => { live = false }
  }, [token, run.id, sample, selectedLineId])
  const bandPosition = data?.bands.findIndex(item => item.ccd_index === ccd && item.turn_index === turnIndex) ?? -1
  const observation = useAnalysisExposure(token, run.id, sample, selectedLineId, bandPosition, data)
  const band = observation.band
  const activeInterval = observation.interval ?? data?.exposure_interval
  const points = band?.mean_points ?? []
  const full = { xMin: 1, xMax: Math.max(2, points.length), yMin: Math.min(0, ...points), yMax: Math.max(1, ...points) }
  const view = limitSpectrumRange(range, full)
  // 新谱带恢复全部视野及点位，避免沿用旧 CCD 的坐标。
  useEffect(() => {
    const center = focus?.ccd === ccd ? focus.point + 1 : null
    setRange(center === null ? full : limitSpectrumRange({ ...full, xMin: center - 30, xMax: center + 30 }, full))
    setPoint(center === null ? 1 : Math.round(center))
    setCursor(null)
    setLocked(false)
  }, [band, focus, ccd])
  const zoom = (axis: SpectrumAxis, factor: number) => setRange(stepSpectrumRange(view, full, axis, factor))
  return <section className="analysis-spectrum" aria-label="分析完整谱图">
    <div className="analysis-actions analysis-spectrum-tools">
      <label>查看样品 <select value={sample} onChange={/* 选择当前运行内样品。 */ event => setSample(Number(event.target.value))}>
        {run.samples.map(/* 列出运行内每次重复。 */ item => <option key={item.position} value={item.position}>{item.sample_name} · 重复 {item.position + 1}</option>)}
      </select></label>
      <label>CCD <select value={bandPosition} onChange={event => {
        setFocus(null)
        const next = data?.bands[Number(event.target.value)]
        if (next) { setCcd(next.ccd_index); setTurnIndex(next.turn_index) }
      }}>
        {data?.bands.map((item, index) => <option key={index} value={index}>{item.angle_deg === undefined ? '' : `${item.angle_deg}° · `}CCD {item.ccd_index + 1}</option>)}
      </select></label>
      <button className="secondary-button" disabled={!points.length} onClick={() => zoom('x', ZOOM_IN)}>横向放大</button>
      <button className="secondary-button" disabled={!points.length} onClick={() => zoom('x', ZOOM_OUT)}>横向缩小</button>
      <button className="secondary-button" disabled={!points.length} onClick={() => zoom('y', ZOOM_IN)}>纵向放大</button>
      <button className="secondary-button" disabled={!points.length} onClick={() => zoom('y', ZOOM_OUT)}>纵向缩小</button>
      <button className="secondary-button" disabled={!points.length} onClick={() => setRange({...view,xMin:full.xMin,xMax:full.xMax})}>适合图像</button>
      <button className="secondary-button" disabled={!points.length} onClick={() => setRange({...view,yMin:full.yMin,yMax:full.yMax})}>纵向还原</button>
      <select aria-label="分析谱图工具" value={tool} onChange={/* 切换绘图操作。 */ event => setTool(event.target.value as typeof tool)}>
        <option value="crosshair">十字线</option><option value="pan">滚动工具</option><option value="box">区域放大</option>
      </select>
    </div>
    <details className="analysis-observation-options"><summary>校线</summary><div className="analysis-actions">
      <button className="secondary-button" disabled={busy || !data} onClick={() => void previewCalibration()}>日常校线预览</button>
      <label>校线范围 <select value={scope} onChange={(event) => setScope(event.target.value as typeof scope)}>
        <option value="all">全部谱线</option><option value="reference">仅参考线</option></select></label>
      <label>位置来源 <select value={positionMode} onChange={(event) => { setPositionMode(event.target.value as typeof positionMode); setFocus(null) }}>
        <option value="measured">本次实测位置</option><option value="stored">还原原方法保存位置</option><option value="theoretical">复位理论位置</option></select></label>
      <button className="secondary-button" disabled={!canSaveMethod || busy || !calibration} onClick={() => void saveCalibration()}>保存位置为方法草稿</button>
    </div>
    {calibration && <div className="table-scroll"><table><thead><tr><th>谱线</th><th>理论 (nm)</th><th>原保存 (nm)</th><th>实测 (nm)</th><th>寻峰</th></tr></thead><tbody>
      {calibration.positions.filter((row) => scope === 'all' || row.line_type === 'baseline').map((row) => <tr key={row.line_id} onClick={() => {
        setCcd(row.ccd_index); setTurnIndex(row.turn_index); setFocus({ ccd: row.ccd_index, point: row[`${positionMode}_point`] })
      }}><td>{row.element}</td><td>{row.theoretical_wavelength_nm.toFixed(5)}</td><td>{row.stored_wavelength_nm.toFixed(5)}</td><td>{row.measured_wavelength_nm.toFixed(5)}</td><td>{row.found ? '有效峰' : '未找到有效峰，禁止保存实测位置'}</td></tr>)}
    </tbody></table></div>}
    </details>
    {error && <p role="alert">{error}</p>}
    {observation.error && <p role="alert">{observation.error}</p>}
    {band && <>
      {observation.count > 0 && <AnalysisExposureControls key={`${sample}:${bandPosition}:${selectedLineId}`}
        count={observation.count} initial={data?.exposure_interval} busy={observation.busy}
        active={Boolean(observation.interval)} onApply={observation.apply} onReset={observation.reset} />}
      <p role="status">观察曝光区间：{activeInterval ? `${activeInterval[0]}–${activeInterval[1]} 帧` : '整段均值'}</p>
      <div className="analysis-actions">
        {data?.lines.map(/* 定位方法谱线并放大周边窗口。 */ line => <button className="secondary-button" key={line.id} onClick={/* 切换谱线 CCD 和窗口。 */ () => {
          const result = run.line_results.find(/* 优先定位本次样品的实测峰位。 */ item => item.sample_position === sample && item.line_id === line.id)
          setSelectedLineId(line.id)
          setCcd(line.ccd_index)
          setTurnIndex(line.turn_index)
          setFocus({ ccd: line.ccd_index, point: result?.peak_position ?? line.point })
        }}>{line.element} {line.wavelength_nm.toFixed(3)} nm</button>)}
      </div>
      <SpectrumPlot curves={[{ id: 'analysis', label: data!.sample_name, color: '#1570a6', priority: true,
        data: points.map(/* 真实点值映射为绘图坐标。 */ (value, index) => ({ x: index + 1, y: value, point: { point_index: index, value } })) }]}
        xStart={view.xMin} xEnd={view.xMax} yStart={view.yMin} yEnd={view.yMax} tool={tool} cursor={cursor}
        locked={locked} onCursor={setCursor} onToggleLock={/* 切换十字线锁定。 */ () => setLocked(!locked)}
        onBoxSelect={value=>{setRange(limitSpectrumRange(value, full));setTool('crosshair')}}
        onZoomY={factor => zoom('y', factor)}
        onPan={(x, y) => setRange({
          xMin: view.xMin - x * (view.xMax - view.xMin), xMax: view.xMax - x * (view.xMax - view.xMin),
          yMin: view.yMin + y * (view.yMax - view.yMin), yMax: view.yMax + y * (view.yMax - view.yMin)
        })} xAxisLabel="CCD 点位 (1 起)" yAxisLabel="强度 (ADC)" />
      <label className="field">读取点位 <NumericInput min={1} max={points.length} value={point} onValueChange={(value) => { setPoint(value); setCursor(null) }} /></label>
      <output aria-label="任意点强度">CCD{ccd + 1} · 点位 {point} · 强度 {points[point - 1]?.toFixed(6) ?? '点位无效'}</output>
      {cursor && <output>十字线点位 {cursor.datum.x} · 强度 {cursor.datum.y.toFixed(6)}</output>}
      {data?.acquisition_sample_id && observation.count > 0 && <SpectrumPointDetails token={token} recordId={`sample:${data.acquisition_sample_id}`}
        ccd={ccd} point={cursor?.datum.point.point_index ?? point - 1} onToast={onToast}
        analysis={{ runId: run.id, samplePosition: sample, bandPosition }} />}
      <small>输入谱带 SHA-256：{band.mean_sha256}</small>
    </>}
  </section>
}
