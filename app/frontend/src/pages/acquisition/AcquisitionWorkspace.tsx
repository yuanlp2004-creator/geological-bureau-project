import { formatAnalysisValue } from '../../components/analysisUnits'
import { Activity, AlertTriangle, CheckCircle2, ListChecks, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { api, type AcquisitionOptions, type AcquisitionTask } from '../../api'
import type { AcquisitionMeasurements } from '../../api/acquisition'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { FormDisclosure, TaskLayout } from '../../layout/TaskLayout'
import { Chevron, EMPTY_POINTS, Props, SAMPLE_OPTIONS, stateLabel } from './acquisitionView'
import { SampleAcquisitionForm, type SampleAcquisitionFormProps } from './SampleAcquisitionForm'
import { EvaporationAcquisitionForm } from './EvaporationAcquisitionForm'
import { SampleAcquisitionMonitor } from './SampleAcquisitionMonitor'
import { SampleAcquisitionResults } from './SampleAcquisitionResults'
import { useSpectroscopySession } from './spectroscopySession'
export function AcquisitionWorkspace({ token, canWrite, canExecute, onToast, taskKind }: Props & {
  taskKind: AcquisitionTask['task_kind']
}) {
  const isSample = taskKind === 'sample'
  const title = isSample ? '样品摄谱' : '蒸发摄谱'
  const [options, setOptions] = useState<AcquisitionOptions | null>(null)

  const [tasks, setTasks] = useState<AcquisitionTask[]>([])

  const [selected, setSelected] = useState<AcquisitionTask | null>(null)

  const [createError, setCreateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)

  const [auto, setAuto] = useState(false)

  useEffect(() => {
    if (!canExecute) setAuto(false)
  }, [canExecute])
  const [busy, setBusy] = useState(false)
  const pageRef = useRef<HTMLDivElement>(null)
  const runningTask = tasks.find((task) => !['draft', 'completed', 'failed', 'stopped'].includes(task.status))
  const embedded = useSpectroscopySession(isSample ? 'sample-acquisition' : 'evaporation-acquisition',
    runningTask ? `${title}任务“${runningTask.name}”尚未结束，请完成或停止后切换摄谱方式。`
      : busy || loading ? `${title}操作尚未完成，请稍后切换摄谱方式。` : null)
  const Heading = embedded ? 'h2' : 'h1'

  const busyRef = useRef(false)

  const pendingStep = useRef<Promise<void> | null>(null)
  const controlPending = useRef(false)
  const selectionGeneration = useRef(0)

  useLayoutEffect(() => {
    selectionGeneration.current++
    setAuto(false)
    return () => {
      selectionGeneration.current++
    }
  }, [selected?.id, token])

  const [taskName, setTaskName] = useState(isSample ? '样品采集' : '蒸发实验')

  const [profileId, setProfileId] = useState<number | null>(null)

  const [layoutId, setLayoutId] = useState<string>('default')

  const [methodKey, setMethodKey] = useState('')

  const [queueId, setQueueId] = useState('')

  const [queueItemId, setQueueItemId] = useState('')

  const [sampleName, setSampleName] = useState('')

  const [nameLength, setNameLength] = useState<12 | 20>(12)
  const [renameLength, setRenameLength] = useState<12 | 20>(12)
  const [measurements, setMeasurements] = useState<AcquisitionMeasurements | null>(null)
  const [measurementError, setMeasurementError] = useState('')
  const [sampleKind, setSampleKind] = useState<'test' | 'normal' | 'standard' | 'blank' | 'preheat'>('test')

  const [storageMode, setStorageMode] = useState<'averaged' | 'full_interval'>('averaged')

  const [useMethodIntervals, setUseMethodIntervals] = useState(false)
  const [useMethodConditions, setUseMethodConditions] = useState(true)
  const [managementSample, setManagementSample] = useState(false)
  const [repeatCount, setRepeatCount] = useState(1)

  const [burnCount, setBurnCount] = useState(3)

  const [darkCount, setDarkCount] = useState(1)

  const [countdown, setCountdown] = useState(0)

  const [preExcitation, setPreExcitation] = useState(1)

  const [samplingPeriod, setSamplingPeriod] = useState(1)

  const [burnCycle, setBurnCycle] = useState(1)

  const [darkCycle, setDarkCycle] = useState(1)

  const [simulatorSample, setSimulatorSample] = useState(SAMPLE_OPTIONS[0])

  const [seed, setSeed] = useState(13)

  const [renameValue, setRenameValue] = useState('')

  const [ccdIndex, setCcdIndex] = useState(0)
  const defaultsLoaded = useRef(false)
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
      setQueueId(String(selected.queue_id))
      setQueueItemId(next ? String(next.id) : '')
      if (next) {
        setSampleName(next.post_name ?? next.pre_name)
        setRepeatCount(next.repeats || 1)
        setQueueProgressMessage(`已带出下一样号：${(next.post_name ?? next.pre_name) || '空样'}，请创建任务后激发。`)
      } else setQueueProgressMessage('已到样品编号表尾部')
    }).catch((error) => { if (live) onToast(error instanceof Error ? error.message : '读取下一样号失败') })
    return () => { live = false }
  }, [selected?.id, selected?.status, selected?.queue_id, selected?.queue_item_id, isSample, token, onToast])

  const inheritedConditions = options?.methods.find((item) => `${item.method_id}:${item.method_version}` === methodKey)?.conditions
  useEffect(() => {
    if (taskKind !== 'sample' || sampleKind === 'preheat' || !useMethodConditions || !inheritedConditions) return
    setBurnCount(inheritedConditions.frame_count)
    setLayoutId(String(inheritedConditions.ccd_layout_id))
    setDarkCount(inheritedConditions.dark_frame_count)
    setPreExcitation(inheritedConditions.pre_excitation_seconds)
    setSamplingPeriod(inheritedConditions.sampling_period_seconds)
    setBurnCycle(inheritedConditions.sampling_period_seconds)
    setDarkCycle(inheritedConditions.sampling_period_seconds)
    setRepeatCount(managementSample || sampleName.toUpperCase().startsWith('D') ? inheritedConditions.control_repeats
      : sampleKind === 'standard' ? inheritedConditions.standard_repeats : inheritedConditions.sample_repeats)
  }, [taskKind, useMethodConditions, inheritedConditions, managementSample, sampleKind, sampleName])
  const preliminaryMode = taskKind === 'evaporation' ? 'edt' : sampleKind === 'preheat' ? 'wdt' : null
  const preliminary = useRef({ edt: { pre: 1, period: 1, burn: 3, dark: 1 }, wdt: { pre: 1, period: 1, burn: 3, dark: 1 } })
  const previousPreliminary = useRef<typeof preliminaryMode>(null)
  useEffect(() => {
    if (previousPreliminary.current) preliminary.current[previousPreliminary.current] = { pre: preExcitation, period: samplingPeriod, burn: burnCount, dark: darkCount }
    if (preliminaryMode) {
      const saved = preliminary.current[preliminaryMode]
      setPreExcitation(saved.pre); setSamplingPeriod(saved.period); setBurnCycle(saved.period); setDarkCycle(saved.period)
      setBurnCount(saved.burn); setDarkCount(saved.dark); setRepeatCount(1)
    }
    previousPreliminary.current = preliminaryMode
  }, [preliminaryMode])

  useEffect(() => {
    setRenameLength(selected?.name_length === 20 ? 20 : 12)
    setMeasurements(null)
  }, [selected?.id, token])
  useEffect(() => {
    if (!selected || !isSample) return
    let cancelled = false
    const generation = selectionGeneration.current
    void api
      .acquisitionMeasurements(token, selected.id)
      .then((next) => {
        if (cancelled || generation !== selectionGeneration.current) return
        setMeasurements(next)
        setMeasurementError('')
      })
      .catch((error) => {
        if (cancelled || generation !== selectionGeneration.current) return
        setMeasurements(null)
        setMeasurementError(error instanceof Error ? error.message : '即时测量读取失败')
      })
    return () => {
      cancelled = true
    }
  }, [isSample, selected, token])
  const loadGeneration = useRef(0)
  useEffect(() => () => { loadGeneration.current++ }, [token, taskKind])
  const load = useCallback(async () => {
    const generation = ++loadGeneration.current
    setLoading(true)
    try {
      const [nextOptions, nextTasks] = await Promise.all([
        api.acquisitionOptions(token),
        api.acquisitionTasks(token, taskKind)
      ])

      if (generation !== loadGeneration.current) return
      if (!defaultsLoaded.current && !isSample && nextOptions.preliminary_defaults) {
        defaultsLoaded.current = true
        const saved = nextOptions.preliminary_defaults.evaporation
        preliminary.current.edt = { pre: saved.pre_excitation_seconds, period: saved.sampling_period_seconds,
          burn: saved.frame_count, dark: saved.dark_frame_count }
        setPreExcitation(saved.pre_excitation_seconds); setSamplingPeriod(saved.sampling_period_seconds)
        setBurnCycle(saved.sampling_period_seconds); setDarkCycle(saved.sampling_period_seconds)
        setBurnCount(saved.frame_count); setDarkCount(saved.dark_frame_count)
      }
      const matchingTasks = nextTasks.filter((item) => item.task_kind === taskKind)
      setOptions(nextOptions)
      setTasks(matchingTasks)
      setProfileId((current) => current ?? nextOptions.profiles[0]?.id ?? null)
      setLayoutId((current) => current || String(nextOptions.layouts[0]?.id ?? 'default'))
      setMethodKey((current) =>
        nextOptions.methods.some((item) => `${item.method_id}:${item.method_version}` === current)
          ? current
          : nextOptions.methods[0]
            ? `${nextOptions.methods[0].method_id}:${nextOptions.methods[0].method_version}`
            : ''
      )
      setSelected((current) =>
        matchingTasks.find((item) => item.id === current?.id) ?? matchingTasks[0] ?? null
      )
    } catch (error) {
      if (generation === loadGeneration.current)
        onToast(error instanceof Error ? error.message : `无法读取${title}配置`)
    } finally {
      if (generation === loadGeneration.current) setLoading(false)
    }
  }, [onToast, taskKind, title, token])

  useEffect(() => {
    void load()
  }, [load])
  const selectedNeedsPoints = selected?.last_event?.ccds.some((item) => !Array.isArray(item.points)) ?? false

  useEffect(() => {
    if (!selected || !selectedNeedsPoints) return
    let cancelled = false

    const taskId = selected.id

    const generation = selectionGeneration.current
    void api
      .acquisitionTask(token, taskId, true)
      .then((next) => {
        if (cancelled || generation !== selectionGeneration.current) return
        setSelected((current) => (current?.id === taskId ? next : current))
        setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      })
      .catch((error) => {
        if (!cancelled && generation === selectionGeneration.current)
          onToast(error instanceof Error ? error.message : '无法读取采集曲线')
      })
    return () => {
      cancelled = true
    }
  }, [onToast, selected, selectedNeedsPoints, token])

  useEffect(() => {
    if (
      !auto ||
      !canExecute ||
      !selected ||
      !['countdown', 'pre_excitation', 'burn', 'dark', 'between_repeats'].includes(selected.status)
    )
      return
    const generation = selectionGeneration.current

    let cancelled = false

    const timer = window.setInterval(
      () => {
        if (
          cancelled ||
          generation !== selectionGeneration.current ||
          busyRef.current ||
          controlPending.current
        )
          return
        busyRef.current = true
        const request = api
          .stepAcquisitionTask(token, selected.id)
          .then((next) => {
            if (cancelled || generation !== selectionGeneration.current) return
            setSelected(next)
            setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
            if (['completed', 'failed', 'stopped'].includes(next.status)) setAuto(false)
          })
          .catch((error) => {
            if (cancelled || generation !== selectionGeneration.current) return
            setAuto(false)
            onToast(error instanceof Error ? error.message : '连续采集失败')
          })
          .finally(() => {
            busyRef.current = false
            if (pendingStep.current === request) pendingStep.current = null
          })

        pendingStep.current = request
      },
      Math.max(250, selected.sampling_period_seconds * 1000)
    )

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [auto, canExecute, onToast, selected, token])
  const queue = options?.queues.find((item) => String(item.id) === queueId)

  const queueItem = queue?.items.find((item) => String(item.id) === queueItemId)

  const displayedRepeatCount = queueItem ? queueItem.repeats || 1 : repeatCount

  const [methodId, methodVersion] = methodKey.split(':').map(Number)

  const selectedCcd =
    selected?.last_event?.ccds.find((item) => item.ccd_index === ccdIndex) ?? selected?.last_event?.ccds[0]

  const selectedPoints = selectedCcd?.points ?? EMPTY_POINTS

  const boundMethod = options?.methods.find(
    (item) => item.method_id === selected?.method_id && item.method_version === selected?.method_version
  )

  const messageTone = selected?.messages.some((item) => item.level === 'error')
    ? 'error'
    : selected?.messages.some((item) => item.level === 'warning')
      ? 'warning'
      : selected?.messages.some((item) => item.level === 'success')
        ? 'success'
        : 'info'


  const progressLabel = selected
    ? `${selected.progress.toFixed(1)}% · ${selected.completed_repeats}/${selected.repeat_count} 重复`
    : '--'

  const apply = async (action: 'start' | 'step' | 'pause' | 'resume' | 'stop') => {
    if (!selected) return
    if (controlPending.current) return onToast('当前采集控制操作尚未完成，请稍后再试')
    const automaticStep = pendingStep.current
    if (busyRef.current && !(automaticStep && ['pause', 'stop'].includes(action)))
      return onToast('当前采集操作尚未完成，请稍后再试')
    const generation = ++selectionGeneration.current

    if (action !== 'step' && action !== 'stop' && !canExecute) return onToast('当前账户没有采集执行权限')
    controlPending.current = true
    setBusy(true)
    try {
      if (automaticStep) await automaticStep
      if (generation !== selectionGeneration.current) return
      busyRef.current = true
      const methods = {
        start: api.startAcquisitionTask,
        step: api.stepAcquisitionTask,
        pause: api.pauseAcquisitionTask,
        resume: api.resumeAcquisitionTask,
        stop: api.stopAcquisitionTask
      }

      const next = await methods[action](token, selected.id)

      if (generation !== selectionGeneration.current) return
      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      if (action === 'stop' || ['completed', 'failed', 'stopped'].includes(next.status)) setAuto(false)
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
    if (
      taskKind === 'sample' &&
      (!Number.isInteger(methodId) || methodId < 1 || !Number.isInteger(methodVersion) || methodVersion < 1)
    )
      return onToast('请选择已发布方法版本')
    setCreateError(null)
    setBusy(true)
    try {
      const next = await api.createAcquisitionTask(token, {
        task_kind: taskKind,
        name: taskName,
        device_profile_id: profileId,
        ccd_layout_id: layoutId,
        method_id: taskKind === 'sample' ? methodId : undefined,
        method_version: taskKind === 'sample' ? methodVersion : undefined,
        queue_id: isSample && queueId ? Number(queueId) : undefined,
        queue_item_id: isSample && queueItemId ? Number(queueItemId) : undefined,
        sample_name: sampleName,

        name_length: nameLength,
        sample_kind: sampleKind,
        use_method_intervals: taskKind === 'sample' && useMethodIntervals,
        use_method_conditions: taskKind === 'sample' && sampleKind !== 'preheat' && useMethodConditions,
        management_sample: taskKind === 'sample' && managementSample,
        storage_mode: taskKind === 'evaporation' ? 'full_interval' : storageMode,
        repeat_count: isSample ? displayedRepeatCount : 1,
        burn_frame_count: burnCount,
        dark_frame_count: darkCount,
        countdown_seconds: countdown,
        pre_excitation_seconds: preExcitation,
        sampling_period_seconds: samplingPeriod,
        burn_cycle_seconds: burnCycle,
        dark_cycle_seconds: darkCycle,
        simulator_sample: simulatorSample,
        seed
      })

      setTasks((current) => [next, ...current])
      setSelected(next)
      onToast('采集任务已创建')
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : '创建采集任务失败')
      onToast(error instanceof Error ? error.message : '创建采集任务失败')
    } finally {
      setBusy(false)
    }
  }

  const saveConditions = async () => {
    if (!canWrite || busy) return
    if (!reportInvalidNumericInput(pageRef.current?.querySelector('.acquisition-form') ?? null)) return onToast('请先修正激发参数')
    setBusy(true)
    try {
      await api.saveEvaporationDefaults(token, { pre_excitation_seconds: preExcitation,
        sampling_period_seconds: samplingPeriod, frame_count: burnCount, dark_frame_count: darkCount })
      onToast('蒸发激发条件已保存，下次新建时自动载入')
    } catch (error) { onToast(error instanceof Error ? error.message : '保存激发条件失败') }
    finally { setBusy(false) }
  }

  const rename = async () => {
    const sample = selected?.samples.find((item) => item.status === 'completed' && !item.discarded)

    if (!selected || !sample || !renameValue.trim() || !canWrite || busy || loading) return
    setBusy(true)
    try {
      const next = await api.renameAcquisitionSample(
        token,
        selected.id,
        sample.id,
        renameValue.trim(),
        renameLength
      )

      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      setRenameValue('')
      onToast('采集后名称已保存，数据哈希未改变')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '采集后命名失败')
    } finally { setBusy(false) }
  }

  const discard = async () => {
    if (!selected || !canWrite || controlPending.current) return
    const automaticStep = pendingStep.current
    if (busyRef.current && !automaticStep) return onToast('当前采集控制尚未完成')
    const generation = ++selectionGeneration.current
    controlPending.current = true
    setAuto(false)
    setBusy(true)
    setMeasurements(null)
    try {
      if (automaticStep) await automaticStep
      if (generation !== selectionGeneration.current) return
      busyRef.current = true
      const next = await api.discardAcquisitionSample(token, selected.id, '激发能量不足')
      if (generation !== selectionGeneration.current) return
      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      onToast('异常样品已删除，原始帧保留供追溯，可重新摄谱')
    } catch (error) {
      if (generation === selectionGeneration.current)
        onToast(error instanceof Error ? error.message : '删除异常样品失败')
    } finally {
      controlPending.current = false
      busyRef.current = false
      setBusy(false)
    }
  }
  const form: SampleAcquisitionFormProps = {
    saveConditions,
    useMethodIntervals: useMethodIntervals,
    useMethodConditions: useMethodConditions,
    setUseMethodConditions: setUseMethodConditions,
    setUseMethodIntervals: setUseMethodIntervals,
    managementSample: managementSample,
    setManagementSample: setManagementSample,
    create: create,
    canWrite: canWrite,
    busy: busy || loading || Boolean(runningTask),
    taskName: taskName,
    setTaskName: setTaskName,
    profileId: profileId,
    setProfileId: setProfileId,
    options: options,
    layoutId: layoutId,
    setLayoutId: setLayoutId,
    methodKey: methodKey,
    setMethodKey: setMethodKey,
    queueId: queueId,
    setQueueId: setQueueId,
    setQueueItemId: setQueueItemId,
    queue: queue,
    queueItemId: queueItemId,
    sampleName: sampleName,
    setSampleName: setSampleName,
    nameLength: queue?.name_length === 20 ? 20 : queue ? 12 : nameLength,
    setNameLength: setNameLength,
    sampleKind: sampleKind,
    setSampleKind: setSampleKind,
    storageMode: storageMode,
    setStorageMode: setStorageMode,
    burnCount: burnCount,
    setBurnCount: setBurnCount,
    darkCount: darkCount,
    setDarkCount: setDarkCount,
    queueItem: queueItem,
    displayedRepeatCount: displayedRepeatCount,
    setRepeatCount: setRepeatCount,
    countdown: countdown,
    setCountdown: setCountdown,
    preExcitation: preExcitation,
    setPreExcitation: setPreExcitation,
    samplingPeriod: samplingPeriod,
    setSamplingPeriod: setSamplingPeriod,
    simulatorSample: simulatorSample,
    setSimulatorSample: setSimulatorSample,
    seed: seed,
    setSeed: setSeed,
  }
  return (
    <div
      ref={pageRef}
      className={`${embedded ? 'spectroscopy-mode-content' : 'page-content'} sample-acquisition-page refined-page remaining-page`}
      data-testid={`${taskKind}-acquisition-page`}
    >
      {!embedded && <section className="page-action-toolbar">
        
        <button className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
          刷新
        </button>
      </section>}
      <TaskLayout
        showEmptyRail
        actions={embedded && <button className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />刷新
        </button>}
        className="sample-acquisition-grid"
        hasItems={Boolean(tasks.length)}
        current={
          selected ? `${selected.name} · ${stateLabel[selected.status] ?? selected.status}` : '尚未选择'
        }
      >
        <aside className="surface acquisition-task-list">
          <div className="surface-heading">
            <div>
              <h2>
                {isSample ? '样品任务' : '蒸发实验'} <span className="count-badge">{tasks.length}</span>
              </h2>
            </div>
            <Activity size={17} />
          </div>
          {tasks.length === 0 ? (
            <div className="empty-state">暂无{title}任务</div>
          ) : (
            <div className="acquisition-task-rows">
              {tasks.map((item) => {
                const metadata = `${item.task_kind === 'evaporation' ? '蒸发' : item.sample_name || '临时样品'} · ${stateLabel[item.status]}`

                return (
                  <button
                    key={item.id}
                    disabled={busy || Boolean(runningTask && runningTask.id !== item.id)}
                    className={selected?.id === item.id ? 'active' : ''}
                    onClick={() => setSelected(item)}
                  >
                    <span className={`task-state-dot ${item.status}`} />
                    <span>
                      <strong title={item.name}>{item.name}</strong>
                      <small title={metadata}>{metadata}</small>
                    </span>
                    <Chevron item={item} />
                  </button>
                )
              })}
            </div>
          )}
        </aside>
        <main className="sample-acquisition-main">
          {queueProgressMessage && <p role="status" className="acquisition-management-note">{queueProgressMessage}</p>}
          <SampleAcquisitionMonitor
            setup={
              <>
                {selected && <SampleAcquisitionResults
                  canWrite={canWrite} selected={selected} renameValue={renameValue} setRenameValue={setRenameValue}
                  rename={rename} nameLength={renameLength} setNameLength={setRenameLength} busy={busy}
                />}
                <FormDisclosure title={`建立${title}任务`} error={createError} hasItems={false} objectKey={selected?.id}>
                  {isSample ? <SampleAcquisitionForm {...form} /> : <EvaporationAcquisitionForm {...form} />}
                </FormDisclosure>
              </>
            }
            selected={selected}
            apply={apply}
            busy={busy}
            canExecute={canExecute && (!runningTask || selected?.id === runningTask.id)}
            setAuto={setAuto}
            auto={auto}
            progressLabel={progressLabel}
            ccdIndex={ccdIndex}
            setCcdIndex={setCcdIndex}
            selectedCcd={selectedCcd}
            selectedPoints={selectedPoints}
            boundMethod={boundMethod}
          />
          {isSample && selected && (
            <section className="surface acquisition-measurements" data-testid="acquisition-measurements">
              <div className="surface-heading">
                <div>
                  <h2>即时测量结果</h2>
                  <p>{measurementError || measurements?.message || '正在读取当前测量…'}</p>
                </div>
                <button
                  className="secondary-button danger"
                  onClick={() => void discard()}
                  disabled={!canWrite || busy || !selected.samples.some((item) => !item.discarded)}
                >
                  删除异常样品（能量不足）
                </button>
              </div>
              <div className="sample-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>样号 / 重复</th>
                      <th>元素 / 波长</th>
                      <th>峰位</th>
                      <th>峰强度</th>
                      <th>净强度</th>
                      <th>定量信号</th>
                      <th>浓度</th>
                      <th>状态 / 曲线</th>
                    </tr>
                  </thead>
                  <tbody>
                    {measurements?.rows.map((row) => (
                      <tr key={`${row.sample_id}-${row.line_id}`}>
                        <td>
                          {row.sample_name || '未命名'} / {row.repeat_index + 1}
                        </td>
                        <td>
                          {row.element} / {row.wavelength_nm.toFixed(3)}
                        </td>
                        <td>{row.peak_position ?? '—'}</td>
                        <td>{row.peak_height?.toPrecision(6) ?? '—'}</td>
                        <td>{row.net_signal?.toPrecision(6) ?? '—'}</td>
                        <td>{row.quantitative_signal?.toPrecision(6) ?? '—'}</td>
                        <td>
                          {row.concentration === null
                            ? '—'
                            : `${formatAnalysisValue(row.concentration, row.decimal_places)} ${row.unit}`}
                        </td>
                        <td>
                          {row.message}
                          {row.curve_snapshot_id ? ` · #${row.curve_snapshot_id}` : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {selected && (
            <section className="surface acquisition-messages">
              <div className="surface-heading">
                <div>
                  <h2>
                    全部采集消息 <span className="count-badge">{selected.messages.length}</span>
                  </h2>
                </div>
                <span className={`message-summary-icon ${messageTone}`}>
                  {messageTone === 'error' || messageTone === 'warning' ? (
                    <AlertTriangle size={16} />
                  ) : messageTone === 'success' ? (
                    <CheckCircle2 size={16} />
                  ) : (
                    <ListChecks size={16} />
                  )}
                </span>
              </div>
              <div className="message-list">
                {[...selected.messages].reverse().map((item) => (
                  <div key={item.id} className={item.level}>
                    <span>{item.created_at.slice(11, 19)}</span>
                    <strong title={item.message}>{item.message}</strong>
                    <code title={item.code}>{item.code}</code>
                  </div>
                ))}
              </div>
            </section>
          )}
        </main>
      </TaskLayout>
    </div>
  )
}
