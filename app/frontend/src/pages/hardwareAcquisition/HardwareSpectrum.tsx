import { useEffect, useState } from 'react'
import { api, type HardwareTask } from '../../api'
import { SpectrumInspector } from '../../components/SpectrumInspector'

type Frame = { id: number; step_id: number; attempt: number; ccd_index: number;
  points: number[]; damaged: boolean; confirmed: boolean }

export function HardwareSpectrum({ token, selected }: { token: string; selected: HardwareTask }) {
  const [frames, setFrames] = useState<Frame[]>([])
  const [frameId, setFrameId] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  // 只在帧列表或确认状态改变时解码，不在每个状态轮询中重复读取全点值。
  const signature = selected.frames.map((frame) => `${frame.id}:${frame.confirmed}:${frame.damaged}`).join(',')
  useEffect(() => {
    let live = true
    setLoading(true)
    setError('')
    setFrames([])
    api.hardwareAcquisitionFrames(token, selected.id, true).then((next) => {
      if (!live) return
      setFrames(next.map((frame) => ({ id: Number(frame.id), step_id: Number(frame.step_id),
        attempt: Number(frame.attempt), ccd_index: Number(frame.ccd_index),
        points: Array.isArray(frame.points) ? frame.points as number[] : [],
        damaged: Boolean(frame.damaged), confirmed: Boolean(frame.confirmed) })))
    }, (failure) => { if (live) setError(failure instanceof Error ? failure.message : '读取转角谱图失败') })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [token, selected.id, signature, refresh])
  const frame = frames.find((item) => item.id === frameId) ?? frames[frames.length - 1]
  const step = selected.steps.find((item) => item.id === frame?.step_id)
  const label = frame ? `CCD ${frame.ccd_index + 1} · 转角 ${step ? step.order_index + 1 : '--'} · 尝试 ${frame.attempt}` : '转角采集谱图'
  return <section className="surface" aria-label="转角采集谱图">
    <div className="surface-heading"><h2>转角采集谱图</h2>
      <button className="secondary-button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>刷新谱图</button>
    </div>
    <div className="inspector-frame-tools">
      <label>原始帧 <select aria-label="转角原始帧" value={frame?.id ?? ''} disabled={!frames.length || loading}
        onChange={(event) => setFrameId(Number(event.target.value))}>
        {frames.map((item) => <option key={item.id} value={item.id}>
          转角 {(selected.steps.find((entry) => entry.id === item.step_id)?.order_index ?? -1) + 1}
          {' · '}尝试 {item.attempt} · CCD {item.ccd_index + 1}
          {' · '}{item.damaged ? '损坏' : item.confirmed ? '已确认' : '待确认'}
        </option>)}
      </select></label>
      {frame && <span>{frame.damaged ? '原始帧损坏，无法显示有效点值' : frame.confirmed ? '已确认帧' : '待确认帧，观察后在任务区处置'}</span>}
    </div>
    {error && <p role="alert">{error}</p>}
    <SpectrumInspector key={`${selected.id}:${frame?.id ?? 'empty'}`} points={frame?.damaged ? [] : frame?.points ?? []}
      label={label} emptyText={loading ? '正在读取原始点值…' : error ? '谱图读取失败，请刷新重试'
        : frame?.damaged ? '损坏帧无有效点值' : '采集到原始帧后显示谱图'} />
  </section>
}
