import { useEffect, useId, useRef, useState, type PointerEvent, type WheelEvent, type KeyboardEvent } from 'react'
import type { SpectrumPoint } from '../api'
import { formatIntegerTick, integerAxisTicks } from './SimpleChartAxes'

export type SpectrumPlotDatum = { point: SpectrumPoint; x: number; y: number }
export type SpectrumPlotCurve = {
  id: string
  label: string
  color: string
  priority: boolean
  data: SpectrumPlotDatum[]
}
export type SpectrumPlotCursor = {
  curveId: string
  curveLabel: string
  x: number
  y: number
  datum: SpectrumPlotDatum
}

export type SpectrumPlotMarker = {
  key: string
  position: number
  label: string
  kind: 'expected' | 'located'
}

type Props = {
  curves: SpectrumPlotCurve[]
  xStart: number
  xEnd: number
  yStart: number
  yEnd: number
  tool: 'crosshair' | 'pan' | 'box'
  cursor: SpectrumPlotCursor | null
  locked: boolean
  onCursor: (cursor: SpectrumPlotCursor | null) => void
  onToggleLock: (cursor?: SpectrumPlotCursor) => void
  onPan: (xDelta: number, yDelta: number) => void
  onBoxSelect: (range: { xMin: number; xMax: number; yMin: number; yMax: number }) => void
  xAxisLabel?: string
  yAxisLabel?: string
  fitContainer?: boolean
  markers?: SpectrumPlotMarker[]
}

const LEFT = 54
const TOP = 42

