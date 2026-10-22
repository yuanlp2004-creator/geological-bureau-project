import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Lightbulb,
  PlayCircle,
  RotateCcw,
  ShieldAlert,
  Square
} from 'lucide-react'
import { type MercurySession } from '../../api'
import { activeStates, labels, terminalStates } from './mercuryView'
import { SectionHeading } from '../../components/SectionHeading'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  selected: MercurySession | null
  run: (action: "start" | "step" | "stop" | "apply" | "rollback") => Promise<void>
  busy: boolean
  canExecute: boolean
  setAuto: React.Dispatch<React.SetStateAction<boolean>>
  auto: boolean
  canWrite: boolean
}

export function MercuryCalibrationMonitor({
  selected,
  run,
  busy,
  canExecute,
  setAuto,
  auto,
  canWrite,
}: PanelProps) {
  return (
    <section className="surface mercury-monitor">
      <div className="surface-heading">
        <SectionHeading title="汞灯调试" description={<>
          {selected?.name ?? '选择一个会话'}{' '}
          {selected && <span className={`state-chip ${selected.status}`}>{labels[selected.status]}</span>}
        </>} />
        <div className="mercury-actions">
          <button
            className="primary-button"
            onClick={() => void run('start')}
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
            {auto ? '停止自动' : '自动推进'}
          </button>
          <button
            className="secondary-button"
            onClick={() => void run('step')}
            disabled={!selected || busy || !canExecute || !activeStates.has(selected.status)}
          >
            <ChevronRight size={15} />
            单步
          </button>
          <button
            className="secondary-button"
            onClick={() => void run('apply')}
            disabled={!selected || busy || !canWrite || selected.status !== 'ready'}
          >
            <CheckCircle2 size={15} />
            应用建议
          </button>
          <button
            className="secondary-button"
            onClick={() => void run('rollback')}
            disabled={!selected || busy || !canWrite || selected.status !== 'applied'}
          >
            <RotateCcw size={15} />
            回滚
          </button>
          <button
            className="icon-button compact danger"
            title="安全停止"
            onClick={() => void run('stop')}
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
              : '真实设备 · 连接与协议状态以当前任务反馈为准'}
          </div>
          <div className="mercury-metrics">
            <div>
              <span>稳定进度</span>
              <strong>
                {selected.stabilized_frames}/{selected.stabilization_frames}
              </strong>
            </div>
            <div>
              <span>校准前版本</span>
              <strong>
                v{selected.before_version.version} · {selected.before_version.offset_points.toFixed(3)} 点
              </strong>
            </div>
            <div>
              <span>建议校正</span>
              <strong>{selected.analysis ? `${selected.analysis.suggestion_points.toFixed(3)} 点` : '--'}</strong>
            </div>
            <div>
              <span>残差 RMS</span>
              <strong className={selected.analysis?.within_tolerance ? 'good' : ''}>
                {selected.analysis
                  ? `${selected.analysis.before_rms.toFixed(3)} → ${selected.analysis.after_rms.toFixed(3)}`
                  : '--'}
              </strong>
            </div>
            <div>
              <span>安全态</span>
              <strong className={selected.safe_off ? 'good' : ''}>
                {selected.safe_off ? '已关闭' : '模拟谱源活动'}
              </strong>
            </div>
          </div>
          {selected.status === 'deferred_external' && (
            <div className="mercury-alert external">
              <ShieldAlert size={17} />
              <span>真实汞灯协议、抓包和现场硬件缺失；没有生成或发送命令字节。</span>
            </div>
          )}
          {selected.status === 'safe_off' && (
            <div className="mercury-alert danger">
              <ShieldAlert size={17} />
              <span>{selected.failure_message || '异常已触发安全关闭，未应用校准。'}</span>
            </div>
          )}
          <div className="mercury-last-message">{selected.last_message || '等待操作'}</div>
        </>
      ) : (
        <div className="empty-state monitor-empty">
          <Lightbulb size={24} />
          <span>建立或选择会话后开始调试</span>
        </div>
      )}
    </section>
  )
}
