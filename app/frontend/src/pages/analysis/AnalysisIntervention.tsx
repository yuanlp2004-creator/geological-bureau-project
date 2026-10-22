import {
  CheckCircle2,
  CirclePause
} from 'lucide-react'
import type { AnalysisCheckpoint } from '../../api/analysis'
import { NumericInput } from '../../components/NumericInput'
import { SimpleChartAxes } from '../../components/SimpleChartAxes'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  checkpoint: AnalysisCheckpoint
  chart: { point_index: number; value: number }[]
  minPoint: number
  span: number
  maxValue: number
  adjustedPosition: number | null
  setAdjustedPosition: React.Dispatch<React.SetStateAction<number | null>>
  reason: string
  setReason: React.Dispatch<React.SetStateAction<string>>
  intervene: (action: "accept" | "discard") => Promise<void>
  busy: boolean
  canIntervene: boolean
}

export function AnalysisIntervention({
  checkpoint,
  chart,
  minPoint,
  span,
  maxValue,
  adjustedPosition,
  setAdjustedPosition,
  reason,
  setReason,
  intervene,
  busy,
  canIntervene,
}: PanelProps) {
  return (
    <div className="analysis-checkpoint">
      <div className="checkpoint-heading">
        <div>
          <CirclePause size={20} />
          <div>
            <span>慢进检查点 #{checkpoint.sequence}</span>
            <strong>
              {checkpoint.candidate.element} {checkpoint.candidate.wavelength_nm.toFixed(4)} nm
            </strong>
          </div>
        </div>
        <small>
          自动峰位 {checkpoint.automatic_position} · 截止{' '}
          {new Date(checkpoint.deadline_at).toLocaleString()}
        </small>
      </div>
      <div className="analysis-checkpoint-chart simple-chart-plot-host">
        <div className="simple-chart-plot">
          <svg viewBox="0 0 690 170" preserveAspectRatio="none" role="img" aria-label="峰位周边谱图">
            <rect x="0" y="0" width="690" height="170" />
            <polyline
              points={chart
                .map(
                  (point) =>
                    `${((point.point_index - minPoint) / span) * 690},${170 - (point.value / maxValue) * 160}`
                )
                .join(' ')}
            />
            <line
              className="auto-line"
              x1={((checkpoint.automatic_position - minPoint) / span) * 690}
              x2={((checkpoint.automatic_position - minPoint) / span) * 690}
              y1="0"
              y2="170"
            />
            <line
              className="adjust-line"
              x1={(((adjustedPosition ?? checkpoint.automatic_position) - minPoint) / span) * 690}
              x2={(((adjustedPosition ?? checkpoint.automatic_position) - minPoint) / span) * 690}
              y1="0"
              y2="170"
            />
          </svg>
        </div>
        <SimpleChartAxes
          xMin={minPoint + 1}
          xMax={minPoint + span + 1}
          yMin={0}
          yMax={maxValue}
          xLabel="CCD 点位"
          yLabel="强度 (ADC)"
        />
      </div>
      <div className="checkpoint-controls">
        <label className="field">
          <span>调整后峰位</span>
          <NumericInput
            min={checkpoint.window_start}
            max={checkpoint.window_end}
            value={adjustedPosition ?? checkpoint.automatic_position}
            onValueChange={setAdjustedPosition}
          />
        </label>
        <label className="field grow">
          <span>调整理由</span>
          <input value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        <button
          className="primary-button"
          onClick={() => void intervene('accept')}
          disabled={busy || !canIntervene}
        >
          <CheckCircle2 size={15} />
          接受调整
        </button>
        <button
          className="secondary-button"
          onClick={() => void intervene('discard')}
          disabled={busy || !canIntervene}
        >
          放弃调整
        </button>
      </div>
    </div>
  )
}
