import { SectionHeading } from '../../components/SectionHeading'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { request } from '../../api/client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, type AcquisitionFrame, type AcquisitionTask } from '../../api'
import { SimpleChartAxes } from '../../components/SimpleChartAxes'
import { TaskLayout } from '../../layout/TaskLayout'
import { stateLabel } from './acquisitionView'

/** Read-only view of the peak/integral values already stored for each evaporation frame. */
export function EvaporationCurvesPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [legacy, setLegacy] = useState<Array<{id:number;sample_name:string}>>([])
  const [legacyId, setLegacyId] = useState<number | null>(null)
  const [legacyCcds, setLegacyCcds] = useState<number[]>([])
  const [tasks, setTasks] = useState<AcquisitionTask[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [frames, setFrames] = useState<AcquisitionFrame[]>([])
  const [ccd, setCcd] = useState(0)
  const [metric, setMetric] = useState<'peak_value' | 'integral_value'>('peak_value')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const generation = useRef(0)
  const listGeneration = useRef(0)
  const selected = tasks.find((task) => task.id === selectedId)
  const load = useCallback(async () => {
    const ticket = ++listGeneration.current
    try {
      const [next, old] = await Promise.all([api.acquisitionTasks(token, 'evaporation'), request<Array<{id:number;sample_name:string}>>('/api/v1/spectrum-migration/evaporation-records', {headers:{Authorization:`Bearer ${token}`}})])
      if (ticket !== listGeneration.current) return
      setLegacy(old)
      const experiments = next.filter((task) => task.task_kind === 'evaporation' && task.sample_kind !== 'preheat')
      setTasks(experiments)
      setSelectedId((current) => experiments.some((task) => task.id === current) ? current : experiments[0]?.id ?? null)
      setRefresh((value) => value + 1)
    } catch (failure) {
      if (ticket === listGeneration.current) onToast(failure instanceof Error ? failure.message : '读取蒸发实验失败')
    }
  }, [token, onToast])
  useEffect(() => { void load(); return () => { listGeneration.current++ } }, [load])
  useEffect(() => {
    if (selected && !selected.ccd_indices.includes(ccd)) setCcd(selected.ccd_indices[0] ?? 0)
  }, [selected, ccd])
  useEffect(() => {
    const ticket = ++generation.current
    setFrames([])
    setError('')
    if (selectedId === null && legacyId === null) { setLoading(false); return }
    setLoading(true)
    void (legacyId !== null
      ? request<{frames:AcquisitionFrame[];ccd_indices:number[]}>(`/api/v1/spectrum-migration/evaporation-records/${legacyId}/curve`, {headers:{Authorization:`Bearer ${token}`}}).then(result => {if(ticket === generation.current) {setLegacyCcds(result.ccd_indices);setCcd(value => result.ccd_indices.includes(value) ? value : result.ccd_indices[0] ?? 0)};return result.frames})
      : api.acquisitionFrames(token, selectedId!, '?phase=burn')).then((next) => {
      if (ticket === generation.current) setFrames(next)
    }).catch((failure) => {
      if (ticket === generation.current) setError(failure instanceof Error ? failure.message : '读取蒸发帧失败')
    }).finally(() => { if (ticket === generation.current) setLoading(false) })
    return () => { generation.current++ }
  }, [token, selectedId, legacyId, refresh])
  const rows = useMemo(() => frames.filter((frame) => frame.ccd_index === ccd && !frame.damaged && frame[metric] !== null)
    .sort((left, right) => left.virtual_time_ms - right.virtual_time_ms || left.frame_index - right.frame_index), [frames, ccd, metric])
  const selectedName = legacyId !== null ? legacy.find(item => item.id === legacyId)?.sample_name ?? '旧蒸发曲线' : selected?.name
  const ccdIndices = legacyId !== null ? legacyCcds : selected?.ccd_indices ?? []
  const xMin = rows[0]?.virtual_time_ms / 1000 || 0
  const xMax = rows.length > 1 ? rows[rows.length - 1].virtual_time_ms / 1000 : xMin + 1
  const yMax = Math.max(1, ...rows.map((frame) => frame[metric] ?? 0)) * 1.05
  const label = metric === 'peak_value' ? '帧峰值' : '帧积分'
  const point = (frame: AcquisitionFrame) => `${((frame.virtual_time_ms / 1000 - xMin) / (xMax - xMin || 1) * 1000).toFixed(3)},${(300 - (frame[metric] ?? 0) / yMax * 300).toFixed(3)}`
  return <div className="page-content evaporation-curves-page refined-page remaining-page" data-testid="evaporation-curves-page">
    
    <TaskLayout className="evaporation-curves-grid" showEmptyRail hasItems={Boolean(tasks.length || legacy.length)} current={selectedName ?? '选择蒸发实验'} actions={<div className="file-actions"> <div className="file-actions"><OpenLegacyFile token={token} purpose="evaporation" label="打开蒸发文件" disabled={loading} onOpened={async result => { await load(); setLegacyId(result.record_ids[0]); setSelectedId(null) }}/>
      <button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div></div>}>
      <aside className="surface acquisition-task-list"><div className="surface-heading"><h2>蒸发实验</h2></div>
        <div className="acquisition-task-rows">{tasks.map((task) => <button key={task.id} className={task.id === selectedId ? 'active' : ''} onClick={() => {setLegacyId(null); setSelectedId(task.id)}}>
          <span><strong>{task.name}</strong><small>{task.samples.find((sample) => !sample.discarded)?.sample_name || '未命名实验'} · {stateLabel[task.status]}</small></span>
        </button>)}{legacy.map(item => <button key={`legacy-${item.id}`} className={legacyId === item.id ? 'active' : ''} onClick={() => {setLegacyId(item.id);setSelectedId(null)}}><span><strong>{item.sample_name || `EDT #${item.id}`}</strong><small>旧蒸发文件</small></span></button>)}{!tasks.length && !legacy.length && <p>打开蒸发文件，或先完成蒸发摄谱。</p>}</div></aside>
      <main className="evaporation-curves-main"><section className="surface">
        <div className="surface-heading"><SectionHeading title={<>{selectedName ?? '蒸发曲线'}</>} /><div className="evaporation-curve-toolbar">
          <label className="field"><span>CCD</span><select aria-label="蒸发曲线CCD" value={ccd} disabled={!ccdIndices.length} onChange={(event) => setCcd(Number(event.target.value))}>
            {ccdIndices.map((index) => <option value={index} key={index}>CCD {index + 1}</option>)}
          </select></label>
          <label className="field"><span>曲线数据</span><select aria-label="蒸发曲线数据" value={metric} onChange={(event) => setMetric(event.target.value as typeof metric)}>
            <option value="peak_value">帧峰值</option><option value="integral_value">帧积分</option>
          </select></label></div></div>
        {error ? <p className="auth-error" role="alert">{error}</p> : loading ? <div className="empty-state">正在读取蒸发帧…</div> : rows.length ? <>
          <div className="evaporation-time-chart simple-chart-plot-host" data-testid="evaporation-time-chart">
            <div className="simple-chart-plot"><svg viewBox="0 0 1000 300" preserveAspectRatio="none" role="img" aria-label="蒸发强度随时间曲线">
              <polyline points={rows.map(point).join(' ')} fill="none" stroke="var(--blue)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
              {rows.length === 1 && <circle cx="0" cy={300 - (rows[0][metric] ?? 0) / yMax * 300} r="4" fill="var(--blue)" />}
            </svg></div><SimpleChartAxes xMin={xMin} xMax={xMax} yMin={0} yMax={yMax} xLabel="采集时间（秒）" yLabel={label} fractionalX />
          </div>
          <div className="sample-table-wrap"><table className="data-table"><thead><tr><th>帧</th><th>采集时间（秒）</th><th>{label}</th></tr></thead>
            <tbody>{rows.map((frame) => <tr key={frame.id}><td>{frame.frame_index + 1}</td><td>{(frame.virtual_time_ms / 1000).toFixed(3)}</td><td>{frame[metric]}</td></tr>)}</tbody>
          </table></div>
        </> : <div className="empty-state">当前实验没有可显示的有效燃烧帧。</div>}
      </section></main>
    </TaskLayout>
  </div>
}
