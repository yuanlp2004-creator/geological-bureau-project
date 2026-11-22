import { useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { SpectrumContextHandler, SpectrumPlotCurve, SpectrumPlotCursor } from './SpectrumPlot'
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
  fitPlot?: boolean
  upperTable?: ReactNode
  onSpectrumContext?: SpectrumContextHandler
  children: ReactNode
}

/** One coordinate range owns the strip and peak plot; the strip is computed from actual stored intensities. */
export function LegacySpectrumSurface(p: Props) {
  const root = useRef<HTMLDivElement>(null), clip = useId()
  const [width, setWidth] = useState(960)
  const drag = useRef<{ start:number; last:number } | null>(null)
  useLayoutEffect(() => {
    if (!p.fitPlot || !root.current) return
    const svg = root.current.querySelector<SVGSVGElement>('svg.spectrum-plot')
    if(!svg)return
    const update=()=>setWidth(svg.viewBox.baseVal.width||960)
    const observer=new MutationObserver(update)
    observer.observe(svg,{attributes:true,attributeFilter:['viewBox']});update()
    return () => observer.disconnect()
  }, [p.fitPlot])
  const curve = p.curves.find(item => item.priority) ?? p.curves[0]
  const data = curve?.data ?? []
  const span = p.xMax - p.xMin || 1, plotWidth = width - 88
  const x = (value: number) => 54 + (value - p.xMin) / span * plotWidth
  const grayscale = useMemo(() => {
    const maximum = Math.max(5000, ...data.map(item => item.y))
    return data.map((datum, index) => {
      const next = data[index + 1]?.x ?? datum.x + (data[index - 1] ? datum.x - data[index - 1].x : 1)
      if (next < p.xMin || datum.x > p.xMax) return null
      const gray = legacyGray(datum.y, maximum)
      return <rect key={index} data-point-index={datum.point.point_index} data-intensity={datum.y} data-gray={gray}
        x={x(datum.x)} y="0" width={Math.max(.01, x(next) - x(datum.x) + .1)} height="72" fill={`rgb(${gray}, ${gray}, ${gray})`}/>
    })
  }, [data, p.xMin, p.xMax, span, plotWidth])
  const nativeX = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return p.xMin + ((event.clientX - rect.left) / rect.width * width - 54) / plotWidth * span
  }
  const nearest = (value: number) => data.length ? data.reduce((best, item) => Math.abs(item.x - value) < Math.abs(best.x - value) ? item : best, data[0]) : null
  const pick = (value: number) => {
    const datum = nearest(value)
    return datum && curve ? { curveId: curve.id, curveLabel: curve.label, x: x(datum.x), y: 0, datum } : null
  }
  const left = nearest(p.xMin), right = nearest(p.xMax)
  const formatEdge = (datum: typeof left) => datum ? `${datum.point.point_index + 1}${datum.point.wavelength_nm == null ? '' : ` (${datum.point.wavelength_nm.toFixed(4)})`}` : '—'
  return <div className="legacy-spectrum-visual" ref={root} data-testid="legacy-spectrum-surface">
    <div className="legacy-spectrum-banner">{p.title}</div>
    {p.upperTable ?? <svg className={`legacy-grayscale tool-${p.tool}`} viewBox={`0 0 ${width} 94`} preserveAspectRatio="none"
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
      <defs><clipPath id={clip}><rect x="54" y="0" width={plotWidth} height="72"/></clipPath></defs>
      <rect x="54" y="0" width={plotWidth} height="72" fill="white"/>
      <g clipPath={`url(#${clip})`}>{grayscale}{p.cursor && <line x1={x(p.cursor.datum.x)} x2={x(p.cursor.datum.x)} y1="0" y2="72" stroke="#e32b2b" />}</g>
      <text x="54" y="88">{formatEdge(left)}</text><text x={width-34} y="88" textAnchor="end">{formatEdge(right)}</text>
    </svg>}
    <div className="legacy-peak-plot">
      {p.children}
      {p.cursor && <output className="legacy-plot-readout" aria-label="谱图同步读数">
        {`坐标：${p.cursor.datum.point.point_index + 1}${p.cursor.datum.point.wavelength_nm == null ? '' : ` · 波长 ${p.cursor.datum.point.wavelength_nm.toFixed(4)} nm`} · 积分强度 ${p.cursor.datum.y.toLocaleString('zh-CN', {maximumFractionDigits:6})}${p.locked ? ' · 已锁定' : ''}`}
      </output>}
    </div>
  </div>
}
