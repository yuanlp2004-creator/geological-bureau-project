import { ClipboardList } from 'lucide-react'
import { type HardwareTask } from '../../api'
import { labels } from './hardwareView'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = { selected: HardwareTask }

/* 展示固定转角步骤、尝试状态及异常决定记录。 */ export function HardwareAcquisitionPlan({
  selected
}: PanelProps) {
  return (
    <section className="surface hardware-plan">
      <div className="surface-heading">
        <div>
          <h2>转角顺序与波段</h2>
        </div>
        <ClipboardList size={16} />
      </div>
      <div className="hardware-table-wrap">
        <table className="hardware-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>波长</th>
              <th>角度</th>
              <th>优先级</th>
              <th>波段</th>
              <th>状态</th>
              <th>重试</th>
              <th>保存区间</th>
            </tr>
          </thead>
          <tbody>
            {selected.steps.map(
              /* 处理本站输入、状态或异步响应。 */ (step) => (
                <tr key={step.id} className={step.order_index === selected.current_step_index ? 'current' : ''}>
                  <td>{step.order_index + 1}</td>
                  <td>
                    <strong>{step.wavelength_nm.toFixed(2)} nm</strong>
                  </td>
                  <td>{step.angle_deg.toFixed(2)}°</td>
                  <td>{step.priority}</td>
                  <td>{step.key_band ? <span className="key-band">关键</span> : '普通'}</td>
                  <td>
                    <span className={`state-chip ${step.status}`}>
                      {labels[step.status] ?? step.status}
                    </span>
                  </td>
                  <td>
                    {step.retry_count}/{selected.retry_limit}
                  </td>
                  <td>{step.start_frame}–{step.end_frame} 帧 · {step.storage_mode === 'averaged' ? '区间平均' : '全区间'}</td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>
      <p>已保存 {selected.exposures?.filter(/* 统计通过确认的结果。 */ item => item.confirmed).length ?? 0} 个区间谱带；原始帧与区间结果分别保留。</p>
    </section>
  )
}
