import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Flame, LogOut, Play, Square, StepForward } from 'lucide-react'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { ContextMenu, useContextMenu } from '../../components/ContextMenu'
import { CaptureLineBar } from './CaptureLineBar'
import { LegacyDeskDock } from './legacyDesk'
import './capture-operation-layout.css'

type Command = { run: () => unknown; enabled: boolean; disabledReason?: string }
type Props = {
  className: string; name?: string; status?: string; statusLabel?: string
  start: Command; preheat: Command; pause: Command; resume: Command; stop: Command; finish?: Command
  records?: ReactNode; leadingActions?: ReactNode; lineBar?: ReactNode; topActions?: ReactNode; inputToolbar?: ReactNode; sampleInput?: ReactNode
  recordTitle?: string; recordChoices?: { value: string; name: string; disabled?: boolean }[]
  recordValue?: string; onRecordChoose?: (value: string) => void; recordDisabled?: boolean; repeats?: number
  viewLabel?: string; progress: { label: string; value: ReactNode; title?: string; current?: number; maximum?: number }[]
  ccd: number; ccdIndices: number[]; onCcdChange: (ccd: number) => void; hash?: string
  children: (detailDock: HTMLElement | null) => ReactNode
  bandTitle?: string; showRepeats?: boolean
  hideIdleTransport?: boolean
  context?: ReactNode; turnPages?: ReactNode; singleTurn?: Command
}

const commandIcons = {
  start: Play,
  'single-turn': StepForward,
  preheat: Flame,
  stop: Square,
  finish: LogOut
}

