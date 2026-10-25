import { useEffect, useMemo, useRef, useState } from 'react'
import { NumericInput } from './NumericInput'
import { SpectrumPlot, type SpectrumPlotCursor, type SpectrumPlotMarker } from './SpectrumPlot'
import { SpectroscopyIcon, type SpectroscopyIconName } from './SpectroscopyIcon'
import { SpectroscopyToolButton } from './SpectroscopyToolButton'
import './spectrum-inspector.css'

export type SpectrumViewRange = { xMin: number; xMax: number; yMin: number; yMax: number }
type Range = SpectrumViewRange
type Props = {
  points: number[]
  label: string
  pointOrigin?: 0 | 1
  markers?: SpectrumPlotMarker[]
  fitPlot?: boolean
  iconToolbar?: boolean
  physicalScale?: { pointWidthUm?: number; screenWidthMm?: number; screenResolutionPx?: number }
  bandNavigation?: { previous: () => void; next: () => void; canPrevious: boolean; canNext: boolean }
  onPrint?: (range: SpectrumViewRange) => void
  printDisabledReason?: string
  toolbar?: import('react').ReactNode
  emptyText?: string
  onPick?: (pointIndex: number | null) => void
}

// 只维护观察视图。调用方用任务/CCD作为key，切换对象时清空锁定点和缩放。
export function SpectrumInspector({ points, label, pointOrigin = 1, markers = [], fitPlot = false, iconToolbar = false,
  physicalScale, bandNavigation, onPrint, printDisabledReason, toolbar,
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
  const root = useRef<HTMLDivElement>(null)
  const [plotWidth, setPlotWidth] = useState(960)
  const [scale, setScale] = useState<1 | 4 | 10 | null>(null)
  useEffect(() => {
    if (!iconToolbar || !root.current) return
    const observer = new ResizeObserver(() => {
      const svg = root.current?.querySelector('svg.spectrum-plot')
      if (svg) setPlotWidth(svg.clientWidth)
    })
    observer.observe(root.current)
    return () => observer.disconnect()
  }, [iconToolbar, points.length > 0])
  const validPhysical = [physicalScale?.pointWidthUm, physicalScale?.screenResolutionPx, physicalScale?.screenWidthMm]
    .every(value => Number.isFinite(value) && Number(value) > 0)
  const physicalSpacing = validPhysical ? Number(physicalScale?.pointWidthUm) / 1000 * 10
    * Number(physicalScale?.screenResolutionPx) / Number(physicalScale?.screenWidthMm) : 0
  const spacing = (scale === 10 ? physicalSpacing : scale ?? 1) / (window.devicePixelRatio || 1)
  const manualView = range ?? full
  const view = scale && spacing > 0 ? { ...manualView, xMax: manualView.xMin + Math.max(1, plotWidth - 88) / spacing } : manualView
  const hasPoints = points.length > 0
  const curves = useMemo(() => [{ id: 'current', label, color: '#1570a6', priority: true,
    data: points.map((value, index) => ({ x: index + pointOrigin, y: value,
      point: { point_index: index, value } })) }], [points, label, pointOrigin])
  const liveCursor = cursor && points[cursor.datum.point.point_index] !== undefined ? {
    ...cursor, datum: { ...cursor.datum, y: points[cursor.datum.point.point_index],
      point: { ...cursor.datum.point, value: points[cursor.datum.point.point_index] } }
  } : null

  useEffect(() => {
    if (!hasPoints) { setCursor(null); setLocked(false); setRange(null); setScale(null); onPick?.(null) }
  }, [hasPoints, onPick])
  const reset = () => { setScale(null); setRange(null); setCursor(null); setLocked(false); setPoint(pointOrigin); onPick?.(null) }
  const zoom = (axis: 'x' | 'y', factor: number) => {
    if (axis === 'x') setScale(null)
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
  return <div ref={root} className="spectrum-inspector" aria-label={label}>
    <div className={`inspector-tools${iconToolbar ? ' inspector-icon-tools' : ''}`} role="group" aria-label="谱图观察工具">
      {iconToolbar && bandNavigation && <div className="inspector-tool-modes" role="group" aria-label="谱带切换">
        <SpectroscopyToolButton icon="previous-band" label="上一谱带" disabled={!bandNavigation.canPrevious} onClick={bandNavigation.previous} />
        <SpectroscopyToolButton icon="next-band" label="下一谱带" disabled={!bandNavigation.canNext} onClick={bandNavigation.next} />
      </div>}
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
      {iconToolbar && <div className="inspector-tool-modes" role="group" aria-label="显示比例">
        <SpectroscopyToolButton icon="fit" label="适合图像" disabled={!hasPoints} onClick={reset} />
        {([1, 4, 10] as const).map(value => <SpectroscopyToolButton key={value} icon={value === 1 ? 'scale-1' : value === 4 ? 'scale-4' : 'scale-10'}
          label={value === 1 ? '一线一点' : value === 4 ? '一线四点' : '十倍 CCD'}
          description={value === 10 && !(physicalSpacing > 0) ? '需要有效的屏幕宽度、分辨率和CCD点宽' : value === 10 ? '按CCD点宽与屏幕参数显示十倍物理比例' : `每个CCD点对应${value}个屏幕像素`}
          disabled={!hasPoints || (value === 10 && !(physicalSpacing > 0))} aria-pressed={scale === value}
          onClick={() => { setRange(view); setScale(value) }} />)}
      </div>}
      {([
        ['横向放大', 'zoom-x-in', () => zoom('x', 0.5)],
        ['横向缩小', 'zoom-x-out', () => zoom('x', 2)],
        ['纵向放大', 'zoom-y-in', () => zoom('y', 0.5)],
        ['纵向缩小', 'zoom-y-out', () => zoom('y', 2)],
        ['适合图像', 'fit', reset]
      ] satisfies [string, SpectroscopyIconName, () => void][]).filter(([name]) => !iconToolbar || name !== '适合图像').map(([name, icon, action]) => (
        <button key={name} type="button" className={`secondary-button${iconToolbar ? ' inspector-icon-button' : ''}`}
          disabled={!hasPoints} aria-label={name} title={name} onClick={action}>
          {iconToolbar ? <SpectroscopyIcon name={icon} /> : name}
        </button>
      ))}
      {iconToolbar && <SpectroscopyToolButton icon="reset-y" label="纵向还原" disabled={!hasPoints}
        onClick={() => setRange({ ...view, yMin: full.yMin, yMax: full.yMax })} />}
      <button type="button" className={`secondary-button${iconToolbar ? ' inspector-icon-button' : ''}`} disabled={!liveCursor}
        aria-label={locked ? '解除锁定' : '锁定点位'} title={locked ? '解除锁定' : '锁定点位'} aria-pressed={locked} onClick={() => toggleLock()}>
        {iconToolbar ? <SpectroscopyIcon name="lock" /> : locked ? '解除锁定' : '锁定点位'}
      </button>
      {iconToolbar && onPrint && <SpectroscopyToolButton icon="print" label="打印谱图" description={printDisabledReason ?? '打印当前可见的已保存谱带'}
        disabled={!hasPoints || Boolean(printDisabledReason)} onClick={() => onPrint(view)} />}
      {toolbar}
    </div>
    {hasPoints ? <>
      <SpectrumPlot fitContainer={fitPlot} curves={curves} xStart={view.xMin} xEnd={view.xMax} yStart={view.yMin} yEnd={view.yMax}
        tool={tool} cursor={liveCursor} locked={locked}
        onCursor={(next) => { setCursor(next); if (next) setPoint(next.datum.x) }} onToggleLock={toggleLock}
        onPan={(x, y) => setRange({ xMin: view.xMin - x * (view.xMax - view.xMin),
          xMax: view.xMax - x * (view.xMax - view.xMin), yMin: view.yMin + y * (view.yMax - view.yMin),
          yMax: view.yMax + y * (view.yMax - view.yMin) })}
        onBoxSelect={next => { setScale(null); setRange(next) }} markers={markers}
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
