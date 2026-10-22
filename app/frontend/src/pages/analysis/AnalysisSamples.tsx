import {
  GitMerge
} from 'lucide-react'
import { api, type AnalysisRun } from '../../api'
import type { AnalysisCurveLine } from '../../api/analysis'
import { formatAnalysisValue } from '../../components/analysisUnits'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  busy: boolean
  canCurve: boolean
  selected: AnalysisRun
  mutate: (operation: () => Promise<AnalysisRun>, success: string, continuous?: boolean) => Promise<boolean>
  token: string
  curveLine: AnalysisCurveLine
}

export function AnalysisSamples({
  busy,
  canCurve,
  selected,
  mutate,
  token,
  curveLine,
}: PanelProps) {
  return (
    <div className="analysis-workspace analysis-matrix">
      <div className="surface-heading">
        <div>
          <h3>样品结果与合并保存</h3>
        </div>
        <button
          className="primary-button"
          disabled={
            busy || !canCurve || selected.curves.lines.some((line) => !line.active_curve_snapshot_id)
          }
          onClick={() =>
            void mutate(
              () => api.mergeAnalysisResults(token, selected.id, '保存当前已发布曲线的批次合并结果'),
              '结果合并快照已保存'
            )
          }
        >
          <GitMerge size={14} />
          合并并保存
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>样品</th>
            <th>谱线</th>
            <th>曲线快照</th>
            <th>有效次数</th>
            <th>均值强度</th>
            <th>分析值</th>
          </tr>
        </thead>
        <tbody>
          {selected.curves.results
            .filter(
              (item) => !item.is_standard && item.curve_snapshot_id === curveLine.active_curve_snapshot_id
            )
            .map((item) => (
              <tr key={item.id}>
                <td>{item.sample_name}</td>
                <td>
                  {curveLine.element} {curveLine.wavelength_nm.toFixed(3)}
                </td>
                <td>
                  <strong>#{item.curve_snapshot_id}</strong>
                </td>
                <td>{item.effective_count}</td>
                <td>{item.intensity.toFixed(6)}</td>
                <td>
                  <strong>
                    {formatAnalysisValue(item.calculated_value, curveLine.decimal_places)} {curveLine.unit}
                  </strong>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
      {!curveLine.active_curve_snapshot_id && (
        <div className="empty-state compact-empty">发布该谱线的曲线快照后生成永久引用的样品结果。</div>
      )}
      <div className="merge-history">
        {selected.curves.merges.map((merge) => (
          <article key={merge.id}>
            <div>
              <strong>合并快照 #{merge.sequence}</strong>
              <span>
                {merge.results.length} 个样品 · 曲线{' '}
                {merge.curve_snapshot_ids.map((id) => `#${id}`).join('、')}
              </span>
            </div>
            <code>{merge.result_sha256.slice(0, 20)}</code>
          </article>
        ))}
      </div>
    </div>
  )
}
