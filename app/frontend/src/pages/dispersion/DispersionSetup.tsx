import {
  Plus,
  Zap
} from 'lucide-react'
import {
  type DispersionOptions
} from '../../api'
import { NumericInput } from '../../components/NumericInput'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  legacySource: string
  setLegacySource: React.Dispatch<React.SetStateAction<string>>
  options: DispersionOptions | null
  profileId: number | null
  setProfileId: React.Dispatch<React.SetStateAction<number | null>>
  layoutId: number | null
  setLayoutId: React.Dispatch<React.SetStateAction<number | null>>
  preSeconds: number
  setPreSeconds: React.Dispatch<React.SetStateAction<number>>
  samplingPeriod: number
  setSamplingPeriod: React.Dispatch<React.SetStateAction<number>>
  frameCount: number
  setFrameCount: React.Dispatch<React.SetStateAction<number>>
  darkFrameCount: number
  setDarkFrameCount: React.Dispatch<React.SetStateAction<number>>
  createTask: () => Promise<void>
  saveConditions: () => Promise<void>
  canWrite: boolean
  busy: boolean
  hideSubmit?: boolean
}

export function DispersionSetup({
  legacySource,
  setLegacySource,
  options,
  profileId,
  setProfileId,
  layoutId,
  setLayoutId,
  preSeconds,
  setPreSeconds,
  samplingPeriod,
  setSamplingPeriod,
  frameCount,
  setFrameCount,
  darkFrameCount,
  setDarkFrameCount,
  createTask,
  saveConditions,
  canWrite,
  busy,
  hideSubmit = false,
}: PanelProps) {
  return (
    <section className="surface dispersion-setup">
      {' '}
      <div className="surface-heading">
        <div>
          <h2>采集条件</h2>
        </div>
        <Zap size={17} />
      </div>
      <div className="dispersion-source-grid">
        <label className="field">
          <span>数据来源</span>
          <select value={legacySource} onChange={(event) => setLegacySource(event.target.value)}>
            <option value="">新采集</option>
            {options?.legacy_sources?.map((source) => (
              <option key={source.id} value={source.id}>
                旧 WDT #{source.id} {source.sample_name || source.band_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>设备档案</span>
          <select value={profileId ?? ''} onChange={(event) => setProfileId(Number(event.target.value))}>
            {options?.device_profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name} · {profile.transport}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>CCD 布局</span>
          <select value={layoutId ?? ''} onChange={(event) => setLayoutId(Number(event.target.value))}>
            {options?.ccd_layouts.map((layout) => (
              <option key={layout.id} value={layout.id}>
                {layout.name} · {layout.frame_count}×{layout.ccds_per_frame}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="dispersion-number-grid">
        <label className="field">
          <span>预激时间（秒）</span>
          <NumericInput min={0} max={600} disabled={!canWrite || busy || !options} value={preSeconds} onValueChange={setPreSeconds} />
        </label>
        <label className="field">
          <span>采样周期（秒）</span>
          <NumericInput
            min={0.01}
            max={60}
            step={0.01}
            value={samplingPeriod}
            disabled={!canWrite || busy || !options}
            onValueChange={setSamplingPeriod}
          />
        </label>
        <label className="field">
          <span>采样次数</span>
          <NumericInput min={1} max={255} disabled={!canWrite || busy || !options} value={frameCount} onValueChange={setFrameCount} />
        </label>
        <label className="field">
          <span>空白次数</span>
          <NumericInput min={0} max={20} disabled={!canWrite || busy || !options} value={darkFrameCount} onValueChange={setDarkFrameCount} />
        </label>
      </div>
      <button className="secondary-button" onClick={() => void saveConditions()}
        disabled={!canWrite || busy}>保存激发条件</button>
      {!hideSubmit && <button
        className="primary-button full-button"
        onClick={() => void createTask()}
        disabled={!canWrite || busy || profileId === null || layoutId === null}
      >
        <Plus size={15} />
        新建任务
      </button>}
    </section>
  )
}
