import { Plus, Trash2 } from 'lucide-react'
import { type AngleExposure, type MethodConditions, type MethodOptions } from '../../api'
import { NumericInput } from '../../components/NumericInput'

export function MethodAngles({ conditions, canWrite, hasIssue, options, onChange }: {
  conditions: MethodConditions
  canWrite: boolean
  hasIssue: (field: string) => boolean
  options: MethodOptions | null
  onChange: (angles: AngleExposure[]) => void
}) {
  const angles = conditions.angle_exposures
  const add = () => onChange([...angles, {
    angle_deg: (angles[angles.length - 1]?.angle_deg ?? -10) + 10,
    storage_mode: 'averaged', start_frame: 1, end_frame: conditions.frame_count
  }])

  return (
    <section className={`surface method-section method-angle-selection ${hasIssue('angle_exposures') ? 'has-errors' : ''}`}>
      <div className="surface-heading">
        <div>
          <h2>转角与存储方式</h2>
          <p>保存范围为全部采集帧（1–{conditions.frame_count}）；逐线曝光起止在“分析谱线”设置。</p>
        </div>
        {canWrite && <button className="secondary-button" onClick={add}>
          <Plus size={15} />添加角度
        </button>}
      </div>
      <div className="method-angle-grid">
        {angles.map((angle, index) => (
          <div className="method-angle-entry" role="group" aria-label={`第${index + 1}项转角配置`} key={index}>
            <span className="method-angle-number" title={`角度位 ${index + 1}`}>{index + 1}</span>
            <label className="field"><span>转角 (°)</span>
              <NumericInput
                aria-label={`第${index + 1}项转角`}
                min="0" max="360" step="0.1" value={angle.angle_deg}
                disabled={!canWrite}
                onValueChange={(value) => onChange(angles.map((item, position) =>
                  position === index ? { ...item, angle_deg: value } : item))}
              />
            </label>
            <label className="field"><span>存储方式</span>
              <select
                aria-label={`第${index + 1}项存储方式`}
                value={angle.storage_mode}
                disabled={!canWrite}
                onChange={(event) => onChange(angles.map((item, position) =>
                  position === index ? { ...item, storage_mode: event.target.value as AngleExposure['storage_mode'] } : item))}
              >
                {options?.storage_modes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
              </select>
            </label>
            {canWrite && <button className="icon-button compact danger"
                title="移除此角度" disabled={angles.length === 1}
                onClick={() => onChange(angles.filter((_, position) => position !== index))}>
                <Trash2 size={14} />
              </button>}
          </div>
        ))}
      </div>
    </section>
  )
}
