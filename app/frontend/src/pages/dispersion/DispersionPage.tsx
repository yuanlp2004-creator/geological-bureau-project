import { PageFileActions } from '../../components/PageFileActions'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { confirmAction } from '../../platform/dialogs'
import {
  RefreshCw
} from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  api,
  type DispersionCalibrationVersion,
  type DispersionLine,
  type DispersionOptions,
  type DispersionTask,
  type MethodRecord
} from '../../api'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { TaskLayout } from '../../layout/TaskLayout'
import { DispersionCalibration } from './DispersionCalibration'
import { DispersionLines } from './DispersionLines'
import { DispersionMonitor } from './DispersionMonitor'
import { DispersionSetup } from './DispersionSetup'
import { Props, runningStates, statusLabels } from './dispersionView'
import { useSpectroscopySession, type SpectroscopyMode } from '../acquisition/spectroscopySession'
import { SpectroscopyTaskDialog } from '../acquisition/SpectroscopyTaskDialog'
import { SpectroscopyTaskList } from '../acquisition/SpectroscopyTaskList'

export function DispersionPage({ token, canWrite, canExecute, canReadMethods = true, onToast, actionsTarget, onCaptureChange, view = 'capture' }: Props & {
  actionsTarget?: HTMLElement | null
  onCaptureChange?: (mode: SpectroscopyMode, capture: boolean) => void
  canReadMethods?: boolean
  view?: 'capture' | 'curve'
}) {
  const [options, setOptions] = useState<DispersionOptions | null>(null)
  const [tasks, setTasks] = useState<DispersionTask[]>([])
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [active, setActive] = useState<DispersionTask | null>(null)
  const [screen, setScreen] = useState<'tasks' | 'capture'>('tasks')
  const [createOpen, setCreateOpen] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  useLayoutEffect(() => {
    onCaptureChange?.('dispersion', view === 'capture' && screen === 'capture')
  }, [view, screen, onCaptureChange])
  const [profileId, setProfileId] = useState<number | null>(null)
  const [layoutId, setLayoutId] = useState<number | null>(null)
  const [legacySource, setLegacySource] = useState('')
  const [preSeconds, setPreSeconds] = useState(3)
  const [samplingPeriod, setSamplingPeriod] = useState(1)
  const [lockedPoint, setLockedPoint] = useState<number | null>(null)
  const [manualLine, setManualLine] = useState<number | null>(null)
  const [frameCount, setFrameCount] = useState(3)
  const [darkFrameCount, setDarkFrameCount] = useState(1)
  const defaultsLoaded = useRef(false)
  const [selectedCcd, setSelectedCcd] = useState(0)
  useEffect(() => {
    setLockedPoint(null)
    setManualLine(null)
  }, [active?.id, selectedCcd])
  const [element, setElement] = useState('Fe')
  const [wavelength, setWavelength] = useState(253.65)
  const [lineCcd, setLineCcd] = useState(0)
  const [calibrationName, setCalibrationName] = useState('S12 色散曲线')
  const [bindMethodId, setBindMethodId] = useState<number | null>(null)
  const [autoRun, setAutoRun] = useState(false)
  const [busy, setBusy] = useState(false)
  const runningTask = tasks.find((task) => !['draft', 'completed', 'failed', 'stopped'].includes(task.status))
  const embedded = useSpectroscopySession('dispersion', runningTask
    ? `色散摄谱任务“${runningTask.name}”尚未结束，请完成或停止后切换摄谱方式。`
    : busy ? '色散摄谱操作尚未完成，请稍后切换摄谱方式。' : null)
  useEffect(() => {
    if (view !== 'capture' || !runningTask) return
    setActive(current => current?.id === runningTask.id ? current : runningTask)
    setScreen('capture')
    setCreateOpen(false)
  }, [runningTask, view])

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
    return () => {
      mounted.current = false
      generation.current++
      stopIntent.current = true
    }
  }, [token])
  const applyTask = (task: DispersionTask) => {
    setActive(task)
    setTasks((items) =>
      items.some((item) => item.id === task.id)
        ? items.map((item) => (item.id === task.id ? task : item))
        : [task, ...items]
    )
  }
  const perform = async (work: () => Promise<DispersionTask>, message = '') => {
    if (operation.current) {
      onToast('上一操作仍在完成，请稍后重试')
      return
    }
    const valid = ticket()
    setBusy(true)
    const pending = work()
    operation.current = pending
    try {
      const task = await pending
      if (!valid()) return
      applyTask(task)
      if (!runningStates.has(task.status)) setAutoRun(false)
      if (message) onToast(message)
      return task
    } catch (error) {
      if (valid()) {
        setAutoRun(false)
        onToast(error instanceof Error ? error.message : '色散操作失败')
      }
    } finally {
      if (operation.current === pending) operation.current = null
      if (valid()) setBusy(false)
    }
  }
  const choose = async (task: DispersionTask) => {
    generation.current++
    stopIntent.current = true
    setAutoRun(false)
    setBusy(false)
    setActive(task)
    const valid = ticket()
    try {
      const fresh = await api.dispersionTask(token, task.id)
      if (valid()) applyTask(fresh)
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '读取任务失败')
    }
  }
  const loadRequest = useRef(0)
  const load = useCallback(async () => {
    const current = ticket(),
      requestId = ++loadRequest.current
    const valid = () => current() && requestId === loadRequest.current
    setBusy(true)
    try {
      const [nextOptions, nextTasks, nextMethods] = await Promise.all([
        api.dispersionOptions(token),
        api.dispersionTasks(token),
        view === 'curve' && canReadMethods ? api.methods(token) : Promise.resolve([])
      ])
      if (!valid()) return
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
      setProfileId((current) => current ?? nextOptions.device_profiles[0]?.id ?? null)
      setLayoutId((current) => current ?? nextOptions.ccd_layouts[0]?.id ?? null)
      setBindMethodId((current) => current ?? nextMethods.find((item) => item.current_version !== null)?.id ?? null)
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '无法读取色散任务')
    } finally {
      if (valid()) setBusy(false)
    }
  }, [canReadMethods, onToast, token, view])

  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    if (!active || !active.ccd_indices.includes(selectedCcd)) setSelectedCcd(active?.ccd_indices[0] ?? 0)
    if (!active || !active.ccd_indices.includes(lineCcd)) setLineCcd(active?.ccd_indices[0] ?? 0)
  }, [active, lineCcd, selectedCcd])
  useEffect(() => {
    if (!autoRun || !active || !runningStates.has(active.status) || busy || stopIntent.current) return
    const timer = window.setTimeout(() => {
      if (!stopIntent.current) void perform(() => api.stepDispersionTask(token, active.id))
    }, 850)
    return () => window.clearTimeout(timer)
  }, [active, autoRun, busy, token])

  const currentCcd =
    active?.last_event?.ccds.find((item) => item.ccd_index === selectedCcd) ?? active?.last_event?.ccds[0]
  const latestCalibration = active?.calibrations[0] ?? null

  const saveConditions = async () => {
    if (!canWrite || busy) return
    if (!reportInvalidNumericInput(document.querySelector('.dispersion-number-grid'))) return onToast('请先修正激发参数')
    setBusy(true)
    try {
      await api.saveDispersionDefaults(token, { pre_excitation_seconds: preSeconds,
        sampling_period_seconds: samplingPeriod, frame_count: frameCount, dark_frame_count: darkFrameCount })
      onToast('色散激发条件已保存，下次新建时自动载入')
    } catch (error) { onToast(error instanceof Error ? error.message : '保存激发条件失败') }
    finally { setBusy(false) }
  }
  const createTask = async () => {
    if (runningTask) return onToast('当前任务尚未结束，请先完成或停止摄谱')
    if (!canWrite || profileId === null || layoutId === null) return
    if (!reportInvalidNumericInput(document.querySelector('.dispersion-number-grid')))
      return onToast('请先修正采集参数')
    setCreateError(null)
    const created = await perform(
      () =>
        api.createDispersionTask(token, {
          name: `色散采集 ${new Date().toLocaleTimeString('zh-CN')}`,
          device_profile_id: profileId,
          ccd_layout_id: layoutId,
          source_record_id: legacySource ? Number(legacySource) : undefined,
          frame_count: frameCount,
          dark_frame_count: darkFrameCount,
          pre_excitation_seconds: preSeconds,
          sampling_period_seconds: samplingPeriod,
          sample: '280-288.acq',
          seed: 12
        }),
      '色散任务已创建'
    )
    if (created) { setCreateOpen(false); setScreen('capture') }
    else setCreateError('任务未创建，参数已保留，请检查错误提示后重试。')
  }
  const formalTask = active?.condition.preheat
    ? tasks.find((task) => task.id === active.condition.preheat_source_task_id) : active
  const start = async () => {
    if (!formalTask || !canExecute) return
    stopIntent.current = false
    const next = await perform(() => api.startDispersionTask(token, formalTask.id), '试样摄谱已开始')
    if (next && !stopIntent.current) setAutoRun(true)
  }
  const preheat = async () => {
    if (!active || !canExecute || !canWrite) return
    stopIntent.current = false
    const next = await perform(() => api.preheatDispersionTask(token, active.id), '预热摄谱已开始')
    if (next && !stopIntent.current) setAutoRun(true)
  }
  const resume = async () => {
    if (!active || !canExecute) return
    stopIntent.current = false
    const next = await perform(() => api.resumeDispersionTask(token, active.id), '采集已继续')
    if (next && !stopIntent.current) setAutoRun(true)
  }
  const halt = async (mode: 'pause' | 'stop') => {
    if (!active || !canExecute) return
    const taskId = active.id,
      valid = ticket()
    stopIntent.current = true
    setAutoRun(false)
    // Preserve this explicit command even when a frame is still awaiting a response.
    await operation.current?.catch(() => { })
    try {
      const task = await (mode === 'stop' ? api.stopDispersionTask : api.pauseDispersionTask)(token, taskId)
      if (valid()) {
        applyTask(task)
        onToast(mode === 'stop' ? '采集已安全收尾' : '采集已暂停')
      }
    } catch (error) {
      if (valid()) onToast(error instanceof Error ? error.message : '停止操作失败，请重试')
    }
  }
  const pause = () => halt('pause')
  const stop = () => halt('stop')
  const change = (work: (id: number) => Promise<unknown>, message = '') => {
    if (!active || !canWrite) return
    const id = active.id
    return perform(async () => {
      await work(id)
      return api.dispersionTask(token, id)
    }, message)
  }
  const addLine = () => {
    if (!reportInvalidNumericInput(document.querySelector('.dispersion-line-form'))) return onToast('请先修正谱线波长')
    return change(
      (id) => api.addDispersionLine(token, id, { element, wavelength_nm: wavelength, ccd_index: lineCcd }),
      '谱线已添加'
    )
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
  const locateAll = () => change((id) => api.locateAllDispersionLines(token, id), '定位结果已刷新，请检查各谱线状态')
  const removeLine = (lineId: number) => change((id) => api.deleteDispersionLine(token, id, lineId))
  const fit = () =>
    change((id) => api.fitDispersionCalibration(token, id, { name: calibrationName, degree: 2, use_legacy_limit: true }), '拟合结果已刷新')
  const publish = (calibration: DispersionCalibrationVersion) =>
    change(() => api.publishDispersionCalibration(token, calibration.id), '不可变色散曲线版本已发布')
  const bind = () => {
    if (!latestCalibration || bindMethodId === null) return
    const method = methods.find((item) => item.id === bindMethodId)
    return change(
      () =>
        api.bindDispersionCalibration(token, latestCalibration.id, bindMethodId, method?.current_version ?? undefined),
      '色散曲线版本已绑定'
    )
  }

  const monitor = <DispersionMonitor view={view} active={active} start={start} preheat={preheat}
            canStart={Boolean(formalTask && !formalTask.condition.preheat && formalTask.status === 'draft')}
            canPreheat={canWrite && Boolean(active && ['draft', 'completed', 'failed', 'stopped'].includes(active.status))}
            canExecute={canExecute && (!runningTask || active?.id === runningTask.id)} pause={pause} resume={resume}
            busy={busy} stop={stop} selectedCcd={selectedCcd} setSelectedCcd={setSelectedCcd}
            currentCcd={currentCcd} lockedPoint={lockedPoint} manualLine={manualLine} setManualLine={setManualLine}
            canWrite={canWrite} change={change} token={token} setLockedPoint={setLockedPoint}
            />

  const fileActions = <PageFileActions target={actionsTarget}>
        {view === 'curve' && <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="dispersion" label="打开色散文件" disabled={busy || Boolean(runningTask)} onOpened={async result => {
        await load()
        if (result.task_ids?.[0]) await choose(await api.dispersionTask(token, result.task_ids[0]))
      }}/>}
        <button className="secondary-button" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={15} className={busy ? 'spin' : ''} />
          刷新
        </button>
      </PageFileActions>

  if (view === 'capture') return <div className={`${embedded ? 'spectroscopy-mode-content' : 'page-content'} dispersion-page refined-page remaining-page`}
    data-testid="dispersion-page" data-view={view} data-stage={screen}>
    <PageFileActions target={actionsTarget}>
      {screen === 'capture' ? <button type="button" className="secondary-button" disabled={busy || Boolean(runningTask)}
        onClick={() => { if (!runningTask && !busy) setScreen('tasks') }}>返回任务列表</button> : <>
        <button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={15} />刷新</button>
        <button type="button" className="primary-button" disabled={!canWrite || busy || Boolean(runningTask)}
          onClick={() => setCreateOpen(true)}>新建任务</button>
      </>}
    </PageFileActions>
    <SpectroscopyTaskDialog open={createOpen} title="建立色散摄谱任务" busy={busy} error={createError} onCancel={() => setCreateOpen(false)}
      actions={<button type="button" className="primary-button" disabled={!canWrite || busy || profileId === null || layoutId === null}
        onClick={() => void createTask()}>新建任务</button>}>
      <DispersionSetup legacySource={legacySource} setLegacySource={setLegacySource} options={options}
        profileId={profileId} setProfileId={setProfileId} layoutId={layoutId} setLayoutId={setLayoutId}
        preSeconds={preSeconds} setPreSeconds={setPreSeconds} samplingPeriod={samplingPeriod} setSamplingPeriod={setSamplingPeriod}
        frameCount={frameCount} setFrameCount={setFrameCount} darkFrameCount={darkFrameCount} setDarkFrameCount={setDarkFrameCount}
        createTask={createTask} saveConditions={saveConditions} canWrite={canWrite && !busy && !runningTask} busy={busy} hideSubmit />
    </SpectroscopyTaskDialog>
    {screen === 'tasks' && <SpectroscopyTaskList title="色散摄谱" busy={busy} runningId={runningTask?.id}
      tasks={tasks.map(task => ({ id: task.id, name: task.name, status: statusLabels[task.status],
        details: `${task.layout.name} · ${task.burn_frames_captured}/${task.frame_count} 燃烧帧${task.condition.preheat ? ' · 预热' : ''}`,
        completed: task.status === 'completed' }))}
      onChoose={id => {
        const task = tasks.find(item => item.id === id)
        if (task && !busy && (!runningTask || runningTask.id === id)) { void choose(task); setScreen('capture') }
      }} />}
    <main className="dispersion-main spectroscopy-capture-page" data-capture-screen hidden={screen !== 'capture'}>{monitor}</main>
  </div>

  return (
    <div className={`${embedded ? 'spectroscopy-mode-content' : 'page-content'} dispersion-page refined-page remaining-page`} data-testid="dispersion-page" data-view={view}>
      {!embedded && <section className="page-action-toolbar">
        

        {fileActions}
      </section>}
      {embedded && view === 'curve' && fileActions}

      <TaskLayout
        showEmptyRail
        actions={embedded && view !== 'curve' && <button className="secondary-button" onClick={() => void load()} disabled={busy}>
          <RefreshCw size={15} className={busy ? 'spin' : ''} />刷新
        </button>}
        className="dispersion-shell"
        hasItems={Boolean(tasks.length)}
        current={active ? `${active.name} · ${statusLabels[active.status] ?? active.status}` : '尚未选择'}
      >
        <aside className="surface dispersion-sidebar">
          <div className="surface-heading"><h2>色散任务 <span className="count-badge">{tasks.length}</span></h2></div>
          <div className="dispersion-task-list">
            {tasks.length === 0 ? <small>尚无色散任务</small> : tasks.map((task) => (
              <button key={task.id} className={active?.id === task.id ? 'active' : ''}
                disabled={busy || Boolean(runningTask && runningTask.id !== task.id)} onClick={() => void choose(task)}>
                <span className={`dispersion-state ${task.status}`} /><strong title={task.name}>{task.name}</strong>
                <small>{statusLabels[task.status]} · {task.burn_frames_captured}/{task.frame_count}</small>
              </button>
            ))}
          </div>
        </aside>
        <main className="dispersion-main">
          {monitor}
      {view === 'curve' && <section className="surface spectroscopy-calibration-versions">
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
      </section>}
          {view === 'curve' && active && (
            <DispersionLines
              locateAll={locateAll}
              canWrite={canWrite && !busy}
              active={active}
              element={element}
              setElement={setElement}
              wavelength={wavelength}
              setWavelength={setWavelength}
              lineCcd={lineCcd}
              setLineCcd={setLineCcd}
              addLine={addLine}
              updateLine={updateLine}
              removeLine={removeLine}
              changeWavelength={(lineId, value) => {
                if (!reportInvalidNumericInput(document.querySelector('.dispersion-lines-panel'))) return onToast('请先修正波长或间隔')
                void change(() => api.updateDispersionWavelength(token,active.id,lineId,value),'波长已更新，请重新拟合')
              }}
              changeGap={(gap, value) => {
                if (!reportInvalidNumericInput(document.querySelector('.dispersion-lines-panel'))) return onToast('请先修正波长或间隔')
                void change(async () => {
                  await api.updateDispersionGap(token,active.id,gap,value)
                  if (active.lines.filter(line=>line.saved_position!=null || line.located_position!=null).length>=3)
                    await api.fitDispersionCalibration(token,active.id,{ name: calibrationName || active.name, degree: 2, use_legacy_limit: true })
                },'CCD 间隔已修正；定位点充足时已重新拟合')
              }}
            />
          )}
          {view === 'curve' && active && (
            <DispersionCalibration
              calibrationName={calibrationName}
              setCalibrationName={setCalibrationName}
              fit={fit}
              canWrite={canWrite}
              active={active}
              latestCalibration={latestCalibration}
              publish={publish}
              bindMethodId={bindMethodId}
              setBindMethodId={setBindMethodId}
              methods={methods}
              bind={bind}
            />
          )}
        </main>
      </TaskLayout>
    </div>
  )
}
