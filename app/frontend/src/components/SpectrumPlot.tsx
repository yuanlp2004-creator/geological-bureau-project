import { useEffect, useId, useMemo, useRef, useState, type PointerEvent, type WheelEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { ZOOM_IN, ZOOM_OUT, type SpectrumViewRange } from './spectrumZoom'
import type { SpectrumPoint } from '../api'
import { formatIntegerTick, integerAxisTicks, fractionalTicks, formatFractionalTick } from './SimpleChartAxes'

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
export type SpectrumContextHandler = (event: MouseEvent<SVGSVGElement>, point: SpectrumPlotCursor | null, markerKey?: string) => void

export type SpectrumPlotMarker = {
  key: string
  position: number
  label: string
  kind: 'expected' | 'located'
  select?: () => void
  selected?: boolean
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
  onPointerPresence?: (inside: boolean, ctrlKey: boolean) => void
  onToggleLock: (cursor?: SpectrumPlotCursor) => void
  onPan: (xDelta: number, yDelta: number) => void
  onBoxSelect: (range: SpectrumViewRange) => void
  onZoomY: (factor: number) => void
  xAxisLabel?: string
  yAxisLabel?: string
  fitContainer?: boolean
  fractionalX?: boolean
  leftPadding?: number
  stretch?: boolean
  markers?: SpectrumPlotMarker[]
  onSpectrumContext?: SpectrumContextHandler
}


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
  onPointerPresence,
  onToggleLock,
  onPan,
  onBoxSelect,
  onZoomY,
  xAxisLabel = '波长 / 点位',
  yAxisLabel = '强度 / 结果',
  markers = [],
  onSpectrumContext,
  fitContainer = false,
  fractionalX = false,
  leftPadding = 54,
  stretch = false
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
  const LEFT = leftPadding
  const TOP = stretch ? 18 : 42
  const WIDTH = viewWidth - LEFT - 34
  const HEIGHT = viewHeight - TOP - 50
  const clipId = useId()
  const [drag, setDrag] = useState<{ startX: number; startY: number; x: number; y: number } | null>(null)
  const [panAnchor, setPanAnchor] = useState<{ x: number; y: number } | null>(null)
  const raf = useRef<number | null>(null)
  useEffect(() => () => { if (raf.current !== null) cancelAnimationFrame(raf.current) }, [])
  const xTicks = fractionalX ? fractionalTicks(xStart, xEnd) : integerAxisTicks(xStart, xEnd)
  const fractionalY = yEnd - yStart < 4
  const yTicks = fractionalY ? fractionalTicks(yStart, yEnd)
    : integerAxisTicks(yStart, yEnd, stretch ? Math.max(2, Math.min(5, Math.floor(HEIGHT / 40))) : 5)

  const plotX = (value: number) => LEFT + ((value - xStart) / (xEnd - xStart || 1)) * WIDTH
  const plotY = (value: number) => TOP + HEIGHT - ((value - yStart) / (yEnd - yStart || 1)) * HEIGHT
  const paths = useMemo(() => [...curves].sort((a, b) => Number(a.priority) - Number(b.priority)).map(curve => {
    if (curve.data.length === 1) return <circle key={curve.id} cx={plotX(curve.data[0].x)} cy={plotY(curve.data[0].y)} r="4"
      className="spectrum-single-point" fill={curve.color} data-curve-id={curve.id} />
    if (!curve.data.length) return null
    const path = curve.data.map((item, index) =>
      `${index ? 'L' : 'M'} ${plotX(item.x).toFixed(2)} ${plotY(item.y).toFixed(2)}`).join(' ')
    return <path key={curve.id} d={path} className={`spectrum-line ${curve.priority ? 'priority' : ''}`}
      style={{ stroke: curve.color }} data-curve-id={curve.id} />
  }), [curves, xStart, xEnd, yStart, yEnd, LEFT, TOP, WIDTH, HEIGHT])
  const dataX = (value: number) => xStart + ((value - LEFT) / WIDTH) * (xEnd - xStart)
  const dataY = (value: number) => yStart + ((TOP + HEIGHT - value) / HEIGHT) * (yEnd - yStart)
  const toSvg = (event: Pick<MouseEvent<SVGSVGElement>, 'currentTarget' | 'clientX' | 'clientY'>) => {
    const matrix = event.currentTarget.getScreenCTM()
    return matrix ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()) : { x: 0, y: 0 }
  }

  const cursorAt = (screenX: number): SpectrumPlotCursor | null => {
    const target = dataX(Math.max(LEFT, Math.min(LEFT + WIDTH, screenX)))
    const priority = curves.find((curve) => curve.priority) ?? curves[0]
    if (!priority?.data.length) return null
    const nearest = priority.data.reduce((best, item) =>
      Math.abs(item.x - target) < Math.abs(best.x - target) ? item : best
    )
    return {
      curveId: priority.id,
      curveLabel: priority.label,
      x: plotX(nearest.x),
      y: plotY(nearest.y),
      datum: nearest
    }
  }
  const updateCursor = (screenX: number) => {
    if (!locked && tool === 'crosshair') onCursor(cursorAt(screenX))
  }

  const pointerMove = (event: PointerEvent<SVGSVGElement>) => {
    onPointerPresence?.(true, event.ctrlKey)
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
    raf.current = null
    if (event.ctrlKey || locked || tool !== 'crosshair') return
    raf.current = requestAnimationFrame(() => {
      updateCursor(position.x)
      raf.current = null
    })
  }

  const pointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return
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
    if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || !event.key.startsWith('Arrow') || !curves.some(curve => curve.data.length)) return
    event.preventDefault()
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      onZoomY(event.key === 'ArrowUp' ? ZOOM_IN : ZOOM_OUT)
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
      preserveAspectRatio={stretch ? 'none' : undefined}
      role="img"
      aria-label="谱图曲线"
      data-testid="spectrum-plot"
      tabIndex={0}
      onKeyDown={keyDown}
      onPointerDown={pointerDown}
      onContextMenu={onSpectrumContext && (event => {
        const marker = (event.target as Element).closest('[data-marker-key]')?.getAttribute('data-marker-key')
        const point = event.clientX || event.clientY ? cursorAt(toSvg(event).x) : cursor
        onSpectrumContext(event, point, marker ?? undefined)
      })}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
      onPointerLeave={event => {
        onPointerPresence?.(false, event.ctrlKey)
        if (raf.current !== null) { cancelAnimationFrame(raf.current); raf.current = null }
        if (!event.ctrlKey && !locked && !drag && !panAnchor) onCursor(null)
      }}
      onClick={(event) => {
        if (event.ctrlKey || tool !== 'crosshair') return
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
        {paths}
        {markers.filter((marker) => Number.isFinite(marker.position)).map((marker) => (
          <g key={marker.key} className={`plot-position-marker ${marker.kind}`}
            data-marker-kind={marker.kind} data-marker-position={marker.position}
            data-marker-key={marker.key}
            role={marker.select ? 'button' : undefined} tabIndex={marker.select ? 0 : undefined}
            aria-pressed={marker.select ? marker.selected : undefined}
            aria-label={marker.select ? marker.label : undefined} style={{ pointerEvents: marker.select ? 'auto' : undefined }}
            onPointerDown={event => { if (marker.select) event.stopPropagation() }}
            onClick={event => { if (marker.select) { event.stopPropagation(); marker.select() } }}
            onKeyDown={event => { if (marker.select && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); event.stopPropagation(); marker.select() } }}>
            <title>{marker.label}</title>
            <line x1={plotX(marker.position)} x2={plotX(marker.position)} y1={TOP} y2={TOP + HEIGHT} pointerEvents="none" />
            <circle cx={plotX(marker.position)} cy={TOP + (marker.kind === 'expected' ? 8 : 20)} r="4" />
          </g>
        ))}
        {cursor && (
          <g pointerEvents="none">
            <line x1={plotX(cursor.datum.x)} y1={TOP} x2={plotX(cursor.datum.x)} y2={TOP + HEIGHT} className="plot-crosshair" />
            <line x1={LEFT} y1={plotY(cursor.datum.y)} x2={LEFT + WIDTH} y2={plotY(cursor.datum.y)} className="plot-crosshair" />
            <circle cx={plotX(cursor.datum.x)} cy={plotY(cursor.datum.y)} r="4" className="plot-cursor" />
          </g>
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
      {!stretch && <text x={LEFT} y="24" className="plot-label">
        {curves.find((curve) => curve.priority)?.label ?? curves[0]?.label ?? '无可显示曲线'}
      </text>}
      {xTicks.map((value) => (
        <text key={`x-${value}`} x={plotX(value)} y={TOP + HEIGHT + 20} textAnchor="middle" className="plot-label plot-tick-label">
          {fractionalX ? formatFractionalTick(value) : formatIntegerTick(value)}
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
          {fractionalY ? formatFractionalTick(value) : formatIntegerTick(value)}
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
        className="plot-label plot-axis-title plot-y-axis-title"
      >
        {yAxisLabel}
      </text>
    </svg>
  )
}
