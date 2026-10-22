import {
  ShieldCheck
} from 'lucide-react'
import {
  type MethodConditions
} from '../../api'
import { NumberField } from './NumberField'

// 父页面保留完整条件草稿；本面板只编辑旧版六项，隐藏字段随草稿原值保存。
type PanelProps = {
  hasIssue: (field: string) => boolean
  conditions: MethodConditions
  canWrite: boolean
  setCondition: <K extends keyof MethodConditions>(key: K, value: MethodConditions[K]) => void
}

export function MethodQuality({
  hasIssue,
  conditions,
  canWrite,
  setCondition,
}: PanelProps) {
  return (
    <section
      className={`surface method-section method-quality ${['sample_repeats', 'standard_repeats', 'control_repeats', 'maximum_id_deviation', 'rsd_enabled', 'rsd_threshold'].some(hasIssue) ? 'has-errors' : ''}`}
    >
      <div className="surface-heading">
        <div>
          <h2>重复与误差</h2>
        </div>
        <ShieldCheck size={17} />
      </div>
      <div className="method-quality-groups">
      <div className="method-repeat-settings">
      <h3>重复摄谱次数</h3>
      <div className="numeric-grid">
        <NumberField
          label="普通样品"
          value={conditions.sample_repeats}
          min={1}
          max={10}
          disabled={!canWrite}
          onChange={(value) => setCondition('sample_repeats', value)}
        />
        <NumberField
          label="标准样品"
          value={conditions.standard_repeats}
          min={1}
          max={10}
          disabled={!canWrite}
          onChange={(value) => setCondition('standard_repeats', value)}
        />
        <NumberField
          label="管理样"
          value={conditions.control_repeats}
          min={1}
          max={10}
          disabled={!canWrite}
          onChange={(value) => setCondition('control_repeats', value)}
        />
      </div>
      </div>
      <div className="method-error-settings">
      <h3>误差控制</h3>
      <div className="numeric-grid">
        <NumberField
          label="重复摄谱最大允许误差[^P]"
          value={conditions.maximum_id_deviation}
          min={0}
          max={20}
          step={0.1}
          disabled={!canWrite}
          onChange={(value) => setCondition('maximum_id_deviation', value)}
        />
        <label className="toggle-row compact-toggle">
          <input
            type="checkbox"
            checked={conditions.rsd_enabled}
            onChange={(event) => setCondition('rsd_enabled', event.target.checked)}
            disabled={!canWrite}
          />
          <strong>相对偏差校验</strong>
        </label>
        <NumberField
          label="最大允许Rsd[%]"
          value={conditions.rsd_threshold}
          min={0}
          max={20}
          step={0.1}
          disabled={!canWrite || !conditions.rsd_enabled}
          onChange={(value) => setCondition('rsd_threshold', value)}
        />
      </div>
      </div>
      </div>
    </section>
  )
}
