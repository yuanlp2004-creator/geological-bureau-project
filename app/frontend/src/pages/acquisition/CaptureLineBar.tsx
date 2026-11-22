import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../../api'
import type { MethodLineCollection } from '../../api/methods'
import type { SpectrumPlotMarker } from '../../components/SpectrumPlot'
import { spectralLineMenuGroups } from '../../components/spectrumMenu'

export type CaptureLineChoice = { id: string; label: string; wavelength: number; exposure?: string }
export function CaptureLineBar({ lines = [], value = '', choose, disabled = false, unavailable = '当前没有可选择的谱线', defaultExposure = '', exposureInput, locate }:
  { lines?: CaptureLineChoice[]; value?: string; choose?: (id: string) => void; disabled?: boolean; unavailable?: string; defaultExposure?: string; exposureInput?: ReactNode; locate?: (value:string)=>void }) {
  const [coordinate,setCoordinate]=useState('')
  const line = lines.find(item => item.id === value)
  return <div className="spectroscopy-line-bar" aria-label="谱线与曝光区间">
    <label><span>选择谱线:</span><select aria-label="选择谱线" value={value} disabled={disabled || !lines.length} title={!lines.length ? unavailable : '查看当前任务谱线'}
      onChange={event => choose?.(event.target.value)}>
      <option value="" />
      {lines.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select></label>
    <label><span>定位谱线:</span><input aria-label="定位谱线" title={locate?'输入波长或 CCD,点位（1起），按回车定位':'当前谱线波长（nm），只读观察'} readOnly={!locate}
      disabled={disabled} value={locate?coordinate:line?.wavelength || ''} placeholder={locate?'波长或 CCD,点位':undefined}
      onChange={event=>setCoordinate(event.target.value)} onKeyDown={event=>{if(locate&&event.key==='Enter'){event.preventDefault();locate(coordinate)}}} /></label>
    <label><span>曝光区间:</span>{exposureInput ?? <input aria-label="曝光区间"
      title="当前任务方法版本规定的帧区间；修改条件请回到方法参数" readOnly value={line?.exposure ?? defaultExposure} />}</label>
  </div>
}

export function useSampleCaptureLines({ token, canReadMethods, taskId, methodId, version, frames, ccd, ccdIndices, pointsPerCcd, chooseCcd, turns, turnIndex }:
  { token: string; canReadMethods: boolean; taskId?: number; methodId: number | null; version: number | null; frames: number;
    ccd: number; ccdIndices: number[]; pointsPerCcd: number; chooseCcd: (ccd: number) => void;
    turns?: import('../../api').AcquisitionTask['turns']; turnIndex?: number }) {
  const [snapshot, setSnapshot] = useState<{ key: string; value: MethodLineCollection } | null>(null)
  const [lineId, setLineId] = useState('')
  const [priorityLine, setPriorityLine] = useState(true)
  const [focusRevision, setFocusRevision] = useState(0)
  const [error, setError] = useState('')
  const key = `${token}:${taskId}:${methodId}:${version}`
  useEffect(() => {
    setSnapshot(null); setLineId(''); setError('')
    if (!canReadMethods || !methodId || !version) return
    let cancelled = false
    void api.methodLines(token, methodId, version).then(value => {
      if (cancelled) return
      if (value.version === version && value.state === 'published') setSnapshot({ key, value })
      else setError('当前任务的方法版本不可用')
    }).catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : '读取任务谱线失败') })
    return () => { cancelled = true }
  }, [key, canReadMethods])
  const turn = turns?.plan.find(item => item.turn_index === turnIndex)
  const methodLines = snapshot?.key === key ? snapshot.value.lines.filter(line => !turn || turn.lines.some(item => item.id === line.id)) : []
  const selectedLine = methodLines.find(line => line.id === lineId)
  const positionOf = (line: typeof selectedLine) => {
    if (turns) {
      const location = turn?.lines.find(item => item.id === line?.id)
      return turn?.turn_index === turnIndex && location ? { detectable: true, ccd_index: location.ccd_index, point_index: location.point_index } : null
    }
    const position = line?.detectability
    return position?.detectable && position.ccd_index !== undefined && ccdIndices.includes(position.ccd_index)
      && position.point_index !== undefined && Number.isFinite(position.point_index)
      && position.point_index >= 0 && position.point_index < pointsPerCcd ? position : null
  }
  const choose = (id: string) => {
    setLineId(id)
    setFocusRevision(value => value + 1)
    const position = positionOf(methodLines.find(line => line.id === id))
    if (position?.ccd_index !== undefined) chooseCcd(position.ccd_index)
  }
  useEffect(() => {
    const position = positionOf(selectedLine)
    if (position && position.ccd_index !== ccd) setLineId('')
  }, [ccd])
  useEffect(() => { setLineId('') }, [turnIndex])
  const selectedPosition = positionOf(selectedLine)
  const markers: SpectrumPlotMarker[] = methodLines.flatMap(line => {
    const position = positionOf(line)
    return position?.ccd_index === ccd && position.point_index !== undefined ? [{
      key: line.id, kind: 'located' as const, position: position.point_index + 1,
      label: `${line.element} ${line.actual_wavelength_nm ?? line.wavelength_nm} nm · 保存位置 ${(position.point_index + 1).toFixed(2)}`,
      select: () => choose(line.id), selected: line.id === lineId
    }] : []
  })
  const lines = methodLines.map(line => ({ id: line.id,
    label: `${line.element} ${line.wavelength_nm}`, wavelength: line.actual_wavelength_nm ?? line.wavelength_nm,
    exposure: `${line.exposure_start_frame ?? 1}-${line.exposure_end_frame ?? frames}` }))
  return {
    focusPoint: priorityLine && selectedPosition?.ccd_index === ccd ? selectedPosition.point_index : null,
    focusRevision,
    markers,
    chooseMarker: setLineId,
    lineMenu: (id: string) => {
      const line = methodLines.find(item => item.id === id)
      if (!line) return undefined
      const restore = () => { setPriorityLine(true); choose(id) }
      return spectralLineMenuGroups(methodLines, line, value => choose(value.id),
        { label: '优先显示', checked: priorityLine, run: () => setPriorityLine(value => !value) }, [], [
          { label: '还原实际位置', run: restore },
          { label: '还原全部位置', run: () => { setLineId(''); setFocusRevision(value => value + 1) } }
        ])
    },
    lineBar: <CaptureLineBar lines={lines} value={lineId} choose={choose} defaultExposure={turn ? `${turn.start_frame}-${turn.end_frame}` : frames ? `1-${frames}` : ''}
      unavailable={error || (!canReadMethods ? '当前没有可定位的方法谱线' : snapshot?.key === key ? '本转角没有已关联谱线' : '等待当前任务的方法谱线')} />
  }
}
