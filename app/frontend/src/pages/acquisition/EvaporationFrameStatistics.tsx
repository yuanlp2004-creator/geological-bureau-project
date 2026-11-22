import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type AcquisitionFrame } from '../../api'
import { request } from '../../api/client'
import { EvaporationCurvePlot } from './EvaporationCurvePlot'

/** Frame statistics follow the record and CCD already chosen in the spectrum viewer. */
export function EvaporationFrameStatistics({ token, taskId, legacyId, initialCcd=0 }: {
  token:string;taskId?:number;legacyId?:number;initialCcd?:number
}) {
  const [frames,setFrames]=useState<AcquisitionFrame[]>([])
  const [ccd,setCcd]=useState(initialCcd)
  const [metric,setMetric]=useState<'peak_value'|'integral_value'>('peak_value')
  const [loading,setLoading]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0)
  const generation=useRef(0)
  useEffect(()=>{setCcd(initialCcd)},[initialCcd])
  useEffect(()=>{
    const ticket=++generation.current
    setFrames([]);setError('')
    if(!taskId&&!legacyId){setLoading(false);return}
    setLoading(true)
    void (legacyId?request<{frames:AcquisitionFrame[]}>(`/api/v1/spectrum-migration/evaporation-records/${legacyId}/curve`,
      {headers:{Authorization:`Bearer ${token}`}}).then(value=>value.frames):api.acquisitionFrames(token,taskId!,'?phase=burn'))
      .then(value=>{if(ticket===generation.current)setFrames(value)})
      .catch(failure=>{if(ticket===generation.current)setError(failure instanceof Error?failure.message:'读取蒸发帧失败')})
      .finally(()=>{if(ticket===generation.current)setLoading(false)})
    return()=>{generation.current++}
  },[token,taskId,legacyId,refresh])
  const indices=useMemo(()=>[...new Set(frames.map(frame=>frame.ccd_index))].sort((a,b)=>a-b),[frames])
  useEffect(()=>{if(indices.length&&!indices.includes(ccd))setCcd(indices[0])},[indices,ccd])
  const rows=useMemo(()=>frames.filter(frame=>frame.ccd_index===ccd&&!frame.damaged&&frame[metric]!==null)
    .sort((a,b)=>a.virtual_time_ms-b.virtual_time_ms||a.frame_index-b.frame_index),[frames,ccd,metric])
  const label=metric==='peak_value'?'原始帧峰值':'原始帧积分'
  return <section data-testid="evaporation-frame-statistics">
    <div className="viewer-dialog-fields">
      <label>统计量<select aria-label="蒸发统计量" value={metric} onChange={event=>setMetric(event.target.value as typeof metric)}>
        <option value="peak_value">帧峰值</option><option value="integral_value">帧积分</option>
      </select></label>
    </div>
    {loading?<p role="status">正在读取蒸发帧…</p>:error?<div role="alert">{error}<button onClick={()=>setRefresh(value=>value+1)}>重试读取</button></div>:
      !rows.length?<p>当前记录没有有效燃烧帧。</p>:<>
        <EvaporationCurvePlot key={`${taskId}:${legacyId}:${ccd}:${metric}:${refresh}`} rows={rows} metric={metric} label={label}
          navigation={<label>CCD<select aria-label="蒸发曲线CCD" value={ccd} onChange={event=>setCcd(Number(event.target.value))}>
            {indices.map(value=><option value={value} key={value}>CCD {value+1}</option>)}</select></label>}/>
        <div className="viewer-frame-table"><table className="legacy-view-table"><thead><tr><th>帧</th><th>时间（秒）</th><th>{label}</th></tr></thead>
          <tbody>{rows.map(row=><tr key={row.id}><td>{row.frame_index+1}</td><td>{(row.virtual_time_ms/1000).toFixed(3)}</td><td>{row[metric]}</td></tr>)}</tbody>
        </table></div>
      </>}
  </section>
}
