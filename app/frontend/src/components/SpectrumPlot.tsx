import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { ZOOM_IN, ZOOM_OUT, type SpectrumViewRange } from './spectrumZoom'
import type { SpectrumPoint } from '../api'
import { formatIntegerTick, integerAxisTicks, fractionalTicks, formatFractionalTick } from './SimpleChartAxes'
import { RenderProfiler } from './RenderProfiler'
import { clientToViewBoxPoint, dataX as toDataX, dataY as toDataY, findNearestDatumIndex,
  observeCanvasEnvironment, plotX as toPlotX, plotY as toPlotY, renderSpectrumCanvas } from './canvasSpectrumRenderer'

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
  datumIndex?: number
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

function cursorDatumIndex(curve: SpectrumPlotCurve, cursor: SpectrumPlotCursor) {
  const { data } = curve
  const pointIndex = cursor.datum.point.point_index
  const cached = curve.id === cursor.curveId ? cursor.datumIndex : undefined
  if (cached !== undefined && data[cached]?.point.point_index === pointIndex) return cached
  if (data[pointIndex]?.point.point_index === pointIndex) return pointIndex

  // Filtering can move a CCD point away from its array offset. Point IDs stay in source order.
  let first = 0
  let end = data.length
  while (first < end) {
    const mid = first + Math.floor((end - first) / 2)
    if (data[mid].point.point_index < pointIndex) first = mid + 1
    else end = mid
  }
  return data[first]?.point.point_index === pointIndex ? first : 0
}

