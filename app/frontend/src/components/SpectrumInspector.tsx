import { useEffect, useMemo, useState } from 'react'
import { NumericInput } from './NumericInput'
import { SpectrumPlot, type SpectrumPlotCursor, type SpectrumPlotMarker } from './SpectrumPlot'
import { SpectroscopyIcon, type SpectroscopyIconName } from './SpectroscopyIcon'
import './spectrum-inspector.css'

type Range = { xMin: number; xMax: number; yMin: number; yMax: number }
type Props = {
  points: number[]
  label: string
  pointOrigin?: 0 | 1
  markers?: SpectrumPlotMarker[]
  fitPlot?: boolean
  iconToolbar?: boolean
  emptyText?: string
  onPick?: (pointIndex: number | null) => void
}

// 只维护观察视图。调用方用任务/CCD作为key，切换对象时清空锁定点和缩放。
export function SpectrumInspector({ points, label, pointOrigin = 1, markers = [], fitPlot = false, iconToolbar = false,
  emptyText = '暂无可显示的谱图', onPick }: Props) {
  const full = useMemo<Range>(() => ({
    xMin: pointOrigin, xMax: Math.max(pointOrigin + 1, points.length - 1 + pointOrigin),
    yMin: Math.min(0, ...points), yMax: Math.max(1, ...points)
  }), [points, pointOrigin])
  const [range, setRange] = useState<Range | null>(null)
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [locked, setLocked] = useState(false)
  const [point, setPoint] = useState<number>(pointOrigin)
  const view = range ?? full
  const hasPoints = points.length > 0
  const curves = useMemo(() => [{ id: 'current', label, color: '#1570a6', priority: true,
    data: points.map((value, index) => ({ x: index + pointOrigin, y: value,
      point: { point_index: index, value } })) }], [points, label, pointOrigin])
  const liveCursor = cursor && points[cursor.datum.point.point_index] !== undefined ? {
    ...cursor, datum: { ...cursor.datum, y: points[cursor.datum.point.point_index],
      point: { ...cursor.datum.point, value: points[cursor.datum.point.point_index] } }
  } : null

  useEffect(() => {
    if (!hasPoints) { setCursor(null); setLocked(false); setRange(null); onPick?.(null) }
  }, [hasPoints, onPick])
  const reset = () => { setRange(null); setCursor(null); setLocked(false); setPoint(pointOrigin); onPick?.(null) }
  const zoom = (axis: 'x' | 'y', factor: number) => {
    const low = axis === 'x' ? view.xMin : view.yMin, high = axis === 'x' ? view.xMax : view.yMax
    const span = Math.max(axis === 'x' ? 1 : 0.01, (high - low) * factor)
    const middle = (high + low) / 2
    setRange(axis === 'x' ? { ...view, xMin: middle - span / 2, xMax: middle + span / 2 }
      : { ...view, yMin: middle - span / 2, yMax: middle + span / 2 })
  }
  const toggleLock = (picked: SpectrumPlotCursor | null = liveCursor) => {
    if (!picked) return
    const next = !locked
    setCursor(picked)
    setPoint(picked.datum.x)
    setLocked(next)
    onPick?.(next ? picked.datum.point.point_index : null)
  }
  const readPoint = (value: number) => {
    setPoint(value)
    const index = value - pointOrigin
    if (!Number.isInteger(index) || index < 0 || index >= points.length) return
    const datum = curves[0].data[index]
    setCursor({ curveId: 'current', curveLabel: label, x: 0, y: 0, datum })
    setLocked(true)
    setTool('crosshair')
    onPick?.(index)
  }
  return <div className="spectrum-inspector" aria-label={label}>
    <div className={`inspector-tools${iconToolbar ? ' inspector-icon-tools' : ''}`} role="group" aria-label="谱图观察工具">
      {iconToolbar ? <div className="inspector-tool-modes" role="group" aria-label="谱图工具">
        {([['crosshair', '十字线', 'crosshair'], ['pan', '滚动工具', 'pan'], ['box', '区域放大', 'box-zoom']] as const).map(([value, name, icon]) => (
          <button key={value} type="button" className="secondary-button inspector-icon-button" disabled={!hasPoints}
            aria-label={name} title={name} aria-pressed={tool === value} onClick={() => setTool(value)}>
            <SpectroscopyIcon name={icon} />
          </button>
        ))}
      </div> : <label>工具 <select aria-label="谱图工具" value={tool} disabled={!hasPoints}
        onChange={(event) => setTool(event.target.value as typeof tool)}>
        <option value="crosshair">十字线</option><option value="pan">滚动工具</option><option value="box">区域放大</option>
      </select></label>}
      {([
        ['横向放大', 'zoom-x-in', () => zoom('x', 0.5)],
        ['横向缩小', 'zoom-x-out', () => zoom('x', 2)],
        ['纵向放大', 'zoom-y-in', () => zoom('y', 0.5)],
        ['纵向缩小', 'zoom-y-out', () => zoom('y', 2)],
        ['适合图像', 'fit', reset]
      ] satisfies [string, SpectroscopyIconName, () => void][]).map(([name, icon, action]) => (
        <button key={name} type="button" className={`secondary-button${iconToolbar ? ' inspector-icon-button' : ''}`}
          disabled={!hasPoints} aria-label={name} title={name} onClick={action}>
          {iconToolbar ? <SpectroscopyIcon name={icon} /> : name}
        </button>
      ))}
      <button type="button" className={`secondary-button${iconToolbar ? ' inspector-icon-button' : ''}`} disabled={!liveCursor}
        aria-label={locked ? '解除锁定' : '锁定点位'} title={locked ? '解除锁定' : '锁定点位'} aria-pressed={locked} onClick={() => toggleLock()}>
        {iconToolbar ? <SpectroscopyIcon name="lock" /> : locked ? '解除锁定' : '锁定点位'}
      </button>
    </div>
    {hasPoints ? <>
      <SpectrumPlot fitContainer={fitPlot} curves={curves} xStart={view.xMin} xEnd={view.xMax} yStart={view.yMin} yEnd={view.yMax}
        tool={tool} cursor={liveCursor} locked={locked}
        onCursor={(next) => { setCursor(next); if (next) setPoint(next.datum.x) }} onToggleLock={toggleLock}
        onPan={(x, y) => setRange({ xMin: view.xMin - x * (view.xMax - view.xMin),
          xMax: view.xMax - x * (view.xMax - view.xMin), yMin: view.yMin + y * (view.yMax - view.yMin),
          yMax: view.yMax + y * (view.yMax - view.yMin) })}
        onBoxSelect={setRange} markers={markers}
        xAxisLabel={`CCD 点位 (${pointOrigin} 起)`} yAxisLabel="强度 (ADC)" />
      <div className="inspector-readout">
        <label>读取点位 <NumericInput min={pointOrigin} max={points.length - 1 + pointOrigin}
          step={1} value={point} onValueChange={readPoint} data-observation-input="true"
          onFocus={() => { setLocked(false); onPick?.(null) }} /></label>
        <output aria-label="谱图点位读数">{liveCursor
          ? `点位 ${liveCursor.datum.x} · 强度 ${liveCursor.datum.y.toLocaleString('zh-CN', { maximumFractionDigits: 6 })}${locked ? ' · 已锁定' : ''}`
          : '移动鼠标查看强度，单击曲线锁定点位'}</output>
        <small>视野 {view.xMin.toFixed(1)}–{view.xMax.toFixed(1)} · 强度 {view.yMin.toFixed(1)}–{view.yMax.toFixed(1)}</small>
      </div>
      {markers.length > 0 && <div className="inspector-markers" aria-label="谱线位置">
        {markers.map((marker) => <button className={`secondary-button ${marker.kind}`} key={marker.key}
          title={marker.label} onClick={() => setRange({ ...full,
            xMin: Math.max(full.xMin, marker.position - 30), xMax: Math.min(full.xMax, marker.position + 30) })}>
          {marker.label}
        </button>)}
      </div>}
    </> : <div className="inspector-empty">{emptyText}</div>}
  </div>
}
