import { AdvancedSettings } from '../../components/AdvancedSettings'
import {
  Beaker,
  Lightbulb,
  ShieldAlert
} from 'lucide-react'
import { type FormEvent } from 'react'
import { type MercuryOptions } from '../../api'
import { NumericInput } from '../../components/NumericInput'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  create: (event: FormEvent) => Promise<void>
  name: string
  setName: React.Dispatch<React.SetStateAction<string>>
  canWrite: boolean
  busy: boolean
  profileId: number | null
  setProfileId: React.Dispatch<React.SetStateAction<number | null>>
  options: MercuryOptions | null
  layoutId: string
  setLayoutId: React.Dispatch<React.SetStateAction<string>>
  stabilizationFrames: number
  setStabilizationFrames: React.Dispatch<React.SetStateAction<number>>
  offset: number
  setOffset: React.Dispatch<React.SetStateAction<number>>
  fault: string
  setFault: React.Dispatch<React.SetStateAction<string>>
  lineIds: number[]
  setLineIds: React.Dispatch<React.SetStateAction<number[]>>
  selectedProfile: { id: number; name: string; transport: "simulator" | "serial"; port: number; baud_rate: number; ccd_indices: number[]; points_per_ccd: number; mercury_protocol_available: boolean; protocol_status: string } | undefined
}

export function MercuryCalibrationForm({
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
  stabilizationFrames,
  setStabilizationFrames,
  offset,
  setOffset,
  fault,
  setFault,
  lineIds,
  setLineIds,
  selectedProfile,
}: PanelProps) {
  return (
    <section className="surface mercury-create">
      <div className="surface-heading">
        <div>
          <h2>选择汞线与设备</h2>
        </div>
        <Beaker size={17} />
      </div>
      <form onSubmit={create}>
        <div className="mercury-form">
          <label className="field">
            <span>会话名称</span>
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
                  {item.name} · {item.transport === 'simulator' ? '合成谱' : '串口'}
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
                <option key={item.id} value={item.id}>
                  {item.name} · {item.points_per_ccd} 点
                </option>
              ))}
            </select>
          </label>
          <AdvancedSettings title="高级光学设置">
            <div className="advanced-field-grid">
              <label className="field">
                <span>稳定帧数</span>
                <NumericInput
                  min={1}
                  max={20}
                  value={stabilizationFrames}
                  onValueChange={setStabilizationFrames}
                  disabled={!canWrite || busy}
                />
              </label>
            </div>
          </AdvancedSettings>
          {selectedProfile?.transport === 'simulator' && (
            <AdvancedSettings title="模拟调试">
              <div className="advanced-field-grid">
          <label className="field">
            <span>模拟峰偏移（点）</span>
            <NumericInput
              min={-100}
              max={100}
              step={0.5}
              value={offset}
              onValueChange={setOffset}
              disabled={!canWrite || busy}
            />
          </label>
          <label className="field">
            <span>故障脚本</span>
            <select
              value={fault}
              onChange={(event) => setFault(event.target.value)}
              disabled={!canWrite || busy}
            >
              <option value="none">无</option>
              <option value="switch_failure">谱源启动失败</option>
              <option value="stability_failure">稳定失败</option>
              <option value="capture_failure">采集失败</option>
            </select>
          </label>
              </div>
            </AdvancedSettings>
          )}
        </div>
        <div className="mercury-line-selector">
          {options?.reference_lines.map((line) => (
            <label key={line.id} className={lineIds.includes(line.id) ? 'selected' : ''}>
              <input
                type="checkbox"
                checked={lineIds.includes(line.id)}
                onChange={() =>
                  setLineIds((current) =>
                    current.includes(line.id) ? current.filter((id) => id !== line.id) : [...current, line.id]
                  )
                }
                disabled={!canWrite || busy}
              />
              <strong>{line.wavelength_nm.toFixed(4)} nm</strong>
              <small>Hg I · 强度 {line.relative_intensity}</small>
            </label>
          ))}
        </div>
        <button
          className="primary-button"
          type="submit"
          disabled={!canWrite || busy || !profileId || lineIds.length < 2}
        >
          <Lightbulb size={15} />
          建立校准会话
        </button>
      </form>
      {selectedProfile?.transport === 'serial' && (
        <div className="surface-note warning-note">
          <ShieldAlert size={16} />
          <span>{options?.protocol_notice} 启动仅登记外部依赖。</span>
        </div>
      )}
    </section>
  )
}
