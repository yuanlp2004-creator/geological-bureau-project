import { useHardwareStopRetry } from '../../stores/hardwareLockStore'
import { api, saveFile, type AcquisitionTask } from '../../api'
import type { DeviceCcd } from '../../api/devices'
import { SpectrumInspector, type SpectrumViewRange } from '../../components/SpectrumInspector'
import { stateLabel } from './acquisitionView'
import { captureStatusInput } from './spectroscopyStatus'
import { SpectroscopyConsole } from './SpectroscopyConsole'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CaptureBandList } from './CaptureBandList'
import { useSampleCaptureLines } from './CaptureLineBar'
import { CaptureTurnPages } from './CaptureTurnPages'
import { useFixedSpectrumView } from '../../components/useFixedSpectrumView'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { CaptureMeasurement, useCaptureMeasurement } from './CaptureMeasurement'
import { AcquisitionMonitoring } from './AcquisitionMonitoring'
import type { AcquisitionIntervention } from '../../api/acquisition'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  token: string
  canExport: boolean
  canReadSpectra: boolean
  canReadMethods: boolean
  onToast: (message: string) => void
  finish: () => void
  canFinish: boolean
  inputToolbar?: ReactNode
  sampleInput?: ReactNode
  selected: AcquisitionTask | null
  formalTask?: AcquisitionTask | null
  onShowFormalTask: () => void
  onChooseTurnTask: (id: number) => void
  apply: (action: "start" | "preheat" | "pause" | "resume" | "stop", turnIndex?: number, singleTurn?: boolean) => Promise<void>
  intervene: (decision: AcquisitionIntervention) => Promise<void>
  busy: boolean
  canExecute: boolean
  canStart: boolean
  canPreheat: boolean
  progressLabel: string
  ccdIndex: number
  setCcdIndex: React.Dispatch<React.SetStateAction<number>>
  selectedCcd: DeviceCcd | undefined
  selectedPoints: number[]
}

