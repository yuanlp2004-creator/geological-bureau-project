import { api, type DispersionFrame, type DispersionTask } from '../../api'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { DeviceCcd } from '../../api/devices'
import { SpectroscopyConsole } from '../acquisition/SpectroscopyConsole'
import { DispersionSpectrum } from './DispersionSpectrum'
import { runningStates, statusLabels } from './dispersionView'
import { SpectrumInspector } from '../../components/SpectrumInspector'
import { CaptureBandList } from '../acquisition/CaptureBandList'
import { CaptureLineBar } from '../acquisition/CaptureLineBar'
import { positionMarkers } from './dispersionView'
import { useFixedSpectrumView } from '../../components/useFixedSpectrumView'
import type { PointDetailsTarget } from '../../components/SpectrumPointDetails'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  focusPoint?: number | null
  locate?: (value:string)=>void
  exposure?: { start: number; end: number }
  onToast?:(message:string)=>void
  recordNumber?:number
  displayName?:string
  detailDock?: HTMLElement | null
  turnPages?: ReactNode
  view?: 'capture' | 'curve'
  finish?: () => void
  canFinish?: boolean
  workflowToolbar?: ReactNode
  lineEditToolbar?: ReactNode
  recordChoices?: { value: string; name: string }[]
  savedBands: { id: number; name: string }[]
  onRecordChoose?: (value: string) => void
  recordDisabled?: boolean
  active: DispersionTask | null
  formalTask?: DispersionTask | null
  onShowFormalTask: () => void
  start: (singleTurn?: boolean) => Promise<void>
  preheat: () => Promise<void>
  canStart: boolean
  canPreheat: boolean
  canExecute: boolean
  pause: () => Promise<void>
  resume: () => Promise<void>
  busy: boolean
  stop: () => Promise<void>
  selectedCcd: number
  setSelectedCcd: React.Dispatch<React.SetStateAction<number>>
  currentCcd: DeviceCcd | undefined
  manualLine: number | null
  setManualLine: React.Dispatch<React.SetStateAction<number | null>>
  token: string
  canExport: boolean
  setLockedPoint: React.Dispatch<React.SetStateAction<number | null>>
}

