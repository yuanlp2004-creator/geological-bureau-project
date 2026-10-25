import { Crosshair } from 'lucide-react'
import { api, type DispersionFrame, type DispersionTask } from '../../api'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { DeviceCcd } from '../../api/devices'
import { SpectroscopyConsole } from '../acquisition/SpectroscopyConsole'
import { DispersionSpectrum } from './DispersionSpectrum'
import { runningStates, statusLabels } from './dispersionView'
import { SpectrumInspector } from '../../components/SpectrumInspector'
import { CaptureBandList } from '../acquisition/CaptureBandList'
import { CaptureLineBar } from '../acquisition/CaptureLineBar'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  view?: 'capture' | 'curve'
  finish?: () => void
  canFinish?: boolean
  workflowToolbar?: ReactNode
  lineEditToolbar?: ReactNode
  recordChoices?: { value: string; name: string }[]
  onRecordChoose?: (value: string) => void
  recordDisabled?: boolean
  active: DispersionTask | null
  start: () => Promise<void>
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
  lockedPoint: number | null
  manualLine: number | null
  setManualLine: React.Dispatch<React.SetStateAction<number | null>>
  canWrite: boolean
  change: (work: (id: number) => Promise<unknown>, message?: string) => Promise<DispersionTask | undefined> | undefined
  token: string
  setLockedPoint: React.Dispatch<React.SetStateAction<number | null>>
}