export function observeSpectrumPlotFrame(host: Element, onChange: (frame: DOMRect, dpr: number, svg: SVGSVGElement) => void, alignedElement?: Element) {
  const frame = host.querySelector<SVGRectElement>('.spectrum-plot-stage > svg > .plot-background')
  const svg = frame?.ownerSVGElement
  if (!frame || !svg) return
  const update = () => {
    const rect = frame.getBoundingClientRect()
    if (rect.width > 0) onChange(rect, window.devicePixelRatio || 1, svg)
  }
  const resize = new ResizeObserver(update)
  resize.observe(svg)
  if (alignedElement) resize.observe(alignedElement)
  const geometry = new MutationObserver(update)
  geometry.observe(frame, { attributes: true, attributeFilter: ['x', 'y', 'width', 'height'] })
  geometry.observe(svg, { attributes: true, attributeFilter: ['viewBox', 'preserveAspectRatio'] })
  const stopObserving = observeCanvasEnvironment(update, svg)
  update()
  return () => {
    resize.disconnect()
    geometry.disconnect()
    stopObserving()
  }
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
  const stageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ width: 960, height: 380 })
  useLayoutEffect(() => {
    const svg = svgRef.current
    if (!fitContainer || !svg) return
    const resize = ({ width, height }: Pick<DOMRectReadOnly, 'width' | 'height'>) => {
      if (width > 0 && height > 0) setSize(previous =>
        previous.width === width && previous.height === height ? previous : { width, height })
    }
    resize(svg.getBoundingClientRect())
    const observer = new ResizeObserver(([entry]) => resize(entry.contentRect))
    observer.observe(svg)
    return () => observer.disconnect()
  }, [fitContainer])
  const viewWidth = fitContainer ? Math.max(200, size.width) : 960
  const viewHeight = fitContainer ? Math.max(150, size.height) : 380
  const LEFT = leftPadding
  const TOP = stretch ? 18 : 42
  const WIDTH = viewWidth - LEFT - 34
  const HEIGHT = viewHeight - TOP - 50
  const rect = useMemo(() => ({ left: LEFT, top: TOP, width: WIDTH, height: HEIGHT, viewWidth, viewHeight }),
    [LEFT, TOP, WIDTH, HEIGHT, viewWidth, viewHeight])
  const yTitleCenter = TOP + HEIGHT / 2
  const clipId = useId()
  const [drag, setDrag] = useState<{ startX: number; startY: number; x: number; y: number } | null>(null)
  const [panAnchor, setPanAnchor] = useState<{ x: number; y: number } | null>(null)
  const raf = useRef<number | null>(null)
  useEffect(() => () => { if (raf.current !== null) cancelAnimationFrame(raf.current) }, [])
  const xTicks = useMemo(() => fractionalX ? fractionalTicks(xStart, xEnd) : integerAxisTicks(xStart, xEnd),
    [fractionalX, xStart, xEnd])
  const fractionalY = yEnd - yStart < 4
  const yTickCount = stretch ? Math.max(2, Math.min(5, Math.floor(HEIGHT / 40))) : 5
  const yTicks = useMemo(() => fractionalY ? fractionalTicks(yStart, yEnd) : integerAxisTicks(yStart, yEnd, yTickCount),
    [fractionalY, yStart, yEnd, yTickCount])

  const canvasFrame = useRef<number | null>(null)
  const drawCanvas = useRef<(() => void) | null>(null)
  const scheduleCanvasDraw = useCallback(() => {
    if (canvasFrame.current !== null) return
    canvasFrame.current = requestAnimationFrame(() => {
      canvasFrame.current = null
      drawCanvas.current?.()
    })
  }, [])

  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const observer = new ResizeObserver(scheduleCanvasDraw)
    observer.observe(stage)
    const stopObserving = observeCanvasEnvironment(scheduleCanvasDraw, stage)
    return () => {
      stopObserving()
      observer.disconnect()
      if (canvasFrame.current !== null) cancelAnimationFrame(canvasFrame.current)
      canvasFrame.current = null
      drawCanvas.current = null
    }
  }, [scheduleCanvasDraw])

  const renderSeq = useRef(0)
  const drawnViewBox = useRef('')
  useLayoutEffect(() => {
    const canvas = canvasRef.current
    const stage = stageRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !stage || !ctx) return
    const viewBox = `${viewWidth} ${viewHeight} ${stretch}`
    drawCanvas.current = () => {
      const { width: cssWidth, height: cssHeight } = canvas.getBoundingClientRect()
      if (cssWidth <= 0 || cssHeight <= 0) return
      const styles = getComputedStyle(stage)
      const readVar = (token: string) => styles.getPropertyValue(token).trim()
      const dash = readVar('--plot-grid-dash')
      const dashLengths = dash.split(/[\s,]+/).map(length => Number.parseFloat(length))
      const gridLineDash = dashLengths.every(length => Number.isFinite(length) && length >= 0) ? dashLengths : []
      const curveBrightness = Number(readVar('--plot-curve-brightness') || 1)
      renderSpectrumCanvas(ctx, {
        rect,
        cssWidth, cssHeight, dpr: window.devicePixelRatio || 1, preserveAspectRatio: stretch ? 'none' : 'meet',
        curves, xStart, xEnd, yStart, yEnd, xTicks, yTicks, readVar, gridLineDash,
        backgroundColor: 'var(--plot-background-color, #fbfcfe)',
        gridColor: 'var(--plot-grid-color, var(--line, #e6ebf2))',
        priorityColor: readVar('--plot-priority-color'),
        priorityLineWidth: Number.parseFloat(readVar('--plot-priority-line-width')) || undefined,
        curveBrightness, priorityBrightness: Number(readVar('--plot-priority-brightness') || curveBrightness)
      })
      let lineCount = 0
      let singlePointCount = 0
      const curveIds: string[] = []
      for (const curve of curves) {
        if (!curve.data.length) continue
        curveIds.push(curve.id)
        if (curve.data.length === 1) singlePointCount++
        else lineCount++
      }
      Object.assign(canvas.dataset, {
        lineCount: String(lineCount), singlePointCount: String(singlePointCount), curveIds: curveIds.join(' '),
        xStart: String(xStart), xEnd: String(xEnd), yStart: String(yStart), yEnd: String(yEnd),
        renderSeq: String(++renderSeq.current)
      })
      drawnViewBox.current = viewBox
    }
    // Draw before paint on mount and when the SVG coordinate system changes.
    if (!canvas.dataset.renderSeq || drawnViewBox.current !== viewBox) {
      if (canvasFrame.current !== null) cancelAnimationFrame(canvasFrame.current)
      canvasFrame.current = null
      drawCanvas.current()
    } else {
      scheduleCanvasDraw()
    }
  }, [scheduleCanvasDraw, rect, viewWidth, viewHeight,
    curves, xStart, xEnd, yStart, yEnd, xTicks, yTicks, stretch])

  const plotX = (value: number) => toPlotX(value, xStart, xEnd, rect)
  const plotY = (value: number) => toPlotY(value, yStart, yEnd, rect)
  const dataX = (value: number) => toDataX(value, xStart, xEnd, rect)
  const dataY = (value: number) => toDataY(value, yStart, yEnd, rect)
  const toSvg = (event: Pick<MouseEvent<SVGSVGElement>, 'currentTarget' | 'clientX' | 'clientY'>) => {
    const matrix = event.currentTarget.getScreenCTM()
    return clientToViewBoxPoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect(),
      viewWidth, viewHeight, stretch ? 'none' : 'meet', matrix?.inverse())
  }

  const priority = curves.find(curve => curve.priority) ?? curves[0]
  const cursorFor = (curve: SpectrumPlotCurve, datumIndex: number): SpectrumPlotCursor => {
    const datum = curve.data[datumIndex]
    return {
      curveId: curve.id,
      curveLabel: curve.label,
      x: plotX(datum.x),
      y: plotY(datum.y),
      datum,
      datumIndex
    }
  }
  const cursorAt = (screenX: number): SpectrumPlotCursor | null => {
    if (!priority) return null
    const target = dataX(Math.max(LEFT, Math.min(LEFT + WIDTH, screenX)))
    const nearest = findNearestDatumIndex(priority.data, target)
    return nearest ? cursorFor(priority, nearest.datumIndex) : null
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
    const curve = curves.find(item => item.id === cursor?.curveId) ?? priority
    if (!curve?.data.length) return
    const index = cursor ? cursorDatumIndex(curve, cursor) : 0
    const next = Math.max(0, Math.min(curve.data.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1)))
    const picked = cursorFor(curve, next)
    const { datum } = picked
    onCursor(picked)
    if (datum.x < xStart || datum.x > xEnd) {
      const half = (xEnd - xStart) / 2
      onBoxSelect({ xMin: datum.x - half, xMax: datum.x + half, yMin: yStart, yMax: yEnd })
    }
  }

  const content = (
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
      <rect x={LEFT} y={TOP} width={WIDTH} height={HEIGHT} className="plot-background" style={{ fill: 'transparent' }} />
      <line x1={LEFT} y1={TOP + HEIGHT} x2={LEFT + WIDTH} y2={TOP + HEIGHT} className="plot-axis" />
      <line x1={LEFT} y1={TOP} x2={LEFT} y2={TOP + HEIGHT} className="plot-axis" />
      <g clipPath={`url(#${clipId})`}>
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
        x="6"
        y="12"
        textAnchor="middle"
        transform={`translate(7 ${yTitleCenter - 12}) rotate(-90 6 12)`}
        className="plot-label plot-axis-title plot-y-axis-title"
      >
        {yAxisLabel}
      </text>
    </svg>
  )
  return <RenderProfiler id="SpectrumPlot">
    <div className="spectrum-plot-stage" data-renderer="canvas" ref={stageRef}>
      <canvas className="spectrum-canvas" aria-hidden="true" ref={canvasRef} />
      {content}
    </div>
  </RenderProfiler>
}