export function SampleAcquisitionMonitor({
  token, canExport, canReadSpectra, canReadMethods, onToast, finish, canFinish, inputToolbar, sampleInput,
  selected,
  formalTask,
  onShowFormalTask,
  onChooseTurnTask,
  apply, intervene,
  busy,
  canExecute,
  canStart,
  canPreheat,
  progressLabel,
  ccdIndex,
  setCcdIndex,
  selectedCcd,
  selectedPoints,
}: PanelProps) {
  const fixed = useFixedSpectrumView()
  const retryStop = useHardwareStopRetry(selected?.task_kind === 'evaporation' ? 'evaporation-acquisition' : 'sample-acquisition',
    selected?.active_capture_id ?? selected?.id)
  const running = Boolean(selected && ['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats'].includes(selected.status))
  const acquiring = Boolean(selected && ['countdown', 'pre_excitation', 'burn', 'dark', 'stopping'].includes(selected.status))
  const enabled = Boolean(selected && !busy && canExecute)
  const isPreheat = selected?.sample_kind === 'preheat'
  const formal = isPreheat ? formalTask : selected
  const formalEnded = Boolean(formal && ['completed', 'failed', 'stopped'].includes(formal.status))
  const [sampleId, setSampleId] = useState<number | null>(null)
  const [band, setBand] = useState<{ key: string; points: number[]; sha256?: string } | null>(null)
  const [error, setError] = useState('')
  const [preheatSpectrum, setPreheatSpectrum] = useState<{ key: string; points: number[]; sha256?: string } | null>(null)
  const [preheatError, setPreheatError] = useState<{ key: string; message: string } | null>(null)
  const [printing, setPrinting] = useState(false)
  const [measurementOpen, setMeasurementOpen] = useState(false)
  const generation = useRef(0)
  const sampleTurns = formal?.turns
  const awaitingTurn = selected?.status === 'paused' && selected.turns?.awaiting_turn
  const lockedTurn = acquiring || selected?.status === 'paused' && !awaitingTurn
  const nextTurn = formal?.status === 'between_repeats' ? 0 : sampleTurns?.turn_index ?? 0
  const [viewTurn, setViewTurn] = useState(0)
  useEffect(() => { setViewTurn(selected?.capture_turn?.turn_index ?? nextTurn) }, [selected?.id, nextTurn])
  const turnIndex = selected?.capture_turn?.turn_index ?? (lockedTurn ? nextTurn : viewTurn)
  const turn = sampleTurns?.plan.find(item => item.turn_index === turnIndex)
  const angle = turn?.angle_deg ?? selected?.capture_turn?.angle_deg
  const visibleCcds = (isPreheat ? selected?.ccd_indices : turn?.ccd_indices) ?? selected?.ccd_indices ?? []
  const ccd = visibleCcds.includes(ccdIndex) ? ccdIndex : visibleCcds[0] ?? ccdIndex
  const liveCcd = selected?.last_event?.ccds.find(item => item.ccd_index === ccd)
  const livePoints = selected?.turns?.multiple && (!selected.turns.positioned || turnIndex !== selected.turns.turn_index)
    ? [] : liveCcd?.points ?? (selectedCcd?.ccd_index === ccd ? selectedPoints : [])
  const captureLines = useSampleCaptureLines({ token, canReadMethods: canReadMethods && !(selected?.task_kind === 'evaporation' && selected.capture_turn?.multiple), taskId: selected?.id,
    methodId: selected?.method_id ?? null, version: selected?.method_version ?? null,
    frames: selected?.burn_frame_count ?? 0, ccd, ccdIndices: visibleCcds,
    pointsPerCcd: selected?.layout.points_per_ccd ?? 0, chooseCcd: setCcdIndex,
    turns: sampleTurns, turnIndex })
  const readyAngle = !sampleTurns?.multiple || turnIndex === nextTurn
  const startAngle = sampleTurns?.multiple ? nextTurn : undefined
  const pages = sampleTurns ? sampleTurns.plan.map(item => ({ ...item, state:
    formal?.status === 'completed' || (formal?.status !== 'between_repeats' && item.turn_index < sampleTurns.completed_turns) ? '已采' :
    item.turn_index === nextTurn && lockedTurn && !isPreheat ? '采集中' : item.turn_index === nextTurn && canStart ? '待开始' : '待采' })) :
    (formal?.capture_turns ?? []).map(item => ({ ...item, state: stateLabel[item.status as AcquisitionTask['status']] ?? item.status }))
  const turnPages = <CaptureTurnPages pages={pages} current={turnIndex} disabled={busy || lockedTurn || Boolean(isPreheat && sampleTurns)}
    choose={index => {
      if (sampleTurns) setViewTurn(index)
      else {
        const page = formal?.capture_turns?.find(item => item.turn_index === index)
        if (page) onChooseTurnTask(page.id)
      }
    }} />
  const preheatComplete = selected?.sample_kind === 'preheat' && selected.status === 'completed'
  const preheatKey = `${token}:${selected?.id}:${ccd}`
  const completed = formal?.samples.filter(sample => sample.sample_kind !== 'preheat' && sample.bands.length > 0
    && sample.finalized && !sample.discarded && sample.status === 'completed') ?? []
  const observedSample = isPreheat ? undefined : completed.find(sample => sample.id === sampleId)
  const measurementTask = (!observedSample || measurementOpen) && !isPreheat && selected?.task_kind === 'sample' ? selected : undefined
  const measuring = measurementOpen && Boolean(measurementTask)
  const measurement = useCaptureMeasurement(token, measuring ? measurementTask : undefined, turnIndex, ccd)
  const observedSlot = observedSample?.bands.findIndex(item => item.ccd_index === ccd && (!selected?.turns || item.turn_index === turnIndex)) ?? -1
  const pointDetails = !measuring && canReadSpectra && observedSample?.storage_mode === 'full_interval' && observedSlot >= 0
    ? { token, recordId: `sample:${observedSample.id}`, ccd: observedSlot, onToast, canOutput: canExport } : undefined
  const observedKey = `${token}:${selected?.id}:${observedSample?.id}:${turnIndex}:${ccd}`
  const [turnPreview, setTurnPreview] = useState<{ key: string; points?: number[]; error?: string } | null>(null)
  const previewKey = awaitingTurn && !observedSample && turnIndex < nextTurn ? `${observedKey}:${selected?.current_repeat_index}` : null
  useEffect(() => {
    if (!previewKey || !selected) return
    let live = true
    const query = `?phase=burn&ccd_index=${ccd}&turn_index=${turnIndex}&repeat_index=${selected.current_repeat_index}&include_points=true`
    void api.acquisitionFrames(token, selected.id, query).then(frames => {
      if (live) setTurnPreview({ key: previewKey, points: frames.filter(frame => !frame.damaged).pop()?.points })
    }).catch(error => {
      if (live) setTurnPreview({ key: previewKey, error: error instanceof Error ? error.message : '读取本转角燃烧帧失败' })
    })
    return () => { live = false }
  }, [previewKey])
  useEffect(() => { setSampleId(null) }, [selected?.id])
  useEffect(() => { if (acquiring) setSampleId(null) }, [acquiring])
  const newestSampleId = completed[completed.length - 1]?.id
  useEffect(() => {
    if (!isPreheat && newestSampleId !== undefined && ['completed', 'between_repeats'].includes(selected?.status ?? '')) setSampleId(newestSampleId)
  }, [selected?.id, selected?.status, newestSampleId, isPreheat])
  useEffect(() => {
    generation.current++
    setBand(null); setError('')
    if (!observedSample) return
    let cancelled = false
    void api.acquisitionBands(token, observedSample.id, true).then(bands => {
      if (cancelled) return
      const next = bands.find(item => item.ccd_index === ccd && (!selected?.turns || item.turn_index === turnIndex))
      if (!next?.mean_points?.length) return setError('当前CCD没有已保存谱带')
      setBand({ key: observedKey, points: next.mean_points, sha256: next.mean_sha256 })
    }).catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : '读取已保存谱带失败') })
    return () => { cancelled = true; generation.current++ }
  }, [token, observedSample?.id, ccd, observedKey])
  // Keep the last burn trace while dark frames finish; warm-up has no formal mean band.
  useEffect(() => {
    if (selected?.sample_kind === 'preheat' && selected.burn_frames_captured > 0
      && selected.dark_frames_captured === 0 && liveCcd?.points?.length)
      setPreheatSpectrum({ key: preheatKey, points: liveCcd.points, sha256: liveCcd.points_sha256 })
  }, [selected?.sample_kind, selected?.burn_frames_captured, selected?.dark_frames_captured,
    liveCcd, preheatKey])
  useEffect(() => {
    if (!preheatComplete || !selected || preheatSpectrum?.key === preheatKey) return
    let cancelled = false
    setPreheatError(null)
    // Reopening a completed warm-up or changing CCD reconstructs the same observation from raw burn frames.
    void api.acquisitionFrames(token, selected.id, `?phase=burn&ccd_index=${ccd}&include_points=true`).then(frames => {
      if (cancelled) return
      const burnFrames = frames.filter(item => !item.damaged && item.points?.length)
      const frame = burnFrames[burnFrames.length - 1]
      if (!frame?.points) return setPreheatError({ key: preheatKey, message: '当前CCD没有可显示的预热燃烧帧' })
      setPreheatSpectrum({ key: preheatKey, points: frame.points, sha256: frame.points_sha256 ?? undefined })
    }).catch(failure => {
      if (!cancelled) setPreheatError({ key: preheatKey, message: failure instanceof Error ? failure.message : '读取预热谱图失败' })
    })
    return () => { cancelled = true }
  }, [preheatComplete, selected?.id, token, ccd, preheatKey, preheatSpectrum?.key])
  const observed = observedSample ? band?.key === observedKey ? band : null : null
  const preheat = preheatSpectrum?.key === preheatKey ? preheatSpectrum : null
  const preview = turnPreview?.key === previewKey ? turnPreview : null
  const points = measuring ? measurement.frame?.points ?? []
    : observedSample ? observed?.points ?? []
    : preheatComplete ? preheat?.points ?? (selected?.dark_frames_captured === 0 ? livePoints : []) : previewKey ? preview?.points ?? [] : livePoints
  const measurementMatchesPlot = !measuring || !measurement.scope || measurement.scope.ccd === ccd && measurement.scope.turn === turnIndex
  const displayError = preview?.error || (!observedSample && preheatComplete ? preheatError?.key === preheatKey ? preheatError.message : '' : error)
  const recordIndex = completed.findIndex(sample => sample.id === sampleId)
  const print = async (range: SpectrumViewRange) => {
    if (!selected || !observedSample || !observed || !canExport || printing || busy || acquiring) return
    const ticket = generation.current
    setPrinting(true)
    try {
      const recordId = `sample:${observedSample.id}`
      const result = await api.printSpectrumPdf(token, recordId, {
        print_scope: 'visible', print_layers: ['curve'], print_scale: 'fit_long', paper: 'A4',
        visible_x_min: range.xMin - 1, visible_x_max: range.xMax - 1, visible_y_min: range.yMin, visible_y_max: range.yMax,
        ccd: observedSample.bands.findIndex(item => item.ccd_index === ccd && (!selected.turns || item.turn_index === turnIndex)), line: 0, mode: 'mean', reference_shift: 0,
        selected_record_ids: [recordId], priority_record_id: recordId, frame_phase: 'burn', frame_index: 0
      })
      if (ticket !== generation.current) return
      const path = await saveFile(result.blob, `摄谱-${observedSample.sample_name || observedSample.id}-CCD${ccd + 1}.pdf`)
      if (ticket === generation.current) onToast(path ? `谱图PDF已保存：${path}` : '已取消保存')
    } catch (failure) {
      if (ticket === generation.current) onToast(failure instanceof Error ? failure.message : '打印谱图失败')
    } finally { setPrinting(false) }
  }
  return (
    <SpectroscopyConsole className="acquisition-monitor" inputToolbar={inputToolbar} sampleInput={sampleInput}
      monitoring={selected?.task_kind === 'sample' && !isPreheat && selected.monitoring &&
        <AcquisitionMonitoring key={selected.id} monitoring={selected.monitoring} enabled={enabled} intervene={intervene} />}
      topActions={measurementTask && <SpectroscopyToolButton icon="crosshair" label="测量观察" aria-pressed={measuring}
        description="查看已入库的新帧和谱线诊断，可慢进逐帧复核" onClick={() => { measurement.reset(); setMeasurementOpen(value => !value) }} />}
      turnPages={turnPages}
      bandTitle={formal?.task_kind === 'evaporation' ? '蒸发数据' : formal?.storage_mode === 'full_interval' ? '全时样品' : '均值样品'}
      showRepeats={selected?.task_kind !== 'evaporation'}
      context={isPreheat ? <>
        <span>预热观察（不生成正式谱带）</span>
        <button type="button" disabled={busy || !canFinish || !formal} onClick={onShowFormalTask}>返回正式任务</button>
      </> : angle !== undefined ? <span>{angle}°{turn?.key_band ? ' · 关键波段' : ''}
        {awaitingTurn ? ` · 等待 ${sampleTurns?.plan[nextTurn]?.angle_deg}° 摄谱` : sampleTurns?.multiple && canStart && readyAngle ? ' · 试样摄谱将连续采集' : ''}</span> : undefined}
      lineBar={captureLines.lineBar}
      recordTitle={selected?.task_kind === 'evaporation' ? '蒸发谱带名' : '样品编号'}
      recordValue={String(selected?.id ?? '')} recordChoices={selected ? [{ value: String(selected.id), name: selected.sample_name || selected.name }] : []}
      repeats={selected?.repeat_count}
      viewLabel={`${measuring ? '原始燃烧帧' : observedSample ? `已保存谱带 · ${observedSample.sample_name || '未命名'} / ${observedSample.repeat_index + 1}` : preheatComplete ? '预热燃烧谱图 · 仅观察' : '实时谱图'}${turn ? ` · ${turn.angle_deg}°` : ''}`}
      records={<CaptureBandList title={formal?.task_kind === 'evaporation' ? '蒸发谱带' : formal?.storage_mode === 'full_interval' ? '全时样品' : '均值样品'}
        variant={selected?.task_kind === 'evaporation' ? 'band' : 'sample'}
        emptyText={isPreheat ? '尚无正式谱带。预热仅供观察，不生成正式谱带。' : '当前任务没有已保存的正式谱带。'}
        rows={completed.map(sample => ({ id: sample.id, name: sample.sample_name || '未命名', sequence: sample.repeat_index + 1, detail: `重复 ${sample.repeat_index + 1} · ${selected?.turns?.multiple ? `${selected.turns.plan.length} 转角 · ` : ''}${new Set(sample.bands.map(band => band.ccd_index)).size} CCD` }))}
        selected={measuring ? null : observedSample?.id ?? null} disabled={busy || acquiring || isPreheat} onChoose={id => {
          setMeasurementOpen(false)
          measurement.reset()
          setSampleId(id)
        }} />}
      finish={{ run: finish, enabled: canFinish }} name={formal?.name ?? selected?.name} {...captureStatusInput(selected)}
      start={{ run: () => apply('start', startAngle), enabled: enabled && canStart && readyAngle,
        disabledReason: formalEnded ? '正式任务已结束，请新建任务后再摄谱' : !readyAngle ? '请先从当前待采转角开始' : undefined }}
      singleTurn={sampleTurns?.multiple || formal?.capture_turn?.multiple ? { run: () => apply('start', startAngle, true), enabled: enabled && canStart && readyAngle,
        disabledReason: !readyAngle ? '请先从当前待采转角开始' : undefined } : undefined}
      preheat={{ run: () => apply('preheat', sampleTurns ? turnIndex : undefined), enabled: enabled && canPreheat }}
      pause={{ run: () => apply('pause'), enabled: enabled && running && selected?.status !== 'between_repeats' && selected?.profile.transport !== 'serial', disabledReason: selected?.profile.transport === 'serial' ? '旧设备协议未提供暂停命令，请使用停止' : undefined }}
      resume={{ run: () => apply('resume'), enabled: enabled && selected?.status === 'paused' && !awaitingTurn
        && !selected.monitoring?.state.awaiting_intervention }}
      stop={{ run: () => apply('stop'), enabled: enabled && (retryStop || selected?.active_capture_id !== undefined
        || ['countdown', 'pre_excitation', 'burn', 'dark', 'paused', 'stopping', 'between_repeats'].includes(selected?.status ?? ''))
        && !selected?.monitoring?.state.awaiting_intervention }}
      progress={selected ? [
        { label: isPreheat ? '预热进度' : '总进度', value: progressLabel, current: selected.progress, maximum: 100 },
        { label: '当前阶段', value: selected.last_message || stateLabel[selected.status], title: selected.last_message || stateLabel[selected.status] },
        { label: '燃烧帧 / 暗帧', value: `${selected.burn_frames_captured}/${selected.burn_frame_count} · ${selected.dark_frames_captured}/${selected.dark_frame_count}` }
      ] : []}
      ccd={ccd} ccdIndices={selected?.ccd_indices ?? []} onCcdChange={setCcdIndex}
      hash={measuring ? measurement.frame?.frame_sha256 ?? undefined : observedSample ? observed?.sha256 : preheatComplete ? preheat?.sha256 : selected?.last_event?.details.sha256}>
      {detailDock => selected && <>
        {displayError && <p role="alert">{displayError}</p>}
        {measuring && <CaptureMeasurement observation={measurement} />}
        <SpectrumInspector fitPlot iconToolbar classic captureView key={`${selected.id}:${turnIndex}:${ccd}:${observedSample?.id ?? 'live'}`} points={points}
          markers={measurementMatchesPlot ? captureLines.markers : []} focusPoint={measurementMatchesPlot ? captureLines.focusPoint : null} focusRevision={captureLines.focusRevision}
          context={{ fixed, scope: `${selected.task_kind}:${selected.method_id}:${selected.method_version}:${turnIndex}:${ccd}`, pointDetails, detailDock,
            lineMenu: captureLines.lineMenu, chooseMarker: captureLines.chooseMarker }}
          ccdNavigation={{ current: ccd, indices: visibleCcds, choose: setCcdIndex }}
          label={measuring ? `CCD ${(measurement.scope?.ccd ?? ccd) + 1} 原始燃烧帧` : `CCD ${ccd + 1} ${previewKey ? '燃烧帧（本轮尚未完成）' : !observedSample && preheatComplete ? '预热燃烧谱图（仅观察）' : `${selected.task_kind === 'evaporation' ? '蒸发' : '样品'}${observedSample ? '已保存均值谱带' : '采集曲线'}`}${angle === undefined ? '' : ` · ${angle}°`}`}
          physicalScale={{ pointWidthUm: selected.layout.point_width_um, screenWidthMm: selected.profile.screen_width_mm, screenResolutionPx: selected.profile.screen_resolution_px }}
          bandNavigation={{ previous: () => setSampleId(completed[recordIndex - 1]?.id ?? null), next: () => setSampleId(completed[recordIndex + 1]?.id ?? null),
            canPrevious: !measuring && !busy && !acquiring && recordIndex > 0, canNext: !measuring && !busy && !acquiring && recordIndex < completed.length - 1 }}
          onPrint={canExport && !measuring ? range => void print(range) : undefined}
          printDisabledReason={measuring ? '切回已保存谱带后可打印' : printing ? '正在生成谱图PDF' : busy || acquiring ? '采集操作完成后可打印' : !observedSample ? '选择左侧已保存谱带后可打印' : !observed ? '等待已保存谱带读取完成' : undefined}
          emptyText={measurement.error || displayError || (measuring ? '等待已入库的原始燃烧帧…' : observedSample ? '正在读取已保存谱带…' : preheatComplete || previewKey ? '正在读取燃烧帧…' : '开始采集后显示实时 CCD 曲线')} />
      </>}
    </SpectroscopyConsole>
  )
}
