import { useEffect, useState } from 'react'
import { api } from '../../api'
import { request } from '../../api/client'
import { SpectrumViewerPage } from '../spectra/SpectrumViewerPage'
import { EvaporationFrameStatistics } from './EvaporationFrameStatistics'

/** Acquisition-only accounts retain their existing read access in one compact view. */
function AcquisitionFrameViewer({token}:{token:string}) {
  const [choices,setChoices]=useState<Array<{key:string;name:string;taskId?:number;legacyId?:number}>>([]),[key,setKey]=useState(''),[error,setError]=useState('')
  useEffect(()=>{let live=true;void Promise.all([api.acquisitionTasks(token,'evaporation'),
    request<Array<{id:number;sample_name:string}>>('/api/v1/spectrum-migration/evaporation-records',{headers:{Authorization:`Bearer ${token}`}})]).then(([tasks,legacy])=>{
    if(!live)return
    const saved=[...tasks.filter(task=>task.task_kind==='evaporation'&&task.sample_kind!=='preheat').map(task=>({key:`task:${task.id}`,name:captureAngleName(task),taskId:task.id})),
      ...legacy.map(record=>({key:`legacy:${record.id}`,name:record.sample_name||`蒸发记录 ${record.id}`,legacyId:record.id}))]
    setChoices(saved);setKey(saved[0]?.key??'')
  }).catch(failure=>{if(live)setError(failure instanceof Error?failure.message:'读取蒸发实验失败')});return()=>{live=false}},[token])
  const selected=choices.find(choice=>choice.key===key)
  return <div className="page-content" data-testid="evaporation-acquisition-viewer">
    {error?<p role="alert">{error}</p>:<><label>蒸发实验<select aria-label="已存蒸发实验" value={key} onChange={event=>setKey(event.target.value)}>
      {!choices.length&&<option value="">暂无已保存实验</option>}{choices.map(choice=><option key={choice.key} value={choice.key}>{choice.name}</option>)}</select></label>
      {selected&&<EvaporationFrameStatistics token={token} taskId={selected.taskId} legacyId={selected.legacyId}/>}</>}
  </div>
}

export function EvaporationCurvesPage(props:{token:string;onToast:(message:string)=>void;onClose?:()=>void;actionsTarget?:HTMLElement|null;canExport?:boolean}) {
  const [spectra,setSpectra]=useState<boolean|null>(null)
  useEffect(()=>{let live=true;void api.me(props.token).then(user=>{if(live)setSpectra(user.permissions.includes('spectra.read'))})
    .catch(()=>{if(live)setSpectra(false)});return()=>{live=false}},[props.token])
  return <div data-testid="evaporation-curves-page">{spectra===null?<p>正在读取查看权限…</p>:
    spectra?<SpectrumViewerPage {...props} viewing="evaporation"/>:<AcquisitionFrameViewer token={props.token}/>}</div>
}
import { captureAngleName } from './CaptureTurnPages'
