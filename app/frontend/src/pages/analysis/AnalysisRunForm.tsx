import { AdvancedSettings } from '../../components/AdvancedSettings'
import { calculationProfileLabel } from '../../components/calculationProfile'
import { type FormEvent } from 'react'
import type { AnalysisSampleOption } from '../../api/analysis'
import { NumericInput } from '../../components/NumericInput'

// State and request ownership remain in the page.
type PanelProps = {
  create: (event: FormEvent) => Promise<void>
  name: string
  setName: React.Dispatch<React.SetStateAction<string>>
  profile: "legacy_2_0_2" | "modern_v1"
  setProfile: React.Dispatch<React.SetStateAction<"legacy_2_0_2" | "modern_v1">>
  timeout: number
  setTimeout: React.Dispatch<React.SetStateAction<number>>
  slowMode: boolean
  setSlowMode: React.Dispatch<React.SetStateAction<boolean>>
  grouped: AnalysisSampleOption[][]
  sampleIds: number[]
  toggleSample: (id: number, methodVersionId: number) => void
  busy: boolean
  canExecute: boolean
}

export function AnalysisRunForm({
  create,
  name,
  setName,
  profile,
  setProfile,
  timeout,
  setTimeout,
  slowMode,
  setSlowMode,
  grouped,
  sampleIds,
  toggleSample,
  busy,
  canExecute,
}: PanelProps) {
  return (
    <form className="surface analysis-create" onSubmit={create} noValidate>
      <div className="surface-heading analysis-preparation-heading">
        <div>
          <h2>准备分析</h2>
          <p>设置批次，选择已完成采集的样品。</p>
        </div>
        <span className="analysis-selection-count">已选 {sampleIds.length} / {grouped.flat().length} 条记录</span>
      </div>
      <div className="analysis-form-grid">
        <label className="field">
          <span>批次名称</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="field">
          <span>计算模式</span>
          <select value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)}>
            <option value="modern_v1">{calculationProfileLabel('modern_v1')}</option>
            <option value="legacy_2_0_2">{calculationProfileLabel('legacy_2_0_2')}</option>
          </select>
        </label>
        <label className="analysis-switch">
          <input type="checkbox" checked={slowMode} onChange={(event) => setSlowMode(event.target.checked)} />
          <span>
            <strong>逐谱线慢进</strong>
            <small>每条谱线暂停并等待接受或放弃</small>
          </span>
        </label>
      </div>
      {slowMode && (
        <AdvancedSettings title="高级慢进设置">
        <label className="field">
          <span>慢进超时（秒）</span>
          <NumericInput min={0.05} max={86_400} step="any" value={timeout} onValueChange={setTimeout} />
        </label>
        </AdvancedSettings>
      )}
      <section className="analysis-source-section" aria-label="选择采集记录">
        <header><h3>采集记录</h3><span>同一分析批次使用同一方法版本</span></header>
        <div className="analysis-source-columns" aria-hidden="true"><span>样品名称</span><span>重复</span><span>方法版本</span></div>
        <div className="analysis-sample-groups">
        {grouped.map((samples) => (
          <div key={samples[0].acquisition_task_id}>
            <div className="analysis-source-group-heading"><strong>{samples[0].acquisition_task_name}</strong><span>{samples.length} 条记录</span></div>
            <div>
              {samples.map((sample) => (
                <label key={sample.id} className={sampleIds.includes(sample.id) ? 'selected' : ''}>
                  <input
                    type="checkbox"
                    checked={sampleIds.includes(sample.id)}
                    onChange={() => toggleSample(sample.id, sample.method_version_id)}
                  />
                  <span>{sample.sample_name || `未命名样品 #${sample.id}`}</span>
                  <small>重复 {sample.repeat_index + 1}</small>
                  <small>方法 v{sample.method_version}</small>
                </label>
              ))}
            </div>
          </div>
        ))}
        {!grouped.length && <p className="analysis-source-empty">暂无已完成采集的样品，请先完成样品摄谱。</p>}
        </div>
      </section>
      <footer className="analysis-create-footer">
        <span>{sampleIds.length ? `已选择 ${sampleIds.length} 条采集记录，可建立分析批次` : '请选择需要分析的采集记录'}</span>
        <button type="submit" className="primary-button" disabled={busy || !canExecute}>
        {busy ? '处理中…' : '建立并锁定输入'}
        </button>
      </footer>
    </form>
  )
}