export function DispersionMonitor({
  focusPoint, locate,
  view = 'capture', exposure, displayName, recordNumber, onToast, detailDock, turnPages,
  finish, canFinish, workflowToolbar, lineEditToolbar, recordChoices, savedBands, onRecordChoose, recordDisabled,
  active,
  formalTask, onShowFormalTask,
  start,
  preheat,
  canStart,
  canPreheat,
  canExecute,
  pause,
  resume,
  busy,
  stop,
  selectedCcd,
  setSelectedCcd,
  currentCcd,
  manualLine,
  setManualLine,
  token,
  canExport,
  setLockedPoint,
}: PanelProps) {
  const fixed = useFixedSpectrumView()
  const running = Boolean(active && runningStates.has(active.status))
  const isPreheat = Boolean(active?.condition.preheat)
  const formal = isPreheat ? formalTask : active
  const formalName = recordChoices?.find(item => item.value === String(formal?.id))?.name ?? formal?.name ?? active?.name
  const formalEnded = formal && ['completed', 'failed', 'stopped'].includes(formal.status)
  const enabled = Boolean(active && !busy && canExecute)
  const total = (active?.frame_count ?? 0) + (active?.dark_frame_count ?? 0)
  const captured = (active?.burn_frames_captured ?? 0) + (active?.dark_frames_captured ?? 0)
  const pointDetails: PointDetailsTarget | undefined = active && captured && !running && onToast
    ? { token, recordId: `dispersion:${active.id}`, ccd: selectedCcd, sampleName: '', bandName: displayName ?? active.name,
      onToast, canOutput: canExport } : undefined
  const context = { fixed, scope: `${view}:${active?.condition.source_sha256 ?? 'native'}:${selectedCcd}`, pointDetails, detailDock }
  const ccdNavigation = active ? { current: selectedCcd, indices: active.ccd_indices, choose: setSelectedCcd } : undefined
  const [saved, setSaved] = useState<{ key: string; frames: DispersionFrame[] } | null>(null)
  const [frameError, setFrameError] = useState('')
  const frameKey = `${token}:${active?.id}:${selectedCcd}`
  useEffect(() => {
    setSaved(null); setFrameError('')
    if (!active || running || view !== 'capture' || !captured) return
    let cancelled = false
    void api.dispersionFrames(token, active.id, selectedCcd).then(frames => {
      if (!cancelled) setSaved({ key: frameKey, frames })
    }).catch(error => { if (!cancelled) setFrameError(error instanceof Error ? error.message : '读取已保存谱帧失败') })
    return () => { cancelled = true }
  }, [frameKey, view, running, captured, active?.status])
  const frames = saved?.key === frameKey ? saved.frames : []
  const bandPosition = savedBands.findIndex(item => item.id === active?.id)
  const completedView = active?.status === 'completed' || active?.status === 'stopped'
  const selectedLine = active?.lines.find(line => line.id === manualLine && line.ccd_index === selectedCcd)
  const captureFocusPoint = focusPoint ?? selectedLine?.located_position ?? selectedLine?.expected_position
  const mean = useMemo(() => {
    const burns = frames.filter(item => item.phase === 'burn')
    const length = burns[0]?.points.length ?? 0
    if (!length || burns.some(item => item.points.length !== length)) return []
    return Array.from({ length }, (_, index) => burns.reduce((sum, item) => sum + item.points[index], 0) / burns.length)
  }, [saved, frameKey])
  if (view === 'curve') return <section className="legacy-view-center dispersion-curve-monitor" data-testid="dispersion-curve-monitor">
    {active ? <>
      <DispersionSpectrum key={`${token}:${active.id}:${selectedCcd}`} token={token} active={active} ccd={selectedCcd} onPick={setLockedPoint} displayName={displayName} onToast={onToast} recordNumber={recordNumber} exposure={exposure} curveView chooseCcd={setSelectedCcd} focusPoint={focusPoint} selectLine={setManualLine}
        context={context} canPrint={canExport}
        bandNavigation={{ previous: () => { const i = recordChoices?.findIndex(item => item.value === String(active.id)) ?? -1; if (i > 0) onRecordChoose?.(recordChoices![i - 1].value) },
          next: () => { const i = recordChoices?.findIndex(item => item.value === String(active.id)) ?? -1; if (i >= 0 && i < (recordChoices?.length ?? 0) - 1) onRecordChoose?.(recordChoices![i + 1].value) },
          canPrevious: !recordDisabled && (recordChoices?.findIndex(item => item.value === String(active.id)) ?? -1) > 0,
          canNext: !recordDisabled && (recordChoices?.findIndex(item => item.value === String(active.id)) ?? -1) >= 0 && (recordChoices?.findIndex(item => item.value === String(active.id)) ?? 0) < (recordChoices?.length ?? 0) - 1 }} />
    </> : <div className="empty-state">先在色散摄谱中采集谱图，再到这里制作色散曲线。</div>}
  </section>
  return (
    <SpectroscopyConsole className="dispersion-run-panel" recordTitle="色散谱带名" recordChoices={recordChoices} showRepeats={false}
      turnPages={turnPages}
      hideIdleTransport leadingActions={lineEditToolbar} topActions={workflowToolbar}
      recordValue={String(formal?.id ?? '')} onRecordChoose={onRecordChoose} recordDisabled={recordDisabled} repeats={1}
      context={isPreheat ? <>
        <span>预热观察（不生成正式谱带）</span>
        <button type="button" disabled={busy || !canFinish || !formal} onClick={onShowFormalTask}>返回正式任务</button>
      </> : undefined}
      lineBar={<CaptureLineBar locate={locate} disabled={busy || running} defaultExposure={active ? `1-${active.frame_count}` : ''} lines={active?.lines.map(line => ({ id: String(line.id), label: `${line.element} ${line.wavelength_nm || "待填波长"}`,
        wavelength: line.wavelength_nm, exposure: `1-${active.frame_count}` }))} value={manualLine === null ? '' : String(manualLine)}
        choose={id => {
          const line = active?.lines.find(line => String(line.id) === id)
          setManualLine(line?.id ?? null)
          if (line) setSelectedCcd(line.ccd_index)
        }} />}
      finish={finish ? { run: finish, enabled: Boolean(canFinish) } : undefined}
      records={<CaptureBandList title="色散谱带" variant="band" rows={savedBands} showReturn={false}
        selected={isPreheat ? null : savedBands.find(item => item.id === active?.id)?.id ?? null}
        disabled={Boolean(recordDisabled)} onChoose={id => { if (id !== null) onRecordChoose?.(String(id)) }} />}
      viewLabel={completedView ? isPreheat ? '预热谱图 · 仅观察' : active?.status === 'completed'
        ? `已保存谱带 · ${displayName ?? active.name}` : '停止谱图 · 燃烧均值' : '实时谱图'}
      name={formalName} status={active?.status}
      statusLabel={active?.positioning ? '正在定位转角' : active ? statusLabels[active.status] : undefined}
      start={{ run: start, enabled: enabled && canStart, disabledReason: formalEnded ? '正式任务已结束，请新建任务后再摄谱' : undefined }}
      singleTurn={formal?.capture_turn?.multiple ? { run: () => start(true), enabled: enabled && canStart } : undefined}
      preheat={{ run: preheat, enabled: enabled && canPreheat }}
      pause={{ run: pause, enabled: Boolean(active && canExecute && running && active.profile.transport !== 'serial'), disabledReason: active?.profile.transport === 'serial' ? '旧设备协议未提供暂停命令，请使用停止' : undefined }}
      resume={{ run: resume, enabled: enabled && active?.status === 'paused' }}
      stop={{ run: stop, enabled: Boolean(active && canExecute
        && (active.active_capture_id !== undefined || running || active.status === 'paused' || active.status === 'stopping')) }}
      progress={active ? [
        { label: '总进度', value: `${total ? (captured / total * 100).toFixed(1) : '0.0'}%`, current: captured, maximum: total },
        { label: '当前阶段', value: active.positioning ? '正在定位转角' : statusLabels[active.status] },
        { label: '燃烧帧 / 暗帧', value: `${active.burn_frames_captured}/${active.frame_count} · ${active.dark_frames_captured}/${active.dark_frame_count}` }
      ] : []}
      ccd={selectedCcd} ccdIndices={active?.ccd_indices ?? []} onCcdChange={setSelectedCcd} hash={active?.last_event?.details.sha256}
      >
      {captureDock => <>{frameError && <p role="alert">{frameError}</p>}
      {active && <SpectrumInspector fitPlot iconToolbar classic captureView key={`${active.id}:${selectedCcd}:${completedView ? 'mean' : 'live'}`} points={completedView ? mean : currentCcd?.points ?? []}
        ccdNavigation={ccdNavigation} context={{ ...context, detailDock: captureDock }}
        physicalScale={{ pointWidthUm: active.layout.point_width_um, screenWidthMm: active.profile.screen_width_mm, screenResolutionPx: active.profile.screen_resolution_px }}
        bandNavigation={{ previous: () => onRecordChoose?.(String(savedBands[bandPosition - 1].id)), next: () => onRecordChoose?.(String(savedBands[bandPosition + 1].id)),
          canPrevious: !recordDisabled && bandPosition > 0, canNext: !recordDisabled && bandPosition >= 0 && bandPosition < savedBands.length - 1 }}
        onPick={setLockedPoint} focusPoint={captureFocusPoint} markers={positionMarkers(active.lines,selectedCcd,active.layout.points_per_ccd,setManualLine).map(marker => ({
          ...marker, selected: marker.key.startsWith(`${manualLine}-`)
        }))}
        pointOrigin={0} label={`CCD ${selectedCcd + 1} 色散${isPreheat ? '预热' : ''}${completedView ? '燃烧均值谱图' : '采集曲线'}${isPreheat ? '（仅观察）' : ''}`}
        emptyText={completedView ? frameError || (!captured ? '当前任务没有可显示的燃烧帧' : saved?.key === frameKey && !mean.length ? '没有可显示的燃烧均值谱图' : '正在读取已保存谱帧…') : '开始采集后显示实时 CCD 曲线'} />}</>}
    </SpectroscopyConsole>
  )
}
