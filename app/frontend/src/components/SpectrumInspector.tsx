import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { NumericInput } from './NumericInput'
import { SpectrumPlot, observeSpectrumPlotFrame, type SpectrumPlotCursor, type SpectrumPlotMarker } from './SpectrumPlot'
import { SpectroscopyIcon, type SpectroscopyIconName } from './SpectroscopyIcon'
import { SpectroscopyToolButton } from './SpectroscopyToolButton'
import { LegacySpectrumSurface } from './LegacySpectrumSurface'
import { LegacyCcdPicker } from './LegacyCcdPicker'
import { ObservationToolbar } from './ObservationToolbar'
import { ContextMenu, useContextMenu, type MenuGroup } from './ContextMenu'
import { spectrumMenuGroups, type CcdNavigation } from './spectrumMenu'
import type { FixedSpectrumView } from './useFixedSpectrumView'
import type { PointDetailsTarget } from './SpectrumPointDetails'
import { SpectrumPointPanel, useSpectrumPointFollow } from './SpectrumPointPanel'
import { limitSpectrumRange, stepSpectrumRange, ZOOM_IN, ZOOM_OUT, type SpectrumAxis, type SpectrumViewRange } from './spectrumZoom'
import './spectrum-inspector.css'

export type { SpectrumViewRange } from './spectrumZoom'
type Range = SpectrumViewRange
type Props = {
  points: number[]
  wavelengths?: Array<number | null>
  yAxisLabel?:string
  label: string
  pointOrigin?: 0 | 1
  markers?: SpectrumPlotMarker[]
  fitPlot?: boolean
  iconToolbar?: boolean
  classic?: boolean
  panOnStripOnly?: boolean
  captureView?: boolean
  physicalScale?: { pointWidthUm?: number; screenWidthMm?: number; screenResolutionPx?: number }
  bandNavigation?: { previous: () => void; next: () => void; canPrevious: boolean; canNext: boolean }
  ccdNavigation?: CcdNavigation
  context?: { fixed: FixedSpectrumView; scope: string; extras?: (point: SpectrumPlotCursor | null) => MenuGroup;
    pointDetails?: PointDetailsTarget; detailDock?: HTMLElement | null;
    lineMenu?: (key: string) => MenuGroup[] | undefined; chooseMarker?: (key: string) => void }
  onPrint?: (range: SpectrumViewRange) => void
  printDisabledReason?: string
  toolbar?: import('react').ReactNode
  emptyText?: string
  onPick?: (pointIndex: number | null) => void
  legacyTitle?: import('react').ReactNode
  focusPoint?: number | null
  focusRevision?: number
}

