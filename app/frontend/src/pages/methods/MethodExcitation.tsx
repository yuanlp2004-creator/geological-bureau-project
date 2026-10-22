import {
  Activity
} from 'lucide-react'
import {
  type MethodConditions
} from '../../api'
import { NumberField } from './NumberField'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  hasIssue: (field: string) => boolean
  conditions: MethodConditions
  canWrite: boolean
  setCondition: <K extends keyof MethodConditions>(key: K, value: MethodConditions[K]) => void
}

export function MethodExcitation({
  hasIssue,
  conditions,
  canWrite,
  setCondition,
}: PanelProps) {
  return (
    <section
      className={`surface method-section method-excitation ${hasIssue('frame_count') || hasIssue('dark_frame_count') ? 'has-errors' : ''}`}
    >
      <div className="surface-heading">
        <div>
          <h2>激发参数</h2>
        </div>
        <Activity size={17} />
      </div>
      <div className="numeric-grid">
        <label className="checkbox-row method-interval-mode">
          <input type="checkbox" aria-label="区间曝光" checked={conditions.exposure_mode === 'line_interval'}
            disabled={!canWrite} onChange={(event) => {
              setCondition('exposure_mode', event.target.checked ? 'line_interval' : 'simple_mean')
              if (event.target.checked && conditions.frame_count < 2) setCondition('frame_count', 2)
            }} />
          <span>区间曝光</span>
        </label>
        <p className="method-exposure-help">关闭时按简单均值保存；开启后保存全时数据，保存方法后在“分析谱线”设置每条线的曝光起止帧。</p>
        <NumberField
          label="预激时间 (s)"
          value={conditions.pre_excitation_seconds}
          min={1}
          max={10}
          step="any"
          disabled={!canWrite}
          onChange={(value) => setCondition('pre_excitation_seconds', value)}
        />
        <NumberField
          label="采样周期 (s)"
          value={conditions.sampling_period_seconds}
          min={1}
          max={2}
          step="any"
          disabled={!canWrite}
          onChange={(value) => setCondition('sampling_period_seconds', value)}
        />
        <NumberField
          label="采样次数"
          value={conditions.frame_count}
          min={conditions.exposure_mode === 'line_interval' ? 2 : 1}
          max={255}
          disabled={!canWrite}
          onChange={(value) => setCondition('frame_count', value)}
        />
        <NumberField
          label="空白次数"
          value={conditions.dark_frame_count}
          min={0}
          max={20}
          disabled={!canWrite}
          onChange={(value) => setCondition('dark_frame_count', value)}
        />
      </div>
    </section>
  )
}
