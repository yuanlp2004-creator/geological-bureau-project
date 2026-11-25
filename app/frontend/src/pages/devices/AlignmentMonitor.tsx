import { useId, useLayoutEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import type { DeviceEvent, DeviceProfile } from '../../api'
import { LegacyCcdPicker } from '../../components/LegacyCcdPicker'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { clampSpectrumZoom, MAX_SPECTRUM_ZOOM, ZOOM_IN, ZOOM_OUT } from '../../components/spectrumZoom'
import { ContextMenu, useContextMenu } from '../../components/ContextMenu'
import { zoomMenuItems } from '../../components/spectrumMenu'
import { alignmentStats, alignmentXRange, alignmentYRange, initialAlignmentViews, resetAlignmentView, type AlignmentView } from './alignmentView'
import './alignment-monitor.css'

const EMPTY: number[] = []
type Props = {
  indices: number[]; frame: DeviceEvent | null; profile: DeviceProfile | undefined; active: boolean
  connection: ReactNode; footer: ReactNode; canFinish: boolean; finish: () => Promise<void>
  turnControl?: ReactNode
}

/** FmDebug: one shared toolbar acts on the focused one of three CCD views. */
export function AlignmentMonitor({ indices, frame, profile, active, connection, footer, canFinish, finish, turnControl }: Props) {
  const root = useRef<HTMLElement>(null)
  const clip = useId()
  const [views, setViews] = useState(() => initialAlignmentViews(indices))
  const [selected, setSelected] = useState(0)
  const current = views[selected]
  const menu = useContextMenu<number>()
  const [subtractBackground, setSubtractBackground] = useState(true)
  const [plotWidth, setPlotWidth] = useState(513)
  const [cursor, setCursor] = useState<{ slot: number; point: number } | null>(null)
  const [drag, setDrag] = useState<{ slot: number; x0: number; y0: number; x: number; y: number } | null>(null)
  const ratio = window.devicePixelRatio || 1
  const physicalPointPx = profile && profile.screen_width_mm > 0 && profile.screen_resolution_px > 0 && profile.point_width_um > 0
    ? profile.point_width_um / 1000 * profile.screen_resolution_px / profile.screen_width_mm : 0
  useLayoutEffect(() => {
    const element = root.current
    if (!element || !active) return
    const viewport = element.closest('.page-scroll-region')
    let frame = 0
    const resize = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const bottom = viewport?.getBoundingClientRect().bottom ?? window.innerHeight
        // Use its layout position; scrolling must not make the desk grow taller.
        element.style.height = `${Math.max(650, Math.floor(bottom - element.getBoundingClientRect().top - (viewport?.scrollTop ?? 0) - 8))}px`
        const width = element.querySelector('.alignment-plot')?.getBoundingClientRect().width
        if (width) setPlotWidth(width)
      })
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    if (viewport) observer.observe(viewport)
    window.addEventListener('resize', resize); resize()
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', resize) }
  }, [active])
  const series = useMemo(() => views.map(view => {
    const points = frame?.ccds.find(ccd => ccd.ccd_index === view.ccd)?.points ?? EMPTY
    return { points, stats: alignmentStats(points), x: alignmentXRange(view, points.length, plotWidth, ratio, physicalPointPx, MAX_SPECTRUM_ZOOM),
      y: alignmentYRange(points, subtractBackground, view.zoomY) }
  }), [views, frame, plotWidth, ratio, physicalPointPx, subtractBackground])
  const peak = series.reduce<{ value: number; ccd: number; point: number } | null>((best, item, slot) =>
    item.stats && item.stats.max > 1000 && (!best || item.stats.max > best.value)
      ? { value: item.stats.max, ccd: views[slot].ccd!, point: item.stats.peakIndex + 1 } : best, null)
  const currentSeries = series[selected]
  const hasPoints = currentSeries.points.length > 0
  const update = (slot: number, patch: Partial<AlignmentView>) => setViews(values => values.map((value, index) => index === slot ? { ...value, ...patch } : value))
  const resetAll = () => { setViews(values => values.map(value => resetAlignmentView(value.ccd))); setCursor(null); setDrag(null) }
  const fit = (slot: number) => update(slot, { scale: null, span: null, start: 1 })
  const resetY = (slot: number) => update(slot, { zoomY: 1 })
  const zoomX = (slot: number, factor: number) => {
    const range = series[slot].x
    const span = Math.min(range.full, Math.max(range.minimum, range.span * factor))
    update(slot, { scale: null, span, start: (range.min + range.max - span) / 2 })
  }
  const zoomY = (slot: number, factor: number) => update(slot, { zoomY: clampSpectrumZoom(views[slot].zoomY / factor) })
  const selectCcd = (ccd: number) => {
    // FmDebug.SetActiveIen fixes the first view; PmSelCcd excludes displayed CCDs.
    if (selected === 0 || !indices.includes(ccd) || views.some((view, slot) => slot !== selected && view.ccd === ccd)) return
    setViews(values => values.map((value, slot) => slot === selected ? resetAlignmentView(ccd) : value))
    setCursor(null)
  }
  const position = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return { x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) }
  }
  const atPoint = (slot: number, fraction: number) =>
    series[slot].x.min + Math.min(1, fraction * 513 / 512) * series[slot].x.span
  const move = (slot: number, event: PointerEvent<SVGSVGElement>) => {
    const point = position(event)
    if (drag?.slot === slot) { setDrag({ ...drag, ...point }); return }
    if (views[slot].tool !== 'crosshair' || !series[slot].points.length) return
    setCursor({ slot, point: Math.max(0, Math.min(series[slot].points.length - 1, Math.round(atPoint(slot, point.x)) - 1)) })
  }
  const endDrag = (slot: number, event: PointerEvent<SVGSVGElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (drag?.slot === slot && Math.abs(drag.x - drag.x0) * plotWidth > 4) {
      const range = series[slot].x
      const span = Math.max(range.minimum, range.span * Math.abs(drag.x - drag.x0))
      update(slot, { scale: null, span, start: range.min + range.span * (drag.x + drag.x0) / 2 - span / 2,
        zoomY: clampSpectrumZoom(views[slot].zoomY / (1 - Math.min(drag.y, drag.y0))) })
    }
    setDrag(null)
  }
  const value = cursor ? series[cursor.slot]?.points[cursor.point] : undefined
  const menuSlot = menu.target?.data ?? selected
  const { x: menuRange, points: menuPoints } = series[menuSlot]
  const menuZoom = views[menuSlot].zoomY
  return <section ref={root} className="alignment-desk" aria-label="调试对中工作台">
    {menu.target && <ContextMenu target={menu.target} close={menu.close} label={`第 ${menuSlot + 1} 路对中曲线菜单`} groups={[
      [{ label: '适合图像', disabled: !menuPoints.length, run: () => fit(menuSlot) },
        ...zoomMenuItems('x', (_, factor) => zoomX(menuSlot, factor), Boolean(menuPoints.length && menuRange.span > menuRange.minimum), Boolean(menuPoints.length && menuRange.span < menuRange.full))],
      [...zoomMenuItems('y', (_, factor) => zoomY(menuSlot, factor), Boolean(menuPoints.length && menuZoom < MAX_SPECTRUM_ZOOM), Boolean(menuPoints.length && menuZoom > 1)),
        { label: '纵向还原', disabled: !menuPoints.length || menuZoom <= 1, run: () => resetY(menuSlot) }],
      [{ label: '全部还原', run: resetAll }]
    ]} />}
    <div className="alignment-connection-bar">{connection}</div>
    <div className="alignment-tools" role="toolbar" aria-label="调试对中查看工具">
      {turnControl && <>{turnControl}<span className="alignment-tool-separator" /></>}
      <label className="alignment-background"><input type="checkbox" checked={subtractBackground} onChange={event => setSubtractBackground(event.target.checked)} />扣除背景</label>
      <LegacyCcdPicker aria-label="设定 CCD" title={selected === 0 ? '第一视图区的 CCD 固定' : '更换当前视图区的 CCD'} value={current.ccd ?? ''}
        disabled={selected === 0 || !indices.length} onChange={event => selectCcd(Number(event.target.value))}>
        {current.ccd === null && <option value="">未安装 CCD</option>}
        {indices.map(index => <option key={index} value={index} disabled={views.some((view, slot) => slot !== selected && view.ccd === index)}>CCD {index + 1}</option>)}
      </LegacyCcdPicker>
      <span className="alignment-tool-separator" />
      <SpectroscopyToolButton icon="crosshair" label="查看工具" disabled={!hasPoints} aria-pressed={current.tool === 'crosshair'} onClick={() => update(selected, { tool: 'crosshair' })} />
      <SpectroscopyToolButton icon="box-zoom" label="区域放大" disabled={!hasPoints} aria-pressed={current.tool === 'box'} onClick={() => { update(selected, { tool: 'box' }); setCursor(null) }} />
      <span className="alignment-tool-separator" />
      <SpectroscopyToolButton icon="fit" label="适合图像" disabled={!hasPoints} onClick={() => fit(selected)} />
      {([1, 4, 10] as const).map(scale => <SpectroscopyToolButton key={scale} icon={`scale-${scale}`} label={scale === 1 ? '一线一点' : scale === 4 ? '一线四点' : '十倍 CCD'}
        description={scale === 10 && !physicalPointPx ? '需要有效的 CCD 点宽与屏幕参数' : undefined} disabled={!hasPoints || (scale === 10 && !physicalPointPx)}
        aria-pressed={current.scale === scale} onClick={() => update(selected, { scale, start: 1 })} />)}
      <SpectroscopyToolButton icon="zoom-x-in" label="横向放大" disabled={!hasPoints || currentSeries.x.span <= currentSeries.x.minimum} onClick={() => zoomX(selected, ZOOM_IN)} />
      <SpectroscopyToolButton icon="zoom-x-out" label="横向缩小" disabled={!hasPoints || currentSeries.x.span >= currentSeries.x.full} onClick={() => zoomX(selected, ZOOM_OUT)} />
      <span className="alignment-tool-separator" />
      <SpectroscopyToolButton icon="zoom-y-in" label="纵向放大" disabled={!hasPoints || current.zoomY >= MAX_SPECTRUM_ZOOM} onClick={() => zoomY(selected, ZOOM_IN)} />
      <SpectroscopyToolButton icon="zoom-y-out" label="纵向缩小" disabled={!hasPoints || current.zoomY <= 1} onClick={() => zoomY(selected, ZOOM_OUT)} />
      <SpectroscopyToolButton icon="reset-y" label="纵向还原" disabled={!hasPoints || current.zoomY <= 1} onClick={() => resetY(selected)} />
      <span className="alignment-tool-separator" />
      <SpectroscopyToolButton icon="fit" label="还原全部 CCD 视图" onClick={resetAll} />
      <SpectroscopyToolButton icon="close" label="结束调试" description="停止调试并断开设备" disabled={!canFinish} onClick={() => void finish()} />
    </div>
    <div className="alignment-canvas">
      <output className="alignment-peak" data-has-peak={Boolean(peak)} aria-label="最大峰值">{peak ? `最大峰值强度:${peak.value} 位置:(${peak.ccd + 1}, ${peak.point})` : '未发现有效峰值'}</output>
      <output className="alignment-point" aria-label="当前点位读数">{cursor && value !== undefined
        ? <>强度:<strong>{value}</strong>　位置:({views[cursor.slot].ccd! + 1}, {cursor.point + 1})</> : '移动鼠标查看点位强度；单击曲线选择活动视图区'}</output>
      <div className="alignment-plots">{views.map((view, slot) => {
        const { points, x, y } = series[slot]
        const toX = (point: number) => (point - x.min) / x.span * 512
        const toY = (value: number) => 127 - (value - y.min) / (y.max - y.min) * 126
        const path = points.map((value, index) => `${index ? 'L' : 'M'}${toX(index + 1).toFixed(2)},${Math.max(1, toY(value)).toFixed(2)}`).join(' ')
        const picked = cursor?.slot === slot && value !== undefined ? cursor.point : null
        return <div key={slot} className={`alignment-row ${selected === slot ? 'active' : ''}`} data-testid={`alignment-view-${slot}`} data-ccd={view.ccd ?? ''}
          data-y-min={y.min} data-y-max={y.max} data-x-min={x.min} data-x-max={x.max} data-zoom-y={view.zoomY}>
          <div className="alignment-axis-labels"><span>{points.length ? Math.round(y.max) : '--'}</span>
            <button className="alignment-select-view" aria-label={`选择视图区 ${slot + 1}`} aria-pressed={selected === slot} onClick={() => setSelected(slot)}>{view.ccd === null ? '未安装' : `CCD${view.ccd + 1}`}</button>
            <span>{points.length ? y.min : '--'}</span></div>
          <div className="alignment-plot-column">
            <div className="alignment-plot-surface"><svg className="alignment-plot" role="img" aria-label={`视图区 ${slot + 1} CCD ${view.ccd === null ? '未安装' : view.ccd + 1} 实时曲线`} viewBox="0 0 513 128" preserveAspectRatio="none" tabIndex={0}
               onFocus={() => setSelected(slot)} onContextMenu={event => { setSelected(slot); menu.open(event, slot) }} onPointerDown={event => {
                 if (event.button !== 0) return
                setSelected(slot); event.currentTarget.focus()
                if (view.tool === 'box' && points.length) { const point = position(event); event.currentTarget.setPointerCapture(event.pointerId); setDrag({ slot, x0: point.x, y0: point.y, ...point }) }
              }} onPointerMove={event => move(slot, event)} onPointerUp={event => endDrag(slot, event)} onPointerCancel={() => setDrag(null)}
              onPointerLeave={() => { if (!drag) setCursor(null) }} onKeyDown={event => {
                if (!points.length || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key) || event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return
                event.preventDefault()
                if (event.key === 'ArrowUp' || event.key === 'ArrowDown') zoomY(slot, event.key === 'ArrowUp' ? ZOOM_IN : ZOOM_OUT)
                else {
                  const step = event.key === 'ArrowRight' ? 1 : -1
                  const point = Math.max(0, Math.min(points.length - 1, (picked ?? Math.ceil(x.min) - 1) + step))
                  const position = point + 1
                  setCursor({ slot, point })
                  if (position < x.min) update(slot, { start: position })
                  else if (position > x.max) update(slot, { start: position - x.span })
                }
              }}>
              <defs><clipPath id={`${clip}-${slot}`}><rect width="513" height="128"/></clipPath></defs>
              <rect className="alignment-plot-background" width="513" height="128"/>
              {Array.from({ length: 9 }, (_, index) => <line key={`x${index}`} className="alignment-grid" x1={index * 64} x2={index * 64} y1="0" y2="128"/>)}
              {[0, 63.5, 127].map(y => <line key={y} className="alignment-grid" x1="0" x2="513" y1={y} y2={y}/>)}
              <g clipPath={`url(#${clip}-${slot})`}><path className="alignment-curve" d={path}/>
                {picked !== null && <g className="alignment-crosshair"><line x1={toX(picked + 1)} x2={toX(picked + 1)} y1="0" y2="128"/><line x1="0" x2="513" y1={Math.max(1, toY(points[picked]))} y2={Math.max(1, toY(points[picked]))}/></g>}
                {drag?.slot === slot && <rect className="alignment-selection" x={Math.min(drag.x, drag.x0) * 513} y={Math.min(drag.y, drag.y0) * 128} width={Math.abs(drag.x - drag.x0) * 513} height={Math.abs(drag.y - drag.y0) * 128}/>}</g>
            </svg>
            {!points.length && <span className="alignment-empty">{view.ccd === null ? '未安装 CCD' : '等待调试数据'}</span>}
            </div>
            <div className="alignment-x-range"><span>{Math.ceil(x.min)}</span><span>{points.length ? Math.floor(x.max) : '--'}</span></div>
          </div>
        </div>
      })}</div>
    </div>
    <footer className="alignment-status" role="status">{footer}</footer>
  </section>
}
