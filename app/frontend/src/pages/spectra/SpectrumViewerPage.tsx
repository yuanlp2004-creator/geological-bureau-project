import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, ChevronRight, ChevronLeft, Database, Download, LockKeyhole, UnlockKeyhole, Maximize2, RotateCcw, ZoomIn, ZoomOut, Printer, RefreshCw } from 'lucide-react'
import { api, saveFile, type SpectrumRecordSummary, type SpectrumRecord } from '../../api'
import { SpectrumPlot, type SpectrumPlotCurve, type SpectrumPlotCursor } from '../../components/SpectrumPlot'
import { CopyableCode, ExpandableValue } from '../../components/InformationDisplay'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'

export function SpectrumViewerPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [records, setRecords] = useState<SpectrumRecordSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [overlayIds, setOverlayIds] = useState<string[]>([])
  const [details, setDetails] = useState<Record<string, SpectrumRecord>>({})
  const [priorityId, setPriorityId] = useState<string | null>(null)
  const [ccd, setCcd] = useState(0)
  const [line, setLine] = useState(0)
  const [mode, setMode] = useState<'mean' | 'peak' | 'back' | 'value'>('mean')
  const [angleFilter, setAngleFilter] = useState<string>('all')
  const [exposureEnabled, setExposureEnabled] = useState(false)
  const [exposureStart, setExposureStart] = useState(1)
  const [exposureEnd, setExposureEnd] = useState(1)
  const [referenceShift, setReferenceShift] = useState(0)
  const [zoomX, setZoomX] = useState(1)
  const [zoomY, setZoomY] = useState(1)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [locked, setLocked] = useState(false)
  const [locateValue, setLocateValue] = useState('')
  const [framePhase, setFramePhase] = useState<'burn' | 'dark'>('burn')
  const [frameIndex, setFrameIndex] = useState(0)
  const [frameVisible, setFrameVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const detailRequest = useRef(0)
  const palette = ['#1c68b2', '#c75b39', '#27805d', '#8b5bb5', '#d18b22', '#247c8b', '#b54769', '#58677a']

  const loadRecords = useCallback(async () => {
    setBusy(true)
    try {
      const next = await api.spectrumRecords(token)
      setRecords(next)
      setSelectedId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null)
      setPriorityId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取谱图记录') }
    finally { setBusy(false) }
  }, [token, onToast])

  useEffect(() => { void loadRecords() }, [loadRecords])
  const selected = records.find((item) => item.id === selectedId) ?? null
  const raw = selected?.kind === 'raw'
  const displayIds = useMemo(() => {
    if (!selectedId) return []
    if (!raw) return [selectedId]
    return Array.from(new Set([selectedId, ...overlayIds])).slice(0, 8)
  }, [selectedId, overlayIds, raw])

  const loadDetails = useCallback(async () => {
    if (!displayIds.length) return
    const requestId = ++detailRequest.current
    setBusy(true)
    try {
      const loaded = await Promise.all(displayIds.map(async (id) => {
        const summary = records.find((item) => item.id === id)
        const nextCcd = Math.max(0, Math.min((summary?.ccd_count ?? 1) - 1, ccd))
        const params = {
          ccd: nextCcd,
          line,
          detail: 'summary' as const,
          exposureStart: raw && exposureEnabled ? exposureStart : undefined,
          exposureEnd: raw && exposureEnabled ? exposureEnd : undefined,
        }
        return [id, await api.spectrum(token, id, params)] as const
      }))
      if (requestId !== detailRequest.current) return
      setDetails(Object.fromEntries(loaded))
      setFrameVisible(false)
      setCursor(null)
      setLocked(false)
    } catch (error) { if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '无法读取谱图数据') }
    finally { if (requestId === detailRequest.current) setBusy(false) }
  }, [token, onToast, displayIds, records, ccd, line, raw, exposureEnabled, exposureStart, exposureEnd])
  useEffect(() => { void loadDetails() }, [loadDetails])

  const active = selectedId ? details[selectedId] ?? null : null
  const visibleRecords = useMemo(() => angleFilter === 'all' ? records : records.filter((item) => item.angle_deg != null && String(item.angle_deg) === angleFilter), [records, angleFilter])
  const angles = useMemo(() => Array.from(new Set(records.flatMap((item) => item.angle_deg == null ? [] : [item.angle_deg]))).sort((a, b) => a - b), [records])
  useEffect(() => {
    if (!visibleRecords.length || (selectedId && visibleRecords.some((item) => item.id === selectedId))) return
    const first = visibleRecords[0]
    setSelectedId(first.id); setPriorityId(first.id); setOverlayIds(first.kind === 'raw' ? [first.id] : []); setCcd(0); setLine(0)
  }, [visibleRecords, selectedId])
  const maxExposure = Math.max(1, Number(active?.ignition?.burn_count ?? 1))

  const curves = useMemo<SpectrumPlotCurve[]>(() => displayIds.flatMap((id, index) => {
    const record = details[id]
    if (!record) return []
    const points = id === selectedId && frameVisible ? record.frame_detail?.ccd.points ?? record.ccd?.points ?? [] : record.kind === 'raw' ? record.ccd?.points ?? [] : record.line?.points ?? []
    const data = points.map((point, pointIndex) => {
      const x = Number(point.wavelength_nm ?? point.step ?? point.x ?? pointIndex) + (record.kind === 'raw' ? referenceShift : 0)
      const y = Number(mode === 'peak' ? point.peak : mode === 'back' ? point.back : point.value ?? point.peak ?? point.adc ?? 0)
      return { point, x, y }
    }).filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y))
    const summary = records.find((item) => item.id === id)
    return [{ id, label: summary?.sample_name || summary?.band_name || id, color: palette[index % palette.length], priority: (priorityId ?? selectedId) === id, data }]
  }), [displayIds, details, selectedId, frameVisible, referenceShift, mode, records, priorityId])

  const fullRange = useMemo(() => {
    const all = curves.flatMap((curve) => curve.data)
    if (!all.length) return { xMin: 0, xMax: 1, yMin: 0, yMax: 1 }
    const xs = all.map((item) => item.x); const ys = all.map((item) => item.y)
    const xMin = Math.min(...xs); const xMax = Math.max(...xs)
    const rawYMin = Math.min(...ys); const rawYMax = Math.max(...ys); const yPad = Math.max((rawYMax - rawYMin) * .08, 1)
    return { xMin, xMax: xMax === xMin ? xMin + 1 : xMax, yMin: rawYMin - yPad, yMax: rawYMax + yPad }
  }, [curves])
  const fullXSpan = fullRange.xMax - fullRange.xMin
  const fullYSpan = fullRange.yMax - fullRange.yMin
  const xSpan = fullXSpan / zoomX
  const ySpan = fullYSpan / zoomY
  const xStart = fullRange.xMin + ((panX + 1) / 2) * Math.max(0, fullXSpan - xSpan)
  const xEnd = xStart + xSpan
  const yStart = fullRange.yMin + ((panY + 1) / 2) * Math.max(0, fullYSpan - ySpan)
  const yEnd = yStart + ySpan

  const resetView = (resetCorrection = false) => {
    setZoomX(1); setZoomY(1); setPanX(0); setPanY(0); setCursor(null); setLocked(false)
    if (resetCorrection) setReferenceShift(0)
  }
  useEffect(() => { resetView() }, [selectedId, ccd, line, mode])

  const selectRecord = (record: SpectrumRecordSummary) => {
    setSelectedId(record.id); setPriorityId(record.id); setCcd(0); setLine(0); setFrameVisible(false)
    setMode(record.kind === 'raw' ? 'mean' : record.matrix_kind === 'peak_back' ? 'peak' : 'value')
    if (record.kind === 'raw') setOverlayIds((current) => Array.from(new Set([record.id, ...current])).slice(0, 8)); else setOverlayIds([])
  }
  const moveRecord = (delta: number) => {
    if (!selectedId || !visibleRecords.length) return
    const index = visibleRecords.findIndex((item) => item.id === selectedId)
    selectRecord(visibleRecords[Math.max(0, Math.min(visibleRecords.length - 1, index + delta))])
  }
  const moveBand = (delta: number) => {
    if (!active) return
    if (raw) setCcd((current) => Math.max(0, Math.min(Number(active.layout?.ccd_count ?? 1) - 1, current + delta)))
    else setLine((current) => Math.max(0, Math.min((active.line_count ?? 1) - 1, current + delta)))
  }
  const toggleOverlay = (id: string) => {
    setOverlayIds((current) => current.includes(id) ? (id === selectedId ? current : current.filter((item) => item !== id)) : current.length < 8 ? [...current, id] : current)
  }
  const loadFrame = async () => {
    if (!active || !raw || !selectedId) return
    setBusy(true)
    try {
      const next = await api.spectrum(token, active.id, { ccd, line, detail: 'frame', phase: framePhase, frame: frameIndex })
      setDetails((current) => ({ ...current, [selectedId]: next })); setFrameVisible(true); setMode('mean')
    } catch (error) { onToast(error instanceof Error ? error.message : '原始帧不可用') }
    finally { setBusy(false) }
  }
  const boxSelect = (range: { xMin: number; xMax: number; yMin: number; yMax: number }) => {
    const nextZoomX = Math.max(1, Math.min(32, fullXSpan / Math.max(range.xMax - range.xMin, 1e-9)))
    const nextZoomY = Math.max(1, Math.min(32, fullYSpan / Math.max(range.yMax - range.yMin, 1e-9)))
    const nextXSpan = fullXSpan / nextZoomX; const nextYSpan = fullYSpan / nextZoomY
    setZoomX(nextZoomX); setZoomY(nextZoomY)
    setPanX(fullXSpan === nextXSpan ? 0 : Math.max(-1, Math.min(1, 2 * ((range.xMin - fullRange.xMin) / (fullXSpan - nextXSpan)) - 1)))
    setPanY(fullYSpan === nextYSpan ? 0 : Math.max(-1, Math.min(1, 2 * ((range.yMin - fullRange.yMin) / (fullYSpan - nextYSpan)) - 1)))
    setTool('crosshair')
  }
  const locate = () => {
    const target = Number(locateValue)
    const curve = curves.find((item) => item.priority) ?? curves[0]
    if (!curve?.data.length || !Number.isFinite(target)) return
    const datum = curve.data.reduce((best, item) => Math.abs(item.x - target) < Math.abs(best.x - target) ? item : best)
    setCursor({ curveId: curve.id, curveLabel: curve.label, x: 54 + ((datum.x - xStart) / (xEnd - xStart || 1)) * 872, y: 330 - ((datum.y - yStart) / (yEnd - yStart || 1)) * 288, datum })
    setLocked(true)
  }
  const exportVisible = async () => {
    if (!active) return
    try {
      const result = await api.exportSpectrum(token, active.id, { ccd, line, detail: frameVisible ? 'frame' : 'summary', phase: framePhase, frame: frameIndex, exposureStart: raw && exposureEnabled ? exposureStart : undefined, exposureEnd: raw && exposureEnabled ? exposureEnd : undefined, xMin: xStart, xMax: xEnd, referenceShift })
      const filename = result.filename.match(/filename="?([^";]+)/)?.[1] ?? `spectrum-${active.id.replace(':', '-')}.csv`
      const path = await saveFile(result.blob, filename)
      onToast(path ? `当前可见范围已保存：${path}` : '已取消保存')
    } catch (error) { onToast(error instanceof Error ? error.message : '导出失败') }
  }
  const printVisible = async () => {
    if (!active) return
    setBusy(true)
    try {
      const result = await api.printSpectrumPdf(token, active.id, { visible_x_min: xStart, visible_x_max: xEnd, visible_y_min: yStart, visible_y_max: yEnd, ccd, line, mode: frameVisible ? 'frame' : mode, reference_shift: referenceShift, selected_record_ids: displayIds, priority_record_id: priorityId ?? selectedId ?? undefined, frame_phase: framePhase, frame_index: frameIndex, exposure_start: raw && exposureEnabled ? exposureStart : undefined, exposure_end: raw && exposureEnabled ? exposureEnd : undefined })
      const filename = result.filename.match(/filename="?([^";]+)/)?.[1] ?? `spectrum-${active.id.replace(':', '-')}.pdf`
      const path = await saveFile(result.blob, filename)
      onToast(path ? `谱图 PDF 已保存：${path}；${result.curveCount} 条曲线，${result.pointCount} 个可见点` : '已取消保存')
    } catch (error) { onToast(error instanceof Error ? error.message : '打印准备失败') }
    finally { setBusy(false) }
  }

  return <div className="page-content spectrum-viewer-page refined-page" data-testid="spectrum-viewer-page">
    <div className="page-intro"><div><h1>谱图查看</h1><p>选择记录查看谱图，支持样品叠加、定位、缩放和可见范围输出。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => void loadRecords()} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />刷新</button><button className="secondary-button" onClick={() => void exportVisible()} disabled={!active || busy}><Download size={15} />导出可见范围</button><button className="secondary-button" onClick={() => void printVisible()} disabled={!active || busy} title="生成当前可见范围的打印 PDF"><Printer size={15} />打印 PDF</button></div></div>
    <div className="spectrum-viewer-layout">
      <aside className="surface spectrum-records"><div className="surface-heading"><div><h2>谱图记录 <span className="count-badge">{visibleRecords.length}</span></h2></div><Database size={17} /></div><label className="spectrum-angle-filter"><span>转角</span><select value={angleFilter} onChange={(event) => setAngleFilter(event.target.value)}><option value="all">全部（含未记录）</option>{angles.map((angle) => <option value={String(angle)} key={angle}>{angle}°</option>)}</select></label><div className="spectrum-record-list">{visibleRecords.map((record) => { const name = record.sample_name || record.band_name || record.id; const metadata = record.kind === 'raw' ? `${record.ccd_count} CCD · ${record.points_per_ccd} 点 · ${record.angle_deg == null ? '转角未记录' : `${record.angle_deg}°`}` : `${record.sample_count} 样品 · ${record.line_count} 谱线`; return <div className={`spectrum-record-row ${record.id === selectedId ? 'active' : ''}`} key={record.id}><label className="spectrum-overlay-check" title="加入多样品叠加"><input type="checkbox" checked={displayIds.includes(record.id)} disabled={record.kind !== 'raw'} onChange={() => toggleOverlay(record.id)} /></label><button onClick={() => selectRecord(record)}><span className={`spectrum-kind ${record.kind}`}>{record.kind === 'raw' ? 'RAW' : record.format.toUpperCase()}</span><div><strong title={name}>{name}</strong><small title={metadata}>{metadata}</small></div><ChevronRight size={14} /></button></div> })}</div><small className="spectrum-overlay-note">可叠加 1–8 个原始样品；点击图例设置优先曲线。</small></aside>
      <section className="surface spectrum-workbench">{!active ? <div className="method-empty"><Activity size={30} /><h2>选择一条谱图记录</h2></div> : <>
        <div className="spectrum-toolbar"><div className="spectrum-toolbar-group"><button className="icon-button" onClick={() => moveRecord(-1)} title="上一条记录"><ChevronLeft size={16} /></button><span className="spectrum-position">记录 {Math.max(1, visibleRecords.findIndex((item) => item.id === selectedId) + 1)} / {visibleRecords.length}</span><button className="icon-button" onClick={() => moveRecord(1)} title="下一条记录"><ChevronRight size={16} /></button><span className="toolbar-rule" /><button className="icon-button" onClick={() => moveBand(-1)} title={raw ? '上一 CCD' : '上一谱线'}><ChevronLeft size={16} /></button><span className="spectrum-position">{raw ? `CCD ${ccd + 1} / ${active.layout?.ccd_count ?? 0}` : `谱线 ${line + 1} / ${active.line_count ?? 0}`}</span><button className="icon-button" onClick={() => moveBand(1)} title={raw ? '下一 CCD' : '下一谱线'}><ChevronRight size={16} /></button></div><div className="spectrum-toolbar-group"><button className="tool-button" onClick={() => resetView()}><Maximize2 size={14} />适配</button><button className="tool-button" onClick={() => { setZoomX(1); setPanX(0) }}>100%</button><button className="tool-button" onClick={() => setZoomX(4)}>400%</button><button className="icon-button" onClick={() => setZoomX((value) => Math.min(32, value * 2))} title="横向放大"><ZoomIn size={15} /></button><button className="icon-button" onClick={() => setZoomX((value) => Math.max(1, value / 2))} title="横向缩小"><ZoomOut size={15} /></button><button className="icon-button" onClick={() => setZoomY((value) => Math.min(32, value * 2))} title="纵向放大">Y+</button><button className="icon-button" onClick={() => setZoomY((value) => Math.max(1, value / 2))} title="纵向缩小">Y−</button><button className="icon-button" onClick={() => resetView(true)} title="还原视图与参考校正"><RotateCcw size={15} /></button></div></div>
        <div className="spectrum-controls"><div className="segmented-control">{(['crosshair', 'pan', 'box'] as const).map((value) => <button key={value} className={tool === value ? 'active' : ''} onClick={() => setTool(value)}>{value === 'crosshair' ? '十字线' : value === 'pan' ? '滚动' : '框选'}</button>)}</div><div className="segmented-control">{(raw ? [['mean', '强度']] : active.matrix_kind === 'peak_back' ? [['peak', '峰值'], ['back', '背景']] : [['value', '结果']]).map(([key, label]) => <button key={key} className={mode === key ? 'active' : ''} onClick={() => setMode(key as typeof mode)}>{label}</button>)}</div><label className="spectrum-reference"><span>参考校正</span><EmptyableNumberInput step="0.001" value={referenceShift} onValueChange={setReferenceShift} /><span>nm</span></label><label className="spectrum-reference spectrum-locate"><span>谱线定位</span><input value={locateValue} onChange={(event) => setLocateValue(event.target.value)} placeholder="波长/点" /><button className="tool-button" onClick={locate}>定位并锁定</button></label>{raw && <label className="spectrum-exposure"><input type="checkbox" checked={exposureEnabled} onChange={(event) => setExposureEnabled(event.target.checked)} /><span>曝光区间</span><EmptyableNumberInput min="1" max={maxExposure} value={exposureStart} onValueChange={(value) => setExposureStart(Math.max(1, Math.min(maxExposure, value)))} /><span>–</span><EmptyableNumberInput min={exposureStart} max={maxExposure} value={exposureEnd} onValueChange={(value) => setExposureEnd(Math.max(exposureStart, Math.min(maxExposure, value)))} /></label>}{raw && <div className="spectrum-frame-actions"><select aria-label="原始帧阶段" value={framePhase} onChange={(event) => setFramePhase(event.target.value as 'burn' | 'dark')}><option value="burn">燃烧帧</option><option value="dark">暗帧</option></select><EmptyableNumberInput aria-label="原始帧序号" min="0" value={frameIndex} onValueChange={(value) => setFrameIndex(Math.max(0, value))} /><button className="tool-button" onClick={() => void loadFrame()} disabled={busy}>原始帧</button></div>}</div>
        <div className="spectrum-legend">{curves.map((curve) => <button key={curve.id} className={curve.priority ? 'priority' : ''} onClick={() => setPriorityId(curve.id)}><i style={{ background: curve.color }} />{curve.label}{curve.priority && <span>优先</span>}</button>)}</div>
        <div className="spectrum-plot-wrap"><SpectrumPlot curves={curves} xStart={xStart} xEnd={xEnd} yStart={yStart} yEnd={yEnd} tool={tool} cursor={cursor} locked={locked} xAxisLabel={curves.some((curve) => curve.data.some((item) => item.point.wavelength_nm != null)) ? '波长 (nm)' : raw ? 'CCD 点位' : '步长 / 点位'} yAxisLabel={mode === 'peak' ? '峰值' : mode === 'back' ? '背景' : mode === 'value' ? '结果值' : '强度 (ADC)'} onCursor={setCursor} onToggleLock={() => setLocked((value) => !value)} onPan={(dx, dy) => { setPanX((value) => Math.max(-1, Math.min(1, value - dx * 2))); setPanY((value) => Math.max(-1, Math.min(1, value + dy * 2))) }} onBoxSelect={boxSelect} />{cursor && <div className="spectrum-cursor-readout"><span>{cursor.curveLabel}</span><strong>{cursor.datum.x.toFixed(3)}</strong><span>点 {cursor.datum.point.point_index} · 强度 {cursor.datum.y.toFixed(3)}</span><span>{locked ? <LockKeyhole size={12} /> : <UnlockKeyhole size={12} />}</span></div>}</div>
        <div className="spectrum-pan"><button className="icon-button" aria-label="水平平移" onClick={() => setPanX((value) => Math.max(-1, value - .2))}><ChevronLeft size={15} /></button><button className="icon-button" aria-label="垂直平移" onClick={() => setPanY((value) => Math.max(-1, value - .2))}>↑</button><span>可见范围 X {xStart.toFixed(3)}–{xEnd.toFixed(3)} · Y {yStart.toFixed(2)}–{yEnd.toFixed(2)}</span><button className="icon-button" aria-label="垂直平移" onClick={() => setPanY((value) => Math.min(1, value + .2))}>↓</button><button className="icon-button" aria-label="水平平移" onClick={() => setPanX((value) => Math.min(1, value + .2))}><ChevronRight size={15} /></button></div>
        <div className="spectrum-facts"><div><span>来源 SHA-256</span><CopyableCode value={active.source_sha256} visibleLength={18} /></div><div><span>样品</span><ExpandableValue value={active.sample_name || active.sample_names?.join(' / ') || '—'} /></div><div><span>转角 / CCD</span><strong>{active.angle_deg == null ? '未记录' : `${active.angle_deg}°`} / {raw ? ccd + 1 : '—'}</strong></div><div><span>曝光</span><strong>{active.exposure_segment ? `${active.exposure_segment.start}–${active.exposure_segment.end}` : frameVisible ? `${framePhase} #${frameIndex + 1}` : '均值'}</strong></div><div><span>可见点 / 曲线</span><strong>{curves.reduce((sum, curve) => sum + curve.data.filter((item) => item.x >= xStart && item.x <= xEnd).length, 0)} / {curves.length}</strong></div></div>
      </>}</section>
    </div>
  </div>
}
