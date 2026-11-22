import { ensureCaptureConnection } from '../acquisition/captureConnection'
import { RefreshCw } from 'lucide-react'
import { createPortal } from 'react-dom'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { api, type DeviceProfile, type HardwareOptions, type HardwareTask } from '../../api'
import { AdvancedSettings } from '../../components/AdvancedSettings'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'
import { SpectroscopyTaskDialog } from '../acquisition/SpectroscopyTaskDialog'
import { SpectroscopyTaskList } from '../acquisition/SpectroscopyTaskList'
import { HardwareAcquisitionForm, type ManualTurnDraft } from './HardwareAcquisitionForm'
import { HardwareAcquisitionMonitor } from './HardwareAcquisitionMonitor'
import { HardwareAcquisitionPlan } from './HardwareAcquisitionPlan'
import { HardwareSpectrum } from './HardwareSpectrum'
import { HardwareAnalysisSamplePanel } from './HardwareAnalysisSamplePanel'
import { Props, activeStates, labels, terminalStates } from './hardwareView'

export function HardwareAcquisitionPage({ token, canWrite, canExecute, canSaveSample = false,
  actionsTarget, currentMethodId, onLockChange, onToast }: Props) {
  const [options, setOptions] = useState<HardwareOptions | null>(null)
  const [tasks, setTasks] = useState<HardwareTask[]>([])
  const [selected, setSelected] = useState<HardwareTask | null>(null)
  const [screen, setScreen] = useState<'tasks' | 'capture'>('tasks')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [controlError, setControlError] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const request = useRef(false)
  const mounted = useRef(true)
  const [auto, setAuto] = useState(false)
  const [name, setName] = useState('自动转角任务')
  const [sampleName, setSampleName] = useState('')
  const [currentProfile, setCurrentProfile] = useState<DeviceProfile | null>(null)
  const [layoutId, setLayoutId] = useState('default')
  const [strategy, setStrategy] = useState<'short_to_long' | 'key_first'>('short_to_long')
  const [policy, setPolicy] = useState<'retry_then_stop' | 'manual'>('retry_then_stop')
  const [retryLimit, setRetryLimit] = useState(1)
  const [sample, setSample] = useState('280-288.acq')
  const [seed, setSeed] = useState(14)
  const [methodSelection, setMethodSelection] = useState('')
  const [mode, setMode] = useState<'automatic' | 'manual'>('automatic')
  const [manualTurns, setManualTurns] = useState<ManualTurnDraft[]>([{ id: 1, angle_deg: null, duration_seconds: 10 }])
  const [anomalies, setAnomalies] = useState('[]')
  const [interventionNote, setInterventionNote] = useState('')
  const [viewStep, setViewStep] = useState<number | null>(null)
  const desk = useRef<HTMLDivElement>(null)
  const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(null)
  useLayoutEffect(() => {
    const element = desk.current
    if (!element) return
    const page = element.closest<HTMLElement>('.hardware-page')
    const viewport = element.closest('.page-scroll-region')
    let frame = 0
    const resize = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const bottom = viewport?.getBoundingClientRect().bottom ?? window.innerHeight
        const spacing = page ? Number.parseFloat(getComputedStyle(page).paddingBottom) : 8
        element.style.height = `${Math.max(360, Math.floor(bottom - element.getBoundingClientRect().top - spacing))}px`
      })
    }
    const observer = new ResizeObserver(resize)
    const messages = document.querySelector('[data-testid="runtime-messages"]')
    if (messages) observer.observe(messages)
    if (viewport) observer.observe(viewport)
    window.addEventListener('resize', resize); resize()
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', resize) }
  }, [screen, selected?.id])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const remember = useCallback((next: HardwareTask) => {
    if (!mounted.current) return
    setSelected(next)
    setTasks(current => [next, ...current.filter(item => item.id !== next.id)])
  }, [])
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextOptions, nextTasks, profile] = await Promise.all([
        api.hardwareAcquisitionOptions(token), api.hardwareAcquisitionTasks(token), api.currentDeviceProfile(token)
      ])
      if (!mounted.current) return
      setOptions(nextOptions); setTasks(nextTasks)
      setCurrentProfile(profile)
      setLayoutId(current => current !== 'default' ? current : String(nextOptions.layouts[0]?.id ?? 'default'))
      setMethodSelection(current => {
        const method = nextOptions.methods.find(item => item.method_id === currentMethodId) ?? nextOptions.methods[0]
        return current || (method ? `${method.method_id}-${method.version}` : '')
      })
      setSelected(current => current ? nextTasks.find(item => item.id === current.id) ?? current : null)
    } catch (error) { setCurrentProfile(null); onToast(error instanceof Error ? error.message : '无法读取自动转角配置') }
    finally { if (mounted.current) setLoading(false) }
  }, [currentMethodId, onToast, token])
  useEffect(() => { void load() }, [load])

  // Automatic steps and manual commands share one request lock.
  const control = useCallback(async (action: 'start' | 'step' | 'pause' | 'resume' | 'stop' | 'accept' | 'retry') => {
    if (!selected || request.current || !canExecute) return
    request.current = true; setBusy(true); setControlError('')
    try {
      const methods = { start: api.startHardwareAcquisitionTask, step: api.stepHardwareAcquisitionTask,
        pause: api.pauseHardwareAcquisitionTask, resume: api.resumeHardwareAcquisitionTask, stop: api.stopHardwareAcquisitionTask }
      const next = action === 'accept' || action === 'retry'
        ? await api.interveneHardwareAcquisitionTask(token, selected.id, action, interventionNote.trim())
        : action === 'step' && selected.execution_mode === 'manual'
          ? await api.hardwareAcquisitionTask(token, selected.id) : await methods[action](token, selected.id)
      remember(next)
      if (!mounted.current) return
      setAuto(activeStates.has(next.status) && action !== 'pause' && action !== 'stop')
      if (action === 'accept' || action === 'retry') setInterventionNote('')
    } catch (error) {
      if (!mounted.current) return
      setAuto(false)
      const message = error instanceof Error ? error.message : '采集操作失败，请重试或停止采集'
      setControlError(message); onToast(message)
      // A response can be lost after the command commits. Read its actual state before retrying.
      try { remember(await api.hardwareAcquisitionTask(token, selected.id)) } catch { /* Keep the retry and stop actions available. */ }
    } finally { request.current = false; if (mounted.current) setBusy(false) }
  }, [canExecute, interventionNote, onToast, remember, selected, token])
  useEffect(() => {
    if (!auto || !selected || !canExecute || !activeStates.has(selected.status) || busy) return
    const timer = window.setTimeout(() => { void control('step') }, selected.execution_mode === 'manual' ? 100 : 450)
    return () => window.clearTimeout(timer)
  }, [auto, busy, canExecute, control, selected])
  const running = tasks.find(task => !terminalStates.has(task.status) && task.status !== 'draft')
  const locked = busy || Boolean(selected && selected.status !== 'draft' && !terminalStates.has(selected.status))
  useLayoutEffect(() => {
    onLockChange?.(screen === 'capture' && locked ? '请先停止当前自动转角采集，再切换页面。' : null)
    return () => onLockChange?.(null)
  }, [locked, onLockChange, screen])
  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canWrite || request.current) return
    setCreateError(null)
    const manual = mode === 'manual'
    try {
      if (!methodSelection) throw new Error('请选择已发布方法')
      if (manual) {
        const method = options?.methods.find(item => `${item.method_id}-${item.version}` === methodSelection)
        if (!method?.turn_angles?.length) throw new Error('所选方法未配置转角，请先完善方法')
        if (manualTurns.some(row => row.angle_deg === null || !method.turn_angles?.includes(row.angle_deg)))
          throw new Error('请为每行选择所选方法中的对应转角')
      }
    } catch (error) { setCreateError(error instanceof Error ? error.message : '调试参数无法解析'); return }
    request.current = true; setBusy(true)
    try {
      const profile = await api.currentDeviceProfile(token)
      setCurrentProfile(profile)
      if (!profile) throw new Error('请先在设备参数中选择通讯口，或勾选模拟设备用于测试')
      const anomalyPayload: unknown = profile.transport === 'simulator' ? JSON.parse(anomalies) : []
      if (!Array.isArray(anomalyPayload)) throw new Error('模拟异常脚本必须是数组')
      const [methodId, version] = methodSelection.split('-').map(Number)
      await ensureCaptureConnection(token, profile.id, profile.transport, 'hardware-acquisition')
      const next = await api.createHardwareAcquisitionTask(token, {
        name: name.trim(), sample_name: sampleName.trim(), device_profile_id: profile.id, ccd_layout_id: layoutId,
        execution_mode: mode, manual_turns: manual ? manualTurns.map(({ angle_deg, duration_seconds }) => ({ angle_deg, duration_seconds })) : [],
        strategy: manual ? 'short_to_long' : strategy, anomaly_policy: policy, retry_limit: retryLimit, simulator_sample: sample, seed,
        method_id: methodId, method_version: version,
        simulator_anomalies: anomalyPayload
      })
      remember(next); setAuto(false); setViewStep(null); setControlError(''); setCreating(false); setScreen('capture')
      onToast('任务已建立，点击“开始采集”执行全部转角')
    } catch (error) { setCreateError(error instanceof Error ? error.message : '创建自动转角任务失败') }
    finally { request.current = false; if (mounted.current) setBusy(false) }
  }
  const choose = async (id: number) => {
    if (request.current || (running && running.id !== id)) return
    request.current = true; setBusy(true)
    try {
      const task = await api.hardwareAcquisitionTask(token, id)
      if (['draft','ready'].includes(task.status))
        await ensureCaptureConnection(token, task.device_profile_id, task.transport, 'hardware-acquisition')
      remember(task)
      setAuto(false); setViewStep(null); setControlError(''); setInterventionNote(''); setScreen('capture')
    } catch (error) { onToast(error instanceof Error ? error.message : '读取转角任务失败') }
    finally { request.current = false; if (mounted.current) setBusy(false) }
  }
  const finish = () => { if (!locked) { setAuto(false); setScreen('tasks'); void load() } }
  const actions = screen === 'tasks' ? <div className="file-actions">
    <button className="secondary-button" onClick={() => void load()} disabled={loading || busy}><RefreshCw size={15} />刷新</button>
    <button className="primary-button" disabled={!canWrite || busy || loading || Boolean(running)} onClick={() => { setCreateError(null); setCreating(true); void load() }}>
      <SpectroscopyIcon name="sample-input" />新建任务</button>
  </div> : <button className="secondary-button" onClick={finish} disabled={locked}>
    <SpectroscopyIcon name="finish" />返回任务列表</button>
  return <div className="page-content hardware-page refined-page remaining-page" data-testid="hardware-acquisition-page" data-stage={screen}>
    {actionsTarget ? createPortal(actions, actionsTarget) : <div className="hardware-page-actions">{actions}</div>}
    {screen === 'tasks' ? <SpectroscopyTaskList title="自动转角" busy={busy || loading} runningId={running?.id}
      tasks={tasks.map(task => ({ id: task.id, name: task.name, status: labels[task.status] ?? task.status,
        details: `${task.sample_name || '未命名样品'} · ${task.total_steps} 个转角 · ${task.execution_mode === 'manual' ? '手动顺序' : task.strategy === 'key_first' ? '关键波段优先' : '短波 → 长波'} · ${task.transport === 'simulator' ? '模拟设备' : '串口设备'}`,
        completed: terminalStates.has(task.status) }))} onChoose={id => { void choose(id) }} />
      : selected && <>
        <div ref={desk} className="hardware-capture-desk">
          <header className="hardware-desk-caption"><span>自动转角</span><strong title={selected.name}>{selected.name}</strong>
            <span>{selected.method_id ? `${selected.execution_mode === 'manual' ? '手动 · ' : ''}方法 v${selected.method_version}` : selected.execution_mode === 'manual' ? '手动计划' : '独立调试'}</span></header>
          <div ref={setToolbarTarget} className="hardware-desk-toolbar" aria-label="转角谱图选择" />
          <div className="hardware-desk-body">
            <HardwareAcquisitionPlan selected={selected} viewStep={viewStep} onChoose={setViewStep} />
            <HardwareSpectrum key={selected.id} token={token} selected={selected} viewStep={viewStep}
              toolbarTarget={toolbarTarget} onFollow={() => setViewStep(null)} />
            <HardwareAcquisitionMonitor selected={selected} control={control} busy={busy} canExecute={canExecute}
              auto={auto} controlError={controlError} interventionNote={interventionNote} setInterventionNote={setInterventionNote}>
              {selected.method_id && selected.status === 'completed' && <AdvancedSettings title="保存分析样品">
                <HardwareAnalysisSamplePanel key={selected.id} token={token} task={selected} canSave={canSaveSample} onSaved={load} onToast={onToast} />
              </AdvancedSettings>}
            </HardwareAcquisitionMonitor>
          </div>
          <footer className="hardware-desk-status" aria-label="自动转角状态">
            <span>{labels[selected.status]} · 已完成 {selected.completed_steps} / {selected.total_steps} 个转角</span>
            <progress value={selected.progress} max={100} aria-label="转角总进度" />
            <span>{selected.execution_mode === 'manual' ? '手动顺序' : selected.strategy === 'key_first' ? '关键波段优先' : '短波 → 长波'}</span>
            <span>{selected.transport === 'simulator' ? '模拟设备' : '串口设备'} · 原始帧 {selected.frames.length}</span>
          </footer>
        </div>
      </>}
    <SpectroscopyTaskDialog open={creating} title="新建自动转角任务" busy={busy} error={createError}
      onCancel={() => { if (!busy) setCreating(false) }} actions={<button className="primary-button" type="submit"
        form="hardware-task-form" disabled={!canWrite || busy || loading}>{busy ? '建立中…' : '建立任务'}</button>}>
      <HardwareAcquisitionForm create={create} name={name} setName={setName} sampleName={sampleName} setSampleName={setSampleName}
        mode={mode} setMode={setMode} manualTurns={manualTurns} setManualTurns={setManualTurns}
        canWrite={canWrite} busy={busy || loading} options={options}
        layoutId={layoutId} setLayoutId={setLayoutId} strategy={strategy} setStrategy={setStrategy}
        policy={policy} setPolicy={setPolicy} retryLimit={retryLimit} setRetryLimit={setRetryLimit}
        sample={sample} setSample={setSample} seed={seed} setSeed={setSeed}
        anomalies={anomalies} setAnomalies={setAnomalies} selectedProfile={currentProfile ?? undefined}
        methodSelection={methodSelection} setMethodSelection={setMethodSelection} />
    </SpectroscopyTaskDialog>
  </div>
}
