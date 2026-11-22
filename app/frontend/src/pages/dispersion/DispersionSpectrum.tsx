import { useEffect, useMemo, useRef, useState, type ComponentProps } from 'react'
import { api, saveFile, type DispersionFrame, type DispersionTask } from '../../api'
import { NumericInput } from '../../components/NumericInput'
import { SpectrumInspector } from '../../components/SpectrumInspector'
import { positionMarkers } from './dispersionView'

type Props = {
  recordNumber?:number
  onToast?:(message:string)=>void
  displayName?: string
  token: string
  active: DispersionTask
  ccd: number
  onPick: (point: number | null) => void
  curveView?: boolean
  focusPoint?: number | null
  selectLine?: (id: number) => void
  chooseCcd?: (ccd: number) => void
  exposure?: { start: number; end: number }
  bandNavigation?: { previous: () => void; next: () => void; canPrevious: boolean; canNext: boolean }
  context?: ComponentProps<typeof SpectrumInspector>['context']
  canPrint?: boolean
}

export function DispersionSpectrum({ token, active, ccd, onPick, curveView = false, onToast, displayName, recordNumber, chooseCcd, bandNavigation, exposure, focusPoint, selectLine, context, canPrint = false }: Props) {
  const [printing,setPrinting]=useState(false)
  const [mode, setMode] = useState<'live' | 'frame' | 'average'>(curveView ? 'average' : 'live')
  const [frames, setFrames] = useState<DispersionFrame[]>([])
  const [frameId, setFrameId] = useState<number | null>(null)
  const [localStart, setStart] = useState(1)
  const [localEnd, setEnd] = useState(1)
  const start=exposure?.start ?? localStart, end=exposure?.end ?? localEnd
  const legacyCurve=curveView&&Number(active.condition.source_record_id)>0
  const observationKey=`${token}:${active.id}:${ccd}:${start}:${end}:${active.burn_frames_captured}`
  const [observation,setObservation]=useState<{key:string;points:number[]}|null>(null)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(0)
  const historical = mode !== 'live'
  useEffect(() => {
    const ticket = ++request.current
    if (!historical||curveView) return
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
  }, [token, active.id, ccd, historical, refresh, curveView])
  useEffect(()=>{
    if(!curveView)return
    const ticket=++request.current
    setObservation(null);setError('');setLoading(false)
    if (!legacyCurve && !active.burn_frames_captured) return
    const valid=Number.isInteger(start)&&Number.isInteger(end)&&start>=1&&end>=start&&end<=active.frame_count
    if(!valid){setError('请选择有效的曝光区间');return}
    setLoading(true)
    const read = legacyCurve
      ? api.spectrum(token,`raw:${Number(active.condition.source_record_id)}`,{ccd:active.ccd_indices.indexOf(ccd),detail:'summary',exposureStart:start,exposureEnd:end,intensityMode:'legacy_2_0_2'})
        .then(record => record.ccd?.points.map(item => item.value ?? 0) ?? [])
      : api.dispersionObservationSpectrum(token, active.id, ccd, start, end).then(record => record.points)
    void read.then(points=>{
      if(ticket===request.current)setObservation({key:observationKey,points})
    }).catch(failure=>{if(ticket===request.current)setError(failure instanceof Error?failure.message:'读取区间谱图失败')}).finally(()=>{if(ticket===request.current)setLoading(false)})
    return()=>{request.current++}
  },[curveView,legacyCurve,observationKey,refresh])
  const frame = frames.find((item) => item.id === frameId)
  const burns = frames.filter((item) => item.phase === 'burn')
  const validRange = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= (curveView?active.frame_count:burns.length)
  const points = useMemo(() => {
    if(curveView)return !loading&&!error&&observation?.key===observationKey?observation.points:[]
    if (mode === 'live') return active.last_event?.ccds.find((item) => item.ccd_index === ccd)?.points ?? []
    if (loading || error) return []
    if (mode === 'frame') return frame?.points ?? []
    if (!validRange) return []
    const selected = burns.slice(start - 1, end)
    const count = selected[0]?.points.length ?? 0
    if (!count || selected.some((item) => item.points.length !== count)) return []
    return Array.from({ length: count }, (_, index) => selected.reduce((sum, item) => sum + item.points[index], 0) / selected.length)
  }, [mode, active.last_event, ccd, loading, error, frame, validRange, burns, start, end,curveView,observation,observationKey])
  const markers = positionMarkers(active.lines, ccd, active.layout.points_per_ccd, selectLine)
  const source = mode === 'live' ? '实时 / 最新帧'
    : mode === 'frame' ? `${frame?.phase === 'dark' ? '暗帧' : '燃烧帧'} ${(frame?.frame_index ?? 0) + 1}`
      : legacyCurve?`曝光区间 ${start}–${end} · 旧版积分强度`:`燃烧区间 ${start}–${end} 均值（仅用于观察）`
  const print=async(range:{xMin:number;xMax:number;yMin:number;yMax:number})=>{
    const id=Number(active.condition.source_record_id)
    if(!canPrint||printing||!validRange||!points.length)return
    setPrinting(true)
    try{
      let blob: Blob
      if (legacyCurve) {
      const slot=active.ccd_indices.indexOf(ccd),recordId=`raw:${id}`
      const record=await api.spectrum(token,recordId,{ccd:slot,detail:'summary',exposureStart:start,exposureEnd:end,intensityMode:'legacy_2_0_2'})
      const values=record.ccd?.points??[]
      const native=(point:number)=>{const index=Math.max(0,Math.min(values.length-1,point)),low=values[Math.floor(index)],high=values[Math.ceil(index)];const x=(item:typeof low)=>Number(item?.wavelength_nm??item?.step??item?.point_index??0);return x(low)+(x(high)-x(low))*(index-Math.floor(index))}
      const pdf=await api.printSpectrumPdf(token,recordId,{ccd:slot,line:0,mode:'mean',reference_shift:0,visible_x_min:native(range.xMin),visible_x_max:native(range.xMax),visible_y_min:range.yMin,visible_y_max:range.yMax,
        intensity_mode:'legacy_2_0_2',selected_record_ids:[recordId],priority_record_id:recordId,frame_phase:'burn',frame_index:0,exposure_start:start,exposure_end:end,print_scope:'visible',print_layers:['grayscale','curve'],print_scale:'fit_long',paper:'A4'})
      blob = pdf.blob
      } else {
        blob = await api.printDispersionObservation(token, active.id, {
          ccd, exposure_start: start, exposure_end: end,
          x_min: range.xMin, x_max: range.xMax, y_min: range.yMin, y_max: range.yMax
        })
      }
      const name = (displayName ?? active.name).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
      const path=await saveFile(blob,`色散-${name}-CCD${ccd+1}.pdf`)
      onToast?.(path?`谱图PDF已保存：${path}`:'已取消保存')
    }catch(failure){onToast?.(failure instanceof Error?failure.message:'打印失败')}finally{setPrinting(false)}
  }
  return <div className={`dispersion-spectrum-view${curveView ? ' legacy-view-center' : ''}`}>
    {!curveView && <div className="inspector-frame-tools">
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
    </div>}
    {error && <p role="alert">{error}</p>}
    <SpectrumInspector fitPlot iconToolbar={curveView} focusPoint={focusPoint} yAxisLabel={legacyCurve?'旧版积分强度':undefined} context={context}
      onPrint={curveView?range=>void print(range):undefined}
      printDisabledReason={!canPrint?'需要谱图导出权限':printing?'正在生成PDF':!validRange||!points.length?'请选择已保存的曝光区间':undefined}
      legacyTitle={curveView ? `记录号：[${recordNumber??active.id}]  谱带名称：[${displayName??active.name}]  CCD序号：[${ccd+1}]  曝光区间：[${start}-${end}]` : undefined}
      physicalScale={{ pointWidthUm: active.layout.point_width_um, screenWidthMm: active.profile.screen_width_mm, screenResolutionPx: active.profile.screen_resolution_px }}
      ccdNavigation={chooseCcd ? { current: ccd, indices: active.ccd_indices, choose: chooseCcd } : undefined}
      bandNavigation={bandNavigation} key={`${mode}:${mode === 'frame' ? frameId : mode === 'average' ? `${start}:${end}` : 'latest'}`}
      points={points} pointOrigin={0} label={`CCD ${ccd + 1} · ${source}`} markers={markers} onPick={onPick}
      emptyText={loading ? '正在读取已保存帧…' : error ? '帧读取失败，请刷新重试'
        : mode === 'average' && burns.length && !validRange ? '请选择有效的燃烧帧区间'
          : historical ? '当前 CCD 没有可显示的已保存帧' : '开始采集后显示实时 CCD 曲线'} />
  </div>
}
