import { api, saveFile, type AcquisitionTask } from '../../api'
import type { DeviceCcd } from '../../api/devices'
import { SpectrumInspector, type SpectrumViewRange } from '../../components/SpectrumInspector'
import { stateLabel } from './acquisitionView'
import { SpectroscopyConsole } from './SpectroscopyConsole'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CaptureBandList } from './CaptureBandList'
import { SampleCaptureLineBar } from './CaptureLineBar'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  setup?: ReactNode
  token: string
  canExport: boolean
  canReadMethods: boolean
  onToast: (message: string) => void
  finish: () => void
  canFinish: boolean
  inputToolbar?: ReactNode
  sampleInput?: ReactNode
  selected: AcquisitionTask | null
  apply: (action: "start" | "preheat" | "pause" | "resume" | "stop") => Promise<void>
  busy: boolean
  canExecute: boolean
  canStart: boolean
  canPreheat: boolean
  progressLabel: string
  ccdIndex: number
  setCcdIndex: React.Dispatch<React.SetStateAction<number>>
  selectedCcd: DeviceCcd | undefined
  selectedPoints: number[]
  boundMethod: { method_id: number; method_version: number; name: string } | undefined
}

export function SampleAcquisitionMonitor({
  setup,
  token, canExport, canReadMethods, onToast, finish, canFinish, inputToolbar, sampleInput,
  selected,
  apply,
  busy,
  canExecute,
  canStart,
  canPreheat,
  progressLabel,
  ccdIndex,
  setCcdIndex,
  selectedCcd,
  selectedPoints,
  boundMethod,
}: PanelProps) {
  const running = Boolean(selected && ['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats'].includes(selected.status))
  const acquiring = Boolean(selected && ['countdown', 'pre_excitation', 'burn', 'dark', 'stopping'].includes(selected.status))
  const enabled = Boolean(selected && !busy && canExecute)
  const [sampleId, setSampleId] = useState<number | null>(null)
  const [recordLocked, setRecordLocked] = useState(false)
  const [band, setBand] = useState<{ key: string; points: number[]; sha256?: string } | null>(null)
  const [error, setError] = useState('')
  const [printing, setPrinting] = useState(false)
  const generation = useRef(0)
  const ccd = selected?.ccd_indices.includes(ccdIndex) ? ccdIndex : selected?.ccd_indices[0] ?? ccdIndex
  const completed = selected?.samples.filter(sample => sample.finalized && !sample.discarded && sample.status === 'completed') ?? []
  const observedSample = completed.find(sample => sample.id === sampleId)
  const observedKey = `${token}:${selected?.id}:${observedSample?.id}:${ccd}`
  useEffect(() => { setSampleId(null); setRecordLocked(false) }, [selected?.id])
  useEffect(() => { if (acquiring) { setSampleId(null); setRecordLocked(false) } }, [acquiring])
  const newestSampleId = completed[completed.length - 1]?.id
  useEffect(() => {
    if (newestSampleId !== undefined && ['completed', 'between_repeats'].includes(selected?.status ?? '')) setSampleId(newestSampleId)
  }, [selected?.id, selected?.status, newestSampleId])
  useEffect(() => {
    generation.current++
    setBand(null); setError('')
    if (!observedSample) return
    let cancelled = false
    void api.acquisitionBands(token, observedSample.id, true).then(bands => {
      if (cancelled) return
      const next = bands.find(item => item.ccd_index === ccd)
      if (!next?.mean_points?.length) return setError('当前CCD没有已保存谱带')
      setBand({ key: observedKey, points: next.mean_points, sha256: next.mean_sha256 })
    }).catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : '读取已保存谱带失败') })
    return () => { cancelled = true; generation.current++ }
  }, [token, observedSample?.id, ccd, observedKey])
  const observed = observedSample ? band?.key === observedKey ? band : null : null
  const points = observedSample ? observed?.points ?? [] : selectedPoints
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
        ccd: selected.ccd_indices.indexOf(ccd), line: 0, mode: 'mean', reference_shift: 0,
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
      bandTitle={selected?.task_kind === 'evaporation' ? '蒸发数据' : selected?.storage_mode === 'full_interval' ? '全时样品' : '均值样品'}
      showRepeats={selected?.task_kind !== 'evaporation'}
      canEditSample={completed.length > 0}
      lineBar={<SampleCaptureLineBar token={token} canReadMethods={canReadMethods} methodId={selected?.method_id ?? null}
        version={selected?.method_version ?? null} frames={selected?.burn_frame_count ?? 0} />}
      recordTitle={selected?.task_kind === 'evaporation' ? '蒸发谱带名' : '样品编号'}
      recordValue={String(selected?.id ?? '')} recordChoices={selected ? [{ value: String(selected.id), name: selected.sample_name || selected.name }] : []}
      repeats={selected?.repeat_count}
      viewLabel={observedSample ? `已保存谱带 · ${observedSample.sample_name || '未命名'} / ${observedSample.repeat_index + 1}` : '实时谱图'}
      records={<CaptureBandList title={selected?.task_kind === 'evaporation' ? '蒸发谱带' : selected?.storage_mode === 'full_interval' ? '全时样品' : '均值样品'}
        rows={completed.map(sample => ({ id: sample.id, name: sample.sample_name || '未命名', sequence: sample.repeat_index + 1, detail: `重复 ${sample.repeat_index + 1} · ${sample.bands.length} CCD` }))}
        selected={observedSample?.id ?? null} locked={recordLocked} disabled={busy || acquiring}
        onChoose={setSampleId} onLockChange={setRecordLocked} />}
      finish={{ run: finish, enabled: canFinish }} setup={<>
      {selected && <dl className="spectroscopy-task-summary" aria-label="当前任务条件">
        <div><dt>{selected.task_kind === 'evaporation' ? '保存模式' : '方法版本'}</dt>
          <dd>{selected.task_kind === 'evaporation' ? '全时原始区间'
            : `${boundMethod?.name ?? `方法 #${selected.method_id}`} · v${selected.method_version}`}</dd></div>
        {selected.task_kind === 'sample' && <div><dt>当前样号</dt><dd>{selected.sample_name || '采集后命名'}</dd></div>}
        <div><dt>重复次数</dt><dd>{selected.completed_repeats} / {selected.repeat_count}</dd></div>
        <div><dt>燃烧帧 / 暗帧</dt><dd>{selected.burn_frame_count} / {selected.dark_frame_count}</dd></div>
        <div><dt>预激时间 / 采样周期</dt><dd>{selected.pre_excitation_seconds}s / {selected.sampling_period_seconds}s</dd></div>
      </dl>}
      {setup}
    </>} name={selected?.name} status={selected?.status}
      statusLabel={selected ? stateLabel[selected.status] : undefined}
      source={selected?.profile.transport === 'simulator' ? '模拟设备 · 仅用于软件验证' : '真实设备 · 连接与协议状态以当前任务反馈为准'}
      start={{ run: () => apply('start'), enabled: enabled && canStart }}
      preheat={{ run: () => apply('preheat'), enabled: enabled && canPreheat }}
      pause={{ run: () => apply('pause'), enabled: enabled && running && selected?.status !== 'between_repeats' }}
      resume={{ run: () => apply('resume'), enabled: enabled && selected?.status === 'paused' }}
      stop={{ run: () => apply('stop'), enabled: enabled && ['countdown', 'pre_excitation', 'burn', 'dark', 'paused', 'stopping', 'between_repeats'].includes(selected?.status ?? '') }}
      progress={selected ? [
        { label: '总进度', value: progressLabel, current: selected.progress, maximum: 100 },
        { label: '当前阶段', value: selected.last_message || stateLabel[selected.status], title: selected.last_message || stateLabel[selected.status] },
        { label: '燃烧帧 / 暗帧', value: `${selected.burn_frames_captured}/${selected.burn_frame_count} · ${selected.dark_frames_captured}/${selected.dark_frame_count}` }
      ] : []}
      ccd={ccd} ccdIndices={selected?.ccd_indices ?? []} onCcdChange={setCcdIndex}
      hash={observedSample ? observed?.sha256 : selected?.last_event?.details.sha256}>
      {selected && <>
        {error && <p role="alert">{error}</p>}
        <SpectrumInspector fitPlot iconToolbar classic key={`${selected.id}:${ccd}:${observedSample?.id ?? 'live'}`} points={points}
          ccdNavigation={{ current: ccd, indices: selected.ccd_indices, choose: setCcdIndex }}
          label={`CCD ${ccd + 1} ${selected.task_kind === 'evaporation' ? '蒸发' : '样品'}${observedSample ? '已保存均值谱带' : '采集曲线'}`}
          physicalScale={{ pointWidthUm: selected.layout.point_width_um, screenWidthMm: selected.profile.screen_width_mm, screenResolutionPx: selected.profile.screen_resolution_px }}
          bandNavigation={{ previous: () => setSampleId(completed[recordIndex - 1]?.id ?? null), next: () => setSampleId(completed[recordIndex + 1]?.id ?? null),
            canPrevious: !busy && !acquiring && !recordLocked && recordIndex > 0, canNext: !busy && !acquiring && !recordLocked && recordIndex < completed.length - 1 }}
          onPrint={canExport ? range => void print(range) : undefined}
          printDisabledReason={printing ? '正在生成谱图PDF' : busy || acquiring ? '采集操作完成后可打印' : !observedSample ? '选择左侧已保存谱带后可打印' : !observed ? '等待已保存谱带读取完成' : undefined}
          emptyText={error || (observedSample ? '正在读取已保存谱带…' : '开始采集后显示实时 CCD 曲线')} />
          <div className="acquisition-facts">
            <div>
              <span>峰值 / 位置</span>
              <strong>
                {points.length ? `${Math.max(...points).toLocaleString('zh-CN', { maximumFractionDigits: 3 })} / ${points.indexOf(Math.max(...points)) + 1}` : '--'}
              </strong>
            </div>
            <div>
              <span>虚拟时间</span>
              <strong>
                {selected.last_event?.details.virtual_time_ms
                  ? `${Number(selected.last_event.details.virtual_time_ms).toFixed(0)} ms`
                  : '--'}
              </strong>
            </div>
            <div>
              <span>原始帧</span>
              <strong>{selected.samples.reduce((sum, item) => sum + item.bands.length, 0)} 个均值带</strong>
            </div>
            <div>
              <span>结果</span>
              <strong className={selected.status === 'completed' ? 'good' : ''}>
                {selected.result_sha256 ? '已收尾' : '未完成'}
              </strong>
            </div>
          </div>
      </>}
    </SpectroscopyConsole>
  )
}
