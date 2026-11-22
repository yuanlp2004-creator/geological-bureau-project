import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import '../acquisition/capture-operation-layout.css'
import './device-debug-workbench.css'

type Props = {
  title: string
  active: boolean
  hasPoints: boolean
  toolbar: ReactNode
  listTitle: string
  records: ReactNode
  controls: ReactNode
  footer: ReactNode
  children: ReactNode
}

/** Share the capture desk's three columns and plot styling, with device-specific controls. */
export function DeviceDebugWorkbench({ title, active, hasPoints, toolbar, listTitle, records, controls, footer, children }: Props) {
  const desk = useRef<HTMLElement>(null)
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  useLayoutEffect(() => {
    const element = desk.current
    if (!element || !active) return
    const viewport = element.closest('.page-scroll-region')
    const panel = element.closest('.device-debug-panel')
    let frame = 0
    const resize = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const bottom = viewport?.getBoundingClientRect().bottom ?? window.innerHeight
        element.style.height = `${Math.max(360, Math.floor(bottom - element.getBoundingClientRect().top - 8))}px`
      })
    }
    const observer = new ResizeObserver(resize)
    if (viewport) observer.observe(viewport)
    if (panel) observer.observe(panel)
    window.addEventListener('resize', resize)
    resize()
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', resize) }
  }, [active])
  return <div className="spectroscopy-workbench device-debug-workbench" data-stage="capture">
    <section ref={desk} className={`spectroscopy-console legacy-capture-desk device-debug-desk ${!leftOpen ? 'left-closed' : ''} ${!rightOpen ? 'right-closed' : ''}`} aria-label={`${title}工作台`}>
      <header className="legacy-window-caption">
        <div className="capture-task-caption"><strong>{title}</strong></div>
        <div className="capture-detail-actions">
          {(!leftOpen || !rightOpen) && <button type="button" onClick={() => { setLeftOpen(true); setRightOpen(true) }}>恢复面板</button>}
          <button type="button" onClick={() => desk.current?.querySelector<HTMLDialogElement>('.spectrum-observer-dialog')?.showModal()}
            disabled={!hasPoints}>谱图读数</button>
        </div>
      </header>
      <div className="legacy-main-toolbar device-debug-selection">{toolbar}</div>
      <div className="legacy-dock-body">
        <aside className="legacy-record-dock" hidden={!leftOpen}>
          <header className="legacy-dock-caption"><h2>{listTitle}</h2><button type="button" className="legacy-dock-close" aria-label="收起列表" onClick={() => setLeftOpen(false)}>×</button></header>
          <div className="device-debug-records">{records}</div>
        </aside>
        <main className="spectroscopy-view"><div className="spectroscopy-spectrum">{children}</div></main>
        <aside className="spectroscopy-operator" hidden={!rightOpen} aria-label={`${title}参数与控制`}>
          <header className="legacy-dock-caption"><h2>{title}</h2><button type="button" className="legacy-dock-close" aria-label="隐藏调试控制" onClick={() => setRightOpen(false)}>×</button></header>
          <div className="device-debug-control-content">{controls}</div>
        </aside>
      </div>
      <footer className="device-debug-status" role="status">{footer}</footer>
    </section>
  </div>
}
