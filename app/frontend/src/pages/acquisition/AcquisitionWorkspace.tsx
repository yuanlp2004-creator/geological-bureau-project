import { ensureCaptureConnection } from './captureConnection'
import { groupedCaptureTasks, updateCaptureTask } from './CaptureTurnPages'
import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { api, type AcquisitionOptions, type AcquisitionTask } from '../../api'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { PageFileActions } from '../../components/PageFileActions'
import { EMPTY_POINTS, Props } from './acquisitionView'
import { SampleAcquisitionForm } from './SampleAcquisitionForm'
import { EvaporationAcquisitionForm } from './EvaporationAcquisitionForm'
import { SampleAcquisitionMonitor } from './SampleAcquisitionMonitor'
import { useSpectroscopySession, type SpectroscopyMode } from './spectroscopySession'
import { SpectroscopyTaskDialog } from './SpectroscopyTaskDialog'
import { captureTaskPresentation, SpectroscopyTaskList } from './SpectroscopyTaskList'
import { SampleInputToolButton } from './SampleInputToolButton'
import { SampleQueuePage } from '../sampleQueues/SampleQueuePage'
export function AcquisitionWorkspace({ token, canWrite, canExecute, onToast, taskKind, actionsTarget, onCaptureChange, canExport = false, canReadSpectra = false, canReadMethods = false, canWriteSamples = false, onOpenSamples, onViewSpectra, currentMethodKey }: Props & {
  taskKind: AcquisitionTask['task_kind']
  actionsTarget?: HTMLElement | null
  onCaptureChange?: (mode: SpectroscopyMode, capture: boolean) => void
  canExport?: boolean
  canReadSpectra?: boolean
  canReadMethods?: boolean
  canWriteSamples?: boolean
  onOpenSamples?: () => void
  onViewSpectra?: (group: string) => void
  currentMethodKey?: string
}) {
  const isSample = taskKind === 'sample'
  const title = isSample ? '样品摄谱' : '蒸发摄谱'
  const [options, setOptions] = useState<AcquisitionOptions | null>(null)

  const [tasks, setTasks] = useState<AcquisitionTask[]>([])

  const [selected, setSelected] = useState<AcquisitionTask | null>(null)
  const [screen, setScreen] = useState<'tasks' | 'capture'>('tasks')
  const [createOpen, setCreateOpen] = useState(false)
  const [sampleEditorOpen, setSampleEditorOpen] = useState(false)
  const [sampleEditorBusy, setSampleEditorBusy] = useState(false)
  const [sampleEditorActions, setSampleEditorActions] = useState<HTMLSpanElement | null>(null)
  const [inputCleared, setInputCleared] = useState(false)
  const [captureQueueId, setCaptureQueueId] = useState<number | null>(null)
  const [clearedQueueId,setClearedQueueId]=useState<number|null>(null)
  const [insertTarget,setInsertTarget]=useState<{queueId:number;itemId:number}|undefined>()
  useEffect(() => { if (screen === 'tasks') { setInputCleared(false); setCaptureQueueId(null) } }, [screen])
  const createFormId = useId()
  useLayoutEffect(() => {
    onCaptureChange?.(isSample ? 'sample-acquisition' : 'evaporation-acquisition', screen === 'capture')
  }, [isSample, screen, onCaptureChange])

  const [createError, setCreateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)

  const [auto, setAuto] = useState(false)
  const autoTask = useRef<number | null>(null)

  useEffect(() => {
    if (!canExecute) setAuto(false)
  }, [canExecute])
  const [busy, setBusy] = useState(false)
  const pageRef = useRef<HTMLDivElement>(null)
  const runningTask = tasks.find(task => task.active_capture_id === task.id)
    ?? tasks.find(task => !['draft', 'between_repeats', 'completed', 'failed', 'stopped'].includes(task.status))
  const embedded = useSpectroscopySession(isSample ? 'sample-acquisition' : 'evaporation-acquisition',
    runningTask ? `${title}任务“${runningTask.name}”尚未结束，请完成或停止后切换摄谱方式。`
      : busy || loading || sampleEditorBusy ? `${title}操作尚未完成，请稍后切换摄谱方式。` : null)
  useEffect(() => {
    if (!runningTask) return
    setSelected(current => current?.id === runningTask.id ? current : runningTask)
    setScreen('capture')
    setCreateOpen(false)
  }, [runningTask, selected?.id])

  const busyRef = useRef(false)

  const pendingStep = useRef<Promise<void> | null>(null)
  const controlPending = useRef(false)
  const selectionGeneration = useRef(0)

  useLayoutEffect(() => {
    selectionGeneration.current++
    if (autoTask.current !== selected?.id) setAuto(false)
    return () => {
      selectionGeneration.current++
    }
  }, [selected?.id, token])

  const [taskName, setTaskName] = useState('')









  const [burnCount, setBurnCount] = useState(20)

  const [darkCount, setDarkCount] = useState(8)


  const [preExcitation, setPreExcitation] = useState(1)

  const [samplingPeriod, setSamplingPeriod] = useState(1)




  const [ccdIndex, setCcdIndex] = useState(0)
  const defaultsLoaded = useRef(false)
  const [saveExcitation, setSaveExcitation] = useState(false)
  const advancingTask = useRef<number | null>(null)
  const [queueProgressMessage, setQueueProgressMessage] = useState('')

  // Only a task observed running in this workspace may advance the next sample.
  useEffect(() => {
    if (!isSample || !selected?.queue_id || !selected.queue_item_id) return
    if (['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats', 'paused'].includes(selected.status)) {
      advancingTask.current = selected.id
      return
    }
    if (selected.status !== 'completed' || advancingTask.current !== selected.id) return
    let live = true
    void api.acquisitionOptions(token).then((fresh) => {
      if (!live) return
      advancingTask.current = null
      setOptions(fresh)
      const currentQueue = fresh.queues.find((item) => item.id === selected.queue_id)
      const currentItem = currentQueue?.items.find((item) => item.id === selected.queue_item_id)
      const next = currentQueue?.items.find((item) => item.position > (currentItem?.position ?? -1) && !item.spectrum_hash)
      if (next) {
        setQueueProgressMessage(`已带出下一样号：${(next.post_name ?? next.pre_name) || '空样'}，可选择下一样品后激发。`)
      } else setQueueProgressMessage('已到样品编号表尾部')
    }).catch((error) => { if (live) onToast(error instanceof Error ? error.message : '读取下一样号失败') })
    return () => { live = false }
  }, [selected?.id, selected?.status, selected?.queue_id, selected?.queue_item_id, isSample, token, onToast])

  const loadGeneration = useRef(0)
  useEffect(() => () => { loadGeneration.current++ }, [token, taskKind])
  const load = useCallback(async () => {
    const generation = ++loadGeneration.current
    setLoading(true)
    try {
      const [nextOptions, nextTasks] = await Promise.all([
        api.acquisitionOptions(token),
        api.acquisitionTasks(token, taskKind, false)
      ])

      if (generation !== loadGeneration.current) return
      if (!defaultsLoaded.current && !isSample && nextOptions.preliminary_defaults) {
        defaultsLoaded.current = true
        const saved = nextOptions.preliminary_defaults.evaporation
        setPreExcitation(saved.pre_excitation_seconds); setSamplingPeriod(saved.sampling_period_seconds)
        setBurnCount(saved.frame_count); setDarkCount(saved.dark_frame_count)
      }
      const matchingTasks = nextTasks.filter((item) => item.task_kind === taskKind)
      setOptions(nextOptions)
      setTasks(matchingTasks)
      setSelected((current) =>
        matchingTasks.find((item) => item.id === current?.id) ?? matchingTasks[0] ?? null
      )
    } catch (error) {
      if (generation === loadGeneration.current)
        onToast(error instanceof Error ? error.message : `无法读取${title}配置`)
    } finally {
      if (generation === loadGeneration.current) setLoading(false)
    }
  }, [isSample, onToast, taskKind, title, token])

  useEffect(() => {
    void load()
  }, [load])
  const selectedNeedsPoints = selected?.last_event?.ccds.some((item) => !Array.isArray(item.points)) ?? false

  useEffect(() => {
    if (screen !== 'capture' || !selected || !selectedNeedsPoints) return
    let cancelled = false

    const taskId = selected.id

    const generation = selectionGeneration.current
    void api
      .acquisitionTask(token, taskId, true)
      .then((next) => {
        if (cancelled || generation !== selectionGeneration.current) return
        setSelected((current) => (current?.id === taskId ? next : current))
      setTasks(current => updateCaptureTask(current, next))
      })
      .catch((error) => {
        if (!cancelled && generation === selectionGeneration.current)
          onToast(error instanceof Error ? error.message : '无法读取采集曲线')
      })
    return () => {
      cancelled = true
    }
  }, [onToast, screen, selected, selectedNeedsPoints, token])

  const deleteTask = async (id: number) => {
    const task = tasks.find(item => item.id === id)
    if (!task || !canWrite || busyRef.current || busy || loading || runningTask) throw new Error('当前摄谱任务无法删除')
    busyRef.current = true
    setBusy(true)
    try {
      await api.deleteAcquisitionTask(token, id)
      const removed = new Set([id, ...(task.capture_turns?.map(turn => turn.id) ?? [])])
      setTasks(current => current.filter(task => !removed.has(task.id)))
      setSelected(current => current && removed.has(current.id) ? null : current)
      onToast(`${title}任务已删除`)
      await load()
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  useEffect(() => {
    const remote = selected?.active_capture_id !== undefined || selected?.profile.transport === 'serial'
    const activeStatus = Boolean(selected && ['countdown', 'pre_excitation', 'burn', 'dark'].includes(selected.status))
    if (
      !canExecute ||
      !selected ||
      !(selected.active_capture_id !== undefined || activeStatus && (auto || remote))
    )
      return
    const generation = selectionGeneration.current

    let cancelled = false

    const timer = window.setInterval(
      () => {
        if (
          cancelled ||
          !remote && autoTask.current !== selected.id ||
          generation !== selectionGeneration.current ||
          busyRef.current ||
          controlPending.current
        )
          return
        busyRef.current = true
        const request = (remote ? api.acquisitionTask(token, selected.id, true).then(fresh =>
          fresh.active_capture_id !== undefined && fresh.active_capture_id !== fresh.id
            ? api.acquisitionTask(token, fresh.active_capture_id, true) : fresh) : api.stepAcquisitionTask(token, selected.id))
          .then((next) => {
            if (cancelled || generation !== selectionGeneration.current) return
            setSelected(next)
            setTasks(current => updateCaptureTask(current, next))
            if (['between_repeats', 'completed', 'failed', 'stopped', 'paused'].includes(next.status)) {
              autoTask.current = null
              setAuto(false)
            }
          })
          .catch((error) => {
            if (cancelled || generation !== selectionGeneration.current) return
            setAuto(false)
            autoTask.current = null
            onToast(error instanceof Error ? error.message : '摄谱推进失败')
          })
          .finally(() => {
            busyRef.current = false
            if (pendingStep.current === request) pendingStep.current = null
          })

        pendingStep.current = request
      },
      remote ? 250 : Math.max(250, selected.sampling_period_seconds * 1000)
    )

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [auto, canExecute, onToast, selected, token])

  const selectedCcd =
    selected?.last_event?.ccds.find((item) => item.ccd_index === ccdIndex) ?? selected?.last_event?.ccds[0]

  const selectedPoints = selectedCcd?.points ?? EMPTY_POINTS

  const boundMethod = options?.methods.find(
    (item) => item.method_id === selected?.method_id && item.method_version === selected?.method_version
  )

  const progressLabel = selected
    ? `${selected.progress.toFixed(1)}% · ${selected.completed_repeats}/${selected.repeat_count} 重复`
    : '--'

  const formalTask = selected?.sample_kind === 'preheat'
    ? tasks.find((task) => task.id === selected.excitation_condition.preheat_source_task_id)
    : selected
  const chooseEvaporationTurn = async (id: number) => {
    if (busy || loading || runningTask || busyRef.current || controlPending.current) return
    const generation = ++selectionGeneration.current
    setBusy(true)
    try {
      const next = await api.acquisitionTask(token, id, true)
      if (generation !== selectionGeneration.current) return
      setSelected(next)
      setTasks(current => updateCaptureTask(current, next))
    } catch (error) {
      if (generation === selectionGeneration.current) onToast(error instanceof Error ? error.message : '读取转角摄谱失败')
    } finally { setBusy(false) }
  }
  const inputTask = formalTask ?? selected
  const inputQueue = options?.queues.find(item => item.id === (captureQueueId ?? inputTask?.queue_id))
  const availableTasks = tasks.filter(item => item.sample_kind !== 'preheat' && (!isSample || (
    item.method_id === inputTask?.method_id && item.method_version === inputTask?.method_version
    && (inputQueue ? item.queue_id === inputQueue.id : !item.queue_id))))
  const pendingSamples = (inputQueue?.id===clearedQueueId?[]:inputQueue?.items.filter(item => !item.spectrum_hash && item.repeats > 0
    && !tasks.some(task => task.queue_item_id === item.id && task.sample_kind !== 'preheat')) ?? [])
  const chooseCaptureSample = async (value: string) => {
    if (busy || loading || runningTask || busyRef.current || controlPending.current || !inputTask) return
    if (value.startsWith('task:')) {
      const task = availableTasks.find(item => `task:${item.id}` === value)
      if (task) { setInputCleared(false); setAuto(false); autoTask.current = null; setSelected(task) }
      return
    }
    const item = pendingSamples.find(item => `queue:${item.id}` === value)
    if (!item || !canWrite || !isSample || !inputQueue) return
    const generation = ++selectionGeneration.current
    controlPending.current = true
    busyRef.current = true
    setBusy(true)
    try {
      // Choose the next target using the current immutable acquisition conditions, never a form draft.
      const payload = Object.fromEntries((['device_profile_id', 'ccd_layout_id', 'ccd_indices', 'method_id', 'method_version',
        'burn_frame_count', 'dark_frame_count', 'countdown_seconds', 'pre_excitation_seconds',
        'sampling_period_seconds', 'burn_cycle_seconds', 'dark_cycle_seconds', 'storage_mode'] as const).map(key => [key, inputTask[key]]))
      if (!inputTask.position_controlled)
        await ensureCaptureConnection(token, inputTask.device_profile_id, inputTask.profile.transport, 'acquisition')
      const next = await api.createAcquisitionTask(token, { ...payload, task_kind: 'sample',
        name: inputTask.name, queue_id: inputQueue.id, queue_item_id: item.id,
        sample_name: item.post_name ?? item.pre_name, name_length: inputQueue.name_length,
        sample_kind: inputTask.sample_kind, repeat_count: item.repeats, management_sample: (item.post_name ?? item.pre_name).toUpperCase().startsWith('D'),
        simulator_sample: inputTask.simulator.sample, seed: inputTask.simulator.seed })
      if (generation !== selectionGeneration.current) return
      setTasks(current => [next, ...current]); setSelected(next)
      setInputCleared(false)
      setQueueProgressMessage('')
      onToast('样号已选择，请点击试样摄谱开始本次激发')
    } catch (error) {
      if (generation === selectionGeneration.current) onToast(error instanceof Error ? error.message : '切换样号失败')
    } finally { controlPending.current = false; busyRef.current = false; setBusy(false) }
  }
  const apply = async (action: 'start' | 'preheat' | 'pause' | 'resume' | 'stop', turnIndex?: number, singleTurn = false) => {
    if (!selected) return
    if ((action === 'start' || action === 'preheat') && runningTask && !(action === 'start' && selected.turns?.awaiting_turn))
      return onToast('当前摄谱尚未结束，请先完成或停止摄谱')
    if (controlPending.current) return onToast('当前采集控制操作尚未完成，请稍后再试')
    const automaticStep = pendingStep.current
    if (busyRef.current && !(automaticStep && ['pause', 'stop'].includes(action)))
      return onToast('当前采集操作尚未完成，请稍后再试')
    const generation = ++selectionGeneration.current

    if (!canExecute) return onToast('当前账户没有采集执行权限')
    if (action === 'preheat' && !canWrite) return onToast('当前账户没有采集写入权限')
    if (action === 'pause' || action === 'stop') {
      autoTask.current = null
      setAuto(false)
    }
    controlPending.current = true
    setBusy(true)
    try {
      if (automaticStep) await automaticStep
      if (generation !== selectionGeneration.current) return
      busyRef.current = true
      const methods = {
        start: api.startAcquisitionTask,
        preheat: api.preheatAcquisitionTask,
        pause: api.pauseAcquisitionTask,
        resume: api.resumeAcquisitionTask,
        stop: api.stopAcquisitionTask
      }

      const target = action === 'start' || action === 'preheat' ? formalTask : selected
      if (!target) return onToast('请先选择正式摄谱任务')
      const continuous = !singleTurn && Boolean(target.turns?.multiple || target.capture_turn?.multiple)
      const next = action === 'start' ? await api.startAcquisitionTask(token, target.id, turnIndex, singleTurn, continuous)
        : await methods[action](token, target.id, turnIndex)

      if (generation !== selectionGeneration.current) return
      setSelected(next)
      setTasks(current => updateCaptureTask(current, next))
      const capture = ['start', 'preheat', 'resume'].includes(action)
        && ['countdown', 'pre_excitation', 'burn', 'dark'].includes(next.status)
      autoTask.current = capture ? next.id : null
      setAuto(capture)
    } catch (error) {
      if (generation === selectionGeneration.current)
        onToast(error instanceof Error ? error.message : '采集控制失败')
    } finally {
      busyRef.current = false
      controlPending.current = false
      setBusy(false)
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (runningTask) return onToast('当前任务尚未结束，请先完成或停止摄谱')
    if (!canWrite) return onToast('当前账户没有采集写入权限')
    setCreateError(null)
    setBusy(true)
    try {
      if (!reportInvalidNumericInput(pageRef.current?.querySelector('.acquisition-form') ?? null)) return
      const next = isSample ? await api.createSampleSession(token, taskName)
        : await api.createEvaporationSession(token, { name: taskName, pre_excitation_seconds: preExcitation,
          sampling_period_seconds: samplingPeriod, frame_count: burnCount, dark_frame_count: darkCount,
          save_conditions: saveExcitation })
      if (!isSample) { defaultsLoaded.current = false; setSaveExcitation(false); setTaskName('') }
      setTasks((current) => [next, ...current])
      setSelected(next)
      setInputCleared(false)
      setCaptureQueueId(null)
      onToast('采集任务已创建')
      setCreateOpen(false)
      setScreen('capture')
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : '创建采集任务失败')
      onToast(error instanceof Error ? error.message : '创建采集任务失败')
    } finally {
      setBusy(false)
    }
  }

  const form = { create, canWrite, busy: busy || loading || Boolean(runningTask), taskName, setTaskName }
  const openCreate = async () => {
    if (!isSample && !defaultsLoaded.current) {
      setBusy(true)
      try {
        const fresh = await api.acquisitionOptions(token)
        setOptions(fresh)
        const saved = fresh.preliminary_defaults?.evaporation
        if (saved) { setPreExcitation(saved.pre_excitation_seconds); setSamplingPeriod(saved.sampling_period_seconds); setBurnCount(saved.frame_count); setDarkCount(saved.dark_frame_count) }
        defaultsLoaded.current = true
      } catch (error) { onToast(error instanceof Error ? error.message : '读取蒸发激发条件失败'); return }
      finally { setBusy(false) }
    }
    if (!taskName) {
      const methodName = options?.methods.find(item => `${item.method_id}:${item.method_version}` === currentMethodKey)?.name ?? '样品'
      const now = new Date()
      const stamp = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}`
      setTaskName(`${methodName.replace(/[\\/:*?<>|" ]/g,'_')}_${stamp}`.slice(0,120))
    }
    setCreateError(null); setCreateOpen(true)
  }
  return (
    <div
      ref={pageRef}
      className={`${embedded ? 'spectroscopy-mode-content' : 'page-content'} sample-acquisition-page refined-page remaining-page`}
      data-testid={`${taskKind}-acquisition-page`} data-stage={screen}
    >
      <PageFileActions target={actionsTarget}>
        {screen === 'capture' ? <>
          {formalTask?.status === 'completed' && canWrite && <button type="button" className="secondary-button"
            disabled={busy || loading || Boolean(runningTask)} onClick={() => { if (isSample) { const next = pendingSamples[0]; if (next) void chooseCaptureSample(`queue:${next.id}`); else onToast('已到样品编号表尾部') } else openCreate() }}>{isSample ? '下一样品' : '新一轮摄谱'}</button>}
          <button type="button" className="secondary-button" disabled={busy || loading || Boolean(runningTask)}
            onClick={() => { if (!runningTask && !busy) setScreen('tasks') }}>返回任务列表</button>
        </> : <>
          <button type="button" className="secondary-button" onClick={() => void load()} disabled={loading || busy}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />刷新
          </button>
          <button type="button" className="primary-button" disabled={!canWrite || busy || loading || Boolean(runningTask)}
            onClick={openCreate}>新建任务</button>
        </>}
      </PageFileActions>
      <SpectroscopyTaskDialog open={createOpen} title={isSample ? '样品摄谱' : '蒸发曲线摄谱'} busy={busy || loading}
        error={createError} onCancel={() => setCreateOpen(false)} actions={<button type="submit" form={createFormId} className="primary-button"
          disabled={!canWrite || form.busy || !taskName.trim()}>确定</button>}>
        {isSample ? <SampleAcquisitionForm {...form} formId={createFormId} hideSubmit /> : <EvaporationAcquisitionForm formId={createFormId} create={create} disabled={form.busy || !canWrite}
          name={taskName} onName={setTaskName} saveConditions={saveExcitation} onSaveConditions={setSaveExcitation}
          conditions={{ pre_excitation_seconds: preExcitation, sampling_period_seconds: samplingPeriod, frame_count: burnCount, dark_frame_count: darkCount }}
          onCondition={(key, value) => { if (key === 'pre_excitation_seconds') setPreExcitation(value); else if (key === 'sampling_period_seconds') setSamplingPeriod(value); else if (key === 'frame_count') setBurnCount(value); else setDarkCount(value) }} />}
      </SpectroscopyTaskDialog>
      <SpectroscopyTaskDialog open={sampleEditorOpen} title="预录样号" busy={sampleEditorBusy} dismissLabel="关闭" onCancel={() => {
        setSampleEditorOpen(false)
        void api.acquisitionOptions(token).then(setOptions).catch(error => onToast(error instanceof Error ? error.message : '刷新样号失败'))
      }} actions={<span ref={setSampleEditorActions} />}>
        {sampleEditorOpen && canWriteSamples && <SampleQueuePage insertion={insertTarget} token={token} onToast={onToast}
          onBusyChange={setSampleEditorBusy} confirmation={{
            target: sampleEditorActions,
            onConfirm: queue => {
              setOptions(current => current ? { ...current, queues: [...current.queues.filter(item => item.id !== queue.id), queue] } : current)
              setCaptureQueueId(queue.id)
              setClearedQueueId(null)
              setInputCleared(true)
              setSampleEditorOpen(false)
            },
          }} />}
      </SpectroscopyTaskDialog>
      {screen === 'tasks' && <SpectroscopyTaskList title={title} busy={busy || loading} runningId={runningTask?.id}
        tasks={groupedCaptureTasks(tasks.filter(item => !item.capture_turn?.group || item.sample_kind !== 'preheat')).map(item => ({ id: item.id, name: item.name,
          ...captureTaskPresentation(item, `${item.sample_name || (isSample ? '未命名样品' : '蒸发实验')} · ${item.completed_repeats}/${item.repeat_count} 重复`, tasks),
          completed: item.capture_turns?.length ? item.capture_turns.every(turn => turn.status === 'completed') : item.status === 'completed' }))}
        onView={onViewSpectra ? id => {
          const turn = tasks.find(task => task.id === id)?.capture_turn
          onViewSpectra(!isSample && turn?.multiple && turn.group ? `evaporation:${turn.group}` : `task:${id}`)
        } : undefined}
        onDelete={canWrite ? deleteTask : undefined}
        onChoose={id => {
          const task = tasks.find(item => item.id === id)
          if (task && !busy && (!runningTask || runningTask.id === id)) {
            setBusy(true)
            void (async () => {
              try {
                if (['draft','between_repeats'].includes(task.status))
                  if (!task.position_controlled)
                    await ensureCaptureConnection(token, task.device_profile_id, task.profile.transport, 'acquisition')
                setSelected(task); setScreen('capture')
              } catch (error) { onToast(error instanceof Error ? error.message : '仪器连接检查失败') }
              finally { setBusy(false) }
            })()
          }
        }} />}
      <main className="sample-acquisition-main spectroscopy-capture-page" data-capture-screen hidden={screen !== 'capture'}>
          {queueProgressMessage && <p role="status" className="acquisition-management-note">{queueProgressMessage}</p>}
          <SampleAcquisitionMonitor
            token={token} canExport={canExport} canReadSpectra={canReadSpectra} canReadMethods={canReadMethods} onToast={onToast} finish={() => setScreen('tasks')}
            formalTask={formalTask} onChooseTurnTask={id => void chooseEvaporationTurn(id)} onShowFormalTask={() => { if (formalTask) void chooseCaptureSample(`task:${formalTask.id}`) }}
            sampleInput={<>
              <label><span>{isSample ? '样品编号:' : '蒸发谱带名:'}</span>
                {!isSample ? <input aria-label="蒸发谱带名" readOnly title="本次摄谱的谱带名称" value={inputTask?.sample_name || inputTask?.name || ''} />
                  : <select aria-label="样品编号" value={!inputCleared && inputTask ? `task:${inputTask.id}` : ''}
                  disabled={busy || loading || Boolean(runningTask)} onChange={event => void chooseCaptureSample(event.target.value)}>
                  <option value="" />
                  {availableTasks.map(item => <option key={item.id} value={`task:${item.id}`}>{isSample ? item.sample_name : item.sample_name || item.name}</option>)}
                  {pendingSamples.length > 0 && <optgroup label="待测样品">{pendingSamples.map(item => <option key={item.id}
                    value={`queue:${item.id}`} disabled={!canWrite}>{item.post_name ?? item.pre_name}</option>)}</optgroup>}
                </select>}
              </label>
              {isSample && <label><span>重复摄谱:</span><input aria-label="重复摄谱" readOnly value={!inputCleared ? inputTask?.repeat_count ?? 1 : 1} /></label>}
            </>}
            canFinish={!busy && !loading && !runningTask}
            inputToolbar={<>
              <SampleInputToolButton icon="input-samples" label="录入样品编号" description="打开预录样号窗口"
                disabled={!isSample || !onOpenSamples || !canWriteSamples || busy || Boolean(runningTask)} onClick={() => {setInsertTarget(undefined);setSampleEditorOpen(true)}} />
              <SampleInputToolButton icon="insert-sample" label="插入样品" description="打开样号表，在当前样品之前插入样号"
                disabled={!isSample || !canWriteSamples || !inputQueue || !inputTask?.queue_item_id || busy || Boolean(runningTask)} onClick={() => {if(inputQueue&&inputTask?.queue_item_id){setInsertTarget({queueId:inputQueue.id,itemId:inputTask.queue_item_id});setSampleEditorOpen(true)}}} />
              <SampleInputToolButton icon="clear-samples" label="清除待测样号" description="清除本次待测样号列表和选择，保留已保存队列、任务和谱带"
                disabled={!isSample || busy || Boolean(runningTask)} onClick={() => {setInputCleared(true);setClearedQueueId(inputQueue?.id??null)}} />
            </>}
            selected={selected}
            apply={apply}
            busy={busy}
            canExecute={canExecute && (!runningTask || selected?.id === runningTask.id)}
            canStart={Boolean(!inputCleared && formalTask && formalTask.sample_kind !== 'preheat' &&
              (formalTask.status === 'paused' && formalTask.turns?.awaiting_turn || !runningTask && ['draft', 'between_repeats'].includes(formalTask.status)))}
            canPreheat={canWrite && Boolean(selected && ['draft', 'between_repeats', 'completed', 'failed', 'stopped'].includes(selected.status))}
            progressLabel={progressLabel}
            ccdIndex={ccdIndex}
            setCcdIndex={setCcdIndex}
            selectedCcd={selectedCcd}
            selectedPoints={selectedPoints}
          />
        </main>

    </div>
  )
}
