import type { ReactNode } from 'react'
import { Activity } from 'lucide-react'
import { CopyableCode } from '../../components/InformationDisplay'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'

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
  inputToolbar?: ReactNode
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
  const ccdPosition = props.ccdIndices.indexOf(props.ccd)
  return <section className={`surface spectroscopy-console ${props.records ? 'has-records' : ''} ${props.className}`} data-testid="spectroscopy-console">
    {props.records}
    <div className="spectroscopy-view" aria-label="实时谱图工作区">
      <div className="spectroscopy-view-heading"><h2>{props.viewLabel ?? '实时谱图'}</h2><span>{props.statusLabel ?? '等待摄谱'}</span></div>
      <div className="spectroscopy-curve-toolbar acquisition-curve-toolbar dispersion-curve-toolbar">
        <SpectroscopyToolButton icon="previous-ccd" label="上一 CCD" disabled={ccdPosition <= 0}
          onClick={() => props.onCcdChange(props.ccdIndices[ccdPosition - 1])} />
        <SpectroscopyToolButton icon="next-ccd" label="下一 CCD" disabled={ccdPosition < 0 || ccdPosition >= props.ccdIndices.length - 1}
          onClick={() => props.onCcdChange(props.ccdIndices[ccdPosition + 1])} />
        <label className="field compact-field"><span title="选择CCD"><SpectroscopyIcon name="select-ccd" /></span><select aria-label="选择CCD" value={props.ccd} disabled={!props.ccdIndices.length} onChange={(event) => props.onCcdChange(Number(event.target.value))}>
          {!props.ccdIndices.length && <option value={props.ccd}>等待采集</option>}
          {props.ccdIndices.map((ccd) => <option key={ccd} value={ccd}>CCD {ccd + 1}</option>)}
        </select></label>
        {props.toolbar}
        <CopyableCode value={props.hash} visibleLength={18} empty="等待帧" className="curve-hash" />
      </div>
      <div className="spectroscopy-spectrum">
        {props.children ?? <div className="empty-state monitor-empty"><Activity size={24} /><span>设置采集条件，选择或创建摄谱任务</span></div>}
      </div>
    </div>
    <aside className="spectroscopy-operator" aria-label="摄谱输入与控制">
    <div className="surface-heading spectroscopy-console-heading">
      <div><span className="spectroscopy-section-label">摄谱窗口</span><h2 title={props.name}>{props.name ?? '选择或创建任务'}</h2></div>
      {props.status && <span className={`state-chip ${props.status}`}>{props.statusLabel}</span>}
    </div>
    {props.inputToolbar && <div className="spectroscopy-input-toolbar" aria-label="样号输入工具">{props.inputToolbar}</div>}
    <div className="spectroscopy-setup">{props.setup}</div>
    <div className="spectroscopy-command-area">
    <div className="spectroscopy-controls monitor-actions dispersion-controls" aria-label="摄谱控制">
      {button('试样摄谱', props.start, <SpectroscopyIcon name="capture" />, 'primary-button')}
      {button('预热摄谱', props.preheat, <SpectroscopyIcon name="preheat" />)}
      {props.status === 'paused'
        ? button('继续', props.resume, <SpectroscopyIcon name="measure" />)
        : button('暂停', props.pause, <SpectroscopyIcon name="pause" />)}
      {button('停止摄谱', props.stop, <SpectroscopyIcon name="stop" />, 'secondary-button danger')}
      {props.finish && button('结束', props.finish, <SpectroscopyIcon name="finish" />)}
    </div>
    {props.name ? <>
      <div className="runtime-source">{props.source}</div>
      <div className="spectroscopy-progress">
        {props.progress.map((item) => <div key={item.label}><span>{item.label}</span><strong title={item.title ?? (typeof item.value === 'string' ? item.value : undefined)}>{item.value}</strong>
          {item.maximum !== undefined && <progress max={Math.max(item.maximum, 1)} value={item.current ?? 0} />}</div>)}
      </div>
    </> : <p className="runtime-source">先填写条件并创建任务，再开始摄谱。</p>}
    </div>
    </aside>
  </section>
}
