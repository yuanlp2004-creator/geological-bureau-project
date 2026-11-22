import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { PointDetailsAnalysis, SpectrumPointDetails as Details, SpectrumPointFrames } from '../api/spectrumViewer'
import { copyText } from '../platform/clipboard'
import { saveFile } from '../platform/files'
import { ContextMenu, useContextMenu } from './ContextMenu'

export type PointDetailsTarget = { token: string; recordId: string; ccd: number; onToast: (message: string) => void;
  canOutput?: boolean; analysis?: PointDetailsAnalysis; sampleName?: string; bandName?: string }

type DisplayDetails = Omit<Details, 'sha256'>
type PointFrames = Omit<SpectrumPointFrames, 'frames_base64'> & { data: DataView }

function detailsAt(frames: PointFrames | null, point: number | null): DisplayDetails | null {
  if (!frames || point === null || point < 0 || point >= frames.point_count) return null
  const { data, point_count, wavelengths_nm, ...metadata } = frames
  const rows: DisplayDetails['rows'] = Array.from({ length: frames.burn_count + frames.dark_count }, (_, index) => {
    const burn = index < frames.burn_count
    return { phase: burn ? 'burn' : 'dark', integration: index + 1 - (burn ? 0 : frames.burn_count),
      value: data.getUint16(2 * (index * point_count + point), true) }
  })
  return { ...metadata, point_index: point, wavelength_nm: wavelengths_nm?.[point] ?? null, rows }
}