export function SpectrumPlot({
  curves,
  xStart,
  xEnd,
  yStart,
  yEnd,
  tool,
  cursor,
  locked,
  onCursor,
  onToggleLock,
  onPan,
  onBoxSelect,
  xAxisLabel = '波长 / 点位',
  yAxisLabel = '强度 / 结果',
  markers = [],
  fitContainer = false
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ width: 960, height: 380 })
  useEffect(() => {
    if (!fitContainer || !svgRef.current) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setSize({ width, height })
    })
    observer.observe(svgRef.current)
    return () => observer.disconnect()
  }, [fitContainer])
  const viewWidth = fitContainer ? Math.max(200, size.width) : 960
  const viewHeight = fitContainer ? Math.max(150, size.height) : 380
  const WIDTH = viewWidth - 88
  const HEIGHT = viewHeight - 92
  const clipId = useId()
  const [drag, setDrag] = useState<{ startX: number; startY: number; x: number; y: number } | null>(null)
  const [panAnchor, setPanAnchor] = useState<{ x: number; y: number } | null>(null)
  const raf = useRef<number | null>(null)
  useEffect(() => () => { if (raf.current !== null) cancelAnimationFrame(raf.current) }, [])
  const xTicks = integerAxisTicks(xStart, xEnd)
  const yTicks = integerAxisTicks(yStart, yEnd)

  const plotX = (value: number) => LEFT + ((value - xStart) / (xEnd - xStart || 1)) * WIDTH
  const plotY = (value: number) => TOP + HEIGHT - ((value - yStart) / (yEnd - yStart || 1)) * HEIGHT
  const dataX = (value: number) => xStart + ((value - LEFT) / WIDTH) * (xEnd - xStart)
  const dataY = (value: number) => yStart + ((TOP + HEIGHT - value) / HEIGHT) * (yEnd - yStart)
  const toSvg = (event: Pick<PointerEvent<SVGSVGElement>, 'currentTarget' | 'clientX' | 'clientY'>) => {
    const matrix = event.currentTarget.getScreenCTM()
    return matrix ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()) : { x: 0, y: 0 }
  }

  const cursorAt = (screenX: number): SpectrumPlotCursor | null => {
    const target = dataX(Math.max(LEFT, Math.min(LEFT + WIDTH, screenX)))
    const priority = curves.find((curve) => curve.priority) ?? curves[0]
    const candidates = priority ? priority.data.map((datum) => ({ curve: priority, datum })) : []
    if (!candidates.length) return null
    const nearest = candidates.reduce((best, item) =>
      Math.abs(item.datum.x - target) < Math.abs(best.datum.x - target) ? item : best
    )
    return {
      curveId: nearest.curve.id,
      curveLabel: nearest.curve.label,
      x: plotX(nearest.datum.x),
      y: plotY(nearest.datum.y),
      datum: nearest.datum
    }
  }
  const updateCursor = (screenX: number) => {
    if (!locked && tool === 'crosshair') onCursor(cursorAt(screenX))
  }

  const pointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const position = toSvg(event)
    if (drag) {
      setDrag({
        ...drag,
        x: Math.max(LEFT, Math.min(LEFT + WIDTH, position.x)),
        y: Math.max(TOP, Math.min(TOP + HEIGHT, position.y))
      })
      return
    }
    if (panAnchor) {
      onPan((position.x - panAnchor.x) / WIDTH, (position.y - panAnchor.y) / HEIGHT)
      setPanAnchor(position)
      return
    }
    if (raf.current !== null) cancelAnimationFrame(raf.current)
    raf.current = requestAnimationFrame(() => {
      updateCursor(position.x)
      raf.current = null
    })
  }

  const pointerDown = (event: PointerEvent<SVGSVGElement>) => {
    event.currentTarget.focus()
    const position = toSvg(event)
    if (position.x < LEFT || position.x > LEFT + WIDTH || position.y < TOP || position.y > TOP + HEIGHT) return
    event.currentTarget.setPointerCapture(event.pointerId)
    if (tool === 'box') setDrag({ startX: position.x, startY: position.y, x: position.x, y: position.y })
    if (tool === 'pan') setPanAnchor(position)
  }

  const pointerUp = (event: PointerEvent<SVGSVGElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    if (drag && Math.abs(drag.x - drag.startX) > 4 && Math.abs(drag.y - drag.startY) > 4) {
      const x1 = dataX(drag.startX)
      const x2 = dataX(drag.x)
      const y1 = dataY(drag.startY)
      const y2 = dataY(drag.y)
      onBoxSelect({ xMin: Math.min(x1, x2), xMax: Math.max(x1, x2), yMin: Math.min(y1, y2), yMax: Math.max(y1, y2) })
    }
    setDrag(null)
    setPanAnchor(null)
  }

  const wheel = (event: WheelEvent<SVGSVGElement>) => {
    if (tool !== 'pan') return
    event.preventDefault()
    onPan(event.deltaX / 1200, event.deltaY / 1200)
  }

  const keyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || !event.key.startsWith('Arrow')) return
    event.preventDefault()
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      const factor = event.key === 'ArrowUp' ? 0.5 : 2
      const center = (yStart + yEnd) / 2, half = Math.max(0.001, (yEnd - yStart) * factor / 2)
      onBoxSelect({ xMin: xStart, xMax: xEnd, yMin: center - half, yMax: center + half })
      return
    }
    const curve = curves.find((item) => item.id === cursor?.curveId) ?? curves.find((item) => item.priority) ?? curves[0]
    if (!curve?.data.length) return
    const index = cursor ? curve.data.findIndex((datum) => datum.point.point_index === cursor.datum.point.point_index) : 0
    const next = Math.max(0, Math.min(curve.data.length - 1, Math.max(0, index) + (event.key === 'ArrowRight' ? 1 : -1)))
    const datum = curve.data[next]
    onCursor({ curveId: curve.id, curveLabel: curve.label, x: plotX(datum.x), y: plotY(datum.y), datum })
    if (datum.x < xStart || datum.x > xEnd) {
      const half = (xEnd - xStart) / 2
      onBoxSelect({ xMin: datum.x - half, xMax: datum.x + half, yMin: yStart, yMax: yEnd })
    }
  }

  return (
    <svg
      className={`spectrum-plot tool-${tool}`}
      ref={svgRef}
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      role="img"
      aria-label="谱图曲线"
      data-testid="spectrum-plot"
      tabIndex={0}
      onKeyDown={keyDown}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
      onPointerLeave={() => {
        if (!locked && !drag && !panAnchor) onCursor(null)
      }}
      onClick={(event) => {
        if (tool !== 'crosshair') return
        const position = toSvg(event)
        if (position.x < LEFT || position.x > LEFT + WIDTH || position.y < TOP || position.y > TOP + HEIGHT) return
        if (raf.current !== null) { cancelAnimationFrame(raf.current); raf.current = null }
        const picked = locked ? cursor : cursorAt(position.x)
        if (picked) { onCursor(picked); onToggleLock(picked) }
      }}
      onWheel={wheel}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={LEFT} y={TOP} width={WIDTH} height={HEIGHT} />
        </clipPath>
      </defs>
      <rect x={LEFT} y={TOP} width={WIDTH} height={HEIGHT} className="plot-background" />
      {xTicks.map((value) => (
        <line
          key={`grid-x-${value}`}
          x1={plotX(value)}
          y1={TOP}
          x2={plotX(value)}
          y2={TOP + HEIGHT}
          className="plot-grid"
        />
      ))}
      {yTicks.map((value) => (
        <line
          key={`grid-y-${value}`}
          x1={LEFT}
          y1={plotY(value)}
          x2={LEFT + WIDTH}
          y2={plotY(value)}
          className="plot-grid"
        />
      ))}
      <line x1={LEFT} y1={TOP + HEIGHT} x2={LEFT + WIDTH} y2={TOP + HEIGHT} className="plot-axis" />
      <line x1={LEFT} y1={TOP} x2={LEFT} y2={TOP + HEIGHT} className="plot-axis" />
      <g clipPath={`url(#${clipId})`}>
        {[...curves]
          .sort((a, b) => Number(a.priority) - Number(b.priority))
          .map((curve) => {
            const path = curve.data
              .map((item, index) => `${index ? 'L' : 'M'} ${plotX(item.x).toFixed(2)} ${plotY(item.y).toFixed(2)}`)
              .join(' ')
            return path ? (
              <path
                key={curve.id}
                d={path}
                className={`spectrum-line ${curve.priority ? 'priority' : ''}`}
                style={{ stroke: curve.color }}
                data-curve-id={curve.id}
              />
            ) : null
          })}
        {markers.filter((marker) => Number.isFinite(marker.position)).map((marker) => (
          <g key={marker.key} className={`plot-position-marker ${marker.kind}`}
            data-marker-kind={marker.kind} data-marker-position={marker.position}>
            <title>{marker.label}</title>
            <line x1={plotX(marker.position)} x2={plotX(marker.position)} y1={TOP} y2={TOP + HEIGHT} />
            <circle cx={plotX(marker.position)} cy={TOP + (marker.kind === 'expected' ? 8 : 20)} r="4" />
          </g>
        ))}
        {cursor && (
          <>
            <line x1={plotX(cursor.datum.x)} y1={TOP} x2={plotX(cursor.datum.x)} y2={TOP + HEIGHT} className="plot-crosshair" />
            <line x1={LEFT} y1={plotY(cursor.datum.y)} x2={LEFT + WIDTH} y2={plotY(cursor.datum.y)} className="plot-crosshair" />
            <circle cx={plotX(cursor.datum.x)} cy={plotY(cursor.datum.y)} r="4" className="plot-cursor" />
          </>
        )}
        {drag && (
          <rect
            x={Math.min(drag.startX, drag.x)}
            y={Math.min(drag.startY, drag.y)}
            width={Math.abs(drag.x - drag.startX)}
            height={Math.abs(drag.y - drag.startY)}
            className="plot-selection"
          />
        )}
      </g>
      <text x={LEFT} y="24" className="plot-label">
        {curves.find((curve) => curve.priority)?.label ?? curves[0]?.label ?? '无可显示曲线'}
      </text>
      {xTicks.map((value) => (
        <text key={`x-${value}`} x={plotX(value)} y={TOP + HEIGHT + 20} textAnchor="middle" className="plot-label plot-tick-label">
          {formatIntegerTick(value)}
        </text>
      ))}
      {yTicks.map((value) => (
        <text
          key={`y-${value}`}
          x={LEFT - 7}
          y={plotY(value) + 4}
          textAnchor="end"
          className="plot-label plot-tick-label"
        >
          {formatIntegerTick(value)}
        </text>
      ))}
      <text x={LEFT + WIDTH / 2} y={viewHeight - 8} textAnchor="middle" className="plot-label plot-axis-title">
        {xAxisLabel}
      </text>
      <text
        x="13"
        y={TOP + HEIGHT / 2}
        textAnchor="middle"
        transform={`rotate(-90 13 ${TOP + HEIGHT / 2})`}
        className="plot-label plot-axis-title"
      >
        {yAxisLabel}
      </text>
    </svg>
  )
}
