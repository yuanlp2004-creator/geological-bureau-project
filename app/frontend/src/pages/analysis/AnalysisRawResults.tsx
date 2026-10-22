import { type AnalysisRun } from '../../api'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  selected: AnalysisRun
}

export function AnalysisRawResults({
  selected,
}: PanelProps) {
  return (
    <div className="analysis-matrix">
      <div className="surface-heading">
        <div>
          <h3>原始单/多样品结果矩阵</h3>
        </div>
        <span>{selected.line_results.filter((item) => item.line_type === 'analysis').length} 条结果</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>样品</th>
            <th>谱线</th>
            <th>峰位</th>
            <th>峰高</th>
            <th>背景</th>
            <th>Sigma</th>
            <th>面积</th>
            <th>定量信号</th>
          </tr>
        </thead>
        <tbody>
          {selected.line_results
            .filter((item) => item.line_type === 'analysis')
            .map((item) => (
              <tr key={item.id}>
                <td>{selected.samples[item.sample_position]?.sample_name}</td>
                <td>
                  {item.element} {item.wavelength_nm.toFixed(3)}
                </td>
                <td>
                  {item.peak_position}
                  {item.intervention_id ? ' · 人工' : ''}
                </td>
                <td>{item.peak_height.toFixed(3)}</td>
                <td>{item.background.toFixed(3)}</td>
                <td>{item.gaussian_sigma?.toFixed(4) ?? '—'}</td>
                <td>{item.gaussian_area?.toFixed(3) ?? '—'}</td>
                <td>
                  <strong>{item.quantitative_signal.toFixed(5)}</strong>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}
