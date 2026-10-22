import {useEffect,useState} from 'react'
import {request} from '../../api/client'
import {saveFile} from '../../platform/files'
import { Download, FileText, Printer } from 'lucide-react'

type Options={save_intensity:boolean;print_intensity:boolean;print_to_text:boolean;save_positions:boolean}
export function IntensityOutput({token,runId,defaults,canPrint,canSaveMethod,canExecute,allowPositionOutput=true,presentation='analysis',disabled=false,onBusyChange,onToast}: {
  token:string;runId:number;defaults?:Options;canPrint:boolean;canSaveMethod:boolean;canExecute:boolean;allowPositionOutput?:boolean;presentation?:'analysis'|'report';disabled?:boolean;onBusyChange?:(busy:boolean)=>void;onToast:(text:string)=>void
}) {
  const [options,setOptions]=useState<Options>({save_intensity:true,print_intensity:false,print_to_text:false,save_positions:false})
  const [busy,setBusy]=useState(false)
  useEffect(() => {if(defaults)setOptions({...defaults,print_intensity:defaults.print_intensity&&canPrint,save_positions:defaults.save_positions&&canSaveMethod&&allowPositionOutput})},[defaults,canPrint,canSaveMethod,allowPositionOutput])
  useEffect(() => {onBusyChange?.(busy)},[busy,onBusyChange])
  useEffect(() => () => {onBusyChange?.(false)},[onBusyChange])
  const output=async (selected=options) => {
    if(busy||disabled)return
    setBusy(true)
    try {
      const result=await request<{files:Array<{filename:string;content_base64:string;media_type:string}>;method_draft?:{latest_version:number};print_job?:{status:string}}>(`/api/v1/analyses/runs/${runId}/intensity-output`,{
        method:'POST',headers:{Authorization:`Bearer ${token}`},body:JSON.stringify(selected)
      })
      let saved=0
      for(const file of result.files)if(await saveFile(new Blob([Uint8Array.from(atob(file.content_base64),char=>char.charCodeAt(0))],{type:file.media_type}),file.filename))saved++
      onToast(`强度输出完成，已保存 ${saved} 个文件${result.print_job?'；打印已提交':''}${result.method_draft?`；位置已保存为方法草稿 v${result.method_draft.latest_version}`:''}`)
    } catch(error){onToast(error instanceof Error?error.message:'强度输出失败')}finally{setBusy(false)}
  }
  const choices=<><div className="analysis-actions">
    {([['save_intensity','保存强度文件'],['print_intensity','打印强度'],['print_to_text','强度到文本'],['save_positions','保存校正波长']] as const).filter(([key])=>allowPositionOutput||key!=='save_positions').map(([key,label]) =>
      <label className="checkbox-row" key={key}><input type="checkbox" checked={options[key]} disabled={busy || key==='print_intensity'&&!canPrint || key==='save_positions'&&!canSaveMethod}
        onChange={e=>setOptions({...options,[key]:e.target.checked})}/>{label}</label>)}
    <button className="primary-button" disabled={busy || disabled || !Object.values(options).some(Boolean)} onClick={()=>void output()}>执行所选输出</button>
    <button className="secondary-button" disabled={busy || !canExecute} onClick={async()=>{
      if(busy)return
      setBusy(true)
      try{await request('/api/v1/analyses/intensity-output/defaults',{method:'PUT',headers:{Authorization:`Bearer ${token}`},body:JSON.stringify(options)});onToast('强度输出默认选项已保存')}
      catch(error){onToast(error instanceof Error?error.message:'默认选项保存失败')}
      finally{setBusy(false)}
    }}>保存为默认</button></div><small>逐样品、逐重复的峰值/背景宽表；强度文件采用新版格式{allowPositionOutput?'，校正位置保存为待审核的方法草稿':''}。</small></>
  if(presentation==='report')return <section className="surface report-export intensity-export">
    <div className="surface-heading"><h2>格式与输出</h2><Download size={18}/></div>
    <p className="intensity-output-note">导出或打印当前批次的完整强度表，保存位置在输出时选择。打印使用系统设置中的默认打印机。</p>
    <div className="report-format-actions">
      <button className="secondary-button" disabled={busy||disabled} onClick={()=>void output({save_intensity:false,print_intensity:false,print_to_text:true,save_positions:false})}><FileText size={15}/>文本</button>
      <button className="secondary-button" disabled={busy||disabled||!canPrint} onClick={()=>void output({save_intensity:false,print_intensity:true,print_to_text:false,save_positions:false})}><Printer size={15}/>打印</button>
    </div>
    <details className="intensity-more-options"><summary>更多选项：强度文件与输出默认设置</summary>
      <p className="intensity-output-note">“保存强度文件”保存 JSON 强度快照，包含方法和计算信息。</p>{choices}
    </details>
  </section>
  return <section className="surface"><h3>分析强度输出</h3>{choices}</section>
}