/** Keep the legacy operation order inside the modern application shell. */
export function SpectroscopyConsole(props: Props) {
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  const [detailDock, setDetailDock] = useState<HTMLElement | null>(null)
  const menu = useContextMenu<'caption' | 'capture'>()
  const [captureLocked, setCaptureLocked] = useState(false)
  const captureButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (captureLocked && props.start.enabled && rightOpen && document.activeElement === document.body) {
      captureButton.current?.focus({ preventScroll: true })
    }
  }, [captureLocked, props.start.enabled, rightOpen])
  const running = Boolean(props.status && ['countdown', 'pre_excitation', 'burn', 'dark', 'paused', 'stopping'].includes(props.status))
  const canUseRightDock = rightOpen && !running && props.status !== 'between_repeats'
  const finish = props.finish ?? { run: () => {}, enabled: false }
  const label = props.bandTitle ?? (props.recordTitle === '色散谱带名' ? '色散数据' : props.recordTitle === '蒸发谱带名' ? '蒸发数据' : '样品')
  const command = (text: string, value: Command, kind: keyof typeof commandIcons) => {
    const Icon = commandIcons[kind]
    const lockable = kind === 'start' && props.showRepeats !== false
    return <button type="button" ref={lockable ? captureButton : undefined} aria-label={text}
      data-command={kind}
      aria-description={lockable && captureLocked ? '已锁定键盘焦点，按 Esc 解除锁定' : undefined}
      onContextMenu={lockable ? event => menu.open(event, 'capture') : undefined}
      onKeyDown={lockable ? event => { if (event.key === 'Escape') setCaptureLocked(false) } : undefined}
      title={!value.enabled && value.disabledReason ? value.disabledReason : kind === 'finish' ? '结束当前摄谱，返回任务列表' : text} disabled={!value.enabled} onClick={() => { menu.close(); void value.run() }}>
      <Icon className="capture-command-icon" size={16} strokeWidth={1.75} aria-hidden="true" /><span>{text}</span>
    </button>
  }
  return <section className={`spectroscopy-console legacy-capture-desk ${props.className} ${!leftOpen ? 'left-closed' : ''} ${!rightOpen ? 'right-closed' : ''}`}
    data-testid="spectroscopy-console" data-status={props.status} aria-label="摄谱激发工作台">
    <header className="legacy-window-caption" tabIndex={0} title="右键或Shift+F10恢复停靠面板"
      onContextMenu={event => menu.open(event, 'caption')}
      onKeyDown={event => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) menu.open(event, 'caption') }}>
      <div className="capture-task-caption"><span>{label}</span><strong title={props.name}>{props.name}</strong></div>
      {props.turnPages}
      {(!leftOpen || !rightOpen) && <button type="button" className="capture-restore-panels" onClick={() => { setLeftOpen(true); setRightOpen(true) }}>恢复面板</button>}
    </header>
    <div className="legacy-main-toolbar">
      {props.leadingActions && <div className="legacy-leading-actions" role="group" aria-label="谱线增删">{props.leadingActions}</div>}
      {props.lineBar ?? <CaptureLineBar />}
      <div className="legacy-main-actions" role="group" aria-label="工作台操作">
        {props.topActions}
        {(!props.hideIdleTransport || running) && <>
          <SpectroscopyToolButton icon="measure" label={props.status === 'paused' ? '继续' : '启动测量'} disabled={props.status !== 'paused' || !props.resume.enabled} onClick={() => void props.resume.run()} />
          <SpectroscopyToolButton icon="pause" label="暂停" disabled={!props.pause.enabled || props.status === 'paused'} onClick={() => void props.pause.run()} />
        </>}
        <span className="legacy-tool-separator" />
        <SpectroscopyToolButton icon="close" label="关闭摄谱工作台" disabled={!finish.enabled} onClick={() => void finish.run()} />
      </div>
    </div>
    <div className="legacy-dock-body">
      <div className="legacy-record-dock" hidden={!leftOpen}>
        <LegacyDeskDock.Provider value={{ closeRecords: () => setLeftOpen(false) }}>{props.records}</LegacyDeskDock.Provider>
      </div>
      <div className="spectroscopy-view" aria-label="实时谱图工作区"><div className="spectroscopy-spectrum">
        {props.children(canUseRightDock ? detailDock : null)}
      </div></div>
      <aside className="spectroscopy-operator spectrum-point-rail" ref={setDetailDock} hidden={!rightOpen} aria-label="摄谱输入与控制">
        <header className="legacy-dock-caption"><h2>摄谱窗口</h2><button type="button" className="legacy-dock-close" aria-label="隐藏摄谱窗口" onClick={() => setRightOpen(false)}>×</button></header>
        <div className="spectroscopy-input-toolbar" aria-label="样号输入工具">{props.inputToolbar ?? <>
          <SpectroscopyToolButton icon="input-samples" label="录入样品编号" description="当前摄谱类型无需预录样号" disabled />
          <SpectroscopyToolButton icon="insert-sample" label="插入样品" description="当前摄谱类型无需预录样号" disabled />
          <SpectroscopyToolButton icon="clear-samples" label="清除待测样号" description="当前摄谱类型无需预录样号" disabled />
        </>}</div>
        <fieldset className="spectroscopy-sample-input" data-repeats={props.showRepeats !== false}><legend>样号输入</legend>
          {props.sampleInput ?? <>
            <label><span>{props.recordTitle ?? '谱带名称'}:</span>{props.showRepeats === false
              ? <input aria-label={props.recordTitle ?? '谱带名称'} readOnly title="本次摄谱的谱带名称"
                value={props.recordChoices?.find(choice => choice.value === props.recordValue)?.name ?? props.name ?? ''} />
              : <select aria-label={props.recordTitle ?? '谱带名称'} value={props.recordValue ?? ''}
              disabled={props.recordDisabled || !props.recordChoices?.length} onChange={event => props.onRecordChoose?.(event.target.value)}>
              {props.recordChoices?.map(choice => <option key={choice.value} value={choice.value} disabled={choice.disabled}>{choice.name}</option>)}
            </select>}</label>
            {props.showRepeats !== false && <label><span>重复摄谱:</span><input aria-label="重复摄谱" readOnly value={props.repeats ?? 1} /></label>}
          </>}
        </fieldset>
        <fieldset className="spectroscopy-command-area"><legend>激发控制</legend>
          {props.context && <div className="capture-context" role="group" aria-label="摄谱记录与状态">{props.context}</div>}
          {running && <output className="legacy-running-state" role="status">{props.statusLabel} {props.progress[0]?.value}</output>}
          <div className="spectroscopy-controls" aria-label="摄谱控制">
            {command('试样摄谱', props.start, 'start')}{props.singleTurn && command('仅摄本转角', props.singleTurn, 'single-turn')}
            {command('预热摄谱', props.preheat, 'preheat')}
            {command('停止摄谱', props.stop, 'stop')}{command('结束', finish, 'finish')}
          </div>
        </fieldset>
      </aside>
    </div>
    {menu.target && <ContextMenu target={menu.target} close={menu.close} label={menu.target.data === 'caption' ? '工作台菜单' : '摄谱按钮菜单'}
      groups={menu.target.data === 'caption' ? [[
        { label: '恢复样品表与摄谱窗口', run: () => { setLeftOpen(true); setRightOpen(true) } },
        { label: '返回任务列表', disabled: !finish.enabled, run: () => void finish.run() }
      ]] : [[{ label: captureLocked ? '解除锁定' : '锁定按钮', run: () => setCaptureLocked(value => !value) }]]} />}
  </section>
}
