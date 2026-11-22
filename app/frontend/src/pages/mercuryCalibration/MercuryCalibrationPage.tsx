import {
  ChevronRight,
  FileCheck2,
  Lightbulb,
  RefreshCw,
  SquareTerminal
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type MercuryOptions, type MercurySession } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { PageFileActions } from '../../components/PageFileActions'
import { SpectrumInspector } from '../../components/SpectrumInspector'
import { DeviceDebugWorkbench } from '../devices/DeviceDebugWorkbench'
import { SpectroscopyTaskDialog } from '../acquisition/SpectroscopyTaskDialog'
import { RowSelectionArrow } from '../../components/RowSelectionArrow'
import { MercuryCalibrationForm } from './MercuryCalibrationForm'
import { MercuryCalibrationMonitor } from './MercuryCalibrationMonitor'
import { MercuryCalibrationResults } from './MercuryCalibrationResults'
import { Props, activeStates, labels, terminalStates } from './mercuryView'

export function MercuryCalibrationPage({ token, canWrite, canExecute, onToast, embedded = false, actionsTarget, active = true }: Props) {
  const [createOpen, setCreateOpen] = useState(false)
  const evidence = useRef<HTMLDialogElement>(null)
  const [options, setOptions] = useState<MercuryOptions | null>(null)
  const [sessions, setSessions] = useState<MercurySession[]>([])
  const [selected, setSelected] = useState<MercurySession | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [auto, setAuto] = useState(false)
  const [name, setName] = useState('汞灯光学校准')
  const [profileId, setProfileId] = useState<number | null>(null)
  const [layoutId, setLayoutId] = useState('default')
  const [lineIds, setLineIds] = useState<number[]>([])
  const [stabilizationFrames, setStabilizationFrames] = useState(2)
  const [offset, setOffset] = useState(6)
  const [fault, setFault] = useState('none')
  const [ccdIndex, setCcdIndex] = useState<number | null>(null)

  const update = useCallback((next: MercurySession) => {
    setSelected(next)
    setSessions((current) =>
      current.some((item) => item.id === next.id)
        ? current.map((item) => (item.id === next.id ? next : item))
        : [next, ...current]
    )
    setCcdIndex(current => current !== null && next.layout.ccd_indices.includes(current) ? current : next.layout.ccd_indices[0] ?? null)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextOptions, nextSessions] = await Promise.all([
        api.mercuryCalibrationOptions(token),
        api.mercuryCalibrationSessions(token)
      ])
      setOptions(nextOptions)
      setSessions(nextSessions)
      setProfileId((value) => value ?? nextOptions.profiles[0]?.id ?? null)
      setLayoutId((value) => (value !== 'default' ? value : String(nextOptions.layouts[0]?.id ?? 'default')))
      setLineIds((value) => (value.length ? value : nextOptions.reference_lines.slice(0, 4).map((line) => line.id)))
      if (nextSessions.length) {
        const detail = await api.mercuryCalibrationSession(token, nextSessions[0].id, true)
        update(detail)
      }
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取汞灯校准数据')
    } finally {
      setLoading(false)
    }
  }, [onToast, token, update])

  useEffect(() => {
    void load()
  }, [load])

  const choose = async (session: MercurySession) => {
    try {
      update(await api.mercuryCalibrationSession(token, session.id, true))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取校准会话')
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    if (!canWrite) return onToast('当前账户没有汞灯校准写入权限')
    if (lineIds.length < 2) return onToast('请至少选择两条汞谱线')
    setCreateError(null)
    setBusy(true)
    try {
      const next = await api.createMercuryCalibrationSession(token, {
        name,
        device_profile_id: profileId,
        ccd_layout_id: layoutId,
        line_ids: lineIds,
        stabilization_frames: stabilizationFrames,
        simulator_offset_points: offset,
        simulator_seed: 15,
        simulator_fault: fault
      })
      update(next)
      setCreateOpen(false)
      onToast('汞灯校准会话已建立，选线与校准前版本已锁定')
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : '创建汞灯校准会话失败')
      onToast(error instanceof Error ? error.message : '创建汞灯校准会话失败')
    } finally {
      setBusy(false)
    }
  }

  const run = async (action: 'start' | 'step' | 'stop' | 'apply' | 'rollback') => {
    if (!selected) return
    if ((action === 'apply' || action === 'rollback') && !canWrite) return onToast('当前账户没有应用校准版本的权限')
    if (action !== 'apply' && action !== 'rollback' && !canExecute) return onToast('当前账户没有汞灯调试执行权限')
    setBusy(true)
    try {
      const methods = {
        start: api.startMercuryCalibrationSession,
        step: api.stepMercuryCalibrationSession,
        stop: api.stopMercuryCalibrationSession,
        apply: api.applyMercuryCalibrationSession,
        rollback: api.rollbackMercuryCalibrationSession
      }
      const next = await methods[action](token, selected.id)
      update(next)
      if (terminalStates.has(next.status) || next.status === 'ready') setAuto(false)
      if (action === 'apply') onToast('光学调整版本已应用，校准前版本仍可回滚')
      if (action === 'rollback') onToast('已恢复校准前光学调整版本')
    } catch (error) {
      setAuto(false)
      onToast(error instanceof Error ? error.message : '校准控制操作失败')
    } finally {
      setBusy(false)
    }
  }

  const advance = useCallback(async () => {
    if (!selected || busyRef.current || !activeStates.has(selected.status)) return
    busyRef.current = true
    try {
      const next = await api.stepMercuryCalibrationSession(token, selected.id)
      update(next)
      if (!activeStates.has(next.status)) setAuto(false)
    } catch (error) {
      setAuto(false)
      onToast(error instanceof Error ? error.message : '自动推进失败')
    } finally {
      busyRef.current = false
    }
  }, [onToast, selected, token, update])

  useEffect(() => {
    if (!auto || !selected || !activeStates.has(selected.status)) return
    const timer = window.setInterval(() => {
      void advance()
    }, 500)
    return () => window.clearInterval(timer)
  }, [advance, auto, selected])

  const selectedProfile = options?.profiles.find(profile => profile.id === profileId)
  const curves = selected?.last_event?.ccds ?? []
  const curve = curves.find(item => item.ccd_index === ccdIndex) ?? curves[0]
  const plotCcd = curve?.ccd_index ?? ccdIndex ?? selected?.layout.ccd_indices[0] ?? 0
  return <div className="page-content mercury-page refined-page remaining-page" data-testid="mercury-calibration-page">
    <PageFileActions target={actionsTarget} hidden={!active}>
      <button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''}/>刷新</button>
      <button className="primary-button" disabled={!canWrite || busy} onClick={() => setCreateOpen(true)}>建立校准会话</button>
    </PageFileActions>
    <SpectroscopyTaskDialog open={createOpen && active} title="建立汞灯校准会话" busy={busy} error={createError} onCancel={() => setCreateOpen(false)}>
            <MercuryCalibrationForm
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
              stabilizationFrames={stabilizationFrames}
              setStabilizationFrames={setStabilizationFrames}
              offset={offset}
              setOffset={setOffset}
              fault={fault}
              setFault={setFault}
              lineIds={lineIds}
              setLineIds={setLineIds}
              selectedProfile={selectedProfile}
            />
    </SpectroscopyTaskDialog>
    <DeviceDebugWorkbench title="汞灯调试" active={active} hasPoints={Boolean(curve?.points?.length)} listTitle="校准会话"
      toolbar={<>
        <label>校准会话 <select aria-label="当前校准会话" value={selected?.id ?? ''} disabled={busy || auto || Boolean(selected && activeStates.has(selected.status)) || !sessions.length}
          onChange={event => { const session = sessions.find(item => item.id === Number(event.target.value)); if (session) void choose(session) }}>
          {sessions.map(session => <option key={session.id} value={session.id}>{session.name}</option>)}
        </select></label>
        <label>CCD <select aria-label="汞谱 CCD" value={plotCcd} onChange={event => setCcdIndex(Number(event.target.value))} disabled={!selected}>
          {selected?.layout.ccd_indices.map(index => <option key={index} value={index}>CCD {index + 1}</option>)}
        </select></label>
        <button type="button" disabled={!selected} onClick={() => evidence.current?.showModal()}>校准结果与轨迹</button>
      </>}
      records={<div className="capture-record-table mercury-session-list"><table><thead><tr><th aria-label="当前会话"/><th>会话名称</th></tr></thead>
        <tbody>{sessions.map(session => <tr key={session.id} aria-selected={selected?.id === session.id}>
          <td>{selected?.id === session.id && <RowSelectionArrow/>}</td><td><button type="button" disabled={busy || auto || Boolean(selected && activeStates.has(selected.status))}
            aria-pressed={selected?.id === session.id} title={session.name} onClick={() => void choose(session)}><strong>{session.name}</strong><small>{labels[session.status]}</small></button></td>
        </tr>)}</tbody></table>{!sessions.length && <div className="empty-state compact-empty">暂无汞灯校准会话</div>}</div>}
      controls={<>          <MercuryCalibrationMonitor
            selected={selected}
            run={run}
            busy={busy}
            canExecute={canExecute}
            setAuto={setAuto}
            auto={auto}
            canWrite={canWrite}
          />
</>}
      footer={<>
        <span>{selected ? labels[selected.status] : '尚未选择会话'} · {selected?.last_message || '等待操作'}</span>
        <span>稳定进度：{selected ? `${selected.stabilized_frames}/${selected.stabilization_frames}` : '--'}</span>
        <span>原始帧：{selected?.frames.length ?? 0}</span>
        <span>安全态：{selected ? selected.safe_off ? '已关闭' : '谱源活动' : '--'}</span>
      </>}>
      {selected ? <>              <SpectrumInspector fitPlot iconToolbar classic ccdNavigation={{ current: plotCcd, indices: selected.layout.ccd_indices, choose: setCcdIndex }} key={`${token}:${selected.id}:${plotCcd}`}
                points={curve?.points ?? []} label={`CCD ${plotCcd + 1} 汞谱`}
                emptyText="推进到稳定帧后显示光谱"
                markers={selected.lines.filter((line) => line.expected_ccd_index === plotCcd).flatMap((line) => [
                  { key: `${line.id}-expected`, kind: 'expected' as const, position: line.expected_position + 1,
                    label: `${line.label} · 预期 ${(line.expected_position + 1).toFixed(2)}` },
                  ...(line.observed_position === null ? [] : [{ key: `${line.id}-located`, kind: 'located' as const,
                    position: line.observed_position + 1, label: `${line.label} · 实测 ${(line.observed_position + 1).toFixed(2)}` }])
                ])} />
</> : <SpectrumInspector fitPlot iconToolbar classic points={[]} label="实时汞谱" emptyText="建立或选择会话后开始汞灯调试"/>}
    </DeviceDebugWorkbench>
    <dialog ref={evidence} className="device-debug-evidence" aria-label="汞灯校准结果与轨迹">
      <header><h2>校准结果与轨迹</h2><button type="button" onClick={() => evidence.current?.close()}>关闭</button></header>
          {selected && (
            <MercuryCalibrationResults
              selected={selected}
            />
          )}
          {selected && (
            <section className="mercury-evidence">
              <section className="surface">
                <div className="surface-heading">
                  <div>
                    <h2>版本与完整性</h2>
                  </div>
                  <FileCheck2 size={16} />
                </div>
                <dl>
                  <dt>活动版本</dt>
                  <dd>v{selected.active_version.version}</dd>
                  <dt>候选版本</dt>
                  <dd>{selected.candidate_version ? `v${selected.candidate_version.version}` : '--'}</dd>
                  <dt>候选快照</dt>
                  <dd>
                    <CopyableCode value={selected.candidate_version?.snapshot_sha256} visibleLength={18} empty="--" />
                  </dd>
                  <dt>原始帧</dt>
                  <dd>{selected.frames.length}</dd>
                </dl>
              </section>
              <section className="surface">
                <div className="surface-heading">
                  <div>
                    <h2>
                      全部调试与安全轨迹 <span className="count-badge">{selected.traces.length}</span>
                    </h2>
                  </div>
                  <SquareTerminal size={16} />
                </div>
                <div className="mercury-traces">
                  {[...selected.traces].reverse().map((trace, index) => (
                    <div key={index}>
                      <span>{String(trace.kind)}</span>
                      <strong title={String(trace.name)}>{String(trace.name)}</strong>
                      <CopyableCode value={String(trace.payload_sha256 ?? '')} visibleLength={12} empty="—" />
                      <small title={String(trace.safe_state ?? '')}>{String(trace.safe_state ?? '')}</small>
                    </div>
                  ))}
                  {!selected.traces.length && <div className="empty-state compact-empty">暂无轨迹</div>}
                </div>
              </section>
            </section>
          )}
    </dialog>
  </div>
}
