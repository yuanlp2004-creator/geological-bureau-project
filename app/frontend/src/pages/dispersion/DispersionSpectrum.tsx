import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type DispersionFrame, type DispersionTask } from '../../api'
import { NumericInput } from '../../components/NumericInput'
import { SpectrumInspector } from '../../components/SpectrumInspector'
import { positionMarkers } from './dispersionView'

type Props = {
  token: string
  active: DispersionTask
  ccd: number
  onPick: (point: number | null) => void
}

export function DispersionSpectrum({ token, active, ccd, onPick }: Props) {
  const [mode, setMode] = useState<'live' | 'frame' | 'average'>('live')
  const [frames, setFrames] = useState<DispersionFrame[]>([])
  const [frameId, setFrameId] = useState<number | null>(null)
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(0)
  const historical = mode !== 'live'
  useEffect(() => {
    const ticket = ++request.current
    if (!historical) return
    setLoading(true)
    setError('')
    setFrames([])
    api.dispersionFrames(token, active.id, ccd).then((next) => {
      if (ticket !== request.current) return
      setFrames(next)
      setFrameId(next[0]?.id ?? null)
      const burns = next.filter((frame) => frame.phase === 'burn')
      setStart(1)
      setEnd(Math.max(1, burns.length))
    }, (failure) => {
      if (ticket === request.current) setError(failure instanceof Error ? failure.message : '读取历史帧失败')
    }).finally(() => { if (ticket === request.current) setLoading(false) })
    return () => { request.current++ }
  }, [token, active.id, ccd, historical, refresh])
  useEffect(() => { onPick(null) }, [mode, frameId, start, end, onPick])
  const frame = frames.find((item) => item.id === frameId)
  const burns = frames.filter((item) => item.phase === 'burn')
  const validRange = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= burns.length
  const points = useMemo(() => {
    if (mode === 'live') return active.last_event?.ccds.find((item) => item.ccd_index === ccd)?.points ?? []
    if (loading || error) return []
    if (mode === 'frame') return frame?.points ?? []
    if (!validRange) return []
    const selected = burns.slice(start - 1, end)
    const count = selected[0]?.points.length ?? 0
    if (!count || selected.some((item) => item.points.length !== count)) return []
    return Array.from({ length: count }, (_, index) => selected.reduce((sum, item) => sum + item.points[index], 0) / selected.length)
  }, [mode, active.last_event, ccd, loading, error, frame, validRange, burns, start, end])
  const markers = positionMarkers(active.lines, ccd, active.layout.points_per_ccd)
  const source = mode === 'live' ? '实时 / 最新帧'
    : mode === 'frame' ? `${frame?.phase === 'dark' ? '暗帧' : '燃烧帧'} ${(frame?.frame_index ?? 0) + 1}`
      : `燃烧区间 ${start}–${end} 均值（仅用于观察）`
  return <div className="dispersion-spectrum-view">
    <div className="inspector-frame-tools">
      <label>查看数据 <select aria-label="色散谱图数据" value={mode}
        onChange={(event) => setMode(event.target.value as typeof mode)}>
        <option value="live">实时 / 最新帧</option><option value="frame">已保存单帧</option>
        <option value="average">燃烧区间均值</option>
      </select></label>
      {historical && <>
        <button className="secondary-button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>刷新已保存帧</button>
        {mode === 'frame' ? <select aria-label="色散历史帧" value={frameId ?? ''} disabled={loading || !frames.length}
          onChange={(event) => setFrameId(Number(event.target.value))}>
          {frames.map((item) => <option key={item.id} value={item.id}>
            {item.phase === 'dark' ? '暗帧' : '燃烧帧'} {item.frame_index + 1}
          </option>)}
        </select> : <>
          <label>开始帧 <NumericInput min={1} max={Math.max(1, burns.length)} step={1} value={start} onValueChange={setStart} data-observation-input="true" /></label>
          <label>结束帧 <NumericInput min={start} max={Math.max(1, burns.length)} step={1} value={end} onValueChange={setEnd} data-observation-input="true" /></label>
        </>}
      </>}
    </div>
    {error && <p role="alert">{error}</p>}
    <SpectrumInspector fitPlot key={`${mode}:${mode === 'frame' ? frameId : mode === 'average' ? `${start}:${end}` : 'latest'}`}
      points={points} pointOrigin={0} label={`CCD ${ccd + 1} · ${source}`} markers={markers} onPick={onPick}
      emptyText={loading ? '正在读取已保存帧…' : error ? '帧读取失败，请刷新重试'
        : mode === 'average' && burns.length && !validRange ? '请选择有效的燃烧帧区间'
          : historical ? '当前 CCD 没有可显示的已保存帧' : '开始采集后显示实时 CCD 曲线'} />
  </div>
}