// 只维护观察视图。调用方用任务/CCD作为key，切换对象时清空锁定点和缩放。
export function SpectrumInspector({ points, wavelengths, label, pointOrigin = 1, markers = [], fitPlot = false, iconToolbar = false, classic = false, captureView = false,
  physicalScale, bandNavigation, ccdNavigation, onPrint, printDisabledReason, toolbar,
  emptyText = '暂无可显示的谱图', onPick, legacyTitle, yAxisLabel, focusPoint, focusRevision, panOnStripOnly = false, context }: Props) {
  const full = useMemo<Range>(() => ({
    xMin: pointOrigin, xMax: Math.max(pointOrigin + 1, points.length - 1 + pointOrigin),
    yMin: Math.min(0, ...points), yMax: Math.max(1, ...points)
  }), [points, pointOrigin])
  const [initialRange, setInitialRange] = useState(() => {
    const saved = context?.fixed.lastRange.current
    return context?.fixed.enabled && saved?.scope === context.scope ? saved : null
  })
  const [range, setRange] = useState<Range | null>(null)
  const menu = useContextMenu<{ point: SpectrumPlotCursor | null; marker?: string }>()
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [locked, setLocked] = useState(false)
  const [point, setPoint] = useState<number>(pointOrigin)
  useEffect(()=>()=>onPick?.(null),[onPick])
  const root = useRef<HTMLDivElement>(null)
  const observerDialog = useRef<HTMLDialogElement>(null)
  const [plotPixels, setPlotPixels] = useState(872)
  const [scale, setScale] = useState<1 | 4 | 10 | null>(null)
  const hasPoints = points.length > 0
  const legacyPlot = Boolean(legacyTitle)
  useLayoutEffect(() => {
    if (!iconToolbar || !root.current) return
    return observeSpectrumPlotFrame(root.current, (frame, dpr) => setPlotPixels(frame.width * dpr))
  }, [iconToolbar, hasPoints, legacyPlot, classic, captureView])
  const validPhysical = [physicalScale?.pointWidthUm, physicalScale?.screenResolutionPx, physicalScale?.screenWidthMm]
    .every(value => Number.isFinite(value) && Number(value) > 0)
  const physicalSpacing = validPhysical ? Number(physicalScale?.pointWidthUm) / 1000 * 10
    * Number(physicalScale?.screenResolutionPx) / Number(physicalScale?.screenWidthMm) : 0
  const spacing = scale === 10 ? physicalSpacing : scale ?? 1
  const manualView = range ?? (initialRange ? { ...full, xMin: initialRange.xMin, xMax: initialRange.xMax } : full)
  const view = limitSpectrumRange(scale && spacing > 0
    ? { ...manualView, xMax: manualView.xMin + plotPixels / spacing }
    : manualView, full)
  const savedRange = context?.fixed.lastRange
  useLayoutEffect(() => {
    if (savedRange && hasPoints && context?.scope !== undefined && view.xMax > view.xMin) {
      savedRange.current = { scope: context.scope, xMin: view.xMin, xMax: view.xMax }
    }
  }, [savedRange, hasPoints, context?.scope, view.xMin, view.xMax])
  const following = Boolean(context?.fixed.showDetails && context.pointDetails)
  const target = context?.pointDetails
  const follow = useSpectrumPointFollow(following && hasPoints, `${target?.recordId}:${target?.ccd}`,
    cursor?.datum.point.point_index ?? null, locked)
  const openSpectrumMenu = context ? (event: MouseEvent, picked: SpectrumPlotCursor | null, marker?: string) => {
    if (marker && context.lineMenu) context.chooseMarker?.(marker)
    menu.open(event, { point: picked, marker })
  } : undefined
  const curves = useMemo(() => [{ id: 'current', label, color: '#1570a6', priority: true,
    data: points.map((value, index) => ({ x: index + pointOrigin, y: value,
      point: { point_index: index, value, wavelength_nm: wavelengths?.[index] } })) }], [points, wavelengths, label, pointOrigin])
  const liveCursor = cursor && points[cursor.datum.point.point_index] !== undefined ? {
    ...cursor, datum: { ...cursor.datum, y: points[cursor.datum.point.point_index],
      point: { ...cursor.datum.point, value: points[cursor.datum.point.point_index] } }
  } : null

  useEffect(() => {
    if (!hasPoints) { setCursor(null); setLocked(false); setRange(null); setScale(null); onPick?.(null) }
  }, [hasPoints, onPick])
  const reset = () => { setInitialRange(null); setScale(null); setRange(null); setCursor(null); setLocked(false); setPoint(pointOrigin); onPick?.(null) }
  const fitWidth = () => {setScale(null);setRange({...view,xMin:full.xMin,xMax:full.xMax})}
  const zoom = (axis: SpectrumAxis, factor: number) => {
    if (axis === 'x') setScale(null)
    setRange(stepSpectrumRange(view, full, axis, factor))
  }
  const boxSelect = (next: Range) => { setScale(null); setRange(limitSpectrumRange(next, full)); setTool('crosshair') }
  const toggleLock = (picked: SpectrumPlotCursor | null = liveCursor) => {
    if (!picked) return
    const next = !locked
    setCursor(picked)
    setPoint(picked.datum.x)
    setLocked(next)
    onPick?.(next ? picked.datum.point.point_index : null)
  }
  const readPoint = (value: number) => {
    setPoint(value)
    const index = value - pointOrigin
    if (!Number.isInteger(index) || index < 0 || index >= points.length) return
    const datum = curves[0].data[index]
    setCursor({ curveId: 'current', curveLabel: label, x: 0, y: 0, datum, datumIndex: index })
    setLocked(true)
    setTool('crosshair')
    onPick?.(index)
  }
  useEffect(() => {
    if (!hasPoints) return
    if (focusPoint == null) {
      if (focusRevision) { setCursor(null); setLocked(false); onPick?.(null) }
      return
    }
    const index = Math.round(focusPoint)
    if (index < 0 || index >= points.length) return
    readPoint(index + pointOrigin)
    const span = Math.min(full.xMax-full.xMin, view.xMax - view.xMin)
    const start = Math.max(full.xMin,Math.min(full.xMax-span,index+pointOrigin-span/2))
    setRange({ ...view, xMin: start, xMax: start + span })
  }, [focusPoint, focusRevision, hasPoints])
  const updateCursor = (next: SpectrumPlotCursor | null) => { setCursor(next); if (next) setPoint(next.datum.x) }
  const plot = <SpectrumPlot fitContainer={fitPlot} stretch={legacyPlot} curves={curves} xStart={view.xMin} xEnd={view.xMax} yStart={view.yMin} yEnd={view.yMax}
    tool={tool} cursor={liveCursor} locked={locked}
    onCursor={updateCursor} onToggleLock={toggleLock}
    onPointerPresence={target ? follow.plotPresence : undefined}
    onPan={(x, y) => { if (panOnStripOnly) return; setRange({ xMin: view.xMin - x * (view.xMax - view.xMin), xMax: view.xMax - x * (view.xMax - view.xMin),
      yMin: view.yMin + y * (view.yMax - view.yMin), yMax: view.yMax + y * (view.yMax - view.yMin) }) }}
    onBoxSelect={boxSelect} onZoomY={factor => zoom('y', factor)} markers={markers} onSpectrumContext={openSpectrumMenu}
    xAxisLabel={`CCD 点位 (${pointOrigin} 起)`} yAxisLabel={yAxisLabel??"强度 (ADC)"} />
  const readout = <div className="inspector-readout">
    <label>读取点位 <NumericInput min={pointOrigin} max={points.length - 1 + pointOrigin} step={1} value={point}
      onValueChange={readPoint} data-observation-input="true" onFocus={() => { setLocked(false); onPick?.(null) }} /></label>
    <output aria-label="谱图点位读数">{liveCursor
      ? `点位 ${liveCursor.datum.x} · 强度 ${liveCursor.datum.y.toLocaleString('zh-CN', { maximumFractionDigits: 6 })}${locked ? ' · 已锁定' : ''}`
      : '移动鼠标查看强度，单击曲线锁定点位'}</output>
    <small>视野 {view.xMin.toFixed(1)}–{view.xMax.toFixed(1)} · 强度 {view.yMin.toFixed(1)}–{view.yMax.toFixed(1)}</small>
  </div>
  const surface = legacyTitle ? <LegacySpectrumSurface title={legacyTitle} curves={curves} xMin={view.xMin} xMax={view.xMax} yMin={view.yMin} yMax={view.yMax}
    cursor={liveCursor} locked={locked} tool={tool} onCursor={updateCursor} onToggleLock={toggleLock}
    onPointerPresence={target ? follow.plotPresence : undefined}
    onPan={x => setRange({ ...view, xMin:view.xMin-x*(view.xMax-view.xMin), xMax:view.xMax-x*(view.xMax-view.xMin) })}
    onBox={boxSelect} onSpectrumContext={openSpectrumMenu}>{plot}</LegacySpectrumSurface> : plot
  const lineMenu = menu.target?.data.marker && context?.lineMenu?.(menu.target.data.marker)
  return <div ref={root} className="spectrum-inspector" aria-label={label}>
    {menu.target && context && hasPoints && <ContextMenu target={menu.target} close={menu.close} label={lineMenu ? '谱线位置菜单' : '谱图菜单'}
      groups={lineMenu || spectrumMenuGroups(ccdNavigation, view, full, zoom,
        { label: '固定视图', checked: context.fixed.enabled, run: context.fixed.toggle }, [
          ...(context.pointDetails ? [{ label: '显示分时', checked: following, run: () => {
            if (!following) {
              const picked = locked ? liveCursor : menu.target?.data.point ?? liveCursor
              follow.openAt(picked?.datum.point.point_index ?? null)
              setCursor(picked)
            }
            context.fixed.setShowDetails(!following)
          } }] : []),
          ...(context.extras?.(menu.target.data.point) ?? [])
        ])} />}
    {legacyTitle ? <ObservationToolbar disabled={!hasPoints} tool={tool} setTool={setTool} fit={fitWidth}
      navigation={<>
        <SpectroscopyToolButton icon="previous-band" label="上一谱带" disabled={!bandNavigation?.canPrevious} onClick={bandNavigation?.previous}/>
        <SpectroscopyToolButton icon="next-band" label="下一谱带" disabled={!bandNavigation?.canNext} onClick={bandNavigation?.next}/>
        <SpectroscopyToolButton icon="previous-ccd" label="上一 CCD" disabled={!hasPoints||!ccdNavigation||ccdNavigation.indices.indexOf(ccdNavigation.current)<=0}
          onClick={()=>ccdNavigation?.choose(ccdNavigation.indices[ccdNavigation.indices.indexOf(ccdNavigation.current)-1])}/>
        <SpectroscopyToolButton icon="next-ccd" label="下一 CCD" disabled={!hasPoints||!ccdNavigation||ccdNavigation.indices.indexOf(ccdNavigation.current)>=ccdNavigation.indices.length-1}
          onClick={()=>ccdNavigation?.choose(ccdNavigation.indices[ccdNavigation.indices.indexOf(ccdNavigation.current)+1])}/>
        <LegacyCcdPicker aria-label="选择CCD" title={`CCD ${(ccdNavigation?.current??0)+1}`} value={ccdNavigation?.current??0} disabled={!hasPoints||!ccdNavigation?.indices.length}
          onChange={event=>ccdNavigation?.choose(Number(event.target.value))}>
          {ccdNavigation?.indices.map(ccd=><option key={ccd} value={ccd}>{ccdNavigation.labels?.[ccd] ?? `CCD ${ccd+1}`}</option>)}
        </LegacyCcdPicker>
      </>}
      scales={<>{([1,4,10] as const).map(value=><SpectroscopyToolButton key={value} icon={value===1?'scale-1':value===4?'scale-4':'scale-10'}
        label={value===1?'一线一点':value===4?'一线四点':'十倍 CCD'} disabled={!hasPoints||(value===10&&!(physicalSpacing>0))} aria-pressed={scale===value}
        onClick={()=>{setRange(view);setScale(value)}}/>)}</>}
      zoom={zoom} resetY={()=>setRange({...view,yMin:full.yMin,yMax:full.yMax})}
      print={()=>onPrint?.(view)} printDisabledReason={printDisabledReason??(!onPrint?'当前谱图不支持打印':undefined)} /> : <div className={`inspector-tools${iconToolbar ? ' inspector-icon-tools' : ''}`} role="group" aria-label="谱图观察工具">
      {iconToolbar && bandNavigation && <div className="inspector-tool-modes" role="group" aria-label="谱带切换">
        <SpectroscopyToolButton icon="previous-band" label="上一谱带" disabled={!bandNavigation.canPrevious} onClick={bandNavigation.previous} />
        <SpectroscopyToolButton icon="next-band" label="下一谱带" disabled={!bandNavigation.canNext} onClick={bandNavigation.next} />
      </div>}
      {iconToolbar && ccdNavigation && <div className="inspector-tool-modes spectroscopy-ccd-tools" role="group" aria-label="CCD切换">
        <SpectroscopyToolButton icon="previous-ccd" label="上一 CCD"
          disabled={(classic && !hasPoints) || ccdNavigation.indices.indexOf(ccdNavigation.current) <= 0}
          onClick={() => ccdNavigation.choose(ccdNavigation.indices[ccdNavigation.indices.indexOf(ccdNavigation.current) - 1])} />
        <SpectroscopyToolButton icon="next-ccd" label="下一 CCD"
          disabled={(classic && !hasPoints) || ccdNavigation.indices.indexOf(ccdNavigation.current) < 0 || ccdNavigation.indices.indexOf(ccdNavigation.current) >= ccdNavigation.indices.length - 1}
          onClick={() => ccdNavigation.choose(ccdNavigation.indices[ccdNavigation.indices.indexOf(ccdNavigation.current) + 1])} />
        <label className={classic ? 'classic-ccd-picker' : 'spectroscopy-ccd-choice'} title={`CCD ${ccdNavigation.current + 1}`}>
          {classic ? <SpectroscopyIcon name="select-ccd" /> : <span aria-hidden="true">CCD</span>}
          {classic && <span aria-hidden="true" />}<select aria-label="选择CCD" title={`CCD ${ccdNavigation.current + 1}`} value={ccdNavigation.current} disabled={!ccdNavigation.indices.length || (classic && !hasPoints)}
          onChange={event => ccdNavigation.choose(Number(event.target.value))}>
          {!ccdNavigation.indices.length && <option value={ccdNavigation.current}>等待采集</option>}
          {ccdNavigation.indices.map(ccd => <option key={ccd} value={ccd}>{ccdNavigation.labels?.[ccd] ?? (classic ? `CCD ${ccd + 1}` : ccd + 1)}</option>)}
        </select></label>
      </div>}
      {iconToolbar ? <div className="inspector-tool-modes" role="group" aria-label="谱图工具">
        {([['crosshair', '十字线', 'crosshair'], ['box', '区域放大', 'box-zoom'], ['pan', '滚动工具', 'pan']] as const).map(([value, name, icon]) => (
          <button key={value} type="button" className="secondary-button inspector-icon-button" disabled={!hasPoints}
            aria-label={name} title={name} aria-pressed={tool === value} onClick={() => setTool(value)}>
            <SpectroscopyIcon name={icon} />
          </button>
        ))}
      </div> : <label>工具 <select aria-label="谱图工具" value={tool} disabled={!hasPoints}
        onChange={(event) => setTool(event.target.value as typeof tool)}>
        <option value="crosshair">十字线</option><option value="pan">滚动工具</option><option value="box">区域放大</option>
      </select></label>}
      {iconToolbar && <div className="inspector-tool-modes" role="group" aria-label="显示比例">
        <SpectroscopyToolButton icon="fit" label="适合图像" disabled={!hasPoints} onClick={fitWidth} />
        {([1, 4, 10] as const).map(value => <SpectroscopyToolButton key={value} icon={value === 1 ? 'scale-1' : value === 4 ? 'scale-4' : 'scale-10'}
          label={value === 1 ? '一线一点' : value === 4 ? '一线四点' : '十倍 CCD'}
          description={value === 10 && !(physicalSpacing > 0) ? '需要有效的屏幕宽度、分辨率和CCD点宽' : value === 10 ? '按CCD点宽与屏幕参数显示十倍物理比例' : `每个CCD点对应${value}个屏幕像素`}
          disabled={!hasPoints || (value === 10 && !(physicalSpacing > 0))} aria-pressed={scale === value}
          onClick={() => { setRange(view); setScale(value) }} />)}
      </div>}
      {([
        ['横向放大', 'zoom-x-in', () => zoom('x', ZOOM_IN)],
        ['横向缩小', 'zoom-x-out', () => zoom('x', ZOOM_OUT)],
        ['纵向放大', 'zoom-y-in', () => zoom('y', ZOOM_IN)],
        ['纵向缩小', 'zoom-y-out', () => zoom('y', ZOOM_OUT)],
        ['适合图像', 'fit', reset]
      ] satisfies [string, SpectroscopyIconName, () => void][]).filter(([name]) => !iconToolbar || name !== '适合图像').map(([name, icon, action]) => (
        <button key={name} type="button" className={`secondary-button${iconToolbar ? ' inspector-icon-button' : ''}`}
          disabled={!hasPoints} aria-label={name} title={name} onClick={action}>
          {iconToolbar ? <SpectroscopyIcon name={icon} /> : name}
        </button>
      ))}
      {iconToolbar && <SpectroscopyToolButton icon="reset-y" label="纵向还原" disabled={!hasPoints}
        onClick={() => setRange({ ...view, yMin: full.yMin, yMax: full.yMax })} />}
      {!classic && <button type="button" className={`secondary-button${iconToolbar ? ' inspector-icon-button' : ''}`} disabled={!liveCursor}
        aria-label={locked ? '解除锁定' : '锁定点位'} title={locked ? '解除锁定' : '锁定点位'} aria-pressed={locked} onClick={() => toggleLock()}>
        {iconToolbar ? <SpectroscopyIcon name="lock" /> : locked ? '解除锁定' : '锁定点位'}
      </button>}
      {iconToolbar && (onPrint || classic) && <SpectroscopyToolButton icon="print" label="打印谱图" description={printDisabledReason ?? '打印当前可见的已保存谱带'}
        disabled={!hasPoints || !onPrint || Boolean(printDisabledReason)} onClick={() => onPrint?.(view)} />}
      {toolbar}
    </div>}
    {hasPoints ? <>
      <div className="spectrum-point-layout">
        <div className="spectrum-point-plot">
          {classic ? <div className={`legacy-plot-frame${captureView ? ' capture-plot-frame' : ''}`} onDoubleClick={captureView ? undefined : () => observerDialog.current?.showModal()}>
            {captureView && <output className="capture-plot-readout" aria-label="谱图同步读数">
              {liveCursor ? `强度：${liveCursor.datum.y.toLocaleString('zh-CN', { maximumFractionDigits: 6 })}　坐标：${liveCursor.datum.x}${locked ? ' · 已锁定' : ''}` : '强度：—　坐标：—'}
            </output>}{surface}</div> : surface}
        </div>
        {following && target && context && <SpectrumPointPanel dock={context.detailDock} target={target} follow={follow}
          onClose={() => context.fixed.setShowDetails(false)} />}
      </div>
      {!captureView && (classic ? <dialog ref={observerDialog} className="spectrum-observer-dialog" aria-label="谱图点位与视野">
        <header><h2>谱图点位与视野</h2><button type="button" aria-label="关闭谱图读数" onClick={() => observerDialog.current?.close()}>×</button></header>
        {readout}<button type="button" aria-label={locked ? '解除锁定' : '锁定点位'} disabled={!liveCursor} onClick={() => toggleLock()}>{locked ? '解除锁定' : '锁定点位'}</button>
      </dialog> : !legacyTitle && readout)}
      {!classic && !legacyTitle && markers.length > 0 && <div className="inspector-markers" aria-label="谱线位置">
        {markers.map((marker) => <button className={`secondary-button ${marker.kind}`} key={marker.key}
          title={marker.label} onClick={() => setRange({ ...full,
            xMin: Math.max(full.xMin, marker.position - 30), xMax: Math.min(full.xMax, marker.position + 30) })}>
          {marker.label}
        </button>)}
      </div>}
    </> : <div className="inspector-empty" title={emptyText}>{classic ? <span className="legacy-empty-banner">[无谱带可显示]</span> : emptyText}</div>}
  </div>
}
