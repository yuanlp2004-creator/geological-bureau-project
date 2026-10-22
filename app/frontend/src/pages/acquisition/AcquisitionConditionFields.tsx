import { type ReactNode } from 'react'
import { AdvancedSettings } from '../../components/AdvancedSettings'
import { NumericInput } from '../../components/NumericInput'
import { SAMPLE_OPTIONS } from './acquisitionView'
import type { AcquisitionOptions } from '../../api'

export type AcquisitionConditionsProps = {
  canWrite: boolean
  busy: boolean
  taskName: string
  setTaskName: React.Dispatch<React.SetStateAction<string>>
  profileId: number | null
  setProfileId: React.Dispatch<React.SetStateAction<number | null>>
  options: AcquisitionOptions | null
  layoutId: string
  setLayoutId: React.Dispatch<React.SetStateAction<string>>
  burnCount: number
  setBurnCount: React.Dispatch<React.SetStateAction<number>>
  darkCount: number
  setDarkCount: React.Dispatch<React.SetStateAction<number>>
  countdown: number
  setCountdown: React.Dispatch<React.SetStateAction<number>>
  preExcitation: number
  setPreExcitation: React.Dispatch<React.SetStateAction<number>>
  samplingPeriod: number
  setSamplingPeriod: React.Dispatch<React.SetStateAction<number>>
  simulatorSample: string
  setSimulatorSample: React.Dispatch<React.SetStateAction<string>>
  seed: number
  setSeed: React.Dispatch<React.SetStateAction<number>>
}

type AcquisitionSetupFieldsProps = Pick<AcquisitionConditionsProps, 'taskName' | 'setTaskName' | 'profileId' | 'setProfileId' | 'options' | 'layoutId' | 'setLayoutId' | 'canWrite' | 'busy'>

export function AcquisitionSetupFields({ taskName, setTaskName, profileId, setProfileId, options, layoutId, setLayoutId, canWrite, busy }: AcquisitionSetupFieldsProps) {
  return <>
        <label className="field">
          <span>任务名称</span>
          <input
            value={taskName}
            onChange={(e) => setTaskName(e.target.value)}
            disabled={!canWrite || busy}
          />
        </label>
        <label className="field">
          <span>设备档案</span>
          <select
            value={profileId ?? ''}
            onChange={(e) => setProfileId(Number(e.target.value))}
            disabled={!canWrite || busy}
          >
            {options?.profiles.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>CCD 布局</span>
          <select value={layoutId} onChange={(e) => setLayoutId(e.target.value)} disabled={!canWrite || busy}>
            {options?.layouts.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name} · {item.points_per_ccd} 点
              </option>
            ))}
          </select>
        </label>
  </>
}

type AcquisitionTimingFieldsProps = Pick<AcquisitionConditionsProps, 'burnCount' | 'setBurnCount' | 'darkCount' | 'setDarkCount' | 'countdown' | 'setCountdown' | 'preExcitation' | 'setPreExcitation' | 'samplingPeriod' | 'setSamplingPeriod' | 'simulatorSample' | 'setSimulatorSample' | 'seed' | 'setSeed' | 'canWrite' | 'busy' | 'options' | 'profileId'> & { conditionsLocked: boolean; advancedFields?: ReactNode }

export function AcquisitionTimingFields({ burnCount, setBurnCount, darkCount, setDarkCount, countdown, setCountdown, preExcitation, setPreExcitation, samplingPeriod, setSamplingPeriod, simulatorSample, setSimulatorSample, seed, setSeed, canWrite, busy, options, profileId, conditionsLocked, advancedFields }: AcquisitionTimingFieldsProps) {
  return <>
        <label className="field">
          <span>采样次数</span>
          <NumericInput
            min={1}
            max={255}
            value={burnCount}
            onValueChange={setBurnCount}
            disabled={!canWrite || busy || conditionsLocked}
          />
        </label>
        <label className="field">
          <span>空白次数</span>
          <NumericInput
            min={0}
            max={20}
            value={darkCount}
            onValueChange={setDarkCount}
            disabled={!canWrite || busy || conditionsLocked}
          />
        </label>
        <label className="field"><span>预激时间（秒）</span>
          <NumericInput
              min={0}
              max={600}
              step={0.1}
              value={preExcitation}
              onValueChange={setPreExcitation}
              disabled={!canWrite || busy || conditionsLocked}
            />
        </label>
        <label className="field">
          <span>采样周期 (秒)</span>
          <NumericInput
            min={0.01}
            max={60}
            step={0.01}
            value={samplingPeriod}
            onValueChange={setSamplingPeriod}
            disabled={!canWrite || busy || conditionsLocked}
          />
        </label>
        <AdvancedSettings title="高级采集设置">
          {advancedFields}
          <label className="field"><span>倒计时（秒）</span>
            <NumericInput
              min={0}
              max={600}
              step={0.1}
              value={countdown}
              onValueChange={setCountdown}
              disabled={!canWrite || busy}
            />
          </label>
        </AdvancedSettings>
        {options?.profiles.find((profile) => profile.id === profileId)?.transport === 'simulator' && (
          <AdvancedSettings title="模拟调试">
            <div className="advanced-field-grid">
        <label className="field">
          <span>模拟帧</span>
          <select
            value={simulatorSample}
            onChange={(e) => setSimulatorSample(e.target.value)}
            disabled={!canWrite || busy}
          >
            {SAMPLE_OPTIONS.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>种子</span>
          <NumericInput
            min={0}
            max={2147483647}
            value={seed}
            onValueChange={setSeed}
            disabled={!canWrite || busy}
          />
        </label>
            </div>
          </AdvancedSettings>
        )}
  </>
}

