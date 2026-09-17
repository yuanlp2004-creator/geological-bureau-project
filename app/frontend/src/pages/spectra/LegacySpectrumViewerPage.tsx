import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { Activity, ChevronRight, ChevronLeft, Database, Crosshair, LockKeyhole, UnlockKeyhole, Maximize2, RotateCcw, ZoomIn, ZoomOut, Printer, RefreshCw } from 'lucide-react'
import { api, type SpectrumRecordSummary, type SpectrumRecord, type SpectrumPoint } from '../../api'
import { CopyableCode, ExpandableValue } from '../../components/InformationDisplay'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'

function LegacySpectrumViewerPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [records, setRecords] = useState<SpectrumRecordSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SpectrumRecord | null>(null)
  const [ccd, setCcd] = useState(0)
  const [line, setLine] = useState(0)
  const [mode, setMode] = useState<'mean' | 'peak' | 'back' | 'value'>('mean')
  const [referenceShift, setReferenceShift] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState(0)
  const [crosshair, setCrosshair] = useState(true)
  const [locked, setLocked] = useState(false)
  const [cursor, setCursor] = useState<{ x: number; y: number; point: SpectrumPoint } | null>(null)
  const [framePhase, setFramePhase] = useState<'burn' | 'dark'>('burn')
  const [frameIndex, setFrameIndex] = useState(0)
  const [frameVisible, setFrameVisible] = useState(false)
  const [busy, setBusy] = useState(false)

  const loadRecords = useCallback(async () => {
    try {
      const next = await api.spectrumRecords(token)
      setRecords(next)
      setSelectedId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取谱图记录') }
  }, [token, onToast])

  const loadDetail = useCallback(async (id: string, nextCcd = ccd, nextLine = line) => {
    setBusy(true)
    try { setDetail(await api.spectrum(token, id, { ccd: nextCcd, line: nextLine, detail: 'summary' })); setFrameVisible(false); setCursor(null) }
    catch (error) { onToast(error instanceof Error ? error.message : '无法读取谱图数据') }
    finally { setBusy(false) }
  }, [token, onToast, ccd, line])

  useEffect(() => { void loadRecords() }, [loadRecords])
  useEffect(() => { if (selectedId) void loadDetail(selectedId) }, [selectedId])
  useEffect(() => { setZoom(1); setPan(0) }, [detail?.id, ccd, line, mode])

  const raw = detail?.kind === 'raw'
  const points = useMemo<SpectrumPoint[]>(() => raw ? (frameVisible ? detail?.frame_detail?.ccd.points ?? detail?.ccd?.points ?? [] : detail?.ccd?.points ?? []) : detail?.line?.points ?? [], [detail, raw, frameVisible])
  const plotted = useMemo(() => points.map((point, index) => {
    const rawX = point.wavelength_nm ?? point.step ?? point.x ?? index
    const y = mode === 'peak' ? point.peak : mode === 'back' ? point.back : point.value ?? point.peak ?? point.adc ?? 0
    return { point, x: rawX + (raw ? referenceShift : 0), y: Number(y ?? 0) }
  }).filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y)), [points, mode, referenceShift])
  const fullRange = useMemo(() => {
    if (!plotted.length) return { start: 0, end: 1, min: 0, max: 1 }
    const xs = plotted.map((item) => item.x); const ys = plotted.map((item) => item.y)
    return { start: Math.min(...xs), end: Math.max(...xs) || 1, min: Math.min(...ys), max: Math.max(...ys) }
  }, [plotted])
  const xSpan = Math.max((fullRange.end - fullRange.start) / zoom, 1e-9)
  const xStart = Math.max(fullRange.start, Math.min(fullRange.end - xSpan, fullRange.start + pan * xSpan * 0.45))
  const xEnd = xStart + xSpan
  const yPad = Math.max((fullRange.max - fullRange.min) * 0.08, 1)
  const yStart = fullRange.min - yPad
  const yEnd = fullRange.max + yPad
  const plotX = (x: number) => 54 + ((x - xStart) / (xEnd - xStart || 1)) * 872
  const plotY = (y: number) => 330 - ((y - yStart) / (yEnd - yStart || 1)) * 278
  const path = plotted.map((item, index) => `${index ? 'L' : 'M'} ${plotX(item.x).toFixed(2)} ${plotY(item.y).toFixed(2)}`).join(' ')
  const selected = records.find((item) => item.id === selectedId) ?? null

  const selectRecord = (record: SpectrumRecordSummary) => {
    setSelectedId(record.id); setCcd(0); setLine(0); setMode(record.kind === 'raw' ? 'mean' : record.matrix_kind === 'peak_back' ? 'peak' : 'value')
  }
  const move = (delta: number) => {
    if (!detail) return
    if (raw) { const count = Number(detail.layout?.ccd_count ?? 1); const next = Math.max(0, Math.min(count - 1, ccd + delta)); if (next !== ccd) { setCcd(next); void loadDetail(detail.id, next, line) } }
    else { const count = detail.line_count ?? 1; const next = Math.max(0, Math.min(count - 1, line + delta)); if (next !== line) { setLine(next); void loadDetail(detail.id, ccd, next) } }
  }
  const loadFrame = async () => {
    if (!detail || !raw) return
    setBusy(true)
    try { setDetail(await api.spectrum(token, detail.id, { ccd, line, detail: 'frame', phase: framePhase, frame: frameIndex })); setFrameVisible(true) }
    catch (error) { onToast(error instanceof Error ? error.message : '原始帧不可用') }
    finally { setBusy(false) }
  }
  const handlePlotMove = (event: MouseEvent<SVGSVGElement>) => {
    if (!crosshair || locked || !plotted.length) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = xStart + ((event.clientX - rect.left) / rect.width) * (xEnd - xStart)
    const nearest = plotted.reduce((best, current) => Math.abs(current.x - x) < Math.abs(best.x - x) ? current : best, plotted[0])
    setCursor({ x: plotX(nearest.x), y: plotY(nearest.y), point: nearest.point })
  }

  return <div className="page-content spectrum-viewer-page refined-page" data-testid="spectrum-viewer-page">
    <div className="page-intro"><div><span className="section-kicker">S10 / SPECTRUM VIEWER</span><h1>谱图查看</h1><p>对已发布的旧谱带和结果矩阵进行完整点位查看；原始帧按需读取。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => void loadRecords()} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />刷新</button><button className="secondary-button" onClick={() => window.print()} disabled={!detail} title="打印当前可见范围"><Printer size={15} />打印</button></div></div>
    <div className="spectrum-viewer-layout">
      <aside className="surface spectrum-records"><div className="surface-heading"><div><span className="section-kicker">PUBLISHED DATA</span><h2>谱图记录</h2></div><Database size={17} /></div>{records.length === 0 ? <div className="method-empty compact"><Database size={25} /><p>暂无已提交谱图</p></div> : <div className="spectrum-record-list">{records.map((record) => { const name = record.sample_name || record.band_name || record.id; const metadata = record.kind === 'raw' ? `${record.ccd_count} CCD · ${record.points_per_ccd} 点` : `${record.sample_count} 样品 · ${record.line_count} 谱线`; return <button key={record.id} className={record.id === selectedId ? 'active' : ''} onClick={() => selectRecord(record)}><span className={`spectrum-kind ${record.kind}`}>{record.kind === 'raw' ? 'RAW' : record.format.toUpperCase()}</span><div><strong title={name}>{name}</strong><small title={metadata}>{metadata}</small></div><ChevronRight size={14} /></button> })}</div>}</aside>
      <section className="surface spectrum-workbench">
        {!detail ? <div className="method-empty"><Activity size={30} /><h2>选择一条谱图记录</h2><p>左侧记录会显示 S08/S09 已提交的数据。</p></div> : <>
          <div className="spectrum-toolbar"><div className="spectrum-toolbar-group"><button className="icon-button" onClick={() => move(-1)} title={raw ? '上一个 CCD' : '上一条谱线'}><ChevronLeft size={16} /></button><span className="spectrum-position">{raw ? `CCD ${ccd + 1} / ${detail.layout?.ccd_count ?? 0}` : `谱线 ${line + 1} / ${detail.line_count ?? 0}`}</span><button className="icon-button" onClick={() => move(1)} title={raw ? '下一个 CCD' : '下一条谱线'}><ChevronRight size={16} /></button></div><div className="spectrum-toolbar-group"><button className="tool-button" onClick={() => { setZoom(1); setPan(0) }} title="适配全部数据"><Maximize2 size={14} />适配</button><button className={`tool-button ${zoom === 1 ? 'active' : ''}`} onClick={() => { setZoom(1); setPan(0) }}>100%</button><button className={`tool-button ${zoom === 4 ? 'active' : ''}`} onClick={() => setZoom(4)}>400%</button><button className="icon-button" onClick={() => { setZoom(1); setPan(0); setReferenceShift(0) }} title="还原视图"><RotateCcw size={15} /></button><button className="icon-button" onClick={() => setZoom((current) => Math.min(16, current * 2))} title="放大"><ZoomIn size={16} /></button><button className="icon-button" onClick={() => setZoom((current) => Math.max(1, current / 2))} title="缩小"><ZoomOut size={16} /></button></div><div className="spectrum-toolbar-group"><button className={`tool-button ${crosshair ? 'active' : ''}`} onClick={() => setCrosshair((value) => !value)} title="十字线"><Crosshair size={14} />十字线</button><button className={`tool-button ${locked ? 'active' : ''}`} onClick={() => setLocked((value) => !value)} title="锁定谱线">{locked ? <LockKeyhole size={14} /> : <UnlockKeyhole size={14} />}锁定</button></div></div>
          <div className="spectrum-controls"><div className="segmented-control">{(raw ? [['mean', '均值']] : detail.matrix_kind === 'peak_back' ? [['peak', '峰值'], ['back', '背景']] : [['value', '结果']]).map(([key, label]) => <button key={key} className={mode === key ? 'active' : ''} onClick={() => setMode(key as typeof mode)}>{label}</button>)}</div><label className="spectrum-reference"><span>参考线偏移</span><EmptyableNumberInput step="0.001" value={referenceShift} onValueChange={setReferenceShift} /><span>nm</span></label>{raw && <div className="spectrum-frame-actions"><select aria-label="原始帧阶段" value={framePhase} onChange={(event) => setFramePhase(event.target.value as 'burn' | 'dark')}><option value="burn">燃烧帧</option><option value="dark">暗帧</option></select><EmptyableNumberInput min={0} value={frameIndex} onValueChange={(value) => setFrameIndex(Math.max(0, value))} /><button className="tool-button" onClick={() => void loadFrame()} disabled={busy}>原始帧</button></div>}</div>
          <div className="spectrum-plot-wrap"><svg className="spectrum-plot" viewBox="0 0 960 380" role="img" aria-label="谱图曲线" onMouseMove={handlePlotMove} onMouseLeave={() => !locked && setCursor(null)} onClick={() => cursor && setLocked(true)}><rect x="54" y="42" width="872" height="288" className="plot-background" /><line x1="54" y1="330" x2="926" y2="330" className="plot-axis" /><line x1="54" y1="42" x2="54" y2="330" className="plot-axis" />{[0, .25, .5, .75, 1].map((ratio) => <line key={ratio} x1="54" y1={42 + 288 * ratio} x2="926" y2={42 + 288 * ratio} className="plot-grid" />)}{path && <path d={path} className="spectrum-line" />}{cursor && crosshair && <><line x1={cursor.x} y1="42" x2={cursor.x} y2="330" className="plot-crosshair" /><line x1="54" y1={cursor.y} x2="926" y2={cursor.y} className="plot-crosshair" /><circle cx={cursor.x} cy={cursor.y} r="4" className="plot-cursor" /></>}<text x="58" y="24" className="plot-label">{detail.kind === 'raw' ? `${detail.sample_name || '谱带'} · ${detail.ccd?.index ?? 0}` : `${detail.line?.element || '谱线'} · ${detail.line?.wavelength_nm ?? ''}`}</text><text x="820" y="365" className="plot-label">{fullRange.end.toFixed(3)}</text><text x="55" y="365" className="plot-label">{fullRange.start.toFixed(3)}</text></svg>{cursor && <div className="spectrum-cursor-readout"><span>点 {cursor.point.point_index}</span><strong>{(cursor.point.wavelength_nm ?? cursor.point.x ?? cursor.point.step ?? cursor.point.point_index).toFixed?.(3) ?? cursor.point.point_index}</strong><span>{mode} {Number(cursor.point[mode === 'peak' ? 'peak' : mode === 'back' ? 'back' : mode === 'value' ? 'value' : 'value'] ?? cursor.point.adc ?? 0).toFixed(3)}</span></div>}</div>
          <div className="spectrum-pan"><button className="icon-button" onClick={() => setPan((value) => Math.max(-1, value - .25))} title="向左滚动"><ChevronLeft size={15} /></button><span>可见范围 {xStart.toFixed(3)} - {xEnd.toFixed(3)}</span><button className="icon-button" onClick={() => setPan((value) => Math.min(1, value + .25))} title="向右滚动"><ChevronRight size={15} /></button></div>
          <div className="spectrum-facts"><div><span>来源 SHA-256</span><CopyableCode value={detail.source_sha256} visibleLength={18} /></div><div><span>样品</span><ExpandableValue value={detail.sample_name || detail.sample_names?.join(' / ') || '—'} /></div><div><span>测量时间</span><strong>{detail.measure_time || '—'}</strong></div><div><span>点数</span><strong>{points.length}</strong></div>{raw && <div><span>当前帧</span><strong>{frameVisible && detail.frame_detail ? `${detail.frame_detail.phase} #${detail.frame_detail.index + 1}` : '均值'}</strong></div>}</div>
        </>}
      </section>
    </div>
  </div>
}