export function SpectrumPointDetails({ token, recordId, ccd, point, onToast, canOutput = true,
  analysis, sampleName, bandName, autoLoad = false, compact = false, onMenuPresence }: PointDetailsTarget & {
    point: number | null; autoLoad?: boolean; compact?: boolean; onMenuPresence?: (open: boolean) => void
  }) {
  const [singlePoint, setSinglePoint] = useState<Details | null>(null)
  const [frames, setFrames] = useState<PointFrames | null>(null)
  const details = useMemo(() => compact ? detailsAt(frames, point) : singlePoint, [compact, frames, point, singlePoint])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const menu = useContextMenu<number>()
  useEffect(() => {
    if (!compact) {
      setSinglePoint(null)
      setError('')
      setBusy(false)
    }
    return () => { generation.current++ }
  }, [token, recordId, ccd, compact ? null : point, analysis?.runId, analysis?.samplePosition, analysis?.bandPosition, compact])
  useEffect(() => {
    if (!compact) return
    const controller = new AbortController()
    void api.spectrumPointFrames(token, recordId, ccd, analysis, controller.signal).then(({ frames_base64, ...metadata }) => {
      if (controller.signal.aborted) return
      const bytes = Uint8Array.from(atob(frames_base64), character => character.charCodeAt(0))
      if (bytes.length !== metadata.point_count * (metadata.burn_count + metadata.dark_count) * 2) {
        throw new Error('分时帧与 CCD 布局不符')
      }
      setFrames({ ...metadata, data: new DataView(bytes.buffer) })
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取明细失败')
    })
    return () => controller.abort()
  }, [compact, token, recordId, ccd, analysis?.runId, analysis?.samplePosition, analysis?.bandPosition])
  const load = async (automatic = false) => {
    if (point == null || (!automatic && busy)) return
    const current = ++generation.current
    setBusy(true)
    setSinglePoint(null)
    setError('')
    try {
      const result = await api.spectrumPointDetails(token, recordId, ccd, point, analysis)
      if (current === generation.current) setSinglePoint(result)
    } catch (failure) { if (current === generation.current) setError(failure instanceof Error ? failure.message : '读取明细失败') }
    finally { if (current === generation.current) setBusy(false) }
  }
  useEffect(() => {
    if (autoLoad && !compact && point !== null) void load(true)
  }, [autoLoad, compact, token, recordId, ccd, point, analysis?.runId, analysis?.samplePosition, analysis?.bandPosition])
  const unavailable = !canOutput || busy || !details || details.point_index !== point
  const copy = async (vertical: boolean) => {
    if (unavailable || point == null) return
    const current = generation.current; setBusy(true)
    try {
      const result = await api.copySpectrumPointDetails(token, recordId, ccd, point, vertical, analysis)
      if (current !== generation.current) return
      await copyText(result.text); onToast(vertical ? '积分明细已纵向复制' : '积分明细已横向复制')
    } catch (failure) { if (current === generation.current) onToast(failure instanceof Error ? failure.message : '复制失败') }
    finally { if (current === generation.current) setBusy(false) }
  }
  const print = async () => {
    if (unavailable || point == null) return
    const current = generation.current; setBusy(true)
    try {
      const blob = await api.printSpectrumPointDetails(token, recordId, ccd, point, analysis)
      if (current === generation.current) await saveFile(blob, `point-${recordId.replace(':', '-')}-${point + 1}.pdf`)
    } catch (failure) { if (current === generation.current) onToast(failure instanceof Error ? failure.message : '打印失败') }
    finally { if (current === generation.current) setBusy(false) }
  }
  const menuTarget = menu.target && menu.target.data === point && details?.point_index === point ? menu.target : null
  useEffect(() => { if (menu.target && !menuTarget) menu.close() }, [menu.target, menuTarget, menu.close])
  useEffect(() => {
    if (!menuTarget) return
    onMenuPresence?.(true)
    return () => onMenuPresence?.(false)
  }, [menuTarget, onMenuPresence])
  const outputMenu = menuTarget && <ContextMenu target={menuTarget} close={menu.close} label="分时数据菜单" groups={[[
      { label: '打印数据 PDF', disabled: unavailable, run: () => void print() },
      { label: '纵向复制', disabled: unavailable, run: () => void copy(true) },
      { label: '横向复制', disabled: unavailable, run: () => void copy(false) }
    ]]} />
  if (compact) return <section className="spectrum-point-compact" aria-label="原始积分明细" tabIndex={0}
    onContextMenu={event => { if (point !== null && details?.point_index === point) menu.open(event, point) }}
    onKeyDown={event => {
      if (point !== null && details?.point_index === point && (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10'))) {
        menu.open(event, point)
      }
    }}>
    {outputMenu}
    {error ? <p role="alert">{error}</p> : details ? <CompactPointDetails details={details} sampleName={sampleName} bandName={bandName} />
      : <p role="status">正在读取分时数据…</p>}
  </section>
  return <section className="spectrum-point-details" aria-label="原始积分明细">
    {outputMenu}
    <div className="analysis-actions">
      <button className="secondary-button" disabled={point == null || busy} onClick={() => void load()}>{autoLoad?'刷新明细':'查看分时明细'}</button>
      {details && <>
        <button className="secondary-button" disabled={unavailable} onClick={() => void copy(true)}>纵向复制</button>
        <button className="secondary-button" disabled={unavailable} onClick={() => void copy(false)}>横向复制</button>
        <button className="secondary-button" disabled={unavailable} onClick={() => void print()}>打印积分明细 PDF</button>
      </>}
    </div>
    {error && <p role="alert">{error}</p>}
    {autoLoad && point == null && <p>移动鼠标查看逐帧积分，单击固定读数。</p>}
    {details && <>
      <p>CCD {details.ccd_index + 1} · 点 {details.point_index + 1} · 预激 {details.pre_excitation_seconds ?? '未记录'} 秒 ·
        燃烧 {details.burn_cycle_seconds ?? '未记录'} 秒 × {details.burn_count} · 空白 {details.dark_cycle_seconds ?? '未记录'} 秒 × {details.dark_count}</p>
      <div className="table-scroll" style={{ maxHeight: 300, overflow: 'auto' }} tabIndex={0}
        onContextMenu={event => { if (point !== null) menu.open(event, point) }}><table><thead><tr><th>阶段</th><th>积分序号</th><th>原始强度 ADC</th></tr></thead>
        <tbody>{details.rows.map((row) => <tr key={`${row.phase}:${row.integration}`}>
          <td>{row.phase === 'burn' ? '燃烧' : '空白'}</td><td>{row.integration}</td><td>{row.value}</td>
        </tr>)}</tbody></table></div>
    </>}
  </section>
}

function CompactPointDetails({ details, sampleName, bandName }: { details: DisplayDetails; sampleName?: string; bandName?: string }) {
  const seconds = (value: number | null) => value === null ? '未记录' : `${value} 秒`
  return <>
    <dl>
      <div><dt>样品编号</dt><dd>[{sampleName ?? details.sample_name}]</dd></div>
      <div><dt>谱带名称</dt><dd>[{bandName ?? ''}]</dd></div>
      <div><dt>当前坐标</dt><dd>({details.ccd_index + 1}, {details.point_index + 1})</dd></div>
      {details.wavelength_nm !== null && <div><dt>当前波长</dt><dd>{details.wavelength_nm.toFixed(4)} nm</dd></div>}
      <div className="point-preheat"><dt>预激时间</dt><dd>{seconds(details.pre_excitation_seconds)}</dd></div>
    </dl>
    {([
      ['burn', '积分', details.burn_cycle_seconds, details.burn_count],
      ['dark', '空白', details.dark_cycle_seconds, details.dark_count],
    ] as const).map(([phase, label, cycle, count]) => count > 0 && <section className="point-phase" key={phase} aria-label={`${label}明细`}>
      <p><span>{label}周期 {seconds(cycle)}</span><span>积分次数 {count}</span></p>
      <dl>{details.rows.filter(row => row.phase === phase).map(row => <div key={row.integration}>
        <dt>第{row.integration}次{label}强度</dt><dd>{row.value}</dd>
      </div>)}</dl>
    </section>)}
  </>
}
