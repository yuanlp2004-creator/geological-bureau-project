import { Crosshair } from 'lucide-react'
import { api, type DispersionTask } from '../../api'
import type { DeviceCcd } from '../../api/devices'
import { SpectroscopyConsole } from '../acquisition/SpectroscopyConsole'
import { DispersionSpectrum } from './DispersionSpectrum'
import { runningStates, statusLabels } from './dispersionView'
import { SpectrumInspector } from '../../components/SpectrumInspector'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  view?: 'capture' | 'curve'
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
    <SpectroscopyConsole className="dispersion-run-panel" setup={active && <dl className="spectroscopy-task-summary" aria-label="当前任务条件">
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
      ccd={selectedCcd} ccdIndices={active?.ccd_indices ?? []} onCcdChange={setSelectedCcd} hash={active?.last_event?.details.sha256}
      toolbar={<>
        <span><Crosshair size={14} />最新帧峰值 {currentCcd ? `${currentCcd.peak} @ ${currentCcd.peak_position}` : '--'}（点位 0 起）</span>
      </>}>
      {active && <SpectrumInspector fitPlot iconToolbar key={`${active.id}:${selectedCcd}`} points={currentCcd?.points ?? []}
        pointOrigin={0} label={`CCD ${selectedCcd + 1} 色散采集曲线`} emptyText="开始采集后显示实时 CCD 曲线" />}
    </SpectroscopyConsole>
  )
}
