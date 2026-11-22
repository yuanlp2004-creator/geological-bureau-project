import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, type HardwareTask } from '../../api'
import { SpectrumInspector } from '../../components/SpectrumInspector'

type Frame = { id: number; step_id: number; attempt: number; ccd_index: number;
  points: number[]; damaged: boolean; confirmed: boolean }

export function HardwareSpectrum({ token, selected, viewStep, toolbarTarget, onFollow }: {
  token: string; selected: HardwareTask; viewStep: number | null; toolbarTarget?: HTMLElement | null; onFollow: () => void
}) {
  const [frames, setFrames] = useState<Frame[]>([])
  const [frameId, setFrameId] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [ccd, setCcd] = useState(selected.ccd_indices[0] ?? 0)
  useEffect(() => { setFrameId(null) }, [selected.id, viewStep])
  const activeStep = selected.steps.find(item => viewStep === null ? item.order_index === selected.current_step_index : item.id === viewStep)
  const activeCcds = selected.plan.find(item => item.order_index === activeStep?.order_index)?.ccd_indices ?? selected.ccd_indices
  const activeCcdKey = activeCcds.join(',')
  useEffect(() => {
    const indices = activeCcdKey.split(',').filter(Boolean).map(Number)
    setCcd(current => indices.includes(current) ? current : indices[0] ?? current)
  }, [selected.id, activeCcdKey])
  // 只在帧列表或确认状态改变时解码，不在每个状态轮询中重复读取全点值。
  const signature = selected.frames.map((frame) => `${frame.id}:${frame.confirmed}:${frame.damaged}`).join(',')
  useEffect(() => {
    let live = true
    setLoading(true)
    setError('')
    api.hardwareAcquisitionFrames(token, selected.id, true).then((next) => {
      if (!live) return
      setFrames(next.map((frame) => ({ id: Number(frame.id), step_id: Number(frame.step_id),
        attempt: Number(frame.attempt), ccd_index: Number(frame.ccd_index),
        points: Array.isArray(frame.points) ? frame.points as number[] : [],
        damaged: Boolean(frame.damaged), confirmed: Boolean(frame.confirmed) })))
    }, (failure) => { if (live) { setFrames([]); setError(failure instanceof Error ? failure.message : '读取转角谱图失败') } })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [token, selected.id, signature, refresh])
  const choices = viewStep === null ? frames : frames.filter(item => item.step_id === viewStep)
  const ccdFrames = choices.filter(item => item.ccd_index === ccd)
  const frame = choices.find(item => item.id === frameId) ?? ccdFrames[ccdFrames.length - 1]
  const step = selected.steps.find((item) => item.id === frame?.step_id)
  const label = frame ? `CCD ${frame.ccd_index + 1} · 转角 ${step ? step.order_index + 1 : '--'} · 尝试 ${frame.attempt}` : '转角采集谱图'
  const frameTools = <div className="inspector-frame-tools">
      <label>原始帧 <select aria-label="转角原始帧" value={frame?.id ?? ''} disabled={!frames.length || loading}
        onChange={(event) => setFrameId(Number(event.target.value))}>
        {choices.map((item) => <option key={item.id} value={item.id}>
          转角 {(selected.steps.find((entry) => entry.id === item.step_id)?.order_index ?? -1) + 1}
          {' · '}尝试 {item.attempt} · CCD {item.ccd_index + 1}
          {' · '}{item.damaged ? '损坏' : item.confirmed ? '已确认' : '待确认'}
        </option>)}
      </select></label>
      {frame && <span>{frame.damaged ? '原始帧损坏，无法显示有效点值' : frame.confirmed ? '已确认帧'
        : selected.execution_mode === 'manual' && selected.status !== 'manual_intervention' ? '未完成采集，数据暂未确认' : '待确认帧，观察后在任务区处置'}</span>}
      {(viewStep !== null || frameId !== null) && <button className="secondary-button" onClick={() => { setFrameId(null); onFollow() }}>返回当前谱图</button>}
      {error && <button className="secondary-button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>重试读取</button>}
    </div>
  return <section className="hardware-spectrum" aria-label="转角采集谱图">
    {toolbarTarget ? createPortal(frameTools, toolbarTarget) : frameTools}
    {error && <p role="alert">{error}</p>}
    <SpectrumInspector key={`${selected.id}:${viewStep}:${frame?.ccd_index ?? ccd}`} iconToolbar fitPlot
      ccdNavigation={{ current: frame?.ccd_index ?? ccd, indices: selected.ccd_indices, choose: value => { setCcd(value); setFrameId(null) } }}
      points={frame?.damaged ? [] : frame?.points ?? []}
      label={label} emptyText={loading ? '正在读取原始点值…' : error ? '谱图读取失败，请刷新重试'
        : frame?.damaged ? '损坏帧无有效点值' : '采集到原始帧后显示谱图'} />
  </section>
}
