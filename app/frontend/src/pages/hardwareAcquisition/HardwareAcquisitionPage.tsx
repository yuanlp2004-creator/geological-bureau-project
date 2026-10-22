import { Activity, ChevronRight, RefreshCw, RotateCcw, ShieldAlert, SquareTerminal } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type HardwareOptions, type HardwareTask } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { FormDisclosure, TaskLayout } from '../../layout/TaskLayout'
import { HardwareAcquisitionForm } from './HardwareAcquisitionForm'
import { HardwareAcquisitionMonitor } from './HardwareAcquisitionMonitor'
import { HardwareAcquisitionPlan } from './HardwareAcquisitionPlan'
import { HardwareSpectrum } from './HardwareSpectrum'
import { HardwareAnalysisSamplePanel } from './HardwareAnalysisSamplePanel'
import { Props, activeStates, defaultTurns, labels, terminalStates } from './hardwareView'
export function HardwareAcquisitionPage({ token, canWrite, canExecute, canSaveSample = false, onToast }: Props) {
  const [options, setOptions] = useState<HardwareOptions | null>(null)

  const [tasks, setTasks] = useState<HardwareTask[]>([])

  const [selected, setSelected] = useState<HardwareTask | null>(null)

  const [createError, setCreateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)

  const [busy, setBusy] = useState(false)

  const busyRef = useRef(false)

  const [auto, setAuto] = useState(false)

  const [name, setName] = useState('自动转角任务')

  const [profileId, setProfileId] = useState<number | null>(null)

  const [layoutId, setLayoutId] = useState<string>('default')

  const [strategy, setStrategy] = useState<'short_to_long' | 'key_first'>('short_to_long')

  const [policy, setPolicy] = useState<'retry_then_stop' | 'manual'>('retry_then_stop')

  const [retryLimit, setRetryLimit] = useState(1)

  const [sample, setSample] = useState('280-288.acq')

  const [seed, setSeed] = useState(14)

  const [turns, setTurns] = useState(defaultTurns)

  const [methodSelection, setMethodSelection] = useState('')
  const [anomalies, setAnomalies] = useState('[]')

  const [interventionNote, setInterventionNote] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextOptions, nextTasks] = await Promise.all([
        api.hardwareAcquisitionOptions(token),
        api.hardwareAcquisitionTasks(token)
      ])

      setOptions(nextOptions)
      setTasks(nextTasks)
      setProfileId((current) => current ?? nextOptions.profiles[0]?.id ?? null)
      setLayoutId((current) =>
        current !== 'default' ? current : String(nextOptions.layouts[0]?.id ?? 'default')
      )
      setSelected((current) =>
        current ? (nextTasks.find((item) => item.id === current.id) ?? current) : (nextTasks[0] ?? null)
      )
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取自动转角配置')
    } finally {
      setLoading(false)
    }
  }, [onToast, token])

  useEffect(() => {
    void load()
  }, [load])
  const refreshSelected = useCallback(async () => {
    if (!selected) return
    try {
      const next = await api.hardwareAcquisitionTask(token, selected.id)

      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法刷新硬件任务')
    }
  }, [onToast, selected, token])

  const advance = useCallback(async () => {
    if (!selected || busyRef.current || !activeStates.has(selected.status)) return
    busyRef.current = true
    try {
      const next = await api.stepHardwareAcquisitionTask(token, selected.id)

      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      if (terminalStates.has(next.status) || next.status === 'manual_intervention') setAuto(false)
    } catch (error) {
      setAuto(false)
      onToast(error instanceof Error ? error.message : '自动转角推进失败')
    } finally {
      busyRef.current = false
    }
  }, [onToast, selected, token])

  useEffect(() => {
    if (!auto || !selected || !activeStates.has(selected.status)) return
    const timer = window.setInterval(() => {
      void advance()
    }, 450)

    return () => window.clearInterval(timer)
  }, [advance, auto, selected])
  const apply = async (action: 'start' | 'step' | 'pause' | 'resume' | 'stop') => {
    if (!selected) return
    if (action !== 'step' && !canExecute) {
      onToast('当前账户没有硬件执行权限')
      return
    }
    setBusy(true)
    try {
      const methods = {
        start: api.startHardwareAcquisitionTask,
        step: api.stepHardwareAcquisitionTask,
        pause: api.pauseHardwareAcquisitionTask,
        resume: api.resumeHardwareAcquisitionTask,
        stop: api.stopHardwareAcquisitionTask
      }

      const next = await methods[action](token, selected.id)

      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      if (terminalStates.has(next.status) || next.status === 'manual_intervention' || action === 'stop')
        setAuto(false)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '硬件任务控制失败')
    } finally {
      setBusy(false)
    }
  }

  const intervene = async (action: 'accept' | 'retry' | 'stop') => {
    if (!selected || !canExecute) return onToast('当前账户没有硬件执行权限')
    setBusy(true)
    try {
      const next = await api.interveneHardwareAcquisitionTask(
        token,
        selected.id,
        action,
        interventionNote.trim()
      )

      setSelected(next)
      setTasks((current) => current.map((item) => (item.id === next.id ? next : item)))
      setInterventionNote('')
      onToast(
        action === 'accept' ? '人工确认已记录' : action === 'retry' ? '人工重试已排程' : '任务已安全停止'
      )
    } catch (error) {
      onToast(error instanceof Error ? error.message : '人工接管操作失败')
    } finally {
      setBusy(false)
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canWrite) return onToast('当前账户没有硬件任务写入权限')
    let turnPayload: unknown
    let anomalyPayload: unknown
    try {
      turnPayload = JSON.parse(turns)
      anomalyPayload = JSON.parse(anomalies)
      if (!Array.isArray(turnPayload) || !turnPayload.length || !Array.isArray(anomalyPayload))
        throw new Error('转角计划和异常脚本必须是数组')
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : '转角 JSON 无法解析')
      onToast(error instanceof Error ? error.message : '转角 JSON 无法解析')
      return
    }
    setCreateError(null)
    setBusy(true)
    try {
      const next = await api.createHardwareAcquisitionTask(token, {
        name,
        device_profile_id: profileId,
        ccd_layout_id: layoutId,
        strategy,
        anomaly_policy: policy,
        retry_limit: retryLimit,
        sample_name: sample,
        simulator_sample: sample,
        seed,
        turns: methodSelection ? [] : turnPayload,
        method_id: methodSelection ? Number(methodSelection.split('-')[0]) : null,
        method_version: methodSelection ? Number(methodSelection.split('-')[1]) : null,
        simulator_anomalies: anomalyPayload
      })

      setTasks((current) => [next, ...current])
      setSelected(next)
      onToast('自动转角任务已创建，计划顺序已锁定')
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : '创建自动转角任务失败')
      onToast(error instanceof Error ? error.message : '创建自动转角任务失败')
    } finally {
      setBusy(false)
    }
  }

  const currentStep = selected?.steps.find((step) => step.order_index === selected.current_step_index)

  const selectedProfile = options?.profiles.find((profile) => profile.id === profileId)

  const latestDecision = selected?.decisions[selected.decisions.length - 1]

  const latestTrace = selected?.traces[selected.traces.length - 1]

  const isExternal = selected?.status === 'deferred_external'

  return (
    <div
      className="page-content hardware-page refined-page remaining-page"
      data-testid="hardware-acquisition-page"
    >
      
      <TaskLayout
        className="hardware-layout"
        hasItems={Boolean(tasks.length)}
        current={selected ? `${selected.name} · ${labels[selected.status] ?? selected.status}` : '尚未选择'}
       actions={<div className="file-actions"> <button className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
          刷新
        </button> </div>}>
        <aside className="surface hardware-task-list">
          <div className="surface-heading">
            <div>
              <h2>
                转角任务 <span className="count-badge">{tasks.length}</span>
              </h2>
            </div>
            <RotateCcw size={17} />
          </div>
          {tasks.length ? (
            <div className="hardware-task-rows">
              {tasks.map((task) => {
                const metadata = `${task.transport === 'serial' ? '真实串口' : '确定性模拟器'} · ${labels[task.status] ?? task.status}`

                return (
                  <button
                    key={task.id}
                    className={selected?.id === task.id ? 'active' : ''}
                    onClick={() => setSelected(task)}
                  >
                    <span className={`task-state-dot ${task.status}`} />
                    <span>
                      <strong title={task.name}>{task.name}</strong>
                      <small title={metadata}>{metadata}</small>
                    </span>
                    <ChevronRight size={14} />
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="empty-state compact-empty">暂无自动转角任务</div>
          )}
        </aside>
        <main className="hardware-main">
          <FormDisclosure
            title="建立转角与采集计划"
            error={createError}
            hasItems={Boolean(tasks.length)}
            objectKey={selected?.id}
          >
            <HardwareAcquisitionForm
              methodSelection={methodSelection}
              setMethodSelection={setMethodSelection}
              create={create}
              name={name}
              setName={setName}
              canWrite={canWrite}
              busy={busy}
              profileId={profileId}
              setProfileId={setProfileId}
              options={options}
              layoutId={layoutId}
              setLayoutId={setLayoutId}
              strategy={strategy}
              setStrategy={setStrategy}
              policy={policy}
              setPolicy={setPolicy}
              retryLimit={retryLimit}
              setRetryLimit={setRetryLimit}
              sample={sample}
              setSample={setSample}
              seed={seed}
              setSeed={setSeed}
              turns={turns}
              setTurns={setTurns}
              anomalies={anomalies}
              setAnomalies={setAnomalies}
              selectedProfile={selectedProfile}
            />
          </FormDisclosure>
          <HardwareAcquisitionMonitor
            selected={selected}
            apply={apply}
            busy={busy}
            canExecute={canExecute}
            setAuto={setAuto}
            auto={auto}
            currentStep={currentStep}
            isExternal={isExternal}
            interventionNote={interventionNote}
            setInterventionNote={setInterventionNote}
            intervene={intervene}
          />
          {selected && <HardwareAcquisitionPlan selected={selected} />}
          {selected && <HardwareAnalysisSamplePanel key={selected.id} token={token} task={selected}
            canSave={canSaveSample} onSaved={load} onToast={onToast} />}
          {selected && <HardwareSpectrum key={`${token}:${selected.id}`} token={token} selected={selected} />}
          {selected && (
            <section className="hardware-evidence-grid">
              <section className="surface">
                <div className="surface-heading">
                  <div>
                    <h2>
                      全部命令与响应 <span className="count-badge">{selected.traces.length}</span>
                    </h2>
                  </div>
                  <SquareTerminal size={16} />
                </div>
                <div className="evidence-list">
                  {[...selected.traces].reverse().map((trace, index) => (
                    <div className="evidence-row" key={`${String(trace.sequence_no)}-${index}`}>
                      <span className={`trace-kind ${String(trace.direction)}`}>{String(trace.kind)}</span>
                      <strong title={String(trace.name)}>{String(trace.name)}</strong>
                      <CopyableCode value={String(trace.payload_sha256 || '')} visibleLength={12} empty="—" />
                      <small title={String(trace.safe_state || '')}>{String(trace.safe_state || '')}</small>
                    </div>
                  ))}
                  {!selected.traces.length && <div className="empty-state compact-empty">暂无追踪记录</div>}
                </div>
              </section>
              <section className="surface">
                <div className="surface-heading">
                  <div>
                    <h2>
                      全部异常处置 <span className="count-badge">{selected.decisions.length}</span>
                    </h2>
                  </div>
                  <ShieldAlert size={16} />
                </div>
                <div className="evidence-list">
                  {[...selected.decisions].reverse().map((decision, index) => (
                    <div className="evidence-row" key={`${String(decision.id)}-${index}`}>
                      <span className={`trace-kind ${String(decision.decision)}`}>
                        {String(decision.decision)}
                      </span>
                      <strong title={String(decision.anomaly_kind || 'none')}>
                        {String(decision.anomaly_kind || 'none')}
                      </strong>
                      <small title={String(decision.reason || '')}>{String(decision.reason || '')}</small>
                    </div>
                  ))}
                  {!selected.decisions.length && (
                    <div className="empty-state compact-empty">暂无处置决定</div>
                  )}
                </div>
              </section>
            </section>
          )}
          {selected && latestTrace && (
            <div className="hardware-footer-note">
              <Activity size={14} />
              最近事件：{String(latestTrace.name)} ·{' '}
              {String(latestDecision?.reason || selected.last_message || '')}
            </div>
          )}
        </main>
      </TaskLayout>
    </div>
  )
}
