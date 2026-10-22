import type { AnalysisCurveSnapshot } from '../../api'
import type { AnalysisCurvePoint } from '../../api/analysis'
import { SimpleChartAxes } from '../../components/SimpleChartAxes'

export function CurveChart({ snapshot, unit, points, selectedPoint, onSelectPoint }: {
  snapshot: AnalysisCurveSnapshot | undefined; unit: string; points?: AnalysisCurvePoint[]
  selectedPoint?: number; onSelectPoint?: (index: number) => void
}) {
  if (!snapshot?.chart.length) return <div className="empty-state compact-empty">拟合后显示不可变曲线快照</div>
  const logarithmic = snapshot.coordinate_type === 'logarithmic'
  const transform = (value: number) => logarithmic ? Math.log(Math.max(value, 1e-300)) : value
  const xValues = [
    ...snapshot.chart.map((item) => transform(item.value)),
    ...(points ?? snapshot.diagnostics.points).map((item) => transform(item.standard_value))
  ]
  const yValues = [
    ...snapshot.chart.map((item) => transform(item.intensity)),
    ...(points ?? snapshot.diagnostics.points).map((item) => transform(item.adjusted_intensity ?? 0))
  ]
  const minX = Math.min(...xValues)
  const maxX = Math.max(...xValues)
  const minY = Math.min(...yValues)
  const maxY = Math.max(...yValues)
  const spanX = Math.max(maxX - minX, 1e-12)
  const spanY = Math.max(maxY - minY, 1e-12)
  const point = (x: number, y: number) => `${40 + (820 * (x - minX)) / spanX},${300 - (260 * (y - minY)) / spanY}`
  return (
    <div className="analysis-curve-chart simple-chart-plot-host">
      <div className="simple-chart-plot">
        <svg viewBox="40 40 820 260" preserveAspectRatio="none" role="img" aria-label="标准曲线" style={{ overflow: 'visible' }}>
          <rect x="40" y="40" width="820" height="260" />
          <polyline points={snapshot.chart.map((item) => point(transform(item.value), transform(item.intensity))).join(' ')} />
          {(points ?? snapshot.diagnostics.points).filter((item) => item.adjusted_intensity != null).map((item) => {
            const [cx, cy] = point(transform(item.standard_value), transform(item.adjusted_intensity ?? 0)).split(',')
            return <circle key={item.point_index} cx={cx} cy={cy} r={selectedPoint === item.point_index ? 8 : 5}
              style={{ fill: item.active ? (selectedPoint === item.point_index ? '#146fa0' : '#ed8c4a') : '#9ba5ad', cursor: onSelectPoint ? 'pointer' : undefined }}
              role={onSelectPoint ? 'button' : undefined} tabIndex={onSelectPoint ? 0 : undefined}
              aria-label={`标准点 ${item.name}`} aria-pressed={selectedPoint === item.point_index}
              onClick={() => onSelectPoint?.(item.point_index)}
              onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectPoint?.(item.point_index) } }}>
              <title>{item.name} · 强度 {item.adjusted_intensity}</title>
            </circle>
          })}
        </svg>
      </div>
      <SimpleChartAxes xMin={minX} xMax={maxX} yMin={minY} yMax={maxY} xLabel={`分析值 (${unit})`} yLabel="强度"
        fractionalX fractionalY logarithmicX={logarithmic} logarithmicY={logarithmic} />
    </div>
  )
}
