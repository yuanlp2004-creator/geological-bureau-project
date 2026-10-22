import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  ShieldAlert,
  Square,
  Wrench
} from 'lucide-react'
import { type HardwareTask } from '../../api'
import type { HardwarePlanStep } from '../../api/hardwareAcquisition'
import { CopyableCode } from '../../components/InformationDisplay'
import { activeStates, labels, terminalStates } from './hardwareView'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  selected: HardwareTask | null
  apply: (action: "start" | "step" | "pause" | "resume" | "stop") => Promise<void>
  busy: boolean
  canExecute: boolean
  setAuto: React.Dispatch<React.SetStateAction<boolean>>
  auto: boolean
  currentStep: HardwarePlanStep | undefined
  isExternal: boolean
  interventionNote: string
  setInterventionNote: React.Dispatch<React.SetStateAction<string>>
  intervene: (action: "accept" | "retry" | "stop") => Promise<void>
}

export function HardwareAcquisitionMonitor({
  selected,
  apply,
  busy,
  canExecute,
  setAuto,
  auto,
  currentStep,
  isExternal,
  interventionNote,
  setInterventionNote,
  intervene,
}: PanelProps) {
  return (
    <section className="surface hardware-monitor">
      <div className="surface-heading">
        <div>
          <h2 title={selected?.name}>
            {selected?.name ?? '选择一个任务'}{' '}
            {selected && (
              <span className={`state-chip ${selected.status}`}>
                {labels[selected.status] ?? selected.status}
              </span>
            )}
          </h2>
        </div>
        <div className="hardware-actions">
          <button
            className="primary-button"
            onClick={() => void apply('start')}
            disabled={!selected || busy || !canExecute || selected.status !== 'draft'}
          >
            <PlayCircle size={15} />
            启动
          </button>
          <button
            className="secondary-button"
            onClick={() => setAuto((value) => !value)}
            disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}
          >
            <Activity size={15} />
            {auto ? '停止自动推进' : '自动推进'}
          </button>
          <button
            className="secondary-button"
            onClick={() => void apply('step')}
            disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}
          >
            <ChevronRight size={15} />
            单步
          </button>
          <button
            className="icon-button compact"
            title="暂停"
            onClick={() => void apply('pause')}
            disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}
          >
            <PauseCircle size={16} />
          </button>
          <button
            className="icon-button compact danger"
            title="安全停止"
            onClick={() => void apply('stop')}
            disabled={!selected || busy || !canExecute || terminalStates.has(selected.status)}
          >
            <Square size={14} />
          </button>
        </div>
      </div>
      {selected ? (
        <>
          <div className="runtime-source">
            {selected.transport === 'simulator'
              ? '模拟设备 · 仅用于软件验证'
              : '真实串口 · 转角协议缺失时禁止执行'}
          </div>
          <div className="hardware-progress">
            <div>
              <span>总进度</span>
              <strong>{selected.progress.toFixed(1)}%</strong>
            </div>
            <div>
              <span>当前计划步</span>
              <strong>
                {currentStep
                  ? `${currentStep.wavelength_nm.toFixed(2)} nm · ${currentStep.angle_deg.toFixed(2)}°`
                  : '--'}
              </strong>
            </div>
            <div>
              <span>连接状态</span>
              <strong>
                {selected.transport === 'serial'
                  ? '协议闸门'
                  : selected.adapter_session_id
                    ? '模拟器已连接'
                    : '未连接'}
              </strong>
            </div>
            <div>
              <span>原始结果</span>
              <CopyableCode
                value={selected.result_sha256}
                visibleLength={18}
                empty="--"
                className={selected.result_sha256 ? 'good' : ''}
              />
            </div>
          </div>
          {isExternal && (
            <div className="hardware-alert external">
              <ShieldAlert size={17} />
              <span>真实硬件协议或现场记录缺失，任务已延后；没有发送命令字节。</span>
            </div>
          )}
          {selected.status === 'safety_stopped' && (
            <div className="hardware-alert danger">
              <AlertTriangle size={17} />
              <span>{selected.failure_message || '异常超过边界，任务已进入安全状态。未确认帧已隔离。'}</span>
            </div>
          )}
          {selected.status === 'manual_intervention' && (
            <div className="hardware-alert manual">
              <Wrench size={17} />
              <div>
                <strong>需要人工接管</strong>
                <small>检查当前帧后选择接受、重试或停止；损坏帧不能被接受。</small>
                <div className="intervention-actions">
                  <input
                    value={interventionNote}
                    onChange={(event) => setInterventionNote(event.target.value)}
                    placeholder="处置说明（可选）"
                    disabled={busy}
                  />
                  <button className="secondary-button" onClick={() => void intervene('accept')} disabled={busy}>
                    <CheckCircle2 size={14} />
                    接受
                  </button>
                  <button className="secondary-button" onClick={() => void intervene('retry')} disabled={busy}>
                    <RotateCcw size={14} />
                    重试
                  </button>
                  <button
                    className="icon-button danger"
                    title="安全停止"
                    onClick={() => void intervene('stop')}
                    disabled={busy}
                  >
                    <Square size={14} />
                  </button>
                </div>
              </div>
            </div>
          )}
          {selected.status === 'paused' && (
            <div className="hardware-alert">
              <PauseCircle size={17} />
              <span>任务暂停在“{labels[selected.paused_from ?? 'turning']}”，恢复后从该阶段继续。</span>
              <button
                className="secondary-button"
                onClick={() => void apply('resume')}
                disabled={busy || !canExecute}
              >
                <PlayCircle size={14} />
                恢复
              </button>
            </div>
          )}
          <div className="hardware-facts">
            <span>最后消息</span>
            <strong title={selected.last_message || '--'}>{selected.last_message || '--'}</strong>
            <span>追踪事件</span>
            <strong>{selected.traces.length}</strong>
            <span>处置决定</span>
            <strong>{selected.decisions.length}</strong>
            <span>CCD 原始帧</span>
            <strong>{selected.frames.length}</strong>
          </div>
        </>
      ) : (
        <div className="empty-state monitor-empty">
          <RotateCcw size={24} />
          <span>创建或选择任务后开始转角</span>
        </div>
      )}
    </section>
  )
}
