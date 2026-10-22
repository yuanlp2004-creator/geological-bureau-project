import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { SpectrumPointDetails as Details } from '../api/spectrumViewer'
import { copyText } from '../platform/clipboard'
import { saveFile } from '../platform/files'

export function SpectrumPointDetails({ token, recordId, ccd, point, onToast,
  analysis }: { token: string; recordId: string; ccd: number; point: number | null
    onToast: (message: string) => void; analysis?: { runId: number; samplePosition: number } }) {
  const [details, setDetails] = useState<Details | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  useEffect(() => { generation.current++; setDetails(null); setError(''); setBusy(false) },
    [token, recordId, ccd, point, analysis?.runId, analysis?.samplePosition])
  const load = async () => {
    if (point == null || busy) return
    const current = ++generation.current; setBusy(true); setDetails(null); setError('')
    try {
      const result = await api.spectrumPointDetails(token, recordId, ccd, point, analysis)
      if (current === generation.current) setDetails(result)
    } catch (failure) { if (current === generation.current) setError(failure instanceof Error ? failure.message : '读取明细失败') }
    finally { if (current === generation.current) setBusy(false) }
  }
  const copy = async (vertical: boolean) => {
    if (!details || point == null || busy) return
    const current = generation.current; setBusy(true)
    try {
      const result = await api.copySpectrumPointDetails(token, recordId, ccd, point, vertical, analysis)
      if (current !== generation.current) return
      await copyText(result.text); onToast(vertical ? '积分明细已纵向复制' : '积分明细已横向复制')
    } catch (failure) { if (current === generation.current) onToast(failure instanceof Error ? failure.message : '复制失败') }
    finally { if (current === generation.current) setBusy(false) }
  }
  const print = async () => {
    if (!details || point == null || busy) return
    const current = generation.current; setBusy(true)
    try {
      const blob = await api.printSpectrumPointDetails(token, recordId, ccd, point, analysis)
      if (current === generation.current) await saveFile(blob, `point-${recordId.replace(':', '-')}-${point + 1}.pdf`)
    } catch (failure) { if (current === generation.current) onToast(failure instanceof Error ? failure.message : '打印失败') }
    finally { if (current === generation.current) setBusy(false) }
  }
  return <section className="spectrum-point-details" aria-label="原始积分明细">
    <div className="analysis-actions">
      <button className="secondary-button" disabled={point == null || busy} onClick={() => void load()}>查看分时明细</button>
      {details && <>
        <button className="secondary-button" disabled={busy} onClick={() => void copy(true)}>纵向复制</button>
        <button className="secondary-button" disabled={busy} onClick={() => void copy(false)}>横向复制</button>
        <button className="secondary-button" disabled={busy} onClick={() => void print()}>打印积分明细 PDF</button>
      </>}
    </div>
    {error && <p role="alert">{error}</p>}
    {details && <>
      <p>CCD {details.ccd_index + 1} · 点 {details.point_index + 1} · 预激 {details.pre_excitation_seconds ?? '未记录'} 秒 ·
        燃烧 {details.burn_cycle_seconds ?? '未记录'} 秒 × {details.burn_count} · 空白 {details.dark_cycle_seconds ?? '未记录'} 秒 × {details.dark_count}</p>
      <div className="table-scroll" style={{ maxHeight: 300, overflow: 'auto' }}><table><thead><tr><th>阶段</th><th>积分序号</th><th>原始强度 ADC</th></tr></thead>
        <tbody>{details.rows.map((row) => <tr key={`${row.phase}:${row.integration}`}>
          <td>{row.phase === 'burn' ? '燃烧' : '空白'}</td><td>{row.integration}</td><td>{row.value}</td>
        </tr>)}</tbody></table></div>
    </>}
  </section>
}
