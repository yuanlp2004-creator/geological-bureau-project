import { useEffect, useState } from 'react'
import type { AcquisitionTask } from '../../api'
import { request } from '../../api/client'
import type { SpectrumConcentrationPreview } from '../../api/spectrumViewer'
import { formatAnalysisValue } from '../../components/analysisUnits'
import './capture-measurement.css'

type FrameScope = { turn: number; repeat: number; frame: number; ccd: number; last: number }
type FrameRow = SpectrumConcentrationPreview['rows'][number] & {
  diagnostic_code: string | null; diagnostic: string | null; reference_interval: [number, number]
}
type FrameObservation = {
  frame_index: number; repeat_index: number; turn_index: number; ccd_index: number
  points: number[]; frame_sha256: string | null; rows: FrameRow[]
  method_name: string | null; method_version: number | null; message: string | null
}

export function useCaptureMeasurement(token: string, task: AcquisitionTask | undefined, turn: number, ccd: number) {
  const [held, setHeld] = useState<(FrameScope & { taskId: number }) | null>(null)
  const [loaded, setLoaded] = useState<{ key: string; data?: FrameObservation; error?: string }>()
  const active = task?.id === held?.taskId ? held : null
  const completedTurn = task?.turns?.multiple && (task.status === 'completed' ||
    (task.status !== 'between_repeats' && turn < task.turns.completed_turns))
  const available = completedTurn ? task.burn_frame_count : !task?.turns || task.turns.turn_index === turn ? task?.burn_frames_captured ?? 0 : 0
  const current: FrameScope | null = task && available > 0
    ? { turn, repeat: task.current_repeat_index, ccd, frame: available - 1, last: available - 1 } : null
  const scope = active ?? current
  const sameRun = current && scope && current.turn === scope.turn && current.repeat === scope.repeat
  const heldCaptureCompleted = active && task && (active.repeat < task.completed_repeats ||
    (active.repeat === task.current_repeat_index && active.turn < (task.turns?.completed_turns ?? 0)))
  const last = heldCaptureCompleted ? task.burn_frame_count - 1 : sameRun ? current.last : scope?.last ?? 0
  const query = scope ? new URLSearchParams({ turn_index: String(scope.turn), repeat_index: String(scope.repeat),
    frame_index: String(scope.frame), ccd: String(scope.ccd) }).toString() : ''
  const key = task && query ? `/api/v1/acquisitions/tasks/${task.id}/measurement-frame?${query}` : ''
  const dark = task?.dark_frames_captured
  const complete = task?.status === 'completed'
  useEffect(() => {
    if (!key) return
    const abort = new AbortController()
    void request<FrameObservation>(key, {
      headers: { Authorization: `Bearer ${token}` }, signal: abort.signal,
    }).then(data => { if (!abort.signal.aborted) setLoaded({ key, data }) })
      .catch(error => { if (!abort.signal.aborted) setLoaded({ key, error: error instanceof Error ? error.message : '读取原始帧失败' }) })
    return () => abort.abort()
  }, [key, token, dark, complete])
  const state = loaded?.key === key ? loaded : undefined
  return { scope, frame: state?.data, error: state?.error, held: Boolean(active), last,
    toggle: () => setHeld(active || !current || !task ? null : { ...current, taskId: task.id }),
    step: (direction: number) => setHeld(value => value && { ...value, last, frame: Math.max(0, Math.min(last, value.frame + direction)) }),
    reset: () => setHeld(null),
  }
}

const anomaly = new Set(['analysis_frame_saturated', 'analysis_frame_peak_missing', 'analysis_frame_internal_peak_missing', 'analysis_gaussian_fit_failed'])

export function CaptureMeasurement({ observation }: { observation: ReturnType<typeof useCaptureMeasurement> }) {
  const { scope, held, frame, error, toggle, step, last } = observation
  const anomalies = frame?.rows.filter(row => row.diagnostic_code && anomaly.has(row.diagnostic_code)).length ?? 0
  return <section className="capture-measurement" aria-label="采集测量观察">
    <div className="capture-measurement-controls">
      <output aria-live="polite">{scope ? `转角 ${scope.turn + 1} · CCD ${scope.ccd + 1} · 重复 ${scope.repeat + 1} · 燃烧帧 ${scope.frame + 1}${frame?.rows.length ? ` · ${anomalies ? `${anomalies} 条峰形异常` : '未发现峰形异常'}` : ''}` : '等待首个燃烧帧入库'}</output>
      <button type="button" aria-pressed={held} disabled={!scope} title="锁定观察帧，采集继续进行" onClick={toggle}>{held ? '跟随新帧' : '慢进观察'}</button>
      {held && <>
        <button type="button" disabled={!scope?.frame} onClick={() => step(-1)}>上一帧</button>
        <button type="button" disabled={scope == null || scope.frame >= last} onClick={() => step(1)}>下一帧</button>
      </>}
    </div>
    {error && <p role="alert">{error}</p>}
    {scope && !frame && !error && <p role="status">正在读取燃烧帧…</p>}
    {frame?.message && <p>{frame.message}</p>}
    {frame && frame.rows.length > 0 && <details open={held || undefined}>
      <summary>谱线诊断与参考含量 · {frame.method_name} v{frame.method_version}</summary>
      <div className="capture-measurement-table"><table><thead><tr><th>谱线</th><th>CCD / 点位</th><th>帧强度 (ADC)</th><th>参考含量 / 状态</th></tr></thead>
        <tbody>{frame.rows.map(row => <tr key={row.line_id} data-anomaly={row.diagnostic_code ? anomaly.has(row.diagnostic_code) : false}>
          <td>{row.element} {row.wavelength_nm.toFixed(4)} nm</td>
          <td>{row.ccd_index == null || row.point_index == null ? '—' : `${row.ccd_index + 1} / ${row.point_index + 1}`}</td>
          <td>{row.raw_intensity == null ? '—' : formatAnalysisValue(row.raw_intensity, 0)}</td>
          <td>{row.diagnostic && <div>{row.diagnostic}</div>}
            {row.concentration == null ? row.message ?? '无法估值' : <>
              {formatAnalysisValue(row.concentration, row.decimal_places)} {row.unit} · 曝光 {row.reference_interval.join('–')} 帧
              {row.message ? ` · ${row.message}` : ''}
            </>}</td>
        </tr>)}</tbody></table></div>
    </details>}
  </section>
}
