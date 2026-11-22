import { useEffect, useLayoutEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { SpectrumPointDetails, type PointDetailsTarget } from './SpectrumPointDetails'
import './spectrum-point-panel.css'

const LEAVE_DELAY = 300

export function useSpectrumPointFollow(enabled: boolean, source: string, cursorPoint: number | null, locked: boolean) {
  const [latest, setLatest] = useState<{ source: string; point: number } | null>(null)
  const [overPlot, setOverPlot] = useState(false)
  const [overPanel, setOverPanel] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [ctrl, setCtrl] = useState(false)
  const visiblePoint = enabled && latest?.source === source ? latest.point : null
  const currentPoint = enabled && (overPlot || (locked && visiblePoint !== null)) ? cursorPoint : null

  useLayoutEffect(() => {
    if (currentPoint !== null) setLatest({ source, point: currentPoint })
  }, [source, currentPoint])

  useEffect(() => {
    if (!enabled) {
      setLatest(null)
      setCtrl(false)
      return
    }
    const updateCtrl = (event: KeyboardEvent) => setCtrl(event.ctrlKey)
    const blur = () => { setCtrl(false); setOverPlot(false); setOverPanel(false) }
    window.addEventListener('keydown', updateCtrl)
    window.addEventListener('keyup', updateCtrl)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', updateCtrl)
      window.removeEventListener('keyup', updateCtrl)
      window.removeEventListener('blur', blur)
    }
  }, [enabled])

  useEffect(() => {
    if (visiblePoint === null || overPanel || menuOpen || ctrl || (locked && cursorPoint !== null) || currentPoint !== null) return
    const timer = window.setTimeout(() => setLatest(null), LEAVE_DELAY)
    return () => window.clearTimeout(timer)
  }, [visiblePoint, ctrl, overPanel, menuOpen, locked, cursorPoint, currentPoint])

  return {
    point: currentPoint ?? visiblePoint,
    openAt: (point: number | null) => setLatest(point === null ? null : { source, point }),
    plotPresence: (inside: boolean, ctrlKey: boolean) => { setOverPlot(inside); setCtrl(ctrlKey) },
    panelPresence: setOverPanel,
    menuPresence: setMenuOpen,
  }
}

export function SpectrumPointPanel({ dock, target, follow, onClose }: {
  dock?: HTMLElement | null
  target: PointDetailsTarget
  follow: ReturnType<typeof useSpectrumPointFollow>
  onClose: () => void
}) {
  const panelPresence = follow.panelPresence
  useEffect(() => () => panelPresence(false), [dock, panelPresence])
  const panel = <aside hidden={follow.point === null} className="spectrum-point-panel" aria-label="分时数据"
    onPointerEnter={() => follow.panelPresence(true)} onPointerLeave={() => follow.panelPresence(false)}
    onKeyDown={event => { if (event.key === 'Escape') onClose() }}>
    <header><strong>分时数据</strong><button type="button" aria-label="关闭分时数据" onClick={onClose}>×</button></header>
    <SpectrumPointDetails key={JSON.stringify([target.token, target.recordId, target.ccd, target.analysis])}
      {...target} point={follow.point} compact onMenuPresence={follow.menuPresence} />
  </aside>
  return dock ? createPortal(panel, dock) : <div className="spectrum-point-dock">{panel}</div>
}
