import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CopyableCode } from '../../components/InformationDisplay'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { CaptureLineBar } from './CaptureLineBar'
import { LegacyDeskDock } from './legacyDesk'
import './capture-operation-layout.css'

type Command = { run: () => unknown; enabled: boolean }
type Props = {
  className: string; name?: string; status?: string; statusLabel?: string; source?: string
  start: Command; preheat: Command; pause: Command; resume: Command; stop: Command; finish?: Command
  records?: ReactNode; lineBar?: ReactNode; topActions?: ReactNode; inputToolbar?: ReactNode; sampleInput?: ReactNode
  recordTitle?: string; recordChoices?: { value: string; name: string; disabled?: boolean }[]
  recordValue?: string; onRecordChoose?: (value: string) => void; recordDisabled?: boolean; repeats?: number
  viewLabel?: string; progress: { label: string; value: ReactNode; title?: string; current?: number; maximum?: number }[]
  ccd: number; ccdIndices: number[]; onCcdChange: (ccd: number) => void; hash?: string
  toolbar?: ReactNode; setup?: ReactNode; children?: ReactNode; bandTitle?: string; showRepeats?: boolean
  canEditSample?: boolean
}

/** Keep the legacy operation order inside the modern application shell. */
export function SpectroscopyConsole(props: Props) {
  const root = useRef<HTMLElement>(null)
  const details = useRef<HTMLDialogElement>(null)
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  useEffect(() => {
    if (!menu) return
    const outside = (event: PointerEvent) => { if (!(event.target as Element | null)?.closest('.legacy-desk-menu')) setMenu(null) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMenu(null); root.current?.querySelector<HTMLElement>('.legacy-window-caption')?.focus() } }
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [menu])
  const running = Boolean(props.status && ['countdown', 'pre_excitation', 'burn', 'dark', 'paused', 'stopping'].includes(props.status))
  const finish = props.finish ?? { run: () => {}, enabled: false }
  const label = props.bandTitle ?? (props.recordTitle === '色散谱带名' ? '色散数据' : props.recordTitle === '蒸发谱带名' ? '蒸发数据' : '样品')
  const openDetails = () => { setMenu(null); if (details.current && !details.current.open) details.current.showModal() }
  const openObserver = () => {
    setMenu(null)
    const dialog = root.current?.querySelector<HTMLDialogElement>('.spectrum-observer-dialog')
    if (dialog && !dialog.open) dialog.showModal()
  }
  const command = (text: string, value: Command, icon: 'capture' | 'preheat' | 'stop' | 'finish') =>
    <button type="button" aria-label={text} title={icon === 'finish' ? '结束当前摄谱，返回任务列表' : text} disabled={!value.enabled} onClick={() => { setMenu(null); void value.run() }}>
      <SpectroscopyIcon name={icon} /><span>{text}</span>
    </button>
  return <section ref={root} className={`spectroscopy-console legacy-capture-desk ${props.className} ${!leftOpen ? 'left-closed' : ''} ${!rightOpen ? 'right-closed' : ''}`}
    data-testid="spectroscopy-console" data-status={props.status} aria-label="摄谱激发工作台"
    onContextMenu={event => { event.preventDefault(); setMenu({ x: Math.min(event.clientX, window.innerWidth - 220), y: Math.min(event.clientY, window.innerHeight - 210) }) }}>
    <header className="legacy-window-caption" tabIndex={0} title="右键或Shift+F10打开工作台菜单"
      onKeyDown={event => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); setMenu({ x: 8, y: 25 }) } }}>
      <div className="capture-task-caption"><span>{label}</span><strong title={props.name}>{props.name}</strong></div>
      <div className="capture-detail-actions">
        {(!leftOpen || !rightOpen) && <button type="button" onClick={() => { setLeftOpen(true); setRightOpen(true) }}>恢复面板</button>}
        <button type="button" onClick={openDetails}>任务详情</button>
        <button type="button" onClick={openObserver}>谱图读数</button>
      </div>
    </header>
    <div className="legacy-main-toolbar">
      {props.lineBar ?? <CaptureLineBar />}
      <div className="legacy-main-actions" role="group" aria-label="工作台操作">
        {props.topActions}
        <SpectroscopyToolButton icon="measure" label={props.status === 'paused' ? '继续' : '启动测量'} disabled={props.status !== 'paused' || !props.resume.enabled} onClick={() => void props.resume.run()} />
        <SpectroscopyToolButton icon="pause" label="暂停" disabled={!props.pause.enabled || props.status === 'paused'} onClick={() => void props.pause.run()} />
        <span className="legacy-tool-separator" />
        <SpectroscopyToolButton icon="close" label="关闭摄谱工作台" disabled={!finish.enabled} onClick={() => void finish.run()} />
      </div>
    </div>
    <div className="legacy-dock-body">
      <div className="legacy-record-dock" hidden={!leftOpen}>
        <LegacyDeskDock.Provider value={{ closeRecords: () => setLeftOpen(false) }}>{props.records}</LegacyDeskDock.Provider>
      </div>
      <div className="spectroscopy-view" aria-label="实时谱图工作区"><div className="spectroscopy-spectrum">{props.children}</div></div>
      <aside className="spectroscopy-operator" hidden={!rightOpen} aria-label="摄谱输入与控制">
        <header className="legacy-dock-caption"><h2>摄谱窗口</h2><button type="button" className="legacy-dock-close" aria-label="隐藏摄谱窗口" onClick={() => setRightOpen(false)}>×</button></header>
        <div className="spectroscopy-input-toolbar" aria-label="样号输入工具">{props.inputToolbar}</div>
        <fieldset className="spectroscopy-sample-input" data-repeats={props.showRepeats !== false}><legend>样号输入</legend>
          {props.sampleInput ?? <>
            <label><span>{props.recordTitle ?? '谱带名称'}:</span><select aria-label={props.recordTitle ?? '谱带名称'} value={props.recordValue ?? ''}
              disabled={props.recordDisabled || !props.recordChoices?.length} onChange={event => props.onRecordChoose?.(event.target.value)}>
              {props.recordChoices?.map(choice => <option key={choice.value} value={choice.value} disabled={choice.disabled}>{choice.name}</option>)}
            </select></label>
            {props.showRepeats !== false && <label><span>重复摄谱:</span><input aria-label="重复摄谱" readOnly value={props.repeats ?? 1} /></label>}
          </>}
        </fieldset>
        <fieldset className="spectroscopy-command-area"><legend>激发控制</legend>
          {running && <output className="legacy-running-state" role="status">{props.statusLabel} {props.progress[0]?.value}</output>}
          <div className="spectroscopy-controls" aria-label="摄谱控制">
            {command('试样摄谱', props.start, 'capture')}{command('预热摄谱', props.preheat, 'preheat')}
            {command('停止摄谱', props.stop, 'stop')}{command('结束', finish, 'finish')}
          </div>
        </fieldset>
      </aside>
    </div>
    <dialog ref={details} className="legacy-task-details" aria-label="任务条件与采后命名" onClick={event => event.stopPropagation()}>
      <header><h2>任务条件与采后命名</h2><button type="button" aria-label="关闭任务详情" onClick={() => details.current?.close()}>×</button></header>
      <div className="spectroscopy-setup">{props.setup}</div><p>{props.source}</p>
      <div className="spectroscopy-progress">{props.progress.map(item => <div key={item.label}>{item.label}：{item.value}</div>)}</div>
      <div>{props.toolbar}<CopyableCode value={props.hash} visibleLength={24} empty="等待帧" /></div>
    </dialog>
    {menu && <div role="menu" aria-label="工作台菜单" className="legacy-desk-menu" style={{ left: menu.x, top: menu.y }} onKeyDown={event => { if (event.key === 'Escape') setMenu(null) }}>
      <button role="menuitem" onClick={openDetails}>任务条件与采后命名</button>
      <button role="menuitem" onClick={openObserver} disabled={!root.current?.querySelector('.spectrum-observer-dialog')}>谱图点位与视野</button>
      <button role="menuitem" onClick={() => { setLeftOpen(true); setRightOpen(true); setMenu(null) }}>恢复样品表与摄谱窗口</button>
      <button role="menuitem" disabled={!finish.enabled} onClick={() => { setMenu(null); void finish.run() }}>返回任务列表</button>
      <button role="menuitem" onClick={() => setMenu(null)}>关闭菜单</button>
    </div>}
  </section>
}
