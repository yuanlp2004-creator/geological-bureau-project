import { useEffect, useRef, useState } from 'react'
import { getAnalysisSpectrum, type AnalysisSpectrum } from '../../api/analysis'
import { NumericInput } from '../../components/NumericInput'

type Interval = [number, number]

export function useAnalysisExposure(token: string, runId: number | undefined, sample: number,
  lineId: string | null, bandPosition: number, observation: AnalysisSpectrum | null) {
  const [result, setResult] = useState<{ base: AnalysisSpectrum; slot: number; data: AnalysisSpectrum } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const version = useRef(0)
  useEffect(() => {
    setResult(null); setBusy(false); setError('')
    return () => { version.current++ }
  }, [token, runId, sample, lineId, bandPosition, observation])
  const band = observation?.bands[bandPosition]
  const count = band?.observation_frame_count ?? 0
  const applied = result?.base === observation && result?.slot === bandPosition ? result.data : null
  const reset = () => { version.current++; setResult(null); setBusy(false); setError('') }
  const apply = async ([start, end]: Interval) => {
    if (!runId || !observation || !count || busy) return
    const ticket = ++version.current
    setBusy(true); setError('')
    try {
      const data = await getAnalysisSpectrum(token, runId, sample, lineId, { bandPosition, start, end })
      if (ticket === version.current) setResult({ base: observation, slot: bandPosition, data })
    } catch (failure) {
      if (ticket === version.current) setError(failure instanceof Error ? failure.message : '读取观察曝光区间失败')
    } finally {
      if (ticket === version.current) setBusy(false)
    }
  }
  return { band: applied?.bands[bandPosition] ?? band, interval: applied?.exposure_interval ?? null, count, busy, error, apply, reset }
}

export function AnalysisExposureControls({ count, initial, busy, active, disabled, onApply, onReset }: {
  count: number; initial?: Interval | null; busy: boolean; active: boolean; disabled?: boolean
  onApply: (value: Interval) => void; onReset: () => void
}) {
  const [start, setStart] = useState(initial?.[0] ?? 1)
  const [end, setEnd] = useState(initial?.[1] ?? count)
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= count
  const reset = () => { setStart(initial?.[0] ?? 1); setEnd(initial?.[1] ?? count); onReset() }
  return <div className="analysis-observation-exposure" role="group" aria-label="观察曝光区间">
    <label>观察曝光区间 <span className="legacy-exposure-range">
      <NumericInput aria-label="分析曝光开始帧" min={1} max={count} step={1} value={start} onValueChange={setStart} disabled={busy || disabled} />
      <span>–</span>
      <NumericInput aria-label="分析曝光结束帧" min={1} max={count} step={1} value={end} onValueChange={setEnd} disabled={busy || disabled} />
    </span></label>
    <button type="button" className="secondary-button" disabled={disabled || !valid || busy} onClick={() => onApply([start, end])}>{busy ? '读取中…' : '查看区间'}</button>
    {active && <button type="button" className="secondary-button" disabled={busy || disabled} onClick={reset}>恢复方法区间</button>}
  </div>
}
