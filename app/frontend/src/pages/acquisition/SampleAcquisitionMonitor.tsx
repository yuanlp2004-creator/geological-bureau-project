import { type AcquisitionTask } from '../../api'
import type { DeviceCcd } from '../../api/devices'
import { SpectrumInspector } from '../../components/SpectrumInspector'
import { stateLabel } from './acquisitionView'
import { SpectroscopyConsole } from './SpectroscopyConsole'
import type { ReactNode } from 'react'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  setup?: ReactNode
  selected: AcquisitionTask | null
  apply: (action: "start" | "step" | "pause" | "resume" | "stop") => Promise<void>
  busy: boolean
  canExecute: boolean
  setAuto: React.Dispatch<React.SetStateAction<boolean>>
  auto: boolean
  progressLabel: string
  ccdIndex: number
  setCcdIndex: React.Dispatch<React.SetStateAction<number>>
  selectedCcd: DeviceCcd | undefined
  selectedPoints: number[]
  boundMethod: { method_id: number; method_version: number; name: string } | undefined
}

export function SampleAcquisitionMonitor({
  setup,
  selected,
  apply,
  busy,
  canExecute,
  setAuto,
  auto,
  progressLabel,
  ccdIndex,
  setCcdIndex,
  selectedCcd,
  selectedPoints,
  boundMethod,
}: PanelProps) {
  const running = Boolean(selected && ['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats'].includes(selected.status))
  const enabled = Boolean(selected && !busy && canExecute)
  return (
    <SpectroscopyConsole className="acquisition-monitor" setup={setup} name={selected?.name} status={selected?.status}
      statusLabel={selected ? stateLabel[selected.status] : undefined}
      source={selected?.profile.transport === 'simulator' ? '模拟设备 · 仅用于软件验证' : '真实设备 · 连接与协议状态以当前任务反馈为准'}
      start={{ run: () => apply('start'), enabled: enabled && selected?.status === 'draft' }}
      pause={{ run: () => apply('pause'), enabled: enabled && running && selected?.status !== 'between_repeats' }}
      resume={{ run: () => apply('resume'), enabled: enabled && selected?.status === 'paused' }}
      stop={{ run: () => apply('stop'), enabled: enabled && !['completed', 'failed', 'stopped'].includes(selected?.status ?? '') }}
      step={{ run: () => apply('step'), enabled: enabled && running }}
      continuous={{ run: () => setAuto((value) => !value), enabled: enabled && running, active: auto }}
      progress={selected ? [
        { label: '总进度', value: progressLabel, current: selected.progress, maximum: 100 },
        { label: '当前阶段', value: selected.last_message || stateLabel[selected.status], title: selected.last_message || stateLabel[selected.status] },
        { label: '燃烧帧 / 暗帧', value: `${selected.burn_frames_captured}/${selected.burn_frame_count} · ${selected.dark_frames_captured}/${selected.dark_frame_count}` }
      ] : []}
      ccd={ccdIndex} ccdIndices={selected?.ccd_indices ?? []} onCcdChange={setCcdIndex} hash={selected?.last_event?.details.sha256}>
      {selected && <>
        <SpectrumInspector fitPlot key={`${selected.id}:${ccdIndex}`} points={selectedPoints}
          label={`CCD ${ccdIndex + 1} ${selected.task_kind === 'evaporation' ? '蒸发' : '样品'}采集曲线`}
          emptyText="开始采集后显示实时 CCD 曲线" />
          <div className="acquisition-facts">
            <div>
              <span>{selected.task_kind === 'evaporation' ? '保存模式' : '方法版本'}</span>
              <strong title={selected.task_kind === 'evaporation' ? '全时原始区间' : boundMethod ? `${boundMethod.name} · v${boundMethod.method_version}` : '未绑定'}>
                {selected.task_kind === 'evaporation' ? '全时原始区间' : boundMethod ? `${boundMethod.name} · v${boundMethod.method_version}` : '未绑定'}
              </strong>
            </div>
            <div>
              <span>峰值 / 位置</span>
              <strong>
                {selectedCcd
                  ? `${selectedCcd.peak.toLocaleString('zh-CN')} / ${selectedCcd.peak_position + 1}`
                  : '--'}
              </strong>
            </div>
            <div>
              <span>虚拟时间</span>
              <strong>
                {selected.last_event?.details.virtual_time_ms
                  ? `${Number(selected.last_event.details.virtual_time_ms).toFixed(0)} ms`
                  : '--'}
              </strong>
            </div>
            <div>
              <span>原始帧</span>
              <strong>{selected.samples.reduce((sum, item) => sum + item.bands.length, 0)} 个均值带</strong>
            </div>
            <div>
              <span>结果</span>
              <strong className={selected.status === 'completed' ? 'good' : ''}>
                {selected.result_sha256 ? '已收尾' : '未完成'}
              </strong>
            </div>
          </div>
      </>}
    </SpectroscopyConsole>
  )
}
