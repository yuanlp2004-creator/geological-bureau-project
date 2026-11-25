import { activeCaptureTask, captureActivity, checkCaptureShutdown, ensureCaptureConnection, prepareCaptureHandoff } from '../acquisition/captureConnection'
import { PageFileActions } from '../../components/PageFileActions'
import { RowSelectionArrow } from '../../components/RowSelectionArrow'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { confirmAction } from '../../platform/dialogs'
import {
  RefreshCw
} from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type DispersionLine,
  type DispersionOptions,
  type DispersionTask,
  type MethodRecord
} from '../../api'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { ExposureIntervalInput } from '../../components/ExposureIntervalInput'
import { TaskLayout } from '../../layout/TaskLayout'
import { DispersionCurveDialog } from './DispersionCurveDialog'
import { DispersionMonitor } from './DispersionMonitor'
import { DispersionSetup } from './DispersionSetup'
import { Props, runningStates, statusLabels } from './dispersionView'
import { useSpectroscopySession, type SpectroscopyMode } from '../acquisition/spectroscopySession'
import { SpectroscopyTaskDialog } from '../acquisition/SpectroscopyTaskDialog'
import { captureTaskPresentation, SpectroscopyTaskList } from '../acquisition/SpectroscopyTaskList'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { LegacyViewingDesk } from '../../components/LegacyViewingDesk'
import { CaptureLineBar } from '../acquisition/CaptureLineBar'
import { captureAngleName, CaptureTurnPages, groupedCaptureTasks, updateCaptureTask } from '../acquisition/CaptureTurnPages'
import { parseCcdCoordinate } from '../../components/legacyObservation'
import { ViewerDialog } from '../spectra/ViewerDialog'
import { ContextMenu, useContextMenu } from '../../components/ContextMenu'
import { spectralLineMenuGroups } from '../../components/spectrumMenu'
import { acquireHardwareOperation, hardwareLockStore, useHardwareOwner } from '../../stores/hardwareLockStore'
import type { HardwareOperation, OperationToken } from '../../stores/hardwareLockStoreCore'
import '../../components/legacy-viewing.css'

const owner = 'dispersion'

