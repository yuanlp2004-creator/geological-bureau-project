import { useMemo, useState, type ReactNode } from 'react'
import type { AcquisitionFrame } from '../../api'
import { ObservationToolbar } from '../../components/ObservationToolbar'
import { SpectrumPlot, type SpectrumPlotCursor } from '../../components/SpectrumPlot'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { limitSpectrumRange, stepSpectrumRange, type SpectrumAxis } from '../../components/spectrumZoom'

export function EvaporationCurvePlot({ rows, metric, label, navigation }: {
  rows: AcquisitionFrame[]; metric: 'peak_value' | 'integral_value'; label: string; navigation: ReactNode
}) {
  const data = useMemo(() => rows.map((frame, index) => ({ x: frame.virtual_time_ms / 1000,
    y: frame[metric] ?? 0, point: { point_index: index, value: frame[metric] ?? 0 } })), [rows, metric])
  const full = useMemo(() => ({ xMin: data[0]?.x ?? 0, xMax: Math.max((data[0]?.x ?? 0) + .001, data[data.length - 1]?.x ?? 1),
    yMin: Math.min(0, ...data.map(item => item.y)), yMax: Math.max(1, ...data.map(item => item.y)) * 1.05 }), [data])
  const [range, setRange] = useState<typeof full | null>(null)
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [locked, setLocked] = useState(false)
  const view = range ? limitSpectrumRange(range, full) : full
  const reset = () => { setRange(null); setCursor(null); setLocked(false) }
  const zoom = (axis: SpectrumAxis, factor: number) => setRange(stepSpectrumRange(view, full, axis, factor))
  return <div className="evaporation-time-chart-view" data-testid="evaporation-time-chart">
    <ObservationToolbar navigation={navigation} disabled={!data.length} tool={tool} setTool={setTool} fit={reset} zoom={zoom}
      resetY={() => setRange({ ...view, yMin: full.yMin, yMax: full.yMax })}>
      <SpectroscopyToolButton icon="lock" label={locked ? '解除锁定' : '锁定点位'} disabled={!cursor} aria-pressed={locked} onClick={() => setLocked(value => !value)} />
    </ObservationToolbar>
    <div className="observation-plot">
      <SpectrumPlot fitContainer fractionalX leftPadding={90} curves={[{ id: 'evaporation', label, color: '#1570a6', priority: true, data }]}
        xStart={view.xMin} xEnd={view.xMax} yStart={view.yMin} yEnd={view.yMax} tool={tool} cursor={cursor} locked={locked}
        onCursor={setCursor} onToggleLock={picked => { if (picked) setCursor(picked); setLocked(value => !value) }}
        onPan={(x, y) => setRange({ xMin: view.xMin - x * (view.xMax - view.xMin), xMax: view.xMax - x * (view.xMax - view.xMin),
          yMin: view.yMin + y * (view.yMax - view.yMin), yMax: view.yMax + y * (view.yMax - view.yMin) })}
        onBoxSelect={next => setRange(limitSpectrumRange(next, full))} onZoomY={factor => zoom('y', factor)}
        xAxisLabel="采集时间（秒）" yAxisLabel={label} />
    </div>
    <div className="observation-status" aria-live="polite"><output aria-label="蒸发曲线读数">{cursor
      ? `帧 ${rows[cursor.datum.point.point_index].frame_index + 1} · 时间 ${cursor.datum.x.toFixed(3)} 秒 · ${label} ${cursor.datum.y.toFixed(3)}${locked ? ' · 已锁定' : ''}`
      : '移动鼠标查看强度，单击曲线锁定点位'}</output></div>
    <div className="observation-status" aria-label="蒸发曲线视野">时间 {view.xMin.toFixed(3)}–{view.xMax.toFixed(3)} 秒 · 强度 {view.yMin.toFixed(3)}–{view.yMax.toFixed(3)}</div>
  </div>
}

