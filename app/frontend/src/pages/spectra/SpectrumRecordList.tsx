import { Fragment, useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import type { SpectrumRecordSummary } from '../../api'
import { spectrumViewerApi, type SpectrumConcentrationPreview } from '../../api/spectrumViewer'
import { formatAnalysisValue } from '../../components/analysisUnits'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { RowSelectionArrow } from '../../components/RowSelectionArrow'

type Props = {
 token: string
 currentMethodVersionId?: number | null
 visibleRecords:SpectrumRecordSummary[]; selectedId:string|null; displayIds:string[]
 selectRecord:(record:SpectrumRecordSummary,additive?:boolean)=>void; recordLocked:boolean
 multiView:boolean; toggleMulti:()=>void; toggleLock:()=>void; onHide:()=>void
 onContextMenu: React.MouseEventHandler<HTMLElement>
}

function RecordConcentrations({ token, recordId }: { token: string; recordId: string }) {
 const [preview, setPreview] = useState<SpectrumConcentrationPreview>()
 const [error, setError] = useState('')
 useEffect(() => {
   const controller = new AbortController()
   spectrumViewerApi.spectrumConcentrations(token, recordId, controller.signal).then(result => {
     if (!controller.signal.aborted) setPreview(result)
   }).catch(error => {
     if (!controller.signal.aborted) setError(error instanceof Error ? error.message : '读取浓度失败')
   })
   return () => controller.abort()
 }, [token, recordId])

 if (error) return <div role="alert">{error}</div>
 if (!preview) return <div role="status">正在计算浓度…</div>
 return <>
   <div className="spectrum-concentration-method">元素强度与参考含量 · {preview.method_name}（版本 {preview.method_version}）</div>
   {preview.method_notice && <small className="spectrum-concentration-message" role="status">{preview.method_notice}</small>}
   {!preview.rows.length ? <div>该方法没有启用的分析谱线</div> :
     <ul aria-label="元素浓度">{preview.rows.map(row => <li key={row.line_id}>
       <span>{row.element} <small>{row.wavelength_nm.toFixed(4)} nm</small></span>
       {row.raw_intensity !== null && <small className="spectrum-concentration-message">
         {row.peak_found ? '峰位强度' : '预计点位强度'} {formatAnalysisValue(row.raw_intensity, 2)} (ADC)
       </small>}
       {row.concentration !== null &&
         <span className="spectrum-concentration-value" title={row.curve_source === 'published' ? '已发布标准曲线' : '用方法中的标准点拟合'}>
           {formatAnalysisValue(row.concentration, row.decimal_places)} {row.unit}
         </span>}
       {(row.message || row.concentration === null) &&
         <span className="spectrum-concentration-message">{row.message || '无法计算'}</span>}
     </li>)}</ul>}
 </>
}

const hasConcentrationPreview = (record: SpectrumRecordSummary) =>
  record.task_kind === 'sample' || record.format === 'cdt' || record.format === 'cmt'

export function SpectrumRecordList(p:Props) {
 const [expandedId, setExpandedId] = useState<string | null>(null)
 const selected=p.visibleRecords.find(item=>item.id===p.selectedId)
 const dispersion=selected?.format==='wdt'||selected?.format==='dispersion'
 const band=dispersion||selected?.format==='edt'||selected?.task_kind==='evaporation'
 const title=dispersion?'色散文件':selected?.format==='edt'||selected?.task_kind==='evaporation'?'蒸发文件'
  :selected?.format==='cmt'||selected?.storage_mode==='full_interval'?'全时样品':'样品谱图'
 return <aside className="legacy-view-rail spectrum-records" aria-label={title} tabIndex={0} onContextMenu={p.onContextMenu}><header><h2 title={`${p.visibleRecords.length} 条`}>{title}</h2><button aria-label="隐藏样品列表" onClick={p.onHide}>×</button></header>
  {!band&&<div className="legacy-record-toolbar" role="toolbar" aria-label="样品列表操作">
   <SpectroscopyToolButton icon="sample-list-input" label="录入样品编号" disabled description="查看页只读；样品编号请在样品队列或摄谱任务中录入"/>
   <SpectroscopyToolButton icon="sample-list-clear" label="清除样品编号" disabled description="查看页只读，不清除已保存的样品编号"/>
   <SpectroscopyToolButton icon="multi-view" label={p.multiView?'切换单样品查看':'切换多样品查看'} aria-pressed={p.multiView} disabled={!selected||selected.kind==='result'} onClick={p.toggleMulti}/>
   <SpectroscopyToolButton icon={p.recordLocked?'record-unlock':'record-lock'} label={p.recordLocked?'解锁谱带记录':'锁定谱带记录'} aria-pressed={p.recordLocked} disabled={!selected} onClick={p.toggleLock}/>
  </div>}
  <div className="legacy-view-table-wrap spectrum-record-list" data-record-kind={band ? 'band' : 'sample'}><table className="legacy-view-table"><colgroup><col className="record-indicator"/>
   {band?<col className="record-name"/>:<><col className="record-number"/><col className="record-name"/><col className="record-concentration"/></>}</colgroup>
   <thead><tr><th className="row-indicator"/>{band?<th>谱带名称</th>:<><th>记录号</th><th>样品编号</th><th className="spectrum-concentration-toggle" aria-label="元素浓度"/></>}</tr></thead>
   <tbody>{p.visibleRecords.map(record => {
    const recordNumber = record.band_id ?? record.record_index
    const panelId = `spectrum-concentrations-${record.id}`
    const expanded = !band && hasConcentrationPreview(record) && expandedId === record.id
    return <Fragment key={record.id}><tr aria-selected={p.displayIds.includes(record.id)} className="spectrum-record-row"
    title={band?undefined:'单击查看；按住 Ctrl 点击可叠加比较'} onClick={event=>p.selectRecord(record,!band&&(event.ctrlKey||event.metaKey))}>
    <td className="row-indicator">{p.selectedId===record.id&&<RowSelectionArrow />}</td>
    {!band&&<td>{recordNumber}</td>}
    <td><button disabled={p.recordLocked&&record.id!==p.selectedId} title={record.band_name||record.sample_name||record.id}
     >{band?record.band_name||record.sample_name||record.id:record.sample_name||record.band_name||record.id}</button></td>
    {!band&&<td className="spectrum-concentration-toggle">{hasConcentrationPreview(record) &&
      <button type="button" aria-label={`记录 ${recordNumber} 的元素浓度`} aria-expanded={expanded}
        aria-controls={expanded ? panelId : undefined} title="元素浓度" onClick={event => {
          event.stopPropagation()
          setExpandedId(expanded ? null : record.id)
        }}><ChevronDown size={16} aria-hidden="true"/></button>}</td>}
   </tr>{expanded && <tr><td colSpan={4} className="spectrum-concentration-cell">
     <div id={panelId} className="spectrum-concentration-panel" role="region" aria-label={`记录 ${recordNumber} 的估算浓度`}>
       <RecordConcentrations key={record.kind === 'raw' ? p.currentMethodVersionId ?? 'no-method' : record.id} token={p.token} recordId={record.id}/>
     </div>
   </td></tr>}</Fragment>
   })}</tbody></table></div>
  <div className="legacy-view-footer">{selected?.measure_time?.replace('T',' ').slice(0,19)||'测量时间未记录'}</div>
 </aside>
}
