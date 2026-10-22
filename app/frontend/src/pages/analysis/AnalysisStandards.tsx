import { type AnalysisRun } from '../../api'
import type { AnalysisCurveLine } from '../../api/analysis'
import { NumericInput } from '../../components/NumericInput'

// 父页面统一持有草稿、选中项和请求状态。
import { useState } from 'react'
type PanelProps = {
  curveLine: AnalysisCurveLine
  selected: AnalysisRun
  setAdjustments: React.Dispatch<React.SetStateAction<Record<string, number>>>
  adjustments: Record<string, number>
  canCurve: boolean
  busy: boolean
  curveAction: (
    lineId: string,
    payload: Record<string, unknown>,
    success: string,
    afterSuccess?: () => void
  ) => void
}
export function AnalysisStandards({
  curveLine,
  selected,
  setAdjustments,
  adjustments,
  canCurve,
  busy,
  curveAction
}: PanelProps) {
  const [controlTask, setControlTask] = useState<number | null>(null)
  const [controlValue, setControlValue] = useState(1)
  const controls =
    selected.quality.latest_snapshot?.groups.filter(
      (group) => group.line_id === curveLine.line_id && group.management_sample
    ) ?? []
  const control = controls.find((group) => group.acquisition_task_id === controlTask) ?? controls[0]
  const adaptation = curveLine.control_adaptations?.[curveLine.control_adaptations.length - 1]
  const snapshot = curveLine.snapshots[curveLine.snapshots.length - 1]
  const currentFit = snapshot?.adjustment_set_id === curveLine.workspace.adjustment_set_id
    && snapshot?.fit_mode === curveLine.workspace.fit_mode && snapshot?.coordinate_type === curveLine.workspace.coordinate_type
  return (
    <div className="analysis-workspace analysis-matrix">
      <div className="analysis-actions" aria-label="管理样适配">
        <label>
          管理样{' '}
          <select
            value={control?.acquisition_task_id ?? ''}
            disabled={busy || !controls.length}
            onChange={(event) => setControlTask(Number(event.target.value))}
          >
            {!controls.length && <option value="">暂无管理样</option>}
            {controls.map((group) => (
              <option key={group.acquisition_task_id} value={group.acquisition_task_id}>
                {group.sample_name} · 强度 {group.statistics.mean?.toFixed(6)}
              </option>
            ))}
          </select>
        </label>
        <label>
          给定含量 ({curveLine.unit}){' '}
          <NumericInput min={0.000001} step="any" value={controlValue} onValueChange={setControlValue} />
        </label>
        <button
          className="primary-button"
          disabled={busy || !canCurve || !control || controlValue <= 0}
          onClick={() =>
            curveAction(
              curveLine.line_id,
              {
                action: 'adapt_control',
                control_task_id: control?.acquisition_task_id,
                control_value: controlValue,
                reason: `按管理样 ${control?.sample_name} 给定含量 ${controlValue} 适配标准强度`
              },
              '管理样适配已保存，请重新拟合并复核发布'
            )
          }
        >
          适配并保存标准强度
        </button>
      </div>
      <p>
        用当前曲线反算给定含量的信号，按管理样实测信号与该信号的倍率修正整组标准强度；保存后重新拟合、复核并发布。
      </p>
      {adaptation && (
        <p>
          已保存适配 #{adaptation.id}：{adaptation.snapshot.sample_name} · 倍率{' '}
          {adaptation.snapshot.factor.toFixed(6)}
        </p>
      )}
      <div className="surface-heading">
        <div>
          <h3>标准点原始强度与修正集</h3>
        </div>
        <span>原始强度只读</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>名称</th>
            <th>原始强度</th>
            <th>修正强度</th>
            <th>标准值</th>
            <th>反算含量</th>
            <th>相对误差 %</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {curveLine.workspace.points.map((point) => {
            const key = `${selected.id}-${curveLine.line_id}-${point.point_index}`
            const diagnostic = currentFit && (adjustments[key] === undefined || adjustments[key] === point.adjusted_intensity)
              ? snapshot?.diagnostics.points.find((item) => item.point_index === point.point_index) : undefined

            const clearAdjustment = () =>
              setAdjustments((current) => {
                const next = { ...current }

                delete next[key]
                return next
              })

            return (
              <tr key={point.point_index} className={point.active ? '' : 'muted-row'}>
                <td>{point.point_index + 1}</td>
                <td>{point.name}</td>
                <td>
                  <strong>{point.original_intensity?.toFixed(6) ?? '缺少重复均值'}</strong>
                </td>
                <td>
                  <NumericInput
                    step="any"
                    value={adjustments[key] ?? point.adjusted_intensity ?? 0}
                    disabled={busy || !canCurve || point.original_intensity == null}
                    onValueChange={(value) => setAdjustments((current) => ({ ...current, [key]: value }))}
                  />
                </td>
                <td>{point.standard_value}</td>
                <td>{diagnostic ? diagnostic.calculated_value.toPrecision(8) : '待重新拟合'}</td>
                <td>{diagnostic?.relative_error_percent == null ? (diagnostic ? '—' : '待重新拟合') : diagnostic.relative_error_percent.toFixed(4)}</td>
                <td>
                  <label className="analysis-point-active">
                    <input
                      type="checkbox"
                      checked={point.active}
                      disabled={busy || !canCurve}
                      onChange={(event) =>
                        curveAction(
                          curveLine.line_id,
                          {
                            action: 'set_active',
                            point_index: point.point_index,
                            active: event.target.checked,
                            reason: `${event.target.checked ? '启用' : '停用'}标准点 ${point.name}`
                          },
                          '标准点启用状态已保存'
                        )
                      }
                    />
                    {point.active ? '参与拟合' : '已停用'}
                  </label>
                </td>
                <td>
                  <div className="analysis-actions">
                    <button
                      disabled={busy || !canCurve || point.original_intensity == null}
                      onClick={() =>
                        curveAction(
                          curveLine.line_id,
                          {
                            action: 'adjust',
                            point_index: point.point_index,
                            adjusted_intensity: adjustments[key] ?? point.adjusted_intensity,
                            reason: `手工保存标准点 ${point.name} 修正强度`
                          },
                          '修正强度已保存到新的修正集',
                          clearAdjustment
                        )
                      }
                    >
                      保存修正
                    </button>
                    <button
                      disabled={busy || !canCurve || point.original_intensity == null}
                      onClick={() =>
                        curveAction(
                          curveLine.line_id,
                          {
                            action: 'restore',
                            point_index: point.point_index,
                            reason: `恢复标准点 ${point.name} 原始强度`
                          },
                          '标准点已恢复原始强度',
                          clearAdjustment
                        )
                      }
                    >
                      恢复原始
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