export function DispersionPage({ token, canWrite, canExecute, canReadMethods = true, canExport = false, onToast, actionsTarget, onCaptureChange, onCloseCurve, onViewSpectra, view = 'capture', visible = true }: Props & {
  canExport?: boolean
  actionsTarget?: HTMLElement | null
  onCaptureChange?: (mode: SpectroscopyMode, capture: boolean) => void
  canReadMethods?: boolean
  onCloseCurve?:()=>void
  onViewSpectra?: (group: string, recordId?: string) => void
  view?: 'capture' | 'curve'
  visible?: boolean
}) {
  const recovery = useMemo(() => ({ owner, read: async () => {
    for (let offset = 0; ; offset += 200) {
      const tasks = await api.dispersionTasks(token, 200, offset)
      const task = activeCaptureTask(tasks)
      if (task || tasks.length < 200) return captureActivity(task)
    }
  } }), [token])
  useHardwareOwner(token, owner, visible && view === 'capture', recovery)
  const [options, setOptions] = useState<DispersionOptions | null>(null)
  const [tasks, setTasks] = useState<DispersionTask[]>([])
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [active, setActive] = useState<DispersionTask | null>(null)
  const [screen, setScreen] = useState<'tasks' | 'capture'>('tasks')
  const [createOpen, setCreateOpen] = useState(false)
  const [processingOpen, setProcessingOpen] = useState(false)
  const [detailDock, setDetailDock] = useState<HTMLElement | null>(null)
  useEffect(() => setProcessingOpen(false), [active?.id])
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const fileMenu = useContextMenu<null>()
  const lineMenu = useContextMenu<{ taskId: number; lineId: number }>()
  const [prioritizeLine,setPrioritizeLine] = useState(true)
  const [createError, setCreateError] = useState<string | null>(null)
  useLayoutEffect(() => {
    onCaptureChange?.('dispersion', view === 'capture' && screen === 'capture')
  }, [view, screen, onCaptureChange])
  const [preSeconds, setPreSeconds] = useState(1)
  const [samplingPeriod, setSamplingPeriod] = useState(1)
  const [lockedPoint, setLockedPoint] = useState<number | null>(null)
  useEffect(() => { setLockedPoint(null) }, [active?.id])
  const [manualLine, setManualLine] = useState<number | null>(null)
  const [frameCount, setFrameCount] = useState(20)
  const [darkFrameCount, setDarkFrameCount] = useState(8)
  const defaultsLoaded = useRef(false)
  const [curveName, setCurveName] = useState('')
  const [saveExcitation, setSaveExcitation] = useState(false)
  const [selectedCcd, setSelectedCcd] = useState(0)
  const [targetPoint,setTargetPoint]=useState<{ccd:number;point:number}|null>(null)
  useEffect(()=>setTargetPoint(null),[active?.id])
  const [exposure, setExposure] = useState({ start: 1, end: 1 })
  const [showCurveLines,setShowCurveLines]=useState(true)
  const availableViewFrames = active?.condition.source_record_id ? active.frame_count : active?.burn_frames_captured ?? 0
  useEffect(() => { setExposure({ start: 1, end: Math.max(1, availableViewFrames) }) }, [active?.id])
  useEffect(() => {
    setManualLine(current => active?.lines.some(line => line.id === current && line.ccd_index === selectedCcd) ? current : null)
  }, [active?.id, active?.lines, selectedCcd])
  const [bindMethodId, setBindMethodId] = useState<number | null>(null)
  const [autoRun, setAutoRun] = useState(false)
  const [busy, setBusy] = useState(false)
  const runningTask = activeCaptureTask(tasks)
  const embedded = useSpectroscopySession('dispersion', runningTask
    ? `色散摄谱任务“${runningTask.name}”尚未结束，请完成或停止后切换摄谱方式。`
    : busy ? '色散摄谱操作尚未完成，请稍后切换摄谱方式。' : null)
  useEffect(() => {
    if (view !== 'capture' || !runningTask) return
    setActive(current => current?.id === runningTask.id ? current : runningTask)
    setScreen('capture')
    setCreateOpen(false)
  }, [runningTask, view, active?.id])

  const generation = useRef(0)
  const mounted = useRef(false)
  const operation = useRef<Promise<unknown> | null>(null)
  const stopIntent = useRef(false)
  const identity = useRef(token)
  identity.current = token
  const ticket = () => {
    const epoch = generation.current
    return () => mounted.current && generation.current === epoch && identity.current === token
  }
  useLayoutEffect(() => {
    mounted.current = true
    stopIntent.current = false
    return () => {
      mounted.current = false
      generation.current++
      stopIntent.current = true
    }
  }, [token])
  const applyTask = (task: DispersionTask) => {
    setActive(task)
    setTasks(items => updateCaptureTask(items, task))
  }
  const perform = async (work: (token: OperationToken | null) => Promise<DispersionTask | undefined>, message = '',
    command?: Omit<HardwareOperation, 'owner'>) => {
    if (operation.current) {
      onToast('上一操作仍在完成，请稍后重试')
      return
    }
    const hardware = command ? acquireHardwareOperation({ owner, ...command }, onToast) : null
    if (command && !hardware) return
    const observation = hardwareLockStore.observation(token)
    const handoff = hardwareLockStore.getSnapshot().status === 'connected_idle'
      && (command?.kind === 'capture_start' || command?.kind === 'capture_preheat') && formalTask?.profile.transport === 'serial'
    const valid = ticket()
    setBusy(true)
    const pending = work(hardware)
    operation.current = pending
    try {
      const task = await pending
      if (hardware && !hardwareLockStore.completeOperation(hardware, {
        capture: command?.kind === 'capture_create' ? undefined : captureActivity(task), portReleased: handoff
      })) return
      if (!task) return
      if (!valid()) return
      if (!hardware) hardwareLockStore.observeCapture(observation, owner, captureActivity(task), active?.active_capture_id ?? active?.id)
      applyTask(task)
      if (!runningStates.has(task.status)) setAutoRun(false)
      if (task.status === 'failed' && active?.status !== 'failed' && task.failure_message) onToast(task.failure_message)
      else if (message) onToast(message)
      return task
    } catch (error) {
      if (hardware) hardwareLockStore.failOperation(hardware, error, recovery)
      else if (valid()) hardwareLockStore.observeFailure(token, observation, error, recovery)
      if (valid()) {
        setAutoRun(false)
        onToast(error instanceof Error ? error.message : '色散操作失败')
      }
    } finally {
      if (operation.current === pending) operation.current = null
      if (valid()) setBusy(false)
    }
  }
  const choose = async (id: number, checkConnection = true) => {
    if (operation.current) return
    const known = tasks.find(task => task.id === id)
    const hardware = acquireHardwareOperation({ owner, kind: 'capture_choose', taskId: id,
      profileId: checkConnection && view !== 'curve' && known?.status === 'draft' && !known.position_controlled
        ? known.device_profile_id : undefined }, onToast)
    if (!hardware) return
    generation.current++
    stopIntent.current = true
    setAutoRun(false)
    setBusy(true)
    const valid = ticket()
    try {
      const fresh = await api.dispersionTask(token, id)
      if (hardwareLockStore.owns(hardware) && checkConnection && view !== 'curve'
        && !fresh.position_controlled && ['draft','ready'].includes(fresh.status))
        await ensureCaptureConnection(token, fresh.device_profile_id, fresh.profile.transport, 'dispersion', hardware)
      if (!hardwareLockStore.completeOperation(hardware, { capture: captureActivity(fresh) ?? undefined })) return
      if (valid()) {
        setSelectedCcd(current => fresh.ccd_indices.includes(current) ? current : fresh.ccd_indices[0] ?? 0)
        applyTask(fresh)
        if (view !== 'curve') setScreen('capture')
      }
    } catch (error) {
      hardwareLockStore.failOperation(hardware, error, recovery)
      if (valid()) onToast(error instanceof Error ? error.message : '读取任务失败')
    } finally { if (valid()) setBusy(false) }
  }
  const loadRequest = useRef(0)
  const load = useCallback(async () => {
    const observation = hardwareLockStore.observation(token)
    const current = ticket(),
      requestId = ++loadRequest.current
    const valid = () => current() && requestId === loadRequest.current
    setBusy(true)
    try {
      const [nextOptions, nextTasks, nextMethods] = await Promise.all([
        api.dispersionOptions(token),
        (async () => {
          const tasks: DispersionTask[] = []
          for (let offset = 0; ; offset += 200) {
            const page = await api.dispersionTasks(token, 200, offset)
            tasks.push(...page)
            if (page.length < 200) return tasks
          }
        })(),
        view === 'curve' && canReadMethods ? api.methods(token) : Promise.resolve([])
      ])
      if (!valid()) return
      hardwareLockStore.observeCapture(observation, owner, captureActivity(activeCaptureTask(nextTasks)))
      if (!defaultsLoaded.current && nextOptions.preliminary_defaults) {
        defaultsLoaded.current = true
        const saved = nextOptions.preliminary_defaults
        setPreSeconds(saved.pre_excitation_seconds); setSamplingPeriod(saved.sampling_period_seconds)
        setFrameCount(saved.frame_count); setDarkFrameCount(saved.dark_frame_count)
      }
      setOptions(nextOptions)
      const visibleTasks = view === 'curve' ? nextTasks.filter((task) => !task.condition.preheat) : nextTasks
      setTasks(visibleTasks)
      setActive((current) =>
        current ? (visibleTasks.find((item) => item.id === current.id) ?? visibleTasks[0] ?? null) : (visibleTasks[0] ?? null)
      )
      setMethods(nextMethods.filter((item) => item.current_version !== null && item.status !== 'deleted'))
      setBindMethodId((current) => current ?? nextMethods.find((item) => item.current_version !== null)?.id ?? null)
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '无法读取色散任务')
    } finally {
      if (valid()) setBusy(false)
    }
  }, [canReadMethods, onToast, token, view])

  const deleteTask = async (id: number) => {
    const task = tasks.find(item => item.id === id)
    if (!task || !canWrite || busy || operation.current || runningTask) throw new Error('当前色散任务无法删除')
    setBusy(true)
    try {
      await api.deleteDispersionTask(token, id)
      const removed = new Set([id, ...(task.capture_turns?.map(turn => turn.id) ?? [])])
      setTasks(current => current.filter(item => !removed.has(item.id)))
      setActive(current => current && removed.has(current.id) ? null : current)
      onToast('色散摄谱任务已删除')
      await load()
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    if (!active || !active.ccd_indices.includes(selectedCcd)) setSelectedCcd(active?.ccd_indices[0] ?? 0)
  }, [active, selectedCcd])
  useEffect(() => {
    if (!visible || view !== 'capture' || !active || busy) return
    const remote = active.active_capture_id !== undefined || active.profile.transport === 'serial' && runningStates.has(active.status)
    if (!remote && (!autoRun || !runningStates.has(active.status) || stopIntent.current)) return
    const timer = window.setTimeout(() => {
      if (remote) void perform(async () => {
        const fresh = await api.dispersionTask(token, active.id)
        return fresh.active_capture_id !== undefined && fresh.active_capture_id !== fresh.id
          ? api.dispersionTask(token, fresh.active_capture_id) : fresh
      })
      else if (!stopIntent.current && hardwareLockStore.getSnapshot().status === 'capturing')
        void perform(() => api.stepDispersionTask(token, active.id))
    }, remote ? 250 : 850)
    return () => window.clearTimeout(timer)
  }, [active, autoRun, busy, token, view, visible])

  const currentCcd =
    active?.last_event?.ccds.find((item) => item.ccd_index === selectedCcd) ?? active?.last_event?.ccds[0]
  const latestCalibration = active?.calibrations.find(item => item.state === 'published' && !item.archived) ?? null

  const openCreate = async () => {
    if (!defaultsLoaded.current) {
      setBusy(true)
      try {
        const fresh = await api.dispersionOptions(token)
        setOptions(fresh)
        const saved = fresh.preliminary_defaults
        if (saved) { setPreSeconds(saved.pre_excitation_seconds); setSamplingPeriod(saved.sampling_period_seconds); setFrameCount(saved.frame_count); setDarkFrameCount(saved.dark_frame_count) }
        defaultsLoaded.current = true
      } catch (error) { onToast(error instanceof Error ? error.message : '读取色散激发条件失败'); return }
      finally { setBusy(false) }
    }
    if (!curveName) {
      const now = new Date()
      setCurveName(`${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}`)
    }
    setCreateError(null); setCreateOpen(true)
  }
  const createTask = async () => {
    if (runningTask) return onToast('当前任务尚未结束，请先完成或停止摄谱')
    if (!canWrite || busy || !curveName.trim()) return
    if (!reportInvalidNumericInput(document.querySelector('.dispersion-setup'))) return onToast('请先修正采集参数')
    setCreateError(null)
    const created = await perform(async hardware => {
      try {
        if (!hardware) return
        await prepareCaptureHandoff(token, hardware, 'dispersion', canReadMethods)
        if (!hardwareLockStore.owns(hardware)) return
        return await api.createDispersionSession(token, { name: curveName, frame_count: frameCount,
        dark_frame_count: darkFrameCount, pre_excitation_seconds: preSeconds,
        sampling_period_seconds: samplingPeriod, save_conditions: saveExcitation })
      }
      catch (error) { setCreateError(error instanceof Error ? error.message : '创建色散摄谱失败'); throw error }
    }, '色散任务已创建', { kind: 'capture_create' })
    if (created) { defaultsLoaded.current = false; setSaveExcitation(false); setCurveName(''); setCreateOpen(false); setScreen('capture') }
  }
  const formalTask = active?.condition.preheat
    ? tasks.find((task) => task.id === active.condition.preheat_source_task_id) : active
  const sourceKey = (task: DispersionTask) => String(task.condition.source_sha256 ?? 'native')
  const bandName = (task: DispersionTask) => options?.legacy_sources
    ?.find(source => source.id === Number(task.condition.source_record_id))?.band_name ?? captureAngleName(task)
  const savedBands = tasks.filter(task => task.status === 'completed' && !task.condition.preheat
    && sourceKey(task) === (formalTask ? sourceKey(formalTask) : 'native'))
    .sort((a, b) => Number(a.condition.source_record_id ?? a.id) - Number(b.condition.source_record_id ?? b.id))
    .map(task => ({ id: task.id, name: bandName(task) }))
  const turnPages = active?.capture_turn && <CaptureTurnPages current={active.capture_turn.turn_index}
    pages={(active.capture_turns ?? []).map(item => ({ ...item, state: statusLabels[item.status as DispersionTask['status']] ?? item.status }))}
    disabled={busy || Boolean(runningTask)} choose={index => {
      const page = active.capture_turns?.find(item => item.turn_index === index)
      if (page && !busy && !runningTask) void choose(page.id, false)
    }} />
  const start = async (singleTurn = false) => {
    if (!formalTask || formalTask.condition.preheat || formalTask.status !== 'draft' || !canExecute || busy || runningTask) return
    stopIntent.current = false
    const next = await perform(() => api.startDispersionTask(token, formalTask.id, !singleTurn && formalTask.capture_turn?.multiple),
      singleTurn ? '本转角摄谱已开始' : '试样摄谱已开始',
      { kind: 'capture_start', taskId: formalTask.id, profileId: formalTask.device_profile_id })
    if (next && !stopIntent.current) setAutoRun(true)
  }
  const preheat = async () => {
    if (!formalTask || formalTask.condition.preheat || !canExecute || !canWrite || busy || runningTask) return
    stopIntent.current = false
    const next = await perform(() => api.preheatDispersionTask(token, formalTask.id), '预热摄谱已开始',
      { kind: 'capture_preheat', taskId: formalTask.id, profileId: formalTask.device_profile_id })
    if (next && !stopIntent.current) setAutoRun(true)
  }
  const resume = async () => {
    if (!active || !canExecute) return
    stopIntent.current = false
    const next = await perform(() => api.resumeDispersionTask(token, active.id), '采集已继续',
      { kind: 'capture_resume', taskId: active.active_capture_id ?? active.id, profileId: active.device_profile_id })
    if (next && !stopIntent.current) setAutoRun(true)
  }
  const halt = async (mode: 'pause' | 'stop') => {
    if (!active || !canExecute) return
    const taskId = active.id,
      valid = ticket()
    const hardware = acquireHardwareOperation({ owner, kind: `capture_${mode}`, taskId: active.active_capture_id ?? taskId,
      profileId: active.device_profile_id }, onToast)
    if (!hardware) return
    stopIntent.current = true
    setAutoRun(false)
    // Preserve this explicit command even when a frame is still awaiting a response.
    await operation.current?.catch(() => { })
    try {
      if (!hardwareLockStore.owns(hardware)) { hardwareLockStore.completeOperation(hardware); return }
      const task = await (mode === 'stop' ? api.stopDispersionTask : api.pauseDispersionTask)(token, taskId)
      checkCaptureShutdown(task)
      if (!hardwareLockStore.completeOperation(hardware, { capture: captureActivity(task) })) return
      if (valid()) {
        applyTask(task)
        onToast(mode === 'stop' ? task.active_capture_id ? '已发出停止请求' : '采集已停止' : '采集已暂停')
      }
    } catch (error) {
      hardwareLockStore.failOperation(hardware, error, recovery)
      if (valid()) onToast(error instanceof Error ? error.message : '停止操作失败，请重试')
    }
  }
  const pause = () => halt('pause')
  const stop = () => halt('stop')
  const change = (work: (id: number) => Promise<unknown>, message = '') => {
    if (!active || !canWrite || busy || runningTask || active.condition.preheat) return
    const id = active.id
    return perform(async () => {
      await work(id)
      return api.dispersionTask(token, id)
    }, message)
  }
  const addPoint = () => {
    if (lockedPoint === null) return
    return change(async id => {
      const line=await api.addDispersionPoint(token,id,selectedCcd,lockedPoint)
      setManualLine(line.id)
    }, '谱线已增加，请在拟合窗口填写已知波长')
  }
  const locateCoordinate = async (value:string) => {
    if (!active || busy || runningTask) return
    const valid=ticket()
    try {
      const parsed=parseCcdCoordinate(value)
      const coordinate=parsed ? {ccd_index:parsed.ccd,point_index:parsed.point}
        : /^\d+(?:\.\d+)?$/.test(value.trim()) && Number(value)>0
          ? await api.dispersionCoordinate(token,active.id,Number(value)) : null
      if (!valid()) return
      if (!coordinate || !active.ccd_indices.includes(coordinate.ccd_index) || coordinate.point_index>=active.layout.points_per_ccd)
        return onToast('请输入有效波长或 CCD,点位（均从1起），且应在当前谱带范围内')
      setManualLine(null);setSelectedCcd(coordinate.ccd_index)
      setTargetPoint({ccd:coordinate.ccd_index,point:coordinate.point_index})
    } catch(error) {if(valid())onToast(error instanceof Error?error.message:'谱线定位失败')}
  }
  const updateLine = (line: DispersionLine, action: 'locate' | 'short' | 'long' | 'save' | 'restore') =>
    change((id) =>
      action === 'locate'
        ? api.locateDispersionLine(token, id, line.id)
        : action === 'short' || action === 'long'
          ? api.moveDispersionLine(token, id, line.id, action)
          : action === 'save'
            ? api.saveDispersionLinePosition(token, id, line.id)
            : api.restoreDispersionLinePosition(token, id, line.id)
    )
  const locateAll = () => change(async id => {
    const result = await api.locateAllDispersionLines(token, id, true)
    onToast(result.all_succeeded ? `已定位 ${result.located.length} 条谱线` :
      `定位完成：${result.located.length} 条成功，${result.errors.length} 条失败；失败谱线位置未改变。${result.errors[0]?.message ?? ''}`)
  })
  const removeLine = (lineId: number) => change(async id => {await api.deleteDispersionLine(token,id,lineId);setManualLine(null)}, '谱线已删除')
  const bind = () => {
    if (!latestCalibration || bindMethodId === null) return
    const method = methods.find((item) => item.id === bindMethodId)
    return change(
      () =>
        api.bindDispersionCalibration(token, latestCalibration.id, bindMethodId, method?.current_version ?? undefined),
      '色散曲线版本已绑定'
    )
  }

  const lineActions = active && <>
    <SpectroscopyToolButton icon="add-line" label="增加谱线" description="先在谱图上单击选点，再增加该点位的谱线；波长在拟合窗口填写"
      disabled={Boolean(active.condition.preheat)||!canWrite||busy||Boolean(runningTask)||lockedPoint===null} onClick={()=>void addPoint()}/>
    <SpectroscopyToolButton icon="delete-line" label="删除谱线" disabled={Boolean(active.condition.preheat)||!canWrite||busy||Boolean(runningTask)||manualLine===null}
      onClick={()=>{if(manualLine!==null)void removeLine(manualLine)}}/>
  </>
  const curveActions = active && <div className="inspector-workflow-tools" role="group" aria-label="色散谱线操作">
    <SpectroscopyToolButton icon="line-correction" label="校正谱线" description="在固定搜索范围内寻峰；无有效峰时保留原位置，人工移动后重新确定范围"
      disabled={Boolean(active.condition.preheat)||!canWrite||busy||Boolean(runningTask)||!active.lines.length||!active.burn_frames_captured} onClick={()=>void locateAll()}/>
    <SpectroscopyToolButton icon="fit-curve" label="拟合曲线" description="打开波长、CCD间隔及拟合窗口；使用 4–8 个有效定位点，通常使用 6 个"
      disabled={!canWrite||Boolean(active.condition.preheat)||busy||Boolean(runningTask)||!active.lines.length} onClick={()=>setProcessingOpen(true)} aria-pressed={processingOpen}/>

  </div>
  const focusedLine=active?.lines.find(line=>line.id===manualLine&&line.ccd_index===selectedCcd)
  const focusPoint=focusedLine && prioritizeLine ? focusedLine.located_position??focusedLine.expected_position : targetPoint?.ccd===selectedCcd?targetPoint.point:null
  const monitor = <DispersionMonitor detailDock={view === 'curve' ? detailDock : null} focusPoint={focusPoint} locate={value=>void locateCoordinate(value)} onToast={onToast} recordNumber={options?.legacy_sources?.find(source=>source.id===Number(active?.condition.source_record_id))?.band_id??active?.id} displayName={options?.legacy_sources?.find(source=>source.id===Number(active?.condition.source_record_id))?.band_name||active?.name} view={view} exposure={exposure} active={active} start={start} preheat={preheat}
            formalTask={formalTask} turnPages={turnPages} savedBands={savedBands}
            onShowFormalTask={() => { if (formalTask && !busy && !runningTask) void choose(formalTask.id, false) }}
            recordChoices={tasks.filter(task => view === 'curve' || !task.condition.preheat).map(task => ({ value: String(task.id), name: bandName(task) }))}
            recordDisabled={busy || Boolean(runningTask)} onRecordChoose={value => {
              if (!busy && !runningTask) { const task = tasks.find(task => String(task.id) === value); if (task) void choose(task.id) }
            }}
            finish={() => setScreen('tasks')} canFinish={!busy && !runningTask}
            lineEditToolbar={lineActions}
            workflowToolbar={curveActions}
            canStart={!runningTask && Boolean(formalTask && !formalTask.condition.preheat && formalTask.status === 'draft')}
            canPreheat={canWrite && !runningTask && Boolean(formalTask && ['draft', 'completed', 'failed', 'stopped'].includes(formalTask.status))}
            canExecute={canExecute && (!runningTask || active?.id === runningTask.id)} pause={pause} resume={resume}
            busy={busy} stop={stop} selectedCcd={selectedCcd} setSelectedCcd={setSelectedCcd}
            currentCcd={currentCcd} manualLine={manualLine} setManualLine={setManualLine}
            token={token} canExport={canExport} setLockedPoint={setLockedPoint}
            />

  const openLineMenu = (event: React.MouseEvent) => {
    const target = event.target as Element
    const marker = target.closest('[data-marker-key]') as HTMLElement | null
    const row = target.closest('[data-line-id]') as HTMLElement | null
    if (!marker && !row) return
    const identifier = Number(marker?.getAttribute('data-marker-key')?.split('-')[0] ?? row?.dataset.lineId)
    const line = active?.lines.find(line => line.id === identifier)
    if (!active || !line) return
    setManualLine(line.id);setSelectedCcd(line.ccd_index)
    lineMenu.open(event, { taskId: active.id, lineId: line.id })
  }
  const moveKey = (event: React.KeyboardEvent) => {
    if (!event.ctrlKey || !['ArrowLeft','ArrowRight'].includes(event.key) || processingOpen || (event.target as Element).closest('input,select,textarea,dialog')) return
    const line = active?.lines.find(line => line.id === manualLine)
    if (line) {event.preventDefault();void updateLine(line,event.key === 'ArrowLeft' ? 'short' : 'long')}
  }
  const orderedLines = active?.legacy_lines?.map(row=>active.lines.find(line=>line.id===row.line_id)!).filter(Boolean) ?? active?.lines ?? []
  const menuLine = orderedLines.find(line => line.id === lineMenu.target?.data.lineId)
  const lineWriteDisabled = !canWrite || busy || Boolean(runningTask || active?.condition.preheat)
  const positionMenu = lineMenu.target && menuLine && active?.id === lineMenu.target.data.taskId &&
    <ContextMenu target={lineMenu.target} close={lineMenu.close} label="谱线位置菜单"
      groups={spectralLineMenuGroups(orderedLines, menuLine, line => { setManualLine(line.id); setSelectedCcd(line.ccd_index) },
        { label: '优先显示', checked: prioritizeLine, run: () => setPrioritizeLine(value => !value) },
        [{ label: '删除谱线', disabled: lineWriteDisabled, run: () => void removeLine(menuLine.id) }], [
          { label: '还原实际位置', disabled: lineWriteDisabled || menuLine.saved_position == null, run: () => void updateLine(menuLine, 'restore') },
          ...(['restore', 'save'] as const).map(action => ({ label: action === 'save' ? '保存全部位置' : '还原全部位置',
            disabled: lineWriteDisabled, run: () => void change(id => api.allDispersionPositions(token, id, action), action === 'save' ? '全部位置已保存' : '全部位置已还原') }))
        ])} />
  const fileActions = <PageFileActions target={actionsTarget}>
        {view === 'curve' && <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="dispersion" label="打开色散文件" disabled={busy || Boolean(runningTask)} onOpened={async result => {
        await load()
        if (result.task_ids?.[0]) await choose(result.task_ids[0])
      }}/>}
        <button className="secondary-button" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={15} className={busy ? 'spin' : ''} />
          刷新
        </button>
      </PageFileActions>

  if (view === 'capture') return <div className={`${embedded ? 'spectroscopy-mode-content' : 'page-content'} dispersion-page refined-page remaining-page`}
    data-testid="dispersion-page" data-view={view} data-stage={screen} onContextMenuCapture={openLineMenu} onKeyDown={moveKey}>
    {positionMenu}
    <PageFileActions target={actionsTarget}>
      {screen === 'capture' ? <button type="button" className="secondary-button" disabled={busy || Boolean(runningTask)}
        onClick={() => { if (!runningTask && !busy) setScreen('tasks') }}>返回任务列表</button> : <>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={15} />刷新</button>
        <button type="button" className="primary-button" disabled={!canWrite || busy || Boolean(runningTask)}
          onClick={openCreate}>新建任务</button>
      </>}
    </PageFileActions>
    <SpectroscopyTaskDialog open={createOpen} title="色散曲线摄谱" busy={busy} error={createError} onCancel={() => setCreateOpen(false)}
      actions={<button type="button" className="primary-button" disabled={!canWrite || busy || !curveName.trim()}
        onClick={() => void createTask()}>确定</button>}>
      <DispersionSetup name={curveName} onName={setCurveName} disabled={!canWrite || busy || Boolean(runningTask)}
        saveConditions={saveExcitation} onSaveConditions={setSaveExcitation}
        conditions={{ pre_excitation_seconds: preSeconds, sampling_period_seconds: samplingPeriod, frame_count: frameCount, dark_frame_count: darkFrameCount }}
        onCondition={(key, value) => { if (key === 'pre_excitation_seconds') setPreSeconds(value); else if (key === 'sampling_period_seconds') setSamplingPeriod(value); else if (key === 'frame_count') setFrameCount(value); else setDarkFrameCount(value) }} />
    </SpectroscopyTaskDialog>
    {screen === 'tasks' && <SpectroscopyTaskList title="色散摄谱" busy={busy} runningId={runningTask?.id}
      tasks={groupedCaptureTasks(tasks.filter(task => !task.capture_turn?.group || !task.condition.preheat)).map(task => ({ id: task.id, name: task.name,
        ...captureTaskPresentation(task, `${task.layout.name} · ${task.burn_frames_captured}/${task.frame_count} 燃烧帧${task.condition.preheat ? ' · 预热' : ''}`, tasks),
        completed: task.capture_turns?.length ? task.capture_turns.every(turn => turn.status === 'completed') : task.status === 'completed' }))}
      onView={onViewSpectra ? id => {
        const task = tasks.find(item => item.id === id)
        if (!task) return
        const { source_record_id, source_sha256 } = task.condition
        if (source_record_id && source_sha256) {
          onViewSpectra(`raw:${source_sha256}`, `raw:${source_record_id}`)
        } else {
          const turn = task.capture_turn
          onViewSpectra(`dispersion:${turn?.multiple && turn.group ? turn.group : task.id}`)
        }
      } : undefined}
      onDelete={canWrite ? deleteTask : undefined}
      onChoose={id => {
        const task = tasks.find(item => item.id === id)
        if (task && !busy && (!runningTask || runningTask.id === id)) { void choose(task.id) }
      }} />}
    <main className="dispersion-main spectroscopy-capture-page" data-capture-screen hidden={screen !== 'capture'}>{monitor}
      {processingOpen && active && !active.condition.preheat && <DispersionCurveDialog key={active.id} active={active} token={token} busy={busy}
        canWrite={canWrite && !runningTask} gapLimits={options?.gap_limits_um ?? [9659,9959]} curves={options?.calibration_versions ?? []} change={change} onClose={() => setProcessingOpen(false)} />}

    </main>
  </div>

  if(view === 'curve') {
    const key=active ? sourceKey(active) : sourceKey(tasks[0] ?? {condition:{}} as DispersionTask)
    const visible=tasks.filter(task => !task.condition.preheat && sourceKey(task)===key).sort((a,b)=>Number(a.condition.source_record_id??a.id)-Number(b.condition.source_record_id??b.id))
    const groups=Array.from(new Set(tasks.filter(task=>!task.condition.preheat).map(sourceKey)))
    const fileSelectionDisabled = busy || Boolean(runningTask)
    const openFileMenu = (event: React.MouseEvent) => fileMenu.open(event, null)
    return <div className="dispersion-page legacy-viewing-page" data-testid="dispersion-page" data-view="curve" onContextMenuCapture={openLineMenu} onKeyDown={moveKey}>
      {positionMenu}
      {fileActions}
      {fileMenu.target && <ContextMenu target={fileMenu.target} close={fileMenu.close} label="色散文件菜单" groups={[[
        { label: '选择色散文件', disabled: fileSelectionDisabled, run: () => setFilesOpen(true) },
        { label: '色散曲线版本管理', disabled: fileSelectionDisabled || !active, run: () => setVersionsOpen(true) },
        ...(!showCurveLines ? [{ label: '显示色散谱线列表', run: () => setShowCurveLines(true) }] : [])
      ]]} />}
      <LegacyViewingDesk>
        <div className="legacy-view-top" role="toolbar" aria-label="色散谱线操作栏">
          {lineActions}<CaptureLineBar locate={value=>void locateCoordinate(value)} lines={active?.lines.map(line=>({id:String(line.id),label:`${line.element} ${line.wavelength_nm || "待填波长"}`,wavelength:line.wavelength_nm}))}
            value={manualLine===null?'':String(manualLine)} disabled={busy} choose={id=>{const line=active?.lines.find(line=>String(line.id)===id);setManualLine(line?.id??null);if(line)setSelectedCcd(line.ccd_index)}}
            exposureInput={<ExposureIntervalInput key={active?.id} {...exposure} max={availableViewFrames}
              disabled={busy||Boolean(runningTask)||availableViewFrames===0} onCommit={(start, end) => setExposure({ start, end })}/>}/>
          {curveActions}
          <span className="legacy-toolbar-separator" aria-hidden="true"/>
          <SpectroscopyToolButton icon="finish" label="关闭色散曲线" disabled={!onCloseCurve||busy||Boolean(runningTask)} onClick={onCloseCurve}/>
        </div>
        <div className={`legacy-view-body${showCurveLines?' has-line-rail':''}`}>
          <aside className="legacy-view-rail dispersion-sidebar" aria-label="色散文件" tabIndex={0} onContextMenu={openFileMenu}><header><h2>色散文件</h2></header>
            <div className="legacy-view-table-wrap dispersion-task-list"><table className="legacy-view-table"><thead><tr><th className="row-indicator"/><th>谱带名称</th></tr></thead><tbody>
              {visible.map(task=><tr key={task.id} aria-selected={active?.id===task.id}><td className="row-indicator">{active?.id===task.id&&<RowSelectionArrow />}</td><td>
                <button disabled={busy || Boolean(runningTask && runningTask.id!==task.id)} onClick={()=>void choose(task.id)} title={bandName(task)}>{bandName(task)}</button></td></tr>)}
            </tbody></table></div><div className="legacy-view-footer">{(options?.legacy_sources?.find(source=>source.id===Number(active?.condition.source_record_id))?.measure_time||active?.updated_at)?.replace('T',' ').slice(0,19)??'尚未选择谱带'}</div>
          </aside>
          {monitor}
          {showCurveLines && <aside className="legacy-view-rail right spectrum-point-rail" ref={setDetailDock}><header><h2>色散谱线列表</h2><button aria-label="隐藏色散谱线列表" onClick={()=>setShowCurveLines(false)}>×</button></header>
            <div className="legacy-view-table-wrap"><table className="legacy-view-table"><thead><tr><th>谱线 / 波长</th><th>实际点位</th></tr></thead><tbody>
              {active?.lines.map(line=><tr key={line.id} data-line-id={line.id} aria-selected={manualLine===line.id}><td><button onClick={()=>{setManualLine(line.id);setSelectedCcd(line.ccd_index)}}>{line.element} {line.wavelength_nm || "待填波长"}</button></td>
                <td>{line.located_position?.toFixed(2)??'未定位'}</td></tr>)}
            </tbody></table></div>
          </aside>}
        </div>
      </LegacyViewingDesk>
      {filesOpen && <ViewerDialog title="选择色散文件" onClose={() => setFilesOpen(false)}>
        <div className="viewer-dialog-fields"><label>色散文件<select aria-label="色散数据文件" value={key} disabled={fileSelectionDisabled} onChange={event=>{
          const task=tasks.find(task=>!task.condition.preheat&&sourceKey(task)===event.target.value)
          if(task){setFilesOpen(false);void choose(task.id)}
        }}>
          {!groups.length&&<option value="">尚无色散文件</option>}
          {groups.map(group=><option value={group} key={group}>{group==='native'?'本机色散采集':options?.legacy_sources?.find(source=>source.source_sha256===group)?.source_filename||`WDT · ${group.slice(0,12)}`}</option>)}
        </select></label></div>
      </ViewerDialog>}
      {processingOpen && active && <DispersionCurveDialog key={active.id} active={active} token={token} busy={busy}
        canWrite={canWrite && !runningTask} gapLimits={options?.gap_limits_um ?? [9659,9959]} curves={options?.calibration_versions ?? []} change={change} onClose={() => setProcessingOpen(false)} />}
      {versionsOpen && <ViewerDialog title="色散曲线版本管理" onClose={() => setVersionsOpen(false)}>
      <details className="surface spectroscopy-calibration-versions observation-details"><summary>色散曲线版本管理</summary>
        <h2>色散曲线版本管理</h2>
        {active?.calibrations.map((calibration) => (
          <div key={calibration.id}>
            <span>
              {calibration.display_name || calibration.name} · v{calibration.version} ·{' '}
              {calibration.archived ? '已归档' : calibration.state}
            </span>
            <button
              disabled={!canWrite || busy}
              onClick={() => {
                const name = window.prompt('色散曲线显示名称', calibration.display_name || calibration.name)
                if (name)
                  void change(
                    () => api.manageDispersionCalibration(token, calibration.id, 'rename', name),
                    '名称已更新'
                  )
              }}
            >
              重命名
            </button>
            <button
              disabled={!canWrite || busy}
              onClick={() =>
                void change(
                  () =>
                    api.manageDispersionCalibration(
                      token,
                      calibration.id,
                      calibration.archived ? 'restore' : 'archive'
                    ),
                  '归档状态已更新'
                )
              }
            >
              {calibration.archived ? '恢复' : '归档'}
            </button>
            {calibration.state === 'draft' && (
              <button
                disabled={!canWrite || busy}
                onClick={async () => {
                  if (await confirmAction('删除此未发布色散曲线草稿？'))
                    void change(() => api.manageDispersionCalibration(token, calibration.id, 'delete'), '草稿已删除')
                }}
              >
                删除草稿
              </button>
            )}
          </div>
        ))}
      </details>
      {latestCalibration && <div className="dispersion-bind"><label className="field"><span>绑定已发布方法版本</span>
        <select aria-label="绑定已发布方法版本" value={bindMethodId ?? ''} onChange={event => setBindMethodId(Number(event.target.value))}>
          {methods.map(method => <option key={method.id} value={method.id}>{method.name} · v{method.current_version}</option>)}
        </select></label><button disabled={!canWrite || busy || bindMethodId === null} onClick={() => void bind()}>绑定修订</button></div>}
      </ViewerDialog>}

    </div>
  }

  return null
}
