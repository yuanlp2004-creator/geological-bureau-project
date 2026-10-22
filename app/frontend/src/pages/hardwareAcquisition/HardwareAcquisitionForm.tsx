import { SectionHeading } from '../../components/SectionHeading'
import { AdvancedSettings } from '../../components/AdvancedSettings'
import { ClipboardList, RotateCcw, ShieldAlert } from 'lucide-react'
import { type FormEvent } from 'react'
import { type HardwareOptions } from '../../api'
import { NumericInput } from '../../components/NumericInput'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  methodSelection: string
  setMethodSelection: React.Dispatch<React.SetStateAction<string>>
  create: (event: FormEvent) => Promise<void>
  name: string
  setName: React.Dispatch<React.SetStateAction<string>>
  canWrite: boolean
  busy: boolean
  profileId: number | null
  setProfileId: React.Dispatch<React.SetStateAction<number | null>>
  options: HardwareOptions | null
  layoutId: string
  setLayoutId: React.Dispatch<React.SetStateAction<string>>
  strategy: 'short_to_long' | 'key_first'
  setStrategy: React.Dispatch<React.SetStateAction<'short_to_long' | 'key_first'>>
  policy: 'retry_then_stop' | 'manual'
  setPolicy: React.Dispatch<React.SetStateAction<'retry_then_stop' | 'manual'>>
  retryLimit: number
  setRetryLimit: React.Dispatch<React.SetStateAction<number>>
  sample: string
  setSample: React.Dispatch<React.SetStateAction<string>>
  seed: number
  setSeed: React.Dispatch<React.SetStateAction<number>>
  turns: string
  setTurns: React.Dispatch<React.SetStateAction<string>>
  anomalies: string
  setAnomalies: React.Dispatch<React.SetStateAction<string>>
  selectedProfile:
    | {
        id: number
        name: string
        transport: string
        port: number
        baud_rate: number
        ccd_indices: number[]
        points_per_ccd: number
      }
    | undefined
}
export function HardwareAcquisitionForm({
  create,
  name,
  setName,
  canWrite,
  busy,
  profileId,
  setProfileId,
  options,
  layoutId,
  setLayoutId,
  strategy,
  setStrategy,
  policy,
  setPolicy,
  retryLimit,
  setRetryLimit,
  sample,
  setSample,
  seed,
  setSeed,
  turns,
  setTurns,
  anomalies,
  setAnomalies,
  selectedProfile,

  methodSelection,
  setMethodSelection
}: PanelProps) {
  return (
    <section className="surface hardware-create">
      <label className="field">
        <span>方法转角区间</span>
        <select value={methodSelection} onChange={(event) => setMethodSelection(event.target.value)}>
          <option value="">自定义转角计划</option>
          {options?.methods.map((method) => (
            <option
              key={`${method.method_id}-${method.version}`}
              value={`${method.method_id}-${method.version}`}
            >
              {method.name} · v{method.version}
            </option>
          ))}
        </select>
        <small>选择方法后按其全部转角和存储区间执行；自定义计划只用于独立调试。</small>
      </label>
      <div className="surface-heading">
        <SectionHeading title={<>建立转角与采集计划</>} />
      </div>
      <form className="hardware-form" onSubmit={create}>
        <label className="field">
          <span>任务名称</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={!canWrite || busy}
          />
        </label>
        <label className="field">
          <span>设备档案</span>
          <select
            value={profileId ?? ''}
            onChange={(event) => setProfileId(Number(event.target.value))}
            disabled={!canWrite || busy}
          >
            {options?.profiles.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.transport === 'simulator' ? '模拟器' : '串口'}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>CCD 布局</span>
          <select
            value={layoutId}
            onChange={(event) => setLayoutId(event.target.value)}
            disabled={!canWrite || busy}
          >
            {options?.layouts.map((item) => (
              <option key={String(item.id)} value={String(item.id)}>
                {String(item.name)} · {String(item.points_per_ccd)} 点
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>执行策略</span>
          <select
            value={strategy}
            onChange={(event) => setStrategy(event.target.value as typeof strategy)}
            disabled={!canWrite || busy}
          >
            <option value="short_to_long">短波 → 长波</option>
            <option value="key_first">关键波段优先</option>
          </select>
        </label>
        <AdvancedSettings title="高级异常处理">
          <div className="advanced-field-grid">
            <label className="field">
              <span>异常策略</span>
              <select
                value={policy}
                onChange={(event) => setPolicy(event.target.value as typeof policy)}
                disabled={!canWrite || busy}
              >
                <option value="retry_then_stop">有限重试后停止</option>
                <option value="manual">转人工接管</option>
              </select>
            </label>
            <label className="field">
              <span>重试上限</span>
              <NumericInput
                min={0}
                max={5}
                value={retryLimit}
                onValueChange={setRetryLimit}
                disabled={!canWrite || busy}
              />
            </label>
          </div>
        </AdvancedSettings>
        <AdvancedSettings title="独立转角调试">
          <p className="field-hint">正常摄谱选择已发布方法；自定义计划仅用于独立调试。</p>
        <label className="field span-2">
          <span>转角计划 JSON</span>
          <textarea
            rows={7}
            value={turns}
            onChange={(event) => setTurns(event.target.value)}
            disabled={!canWrite || busy}
            spellCheck={false}
          />
        </label>

        </AdvancedSettings>
        {selectedProfile?.transport === 'simulator' && (
          <AdvancedSettings title="模拟调试">
            <div className="advanced-field-grid">
        <label className="field">
          <span>模拟样品</span>
          <input
            value={sample}
            onChange={(event) => setSample(event.target.value)}
            disabled={!canWrite || busy}
          />
        </label>
        <label className="field">
          <span>随机种子</span>
          <NumericInput
            min={0}
            max={2147483647}
            value={seed}
            onValueChange={setSeed}
            disabled={!canWrite || busy}
          />
        </label>
        <label className="field span-2">
          <span>模拟异常脚本 JSON</span>
          <textarea
            rows={7}
            value={anomalies}
            onChange={(event) => setAnomalies(event.target.value)}
            disabled={!canWrite || busy}
            spellCheck={false}
            placeholder='[{"step_index":0,"kind":"peak_shift","count":1}]'
          />
        </label>

            </div>
          </AdvancedSettings>
        )}
        <button
          className="primary-button hardware-create-button"
          type="submit"
          disabled={!canWrite || busy || !profileId}
        >
          <RotateCcw size={15} />
          创建任务
        </button>
      </form>
      {selectedProfile?.transport === 'serial' && (
        <div className="surface-note warning-note">
          <ShieldAlert size={16} />
          <span>
            该档案是真实串口。当前缺少已确认的转角协议，启动只会记录
            `deferred_external`，不会发送猜测命令字节。
          </span>
        </div>
      )}
    </section>
  )
}
