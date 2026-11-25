import { useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { observeSpectrumPlotFrame, type SpectrumContextHandler, type SpectrumPlotCurve, type SpectrumPlotCursor } from './SpectrumPlot'
import { findNearestDatumIndex } from './canvasSpectrumRenderer'
import { legacyGray } from './legacyObservation'
import './legacy-viewing.css'

type Props = {
  title: ReactNode
  curves: SpectrumPlotCurve[]
  xMin: number; xMax: number; yMin: number; yMax: number
  cursor: SpectrumPlotCursor | null
  locked: boolean
  tool: 'crosshair' | 'pan' | 'box'
  onCursor: (cursor: SpectrumPlotCursor | null) => void
  onPointerPresence?: (inside: boolean, ctrlKey: boolean) => void
  onToggleLock: (cursor?: SpectrumPlotCursor) => void
  onPan: (x: number, y: number) => void
  onBox: (range: {xMin:number;xMax:number;yMin:number;yMax:number}) => void
  upperTable?: ReactNode
  onSpectrumContext?: SpectrumContextHandler
  children: ReactNode
}

/** One coordinate range owns the strip and peak plot; the strip is computed from actual stored intensities. */
export function LegacySpectrumSurface(p: Props) {
  const root = useRef<HTMLDivElement>(null), clip = useId()
  const strip = useRef<SVGSVGElement>(null)
  const [{ width, left: plotLeft, plotWidth }, setGeometry] = useState({ width: 960, left: 54, plotWidth: 872 })
  const showStrip = p.upperTable == null
  const drag = useRef<{ start:number; last:number } | null>(null)
  useLayoutEffect(() => {
    const element = strip.current
    if (!root.current || !element) return
    return observeSpectrumPlotFrame(root.current, (frame, _dpr, svg) => {
      const bounds = element.getBoundingClientRect()
      if (!bounds.width) return
      const width = svg.viewBox.baseVal.width
      const scale = width / bounds.width
      const left = (frame.left - bounds.left) * scale
      const plotWidth = frame.width * scale
      setGeometry(previous => previous.width === width && previous.left === left && previous.plotWidth === plotWidth
        ? previous : { width, left, plotWidth })
    }, element)
  }, [showStrip])
  const curve = p.curves.find(item => item.priority) ?? p.curves[0]
  const data = curve?.data ?? []
  const span = p.xMax - p.xMin || 1
  const x = (value: number) => plotLeft + (value - p.xMin) / span * plotWidth
  const grayscale = useMemo(() => {
    const maximum = data.reduce((max, datum) => Math.max(max, datum.y), 5000)
    return data.map((datum, index) => {
      const previous = data[index - 1]
      if (previous?.x === datum.x) return null
      let next = index + 1
      while (data[next]?.x === datum.x) next++
      // A cell covers the pixels for which this point is nearest in the peak plot.
      const start = previous ? (previous.x + datum.x) / 2 : p.xMin
      const end = data[next] ? (data[next].x + datum.x) / 2 : p.xMax
      if (end <= p.xMin || start >= p.xMax) return null
      const gray = legacyGray(datum.y, maximum)
      return <rect key={index} data-point-index={datum.point.point_index} data-intensity={datum.y} data-gray={gray}
        x={x(start)} y="0" width={x(end) - x(start)} height="72" shapeRendering="crispEdges"
        fill={`rgb(${gray}, ${gray}, ${gray})`}/>
    })
  }, [data, p.xMin, p.xMax, span, plotLeft, plotWidth])
  const nativeX = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const fraction = ((event.clientX - rect.left) / rect.width * width - plotLeft) / plotWidth
    return p.xMin + Math.max(0, Math.min(1, fraction)) * span
  }
  const pick = (value: number) => {
    const nearest = findNearestDatumIndex(data, value)
    return nearest && curve ? { curveId: curve.id, curveLabel: curve.label, x: x(nearest.datum.x), y: 0, ...nearest } : null
  }
  const left = pick(p.xMin)?.datum, right = pick(p.xMax)?.datum
  const formatEdge = (datum: typeof left) => datum ? `${datum.point.point_index + 1}${datum.point.wavelength_nm == null ? '' : ` (${datum.point.wavelength_nm.toFixed(4)})`}` : '—'
  return <div className="legacy-spectrum-visual" ref={root} data-testid="legacy-spectrum-surface">
    <div className="legacy-spectrum-banner">{p.title}</div>
    {p.upperTable ?? <svg ref={strip} className={`legacy-grayscale tool-${p.tool}`} viewBox={`0 0 ${width} 94`} preserveAspectRatio="none"
      role="img" aria-label="灰度谱带" data-x-min={p.xMin} data-x-max={p.xMax}
      onContextMenu={p.onSpectrumContext && (event => p.onSpectrumContext?.(event, event.clientX || event.clientY ? pick(nativeX(event)) : p.cursor))}
      onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); const value = nativeX(event); drag.current = {start:value,last:event.clientX} }}
      onPointerMove={event => {
        p.onPointerPresence?.(true, event.ctrlKey)
        const value = nativeX(event), current = drag.current
        if (p.tool === 'pan' && current) { p.onPan((event.clientX-current.last)/event.currentTarget.getBoundingClientRect().width*width/plotWidth,0); current.last=event.clientX }
        else if (p.tool === 'crosshair' && !event.ctrlKey && !p.locked) p.onCursor(pick(value))
      }}
      onPointerUp={event => {
        const value = nativeX(event), current = drag.current; drag.current=null
        if (!current) return
        if (p.tool === 'box' && Math.abs(value-current.start) > span*.005)
          p.onBox({xMin:Math.min(value,current.start),xMax:Math.max(value,current.start),yMin:p.yMin,yMax:p.yMax})
        else if (p.tool === 'crosshair' && !event.ctrlKey) {
          const selected = p.locked ? p.cursor : pick(value)
          if (selected) { p.onCursor(selected); p.onToggleLock(selected) }
        }
      }} onPointerCancel={() => {drag.current=null}}
      onPointerLeave={event => {
        p.onPointerPresence?.(false, event.ctrlKey)
        if (!event.ctrlKey && !p.locked && !drag.current) p.onCursor(null)
      }}>
      <defs><clipPath id={clip}><rect x={plotLeft} y="0" width={plotWidth} height="72"/></clipPath></defs>
      <rect x={plotLeft} y="0" width={plotWidth} height="72" fill="white"/>
      <g clipPath={`url(#${clip})`}>{grayscale}{p.cursor && <line x1={x(p.cursor.datum.x)} x2={x(p.cursor.datum.x)} y1="0" y2="72" stroke="var(--spec-crosshair, #e32b2b)" />}</g>
      <text x={plotLeft} y="88">{formatEdge(left)}</text><text x={plotLeft + plotWidth} y="88" textAnchor="end">{formatEdge(right)}</text>
    </svg>}
    <div className="legacy-peak-plot">
      {p.children}
      {p.cursor && <output className="legacy-plot-readout" aria-label="谱图同步读数">
        {`坐标：${p.cursor.datum.point.point_index + 1}${p.cursor.datum.point.wavelength_nm == null ? '' : ` · 波长 ${p.cursor.datum.point.wavelength_nm.toFixed(4)} nm`} · 积分强度 ${p.cursor.datum.y.toLocaleString('zh-CN', {maximumFractionDigits:6})}${p.locked ? ' · 已锁定' : ''}`}
      </output>}
    </div>
  </div>
}
