import type { AnalysisCurveSnapshot } from '../../api'
import type { AnalysisCurvePoint } from '../../api/analysis'
import { useRef, useState, type MouseEvent, type PointerEvent } from 'react'

const gridPositions = Array.from({ length: 11 }, (_, index) => index * 10)
const axisValue = (value: number, logarithmic: boolean) => logarithmic ? Math.log(value) : value
const validAxisValue = (value: number, logarithmic: boolean) => Number.isFinite(value) && (!logarithmic || value > 0)

export function curveChartLimits(snapshot: AnalysisCurveSnapshot | undefined, points: AnalysisCurvePoint[], logarithmic: boolean, legacy: boolean) {
  const chart = snapshot?.chart ?? []
  const standardValues = points.map((item) => item.standard_value).filter((value) => validAxisValue(value, logarithmic))
  const concentrations = [...standardValues, ...(legacy && standardValues.length ? [] : chart.map((item) => item.value))]
    .filter((value) => validAxisValue(value, logarithmic))
  const measured = points.flatMap((item) => item.adjusted_intensity == null ? [] : [item.adjusted_intensity])
  const intensities = (legacy && chart.length ? chart.map((item) => item.intensity) : [...measured, ...chart.map((item) => item.intensity)])
    .filter((value) => validAxisValue(value, logarithmic))
  return {
    valueMin: concentrations.length ? Math.min(...concentrations) : 1,
    valueMax: concentrations.length ? Math.max(...concentrations) : 10,
    intensityMin: intensities.length ? Math.min(...intensities) : 1,
    intensityMax: intensities.length ? Math.max(...intensities) : 10,
  }
}

export function CurveChart({ snapshot, lineLabel, unit, points, logarithmic, legacy, selectedPoint, onSelectPoint, onPointContext, onAdjustPoint }: {
  snapshot: AnalysisCurveSnapshot | undefined
  lineLabel: string
  unit: string
  points: AnalysisCurvePoint[]
  logarithmic: boolean
  legacy: boolean
  selectedPoint: number
  onSelectPoint: (index: number) => void
  onPointContext?: (event: MouseEvent<HTMLButtonElement>, index: number) => void
  onAdjustPoint?: (index: number, intensity: number) => void
}) {
  const plot = useRef<HTMLDivElement>(null)
  const drag = useRef<{ pointer: number; index: number; startY: number; initial: number; scale: number } | null>(null)
  const [preview, setPreview] = useState<{ index: number; intensity: number } | null>(null)
  const { valueMin, valueMax, intensityMin, intensityMax } = curveChartLimits(snapshot, points, logarithmic, legacy)
  const minX = axisValue(valueMin, logarithmic), minY = axisValue(intensityMin, logarithmic)
  const spanX = axisValue(valueMax, logarithmic) - minX
  const spanY = axisValue(intensityMax, logarithmic) - minY
  const x = (value: number) => spanX > 0 ? 100 * (axisValue(value, logarithmic) - minX) / spanX : 50
  const y = (value: number) => spanY > 0 ? 100 - 100 * (axisValue(value, logarithmic) - minY) / spanY : 50
  const coordinates = logarithmic ? '（对数坐标）' : ''
  const fit = snapshot?.chart.filter((item) => validAxisValue(item.value, logarithmic) && validAxisValue(item.intensity, logarithmic)) ?? []
  const dragValue = (event: PointerEvent<HTMLButtonElement>) => {
    const active = drag.current
    if (!active || active.pointer !== event.pointerId || Math.abs(active.startY - event.clientY) < 3) return null
    const scaled = axisValue(active.initial, logarithmic) + (active.startY - event.clientY) * active.scale
    const intensity = logarithmic ? Math.exp(scaled) : scaled
    if (!Number.isFinite(intensity) || intensity <= (legacy ? 1e-5 : 0)) return null
    return { index: active.index, intensity }
  }
  const cancelDrag = () => { drag.current = null; setPreview(null) }
  return (
    <div className="standard-curve-chart">
      <div ref={plot} className="standard-curve-grid">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="标准曲线">
          {gridPositions.map((position) => <path key={position} d={`M${position},0V100 M0,${position}H100`} vectorEffect="non-scaling-stroke" />)}
          {fit.length > 0 && <polyline points={fit.map((item) => `${x(item.value)},${y(item.intensity)}`).join(' ')}
            vectorEffect="non-scaling-stroke" />}
        </svg>
        {points.map((item) => {
          const intensity = preview?.index === item.point_index ? preview.intensity : item.adjusted_intensity
          if (intensity == null || !validAxisValue(intensity, logarithmic) || !validAxisValue(item.standard_value, logarithmic)) return null
          const selected = selectedPoint === item.point_index
          return <button key={item.point_index} className="standard-curve-dot" type="button"
            style={{ left: `${x(item.standard_value)}%`, top: `${Math.max(0, Math.min(100, y(intensity)))}%` }}
            data-active={item.active} data-draggable={Boolean(onAdjustPoint)} aria-pressed={selected} aria-label={`标准点 ${item.name}`}
            title={`${item.name} · 强度 ${intensity}${onAdjustPoint ? ' · 上下拖动调节强度' : ''}`} onClick={() => onSelectPoint(item.point_index)}
            onPointerDown={event => {
              if (!onAdjustPoint || event.button !== 0 || !event.isPrimary || !plot.current) return
              const height = plot.current.getBoundingClientRect().height
              if (!height) return
              const scale = (spanY > 0 ? spanY : Math.max(Math.abs(minY) * 0.1, 1)) / height
              drag.current = { pointer: event.pointerId, index: item.point_index, startY: event.clientY, initial: intensity, scale }
              event.currentTarget.setPointerCapture(event.pointerId)
              onSelectPoint(item.point_index)
            }}
            onPointerMove={event => { if (drag.current?.pointer === event.pointerId) setPreview(dragValue(event)) }}
            onPointerUp={event => {
              const value = dragValue(event)
              cancelDrag()
              if (value) onAdjustPoint?.(value.index, value.intensity)
            }}
            onPointerCancel={cancelDrag} onLostPointerCapture={cancelDrag}
            onContextMenu={onPointContext && (event => onPointContext(event, item.point_index))} />
        })}
        <span className="standard-curve-y">强度{coordinates}<br />{intensityMax.toFixed(2)}</span>
        <span className="standard-curve-line">{lineLabel}</span>
        {preview && <output className="standard-curve-drag-value">修正强度 {preview.intensity.toFixed(3)}</output>}
        <span className="standard-curve-x">含量{coordinates} {valueMax.toFixed(2)} {unit}</span>
      </div>
    </div>
  )
}
