import {
  Activity
} from 'lucide-react'
import { type MercurySession } from '../../api'
import { labels } from './mercuryView'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  selected: MercurySession
}

export function MercuryCalibrationResults({
  selected,
}: PanelProps) {
  return (
    <section className="surface mercury-lines">
      <div className="surface-heading">
        <div>
          <h2>汞线峰位与校正前后</h2>
        </div>
        <Activity size={16} />
      </div>
      <div className="mercury-table-wrap">
        <table>
          <thead>
            <tr>
              <th>汞线</th>
              <th>CCD</th>
              <th>期望位置</th>
              <th>实测位置</th>
              <th>校正前偏移</th>
              <th>校正后偏移</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {selected.lines.map((line) => (
              <tr key={line.id}>
                <td>
                  <strong>{line.wavelength_nm.toFixed(4)} nm</strong>
                </td>
                <td>{line.expected_ccd_index}</td>
                <td>{line.expected_position.toFixed(3)}</td>
                <td>{line.observed_position?.toFixed(3) ?? '--'}</td>
                <td>{line.offset_points?.toFixed(3) ?? '--'}</td>
                <td>{line.after_offset_points?.toFixed(3) ?? '--'}</td>
                <td>
                  <span className={`state-chip ${line.state}`}>{labels[line.state]}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
