import { ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'
import { buildResidualSeries, formatCurveNumber } from './standardCurveModel'

type ResidualSeries = ReturnType<typeof buildResidualSeries>

function residualReading(point: ResidualSeries['series'][number], relative: boolean) {
  if (point.value == null) return point.missingReason === 'zero-standard' ? '—（标准含量为 0）' : '—'
  return `${formatCurveNumber(point.value, relative ? 2 : 4)}${relative ? '%' : ''}`
}

export function CurveResiduals({ points, diagnostics, hoveredPoint, selectedPoint, onHoverPoint, onSelectPoint }: {
  points: Parameters<typeof buildResidualSeries>[0]
  diagnostics: Parameters<typeof buildResidualSeries>[1]
  hoveredPoint: number | null
  selectedPoint: number
  onHoverPoint: (index: number | null) => void
  onSelectPoint: (index: number) => void
}) {
  const [residualOpen, setResidualOpen] = useState(false)
  const panelId = useId()
  const { mode, series } = residualOpen ? buildResidualSeries(points, diagnostics) : { mode: 'absolute', series: [] }
  const relative = mode === 'relative'
  const axisTitle = relative ? '相对误差 (%)' : '绝对残差'
  const highlighted = series.find((point) => point.pointIndex === (hoveredPoint ?? selectedPoint))
  const max = series.reduce((limit, point) => Math.max(limit, Math.abs(point.value ?? 0)), 0) || 1
  const zero = 22
  const height = zero * 2

  return <section className="standard-curve-residuals" aria-label="标准点残差">
    <button type="button" className="curve-residual-toggle" aria-expanded={residualOpen} aria-controls={panelId}
      onClick={() => setResidualOpen(!residualOpen)}>
      <ChevronDown size={13} aria-hidden="true" />残差分布
    </button>
    <div id={panelId} className="curve-residual-panel" hidden={!residualOpen}>
      {residualOpen && <>
        <div className="curve-residual-meta">
          <span>纵轴：{axisTitle}</span>
          {highlighted && <span className="curve-residual-reading">{highlighted.name}：{residualReading(highlighted, relative)}</span>}
        </div>
        {series.length ? <div className="curve-residual-graph">
          <span className="curve-residual-zero" aria-hidden="true">0</span>
          <svg width="100%" height={height} aria-hidden="true">
            <line className="curve-residual-baseline" x1="0" x2="100%" y1={zero} y2={zero} />
            {series.map((point, index) => {
              const x = `${(index + 0.5) * 100 / series.length}%`
              const hovered = point.pointIndex === hoveredPoint
              const selected = point.pointIndex === selectedPoint
              const y = point.value == null ? null : zero - (point.value / max) * (zero - 6)
              return <g key={point.pointIndex} className="curve-residual-marker" data-active={point.active}
                data-hovered={hovered} data-selected={selected}>
                {y == null ? <text x={x} y={height - 2}>—</text> : <>
                  <line x1={x} x2={x} y1={zero} y2={y} />
                  <circle cx={x} cy={y} r={hovered || selected ? 3.5 : 2.5} />
                </>}
              </g>
            })}
          </svg>
          <div className="curve-residual-hit-targets" style={{ gridTemplateColumns: `repeat(${series.length}, minmax(0, 1fr))` }}>
            {series.map((point) => {
              const label = `${point.name}：${residualReading(point, relative)}，${point.active ? '参与拟合' : '未参与拟合'}`
              return <button key={point.pointIndex} type="button" aria-label={label} title={label}
                aria-pressed={point.pointIndex === selectedPoint}
                onPointerEnter={() => onHoverPoint(point.pointIndex)} onPointerLeave={() => onHoverPoint(null)}
                onClick={() => onSelectPoint(point.pointIndex)} />
            })}
          </div>
        </div> : <span className="curve-residual-empty">—</span>}
      </>}
    </div>
  </section>
}
