import type { ReactNode } from 'react'
import { Activity, PauseCircle, PlayCircle } from 'lucide-react'
import { CopyableCode } from '../../components/InformationDisplay'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'

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
  return <section className={`surface spectroscopy-console ${props.className}`} data-testid="spectroscopy-console">
    <div className="spectroscopy-view" aria-label="实时谱图工作区">
      <div className="spectroscopy-view-heading"><h2>实时谱图</h2><span>{props.statusLabel ?? '等待摄谱'}</span></div>
      <div className="spectroscopy-curve-toolbar acquisition-curve-toolbar dispersion-curve-toolbar">
        <label className="field compact-field"><span>CCD</span><select value={props.ccd} disabled={!props.ccdIndices.length} onChange={(event) => props.onCcdChange(Number(event.target.value))}>
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
      <div><span className="spectroscopy-section-label">摄谱控制</span><h2 title={props.name}>{props.name ?? '选择或创建任务'}</h2></div>
      {props.status && <span className={`state-chip ${props.status}`}>{props.statusLabel}</span>}
    </div>
    <div className="spectroscopy-setup">{props.setup}</div>
    <div className="spectroscopy-command-area">
    <div className="spectroscopy-controls monitor-actions dispersion-controls" aria-label="摄谱控制">
      {button('试样摄谱', props.start, <SpectroscopyIcon name="capture" />, 'primary-button')}
      {button('预热摄谱', props.preheat, <SpectroscopyIcon name="preheat" />)}
      {props.status === 'paused'
        ? button('继续', props.resume, <PlayCircle size={15} />)
        : button('暂停', props.pause, <PauseCircle size={15} />)}
      {button('停止摄谱', props.stop, <SpectroscopyIcon name="stop" />, 'secondary-button danger')}
    </div>
    {props.name ? <>
      <div className="runtime-source">{props.source}</div>
      <div className="spectroscopy-progress">
        {props.progress.map((item) => <div key={item.label}><span>{item.label}</span><strong title={item.title}>{item.value}</strong>
          {item.maximum !== undefined && <progress max={Math.max(item.maximum, 1)} value={item.current ?? 0} />}</div>)}
      </div>
    </> : <p className="runtime-source">先填写条件并创建任务，再开始摄谱。</p>}
    </div>
    </aside>
  </section>
}
