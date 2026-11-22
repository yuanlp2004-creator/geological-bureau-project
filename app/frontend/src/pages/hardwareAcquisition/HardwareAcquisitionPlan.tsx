import type { HardwareTask } from '../../api'
import { RowSelectionArrow } from '../../components/RowSelectionArrow'
import { labels } from './hardwareView'

export function HardwareAcquisitionPlan({ selected, viewStep, onChoose }: {
  selected: HardwareTask; viewStep: number | null; onChoose: (id: number) => void
}) {
  const title = selected.execution_mode === 'manual' ? '转角顺序与时长' : '转角顺序与波段'
  return <section className="hardware-plan" aria-label={title}><h2>{title}</h2>
    <div className="hardware-table-wrap"><table className="hardware-table"><thead><tr>
      <th aria-label="当前转角" /><th>{selected.execution_mode === 'manual' ? '角度 / 时长' : '波长 / 角度'}</th><th>状态</th>
    </tr></thead><tbody>{selected.steps.map(step => {
      const current = step.id === viewStep || (viewStep === null && step.order_index === selected.current_step_index)
      return <tr key={step.id} className={current ? 'current' : ''}>
        <td>{current && <RowSelectionArrow />}</td><td><button type="button" title="查看该转角谱图"
          onClick={() => onChoose(step.id)} aria-pressed={current}>
          <strong>{selected.execution_mode === 'manual' ? `${step.angle_deg.toFixed(2)}°` : `${step.wavelength_nm?.toFixed(2)} nm`} {step.key_band && <span className="key-band">关键</span>}</strong>
          <small>{selected.execution_mode === 'manual' ? `采集 ${step.duration_seconds} 秒` : `${step.angle_deg.toFixed(2)}° · ${step.start_frame}–${step.end_frame} 帧`}</small>
        </button></td><td><span>{labels[step.status] ?? step.status}</span>{step.retry_count > 0 && <small>重采 {step.retry_count} 次</small>}</td>
      </tr>
    })}</tbody></table></div>
  </section>
}
