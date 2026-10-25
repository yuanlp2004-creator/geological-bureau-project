import type { ReactNode } from 'react'
import { Activity } from 'lucide-react'
import { CopyableCode } from '../../components/InformationDisplay'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'
import { CaptureLineBar } from './CaptureLineBar'

type Command = { run: () => unknown; enabled: boolean }
type Props = {
  className: string
  name?: string
  status?: string
  statusLabel?: string
  source?: string
  start: Command
  preheat: Command
  pause: Command
  resume: Command
  stop: Command
  finish?: Command
  records?: ReactNode
  lineBar?: ReactNode
  inputToolbar?: ReactNode
  sampleInput?: ReactNode
  recordTitle?: string
  recordChoices?: { value: string; name: string; disabled?: boolean }[]
  recordValue?: string
  onRecordChoose?: (value: string) => void
  recordDisabled?: boolean
  repeats?: number
  viewLabel?: string
  progress: { label: string; value: ReactNode; title?: string; current?: number; maximum?: number }[]
  ccd: number
  ccdIndices: number[]
  onCcdChange: (ccd: number) => void
  hash?: string
  toolbar?: ReactNode
  setup?: ReactNode
  children?: ReactNode
}

/** The legacy shared acquisition view: fixed controls and plot position, with mode-specific content. */
export function SpectroscopyConsole(props: Props) {
  const button = (label: string, command: Command, icon: ReactNode, className = 'secondary-button') => (
    <button type="button" className={className} disabled={!command.enabled} onClick={() => void command.run()}>{icon}{label}</button>
  )
  return <section className={`surface spectroscopy-console ${props.records ? 'has-records' : ''} ${props.className}`} data-testid="spectroscopy-console">
    {props.lineBar ?? <CaptureLineBar />}
    {props.records}
    <div className="spectroscopy-view" aria-label="实时谱图工作区">
      <div className="spectroscopy-view-heading"><h2>{props.viewLabel ?? '实时谱图'}</h2><span className={`state-chip ${props.status ?? ''}`}>{props.statusLabel ?? '等待摄谱'}</span></div>
      <div className="spectroscopy-spectrum">
        {props.children ?? <div className="empty-state monitor-empty"><Activity size={24} /><span>设置采集条件，选择或创建摄谱任务</span></div>}
      </div>
      <div className="spectroscopy-curve-toolbar acquisition-curve-toolbar dispersion-curve-toolbar">
        {props.toolbar}<CopyableCode value={props.hash} visibleLength={12} empty="等待帧" className="curve-hash" />
      </div>
    </div>
    <aside className="spectroscopy-operator" aria-label="摄谱输入与控制">
    <div className="surface-heading spectroscopy-console-heading">
      <h2 title={props.name}>摄谱窗口</h2>
    </div>
    <div className="spectroscopy-input-toolbar" aria-label="样号输入工具">{props.inputToolbar}
      <button type="button" className="secondary-button inspector-icon-button" aria-label={props.status === 'paused' ? '继续' : '暂停'}
        title={props.status === 'paused' ? '继续摄谱' : '暂停摄谱'} disabled={!(props.status === 'paused' ? props.resume : props.pause).enabled}
        onClick={() => void (props.status === 'paused' ? props.resume : props.pause).run()}>
        <SpectroscopyIcon name={props.status === 'paused' ? 'measure' : 'pause'} />
      </button>
    </div>
    <fieldset className="spectroscopy-sample-input"><legend>样号输入</legend>
      {props.sampleInput ?? <>
        <label><span>{props.recordTitle ?? '谱带名称'}:</span><select aria-label={props.recordTitle ?? '谱带名称'}
          value={props.recordValue ?? ''} disabled={props.recordDisabled || !props.recordChoices?.length} onChange={event => props.onRecordChoose?.(event.target.value)}>
          {props.recordChoices?.map(choice => <option key={choice.value} value={choice.value} disabled={choice.disabled}>{choice.name}</option>)}
        </select></label>
        <label><span>重复摄谱:</span><input aria-label="重复摄谱" readOnly value={props.repeats ?? 1} /></label>
      </>}
    </fieldset>
    <fieldset className="spectroscopy-command-area"><legend>激发控制</legend>
    <div className="spectroscopy-controls monitor-actions dispersion-controls" aria-label="摄谱控制">
      {button('试样摄谱', props.start, <SpectroscopyIcon name="capture" />, 'primary-button')}
      {button('预热摄谱', props.preheat, <SpectroscopyIcon name="preheat" />)}
      {button('停止摄谱', props.stop, <SpectroscopyIcon name="stop" />, 'secondary-button danger')}
      {props.finish && button('结束', props.finish, <SpectroscopyIcon name="finish" />)}
    </div>
    </fieldset>
    <details className="spectroscopy-details"><summary>任务条件与采后命名</summary>
      <div className="spectroscopy-setup">{props.setup}</div>
    </details>
    </aside>
    <footer className="spectroscopy-statusbar" aria-label="采集状态">
      <span title={props.source}>{props.source}</span>
      {props.progress.map(item => <span key={item.label} title={item.title ?? (typeof item.value === 'string' ? item.value : undefined)}>
        {item.label}：<strong>{item.value}</strong>{item.maximum !== undefined && <progress max={Math.max(item.maximum, 1)} value={item.current ?? 0} />}
      </span>)}
    </footer>
  </section>
}