export function DispersionMonitor({
  view = 'capture',
  finish, canFinish, workflowToolbar, lineEditToolbar, recordChoices, onRecordChoose, recordDisabled,
  active,
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
  lockedPoint,
  manualLine,
  setManualLine,
  canWrite,
  change,
  token,
  setLockedPoint,
}: PanelProps) {
  const running = Boolean(active && runningStates.has(active.status))
  const enabled = Boolean(active && !busy && canExecute)
  const total = (active?.frame_count ?? 0) + (active?.dark_frame_count ?? 0)
  const captured = (active?.burn_frames_captured ?? 0) + (active?.dark_frames_captured ?? 0)
  const [frameId, setFrameId] = useState<number | null>(null)
  const [saved, setSaved] = useState<{ key: string; frames: DispersionFrame[] } | null>(null)
  const [frameError, setFrameError] = useState('')
  const frameKey = `${token}:${active?.id}:${selectedCcd}`
  useEffect(() => { setFrameId(null) }, [active?.id, selectedCcd])
  useEffect(() => { setLockedPoint(null) }, [active?.id, selectedCcd, frameId, setLockedPoint])
  useEffect(() => {
    setSaved(null); setFrameError('')
    if (!active || running || view !== 'capture' || !captured) return
    let cancelled = false
    void api.dispersionFrames(token, active.id, selectedCcd).then(frames => {
      if (!cancelled) setSaved({ key: frameKey, frames })
    }).catch(error => { if (!cancelled) setFrameError(error instanceof Error ? error.message : '读取已保存谱帧失败') })
    return () => { cancelled = true }
  }, [frameKey, view, running, captured, active?.status])
  useEffect(() => { if (running) setFrameId(null) }, [running])
  const frames = saved?.key === frameKey ? saved.frames : []
  const frame = frames.find(item => item.id === frameId)
  const historical = frameId !== null
  const framePosition = frames.findIndex(item => item.id === frameId)
  const completedView = active?.status === 'completed' || active?.status === 'stopped'
  const mean = useMemo(() => {
    const burns = frames.filter(item => item.phase === 'burn')
    const length = burns[0]?.points.length ?? 0
    if (!length || burns.some(item => item.points.length !== length)) return []
    return Array.from({ length }, (_, index) => burns.reduce((sum, item) => sum + item.points[index], 0) / burns.length)
  }, [saved, frameKey])
  if (view === 'curve') return <section className="surface dispersion-curve-monitor" data-testid="dispersion-curve-monitor">
    <div className="surface-heading"><h2>{active?.name ?? '选择已采集色散谱图'}</h2>
      <label className="field compact-field"><span>CCD</span><select value={selectedCcd} aria-label="色散曲线CCD" disabled={!active}
        onChange={(event) => setSelectedCcd(Number(event.target.value))}>
        {active?.ccd_indices.map((ccd) => <option key={ccd} value={ccd}>CCD {ccd + 1}</option>)}
      </select></label>
    </div>
    {active ? <>
      <DispersionSpectrum key={`${token}:${active.id}:${selectedCcd}`} token={token} active={active} ccd={selectedCcd} onPick={setLockedPoint} />
      <div className="inspector-frame-tools">
        <span>锁定实际点位：{lockedPoint ?? '未选择'}</span>
        <select aria-label="人工定位谱线" value={manualLine ?? ''} onChange={(event) => setManualLine(event.target.value === '' ? null : Number(event.target.value))}>
          <option value="">选择当前 CCD 谱线</option>
          {active.lines.filter((line) => line.ccd_index === selectedCcd).map((line) => <option key={line.id} value={line.id}>{line.element} {line.wavelength_nm}</option>)}
        </select>
        <button disabled={busy || !canWrite || manualLine === null || lockedPoint === null} onClick={() => {
          if (manualLine !== null && lockedPoint !== null)
            void change((id) => api.setDispersionPosition(token, id, manualLine, lockedPoint), '人工点位已设置，可保存或恢复')
        }}>采用锁定点位</button>
      </div>
    </> : <div className="empty-state">先在色散摄谱中采集谱图，再到这里制作色散曲线。</div>}
  </section>
  return (
    <SpectroscopyConsole className="dispersion-run-panel" recordTitle="色散谱带名" recordChoices={recordChoices} showRepeats={false}
      hideIdleTransport leadingActions={lineEditToolbar} topActions={workflowToolbar}
      recordValue={String(active?.id ?? '')} onRecordChoose={onRecordChoose} recordDisabled={recordDisabled} repeats={1}
      lineBar={<CaptureLineBar disabled={busy || running} defaultExposure={active ? `1-${active.frame_count}` : ''} lines={active?.lines.map(line => ({ id: String(line.id), label: `${line.element} ${line.wavelength_nm}`,
        wavelength: line.wavelength_nm, exposure: `1-${active.frame_count}` }))} value={manualLine === null ? '' : String(manualLine)}
        choose={id => {
          const line = active?.lines.find(line => String(line.id) === id)
          setManualLine(line?.id ?? null)
          if (line) setSelectedCcd(line.ccd_index)
        }} />}
      finish={finish ? { run: finish, enabled: Boolean(canFinish) } : undefined}
      records={<CaptureBandList title="色散谱带" variant="band" rows={frames.map(item => ({ id: item.id,
        name: `${item.phase === 'dark' ? '暗帧' : '燃烧帧'} ${item.frame_index + 1}`, detail: `CCD ${item.ccd_index + 1}` }))}
        selected={frameId} disabled={busy || running} onChoose={setFrameId} />}
      viewLabel={frame ? `已保存${frame.phase === 'dark' ? '暗帧' : '燃烧帧'} ${frame.frame_index + 1}` : completedView ? '完成谱图 · 燃烧均值' : '实时谱图'}
      setup={active && <dl className="spectroscopy-task-summary" aria-label="当前任务条件">
      <div><dt>设备档案</dt><dd>{active.profile.name}</dd></div>
      <div><dt>CCD 布局</dt><dd>{active.layout.name}</dd></div>
      <div><dt>燃烧帧 / 暗帧</dt><dd>{active.frame_count} / {active.dark_frame_count}</dd></div>
      <div><dt>预激时间 / 采样周期</dt><dd>{active.pre_excitation_seconds}s / {active.sampling_period_seconds}s</dd></div>
    </dl>} name={active?.name} status={active?.status}
      statusLabel={active ? statusLabels[active.status] : undefined}
      source={active?.condition?.source_format === 'wdt' ? '旧 WDT 原始帧 · 只读重新拟合'
        : active?.profile.transport === 'simulator' ? '模拟设备 · 仅用于软件验证' : '真实设备 · 连接与协议状态以当前任务反馈为准'}
      start={{ run: start, enabled: enabled && canStart }}
      preheat={{ run: preheat, enabled: enabled && canPreheat }}
      pause={{ run: pause, enabled: Boolean(active && canExecute && running) }}
      resume={{ run: resume, enabled: enabled && active?.status === 'paused' }}
      stop={{ run: stop, enabled: Boolean(active && canExecute && (running || active.status === 'paused' || active.status === 'stopping')) }}
      progress={active ? [
        { label: '总进度', value: `${total ? (captured / total * 100).toFixed(1) : '0.0'}%`, current: captured, maximum: total },
        { label: '当前阶段', value: statusLabels[active.status] },
        { label: '燃烧帧 / 暗帧', value: `${active.burn_frames_captured}/${active.frame_count} · ${active.dark_frames_captured}/${active.dark_frame_count}` }
      ] : []}
      ccd={selectedCcd} ccdIndices={active?.ccd_indices ?? []} onCcdChange={setSelectedCcd} hash={historical ? frame?.sha256 : active?.last_event?.details.sha256}
      toolbar={<>
        <span><Crosshair size={14} />最新帧峰值 {currentCcd ? `${currentCcd.peak} @ ${currentCcd.peak_position}` : '--'}（点位 0 起）</span>
      </>}>
      {frameError && <p role="alert">{frameError}</p>}
      {active && <SpectrumInspector fitPlot iconToolbar classic key={`${active.id}:${selectedCcd}:${frameId ?? (completedView ? 'mean' : 'live')}`} points={historical ? frame?.points ?? [] : completedView ? mean : currentCcd?.points ?? []}
        ccdNavigation={{ current: selectedCcd, indices: active.ccd_indices, choose: setSelectedCcd }}
        physicalScale={{ pointWidthUm: active.layout.point_width_um, screenWidthMm: active.profile.screen_width_mm, screenResolutionPx: active.profile.screen_resolution_px }}
        bandNavigation={{ previous: () => setFrameId(frames[framePosition - 1]?.id ?? null), next: () => setFrameId(frames[framePosition + 1]?.id ?? null),
          canPrevious: !busy && !running && framePosition > 0, canNext: !busy && !running && framePosition < frames.length - 1 }}
        onPick={historical ? undefined : setLockedPoint}
        pointOrigin={0} label={`CCD ${selectedCcd + 1} 色散${historical ? '已保存谱帧' : completedView ? '燃烧均值谱图' : '采集曲线'}`}
        emptyText={historical || completedView ? frameError || (!captured ? '当前任务没有可显示的燃烧帧' : saved?.key === frameKey && !mean.length ? '没有可显示的燃烧均值谱图' : '正在读取已保存谱帧…') : '开始采集后显示实时 CCD 曲线'} />}
    </SpectroscopyConsole>
  )
}
