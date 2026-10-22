import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Download,
  LockKeyhole,
  Printer,
  RefreshCw,
  UnlockKeyhole
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, saveFile, type SpectrumRecord, type SpectrumRecordSummary } from '../../api'
import { CopyableCode, ExpandableValue } from '../../components/InformationDisplay'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'
import { SpectrumPlot, type SpectrumPlotCursor, type SpectrumPlotCurve } from '../../components/SpectrumPlot'
import { SpectrumQueryToolbar } from './SpectrumQueryToolbar'
import { SpectrumRecordList } from './SpectrumRecordList'
import { SpectrumViewToolbar } from './SpectrumViewToolbar'
import { SpectrumPointDetails } from '../../components/SpectrumPointDetails'
import { parseCcdCoordinate } from '../../components/legacyObservation'

export function SpectrumViewerPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [pageRecords, setPageRecords] = useState<SpectrumRecordSummary[]>([])
  const [sourceKind, setSourceKind] = useState('all')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const listRequest = useRef(0)
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
  const [recordLocked,setRecordLocked] = useState(false)
  const [pixelMode,setPixelMode] = useState<1|4|10|null>(null)
  const plotRef=useRef<HTMLDivElement>(null)
  const [plotWidth,setPlotWidth]=useState(872)
  const [screenProfiles,setScreenProfiles]=useState<Array<{id:number;name:string;screen_width_mm:number;screen_resolution_px:number}>>([])
  const [screenProfileId,setScreenProfileId]=useState(0)
  useEffect(() => { let live=true;void api.spectrumDisplayProfiles(token).then(next => {if(live){setScreenProfiles(next);setScreenProfileId(next[0]?.id ?? 0)}}).catch(() => {});return () => {live=false} },[token])
  const [locateValue, setLocateValue] = useState('')
  const pendingCoordinate = useRef<{ recordId: string; ccd: number; point: number } | null>(null)
  const [framePhase, setFramePhase] = useState<'burn' | 'dark'>('burn')
  const [frameIndex, setFrameIndex] = useState(0)
  const [frameVisible, setFrameVisible] = useState(false)
  const [printScope, setPrintScope] = useState<'visible' | 'ccd'>('visible')
  const [printLayers, setPrintLayers] = useState<Array<'curve' | 'grayscale'>>(['curve'])
  const [printScale, setPrintScale] = useState<'fit_long' | 'fit_short' | 'ccd_10x'>('fit_long')
  const [printPaper, setPrintPaper] = useState<'A4' | 'A3' | 'Letter'>('A4')
  const [busy, setBusy] = useState(false)
  const detailRequest = useRef(0)
  const palette = ['#1c68b2', '#c75b39', '#27805d', '#8b5bb5', '#d18b22', '#247c8b', '#b54769', '#58677a']

  const loadRecords = useCallback(async () => {
    const requestId = ++listRequest.current
    setBusy(true)
    try {
      const next = await api.spectrumRecords(
        token,
        sourceKind,
        angleFilter === 'all' ? undefined : Number(angleFilter),
        offset,
        search
      )
      if (requestId !== listRequest.current) return
      setPageRecords(next)
      setRecords((current) => [...current.filter((item) => !next.some((fresh) => fresh.id === item.id)), ...next])
      setSelectedId((current) => current ?? next[0]?.id ?? null)
      setPriorityId((current) => current ?? next[0]?.id ?? null)
    } catch (error) {
      if (requestId === listRequest.current) onToast(error instanceof Error ? error.message : '无法读取谱图记录')
    } finally {
      if (requestId === listRequest.current) setBusy(false)
    }
  }, [token, onToast, sourceKind, angleFilter, offset, search])

  useEffect(() => {
    void loadRecords()
    return () => {
      listRequest.current++
    }
  }, [loadRecords])
  const selected = records.find((item) => item.id === selectedId) ?? null
  const raw = selected != null && selected.kind !== 'result'
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
      const loaded = await Promise.all(
        displayIds.map(async (id) => {
          const summary = records.find((item) => item.id === id)
          const nextCcd = Math.max(0, Math.min((summary?.ccd_count ?? 1) - 1, ccd))
          const params = {
            ccd: nextCcd,
            line,
            detail: 'summary' as const,
            exposureStart: raw && exposureEnabled ? exposureStart : undefined,
            exposureEnd: raw && exposureEnabled ? exposureEnd : undefined
          }
          return [id, await api.spectrum(token, id, params)] as const
        })
      )
      if (requestId !== detailRequest.current) return
      const coordinateKinds = new Set(
        loaded.map(([, item]) => item.coordinate_system ?? (item.kind === 'raw' ? 'legacy_wavelength' : 'result_index'))
      )
      if (coordinateKinds.size > 1) throw new Error('叠加来源的坐标和单位不可比，请取消叠加后分别查看')
      setDetails(Object.fromEntries(loaded))
      setFrameVisible(false)
      setCursor(null)
      setLocked(false)
    } catch (error) {
      if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '无法读取谱图数据')
    } finally {
      if (requestId === detailRequest.current) setBusy(false)
    }
  }, [token, onToast, displayIds, records, ccd, line, raw, exposureEnabled, exposureStart, exposureEnd])
  useEffect(() => {
    void loadDetails()
    return () => {
      detailRequest.current++
    }
  }, [loadDetails])

  const active = selectedId ? (details[selectedId] ?? null) : null
  const visibleRecords = pageRecords
  const angles = useMemo(
    () =>
      Array.from(new Set(records.flatMap((item) => (item.angle_deg == null ? [] : [item.angle_deg])))).sort(
        (a, b) => a - b
      ),
    [records]
  )
  const maxExposure = Math.max(1, Number(active?.ignition?.burn_count ?? 1))

  const curves = useMemo<SpectrumPlotCurve[]>(
    () =>
      displayIds.flatMap((id, index) => {
        const record = details[id]
        if (!record) return []
        const points =
          id === selectedId && frameVisible
            ? (record.frame_detail?.ccd.points ?? record.ccd?.points ?? [])
            : record.kind !== 'result'
              ? (record.ccd?.points ?? [])
              : (record.line?.points ?? [])
        const data = points
          .map((point, pointIndex) => {
            const x = pixelMode && record.kind !== 'result' ? Number(point.point_index ?? pointIndex) :
              Number(point.wavelength_nm ?? point.step ?? point.x ?? pointIndex) +
              (record.kind !== 'result' ? referenceShift : 0)
            const y = Number(
              mode === 'peak'
                ? point.peak
                : mode === 'back'
                  ? point.back
                  : (point.value ?? point.peak ?? point.adc ?? 0)
            )
            return { point, x, y }
          })
          .filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y))
        const summary = records.find((item) => item.id === id)
        return [
          {
            id,
            label: summary?.sample_name || summary?.band_name || id,
            color: palette[index % palette.length],
            priority: (priorityId ?? selectedId) === id,
            data
          }
        ]
      }),
    [displayIds, details, selectedId, frameVisible, referenceShift, mode, records, priorityId,pixelMode]
  )

  useEffect(() => {
    const host=plotRef.current;if(!host)return
    const resize=() => {const svg=host.querySelector('svg');if(svg)setPlotWidth((svg.getScreenCTM()?.a ?? svg.getBoundingClientRect().width/960)*872)}
    const observer=new ResizeObserver(resize);observer.observe(host);resize();return () => observer.disconnect()
  },[active?.id])
  useEffect(() => {
    if (!pixelMode || !raw)return
    const profile=screenProfiles.find(p => p.id===screenProfileId)
    const pointWidth=Number(active?.layout?.point_width_um ?? active?.layout?.point_width ?? 0)
    const spacing=(pixelMode===10 ? pointWidth/1000*10*(profile ? profile.screen_resolution_px/profile.screen_width_mm : 0) : pixelMode)/(window.devicePixelRatio||1)
    if (!(spacing>0))return
    const count=curves.find(c => c.id===selectedId)?.data.length ?? 1
    setZoomX(Math.max(1e-9,(count-1)*spacing/Math.max(1,plotWidth)))
  },[pixelMode,raw,active?.layout,screenProfiles,screenProfileId,plotWidth,curves,selectedId])

  const fullRange = useMemo(() => {
    const all = curves.flatMap((curve) => curve.data)
    if (!all.length) return { xMin: 0, xMax: 1, yMin: 0, yMax: 1 }
    const xs = all.map((item) => item.x)
    const ys = all.map((item) => item.y)
    const xMin = Math.min(...xs)
    const xMax = Math.max(...xs)
    const rawYMin = Math.min(...ys)
    const rawYMax = Math.max(...ys)
    const yPad = Math.max((rawYMax - rawYMin) * 0.08, 1)
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
    setPixelMode(null)
    setZoomX(1)
    setZoomY(1)
    setPanX(0)
    setPanY(0)
    setCursor(null)
    setLocked(false)
    if (resetCorrection) setReferenceShift(0)
  }
  useEffect(() => {
    resetView()
  }, [selectedId, ccd, line, mode])

  const selectRecord = (record: SpectrumRecordSummary) => {
    if(recordLocked && record.id!==selectedId)return
    detailRequest.current++
    if (selected?.kind !== record.kind) setOverlayIds([])
    setSelectedId(record.id)
    setPriorityId(record.id)
    setCcd(0)
    setLine(0)
    setFrameVisible(false)
    setMode(record.kind !== 'result' ? 'mean' : record.matrix_kind === 'peak_back' ? 'peak' : 'value')
    if (record.kind !== 'result')
      setOverlayIds((current) =>
        Array.from(new Set([record.id, ...current.filter((id) => id.split(':')[0] === record.id.split(':')[0])])).slice(
          0,
          8
        )
      )
    else setOverlayIds([])
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
    if (selectedId && id.split(':')[0] !== selectedId.split(':')[0])
      return onToast('叠加来源的坐标和单位不可比，请分别查看')
    setOverlayIds((current) =>
      current.includes(id)
        ? id === selectedId
          ? current
          : current.filter((item) => item !== id)
        : current.length < 8
          ? [...current, id]
          : current
    )
  }
  const loadFrame = async () => {
    if (!active || !raw || !selectedId) return
    const requestId = ++detailRequest.current
    setBusy(true)
    try {
      const next = await api.spectrum(token, active.id, {
        ccd,
        line,
        detail: 'frame',
        phase: framePhase,
        frame: frameIndex
      })
      if (requestId !== detailRequest.current) return
      setDetails((current) => ({ ...current, [selectedId]: next }))
      setFrameVisible(true)
      setMode('mean')
    } catch (error) {
      if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '原始帧不可用')
    } finally {
      if (requestId === detailRequest.current) setBusy(false)
    }
  }
  const boxSelect = (range: { xMin: number; xMax: number; yMin: number; yMax: number }) => {
    // Manual area zoom retains the current point/wavelength coordinate system.
    const nextZoomX = Math.max(1, Math.min(32, fullXSpan / Math.max(range.xMax - range.xMin, 1e-9)))
    const nextZoomY = Math.max(1, Math.min(32, fullYSpan / Math.max(range.yMax - range.yMin, 1e-9)))
    const nextXSpan = fullXSpan / nextZoomX
    const nextYSpan = fullYSpan / nextZoomY
    setZoomX(nextZoomX)
    setZoomY(nextZoomY)
    setPanX(
      fullXSpan === nextXSpan
        ? 0
        : Math.max(-1, Math.min(1, 2 * ((range.xMin - fullRange.xMin) / (fullXSpan - nextXSpan)) - 1))
    )
    setPanY(
      fullYSpan === nextYSpan
        ? 0
        : Math.max(-1, Math.min(1, 2 * ((range.yMin - fullRange.yMin) / (fullYSpan - nextYSpan)) - 1))
    )
    setTool('crosshair')
  }
  const locateDatum = (curve: SpectrumPlotCurve, datum: SpectrumPlotCurve['data'][number]) => {
    const nextZoom = Math.max(4, zoomX), span = fullXSpan / nextZoom
    setZoomX(nextZoom)
    setPanX(fullXSpan === span ? 0 : Math.max(-1, Math.min(1,
      2 * ((datum.x - span / 2 - fullRange.xMin) / (fullXSpan - span)) - 1)))
    setCursor({ curveId: curve.id, curveLabel: curve.label, x: 54 + ((datum.x - xStart) / (xEnd - xStart || 1)) * 872,
      y: 330 - ((datum.y - yStart) / (yEnd - yStart || 1)) * 288, datum })
    setLocked(true)
    setTool('crosshair')
  }
  useEffect(() => {
    const pending = pendingCoordinate.current
    if (!pending || pending.recordId !== selectedId || pending.ccd !== ccd || busy
      || !selectedId || details[selectedId]?.ccd?.position !== pending.ccd) return
    const curve = curves.find((item) => item.id === selectedId)
    const datum = curve?.data.find((item) => item.point.point_index === pending.point)
    if (!curve || !datum) return
    pendingCoordinate.current = null
    locateDatum(curve, datum)
  }, [curves, selectedId, ccd, busy])
  const locate = () => {
    if (locateValue.includes(',')) {
      const coordinate = parseCcdCoordinate(locateValue)
      const indices = Array.isArray(active?.layout?.ccd_indices) ? active.layout.ccd_indices as number[]
        : Array.from({ length: Number(active?.layout?.ccd_count ?? 0) }, (_, index) => index)
      const position = coordinate ? indices.indexOf(coordinate.ccd) : -1
      if (!coordinate || position < 0 || coordinate.point >= Number(active?.layout?.points_per_ccd ?? 0))
        return onToast('CCD 坐标超出安装范围，请输入 CCD序号,点位，例如 2,123')
      if (!selectedId) return
      pendingCoordinate.current = { recordId: selectedId, ccd: position, point: coordinate.point }
      if (position === ccd && !busy && details[selectedId]?.ccd?.position === position) {
        const curve = curves.find((item) => item.id === selectedId)
        const datum = curve?.data.find((item) => item.point.point_index === coordinate.point)
        if (curve && datum) { pendingCoordinate.current = null; locateDatum(curve, datum) }
      } else setCcd(position)
      return
    }
    const target = Number(locateValue)
    const curve = curves.find((item) => item.priority) ?? curves[0]
    if (!curve?.data.length || !Number.isFinite(target)) return
    const datum = curve.data.reduce((best, item) =>
      Math.abs(Number(pixelMode ? item.point.wavelength_nm ?? item.point.point_index ?? item.x : item.x) - target)
        < Math.abs(Number(pixelMode ? best.point.wavelength_nm ?? best.point.point_index ?? best.x : best.x) - target) ? item : best
    )
    locateDatum(curve, datum)
  }
  const nativeX = (x: number) => {
    if (!pixelMode || !raw)return x
    const data=curves.find(curve => curve.id===selectedId)?.data ?? []
    if (!data.length)return x
    const lo=data[Math.max(0,Math.min(data.length-1,Math.floor(x)))]
    const hi=data[Math.max(0,Math.min(data.length-1,Math.ceil(x)))]
    const value=(item: typeof lo) => Number(item.point.wavelength_nm ?? item.point.step ?? item.point.point_index ?? item.x)+referenceShift
    return value(lo)+(value(hi)-value(lo))*(x-Math.floor(x))
  }
  const pixelScale = (mode: 1|4|10) => {
    if (!raw)return
    if (mode===10 && (!screenProfiles.length || !Number(active?.layout?.point_width_um ?? active?.layout?.point_width)))
      return onToast('请先在设备参数中设置屏幕宽度、分辨率和 CCD 点宽')
    setPixelMode(mode);setPanX(0);setCursor(null);setLocked(false)
  }
  const exportVisible = async () => {
    if (!active || busy) return
    const requestId = detailRequest.current
    try {
      const result = await api.exportSpectrum(token, active.id, {
        ccd,
        line,
        detail: frameVisible ? 'frame' : 'summary',
        phase: framePhase,
        frame: frameIndex,
        exposureStart: raw && exposureEnabled ? exposureStart : undefined,
        exposureEnd: raw && exposureEnabled ? exposureEnd : undefined,
        xMin: nativeX(xStart),
        xMax: nativeX(xEnd),
        referenceShift
      })
      if (requestId !== detailRequest.current) return
      const filename =
        result.filename.match(/filename="?([^";]+)/)?.[1] ?? `spectrum-${active.id.replace(':', '-')}.csv`
      const path = await saveFile(result.blob, filename)
      onToast(path ? `当前可见范围已保存：${path}` : '已取消保存')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '导出失败')
    }
  }
  const printVisible = async () => {
    if (!active || busy) return
    const requestId = detailRequest.current
    setBusy(true)
    try {
      const result = await api.printSpectrumPdf(token, active.id, {
        print_scope: raw ? printScope : 'visible',
        print_layers: raw ? printLayers : ['curve'],
        print_scale: raw ? printScale : 'fit_long',
        paper: printPaper,
        visible_x_min: nativeX(xStart),
        visible_x_max: nativeX(xEnd),
        visible_y_min: yStart,
        visible_y_max: yEnd,
        ccd,
        line,
        mode: frameVisible ? 'frame' : mode,
        reference_shift: referenceShift,
        selected_record_ids: displayIds,
        priority_record_id: priorityId ?? selectedId ?? undefined,
        frame_phase: framePhase,
        frame_index: frameIndex,
        exposure_start: raw && exposureEnabled ? exposureStart : undefined,
        exposure_end: raw && exposureEnabled ? exposureEnd : undefined
      })
      if (requestId !== detailRequest.current) return
      const filename =
        result.filename.match(/filename="?([^";]+)/)?.[1] ?? `spectrum-${active.id.replace(':', '-')}.pdf`
      const path = await saveFile(result.blob, filename)
      onToast(
        path ? `谱图 PDF 已保存：${path}；${result.curveCount} 条曲线，${result.pointCount} 个可见点` : '已取消保存'
      )
    } catch (error) {
      if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '打印准备失败')
    } finally {
      if (requestId === detailRequest.current) setBusy(false)
    }
  }

  return (
    <div className="page-content spectrum-viewer-page refined-page" data-testid="spectrum-viewer-page">


      
      <SpectrumQueryToolbar
        actions={<div className="page-intro-actions file-actions">
          <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="spectra" label="打开谱文件" disabled={busy || recordLocked} onOpened={async result => {
        const next = await api.spectrumRecords(token, 'raw', undefined, 0, result.source_sha256)
        setRecords(current => [...current.filter(item => !next.some(fresh => fresh.id === item.id)), ...next])
        setSourceKind('all'); setSearch(''); setAngleFilter('all'); setOffset(0); setPageRecords(next)
        setOverlayIds([]); setSelectedId(next[0]?.id ?? null); setPriorityId(next[0]?.id ?? null); setCcd(0); setLine(0)
      }}/>
          <button className="secondary-button" onClick={() => void loadRecords()} disabled={busy}>
            <RefreshCw size={15} className={busy ? 'spin' : ''} />
            刷新
          </button>
          <button className="secondary-button" onClick={() => void exportVisible()} disabled={!active || busy}>
            <Download size={15} />
            导出可见范围
          </button>
          <button
            className="secondary-button"
            onClick={() => void printVisible()}
            disabled={!active || busy}
            title="生成当前可见范围的打印 PDF"
          >
            <Printer size={15} />
            打印 PDF
          </button>
        </div>}
        sourceKind={sourceKind}
        setSourceKind={setSourceKind}
        setOffset={setOffset}
        search={search}
        setSearch={setSearch}
        angleFilter={angleFilter}
        setAngleFilter={setAngleFilter}
        offset={offset}
        busy={busy}
        pageRecords={pageRecords}
      />
      <div className="spectrum-viewer-layout">
        <SpectrumRecordList
          visibleRecords={visibleRecords}
          angleFilter={angleFilter}
          setAngleFilter={setAngleFilter}
          angles={angles}
          selectedId={selectedId}
          displayIds={displayIds}
          toggleOverlay={toggleOverlay}
          selectRecord={selectRecord}
          recordLocked={recordLocked}
        />

        <section className="surface spectrum-workbench">
          {!active ? (
            <div className="method-empty">
              <Activity size={30} />
              <h2>选择一条谱图记录</h2>
            </div>
          ) : (
            <>
              <SpectrumViewToolbar
                moveRecord={moveRecord}
                visibleRecords={visibleRecords}
                selectedId={selectedId}
                moveBand={moveBand}
                raw={raw}
                ccd={ccd}
                active={active}
                line={line}
                resetView={resetView}
                setZoomX={setZoomX}
                setPanX={setPanX}
                setZoomY={setZoomY}
                recordLocked={recordLocked}
                setRecordLocked={setRecordLocked}
                pixelScale={pixelScale}
              />
              {raw && <div className="analysis-actions"><label>屏幕参数 <select aria-label="屏幕比例档案" value={screenProfileId} onChange={e => setScreenProfileId(Number(e.target.value))}>
                {screenProfiles.map(p => <option key={p.id} value={p.id}>{p.name} · {p.screen_width_mm} mm / {p.screen_resolution_px} px</option>)}</select></label>
                {pixelMode && <output>{pixelMode===10?'CCD 十倍物理比例':`每点 ${pixelMode} 像素`}；横轴使用 CCD 点位</output>}</div>}
              <details className="spectrum-print-settings"><summary>CCD 打印设置</summary>
                <div className="analysis-actions">
                  <label>范围 <select aria-label="CCD 打印范围" value={printScope} disabled={!raw} onChange={(event) => setPrintScope(event.target.value as typeof printScope)}>
                    <option value="visible">当前图像</option><option value="ccd">当前 CCD</option></select></label>
                  {(['grayscale', 'curve'] as const).map((layer) => <label className="checkbox-row" key={layer}>
                    <input type="checkbox" checked={printLayers.includes(layer)} disabled={!raw && layer === 'grayscale'}
                      onChange={(event) => setPrintLayers((current) => {
                        const next = event.target.checked ? [...current, layer] : current.filter((value) => value !== layer)
                        return next.length ? next : [layer]
                      })} />{layer === 'grayscale' ? '灰度谱带' : '峰形'}
                  </label>)}
                  <label>比例 <select aria-label="CCD 打印比例" value={printScale} disabled={!raw} onChange={(event) => setPrintScale(event.target.value as typeof printScale)}>
                    <option value="fit_long">纸张宽边</option><option value="fit_short">纸张窄边</option><option value="ccd_10x">十倍 CCD</option></select></label>
                  <label>纸型 <select aria-label="CCD 打印纸型" value={printPaper} onChange={(event) => setPrintPaper(event.target.value as typeof printPaper)}>
                    <option>A4</option><option>A3</option><option>Letter</option></select></label>
                </div>
              </details>
              <div className="spectrum-controls">
                <div className="segmented-control">
                  {(['crosshair', 'pan', 'box'] as const).map((value) => (
                    <button key={value} className={tool === value ? 'active' : ''} onClick={() => setTool(value)}>
                      {value === 'crosshair' ? '十字线' : value === 'pan' ? '滚动工具' : '区域放大'}
                    </button>
                  ))}
                </div>
                <div className="segmented-control">
                  {(raw
                    ? [['mean', '强度']]
                    : active.matrix_kind === 'peak_back'
                      ? [
                        ['peak', '峰值'],
                        ['back', '背景']
                      ]
                      : [['value', '结果']]
                  ).map(([key, label]) => (
                    <button
                      key={key}
                      className={mode === key ? 'active' : ''}
                      onClick={() => setMode(key as typeof mode)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <label className="spectrum-reference">
                  <span>参考校正</span>
                  <EmptyableNumberInput step="0.001" value={referenceShift} onValueChange={setReferenceShift} />
                  <span>
                    {curves.some((curve) => curve.data.some((item) => item.point.wavelength_nm != null)) ? 'nm' : '点'}
                  </span>
                </label>
                <label className="spectrum-reference spectrum-locate">
                  <span>谱线定位</span>
                  <input
                    value={locateValue}
                    onChange={(event) => setLocateValue(event.target.value)}
                    placeholder="波长/点，或 CCD,点位"
                    onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); locate() } }}
                  />
                  <button className="tool-button" onClick={locate}>
                    定位并锁定
                  </button>
                </label>
                {raw && (
                  <label className="spectrum-exposure">
                    <input
                      type="checkbox"
                      checked={exposureEnabled}
                      onChange={(event) => setExposureEnabled(event.target.checked)}
                    />
                    <span>曝光区间</span>
                    <EmptyableNumberInput
                      min="1"
                      max={maxExposure}
                      value={exposureStart}
                      onValueChange={(value) => setExposureStart(Math.max(1, Math.min(maxExposure, value)))}
                    />
                    <span>–</span>
                    <EmptyableNumberInput
                      min={exposureStart}
                      max={maxExposure}
                      value={exposureEnd}
                      onValueChange={(value) => setExposureEnd(Math.max(exposureStart, Math.min(maxExposure, value)))}
                    />
                  </label>
                )}
                {raw && (
                  <div className="spectrum-frame-actions">
                    <select
                      aria-label="原始帧阶段"
                      value={framePhase}
                      onChange={(event) => setFramePhase(event.target.value as 'burn' | 'dark')}
                    >
                      <option value="burn">燃烧帧</option>
                      <option value="dark">暗帧</option>
                    </select>
                    <EmptyableNumberInput
                      aria-label="原始帧序号"
                      min="0"
                      value={frameIndex}
                      onValueChange={(value) => setFrameIndex(Math.max(0, value))}
                    />
                    <button
                      className="tool-button"
                      onClick={() => void loadFrame()}
                      disabled={busy || selected?.available?.[framePhase] === false}
                    >
                      原始帧
                    </button>
                  </div>
                )}
              </div>
              <div className="spectrum-legend">
                {curves.map((curve) => (
                  <button
                    key={curve.id}
                    className={curve.priority ? 'priority' : ''}
                    onClick={() => setPriorityId(curve.id)}
                  >
                    <i style={{ background: curve.color }} />
                    {curve.label}
                    {curve.priority && <span>优先</span>}
                  </button>
                ))}
              </div>
              <div className="spectrum-plot-wrap" ref={plotRef}>
                <SpectrumPlot
                  curves={curves}
                  xStart={xStart}
                  xEnd={xEnd}
                  yStart={yStart}
                  yEnd={yEnd}
                  tool={tool}
                  cursor={cursor}
                  locked={locked}
                  xAxisLabel={
                    pixelMode && raw ? 'CCD 点位' : curves.some((curve) => curve.data.some((item) => item.point.wavelength_nm != null))
                      ? '波长 (nm)'
                      : raw
                        ? 'CCD 点位'
                        : '步长 / 点位'
                  }
                  yAxisLabel={
                    mode === 'peak' ? '峰值' : mode === 'back' ? '背景' : mode === 'value' ? '结果值' : '强度 (ADC)'
                  }
                  onCursor={setCursor}
                  onToggleLock={() => setLocked((value) => !value)}
                  onPan={(dx, dy) => {
                    setPanX((value) => Math.max(-1, Math.min(1, value - dx * 2)))
                    setPanY((value) => Math.max(-1, Math.min(1, value + dy * 2)))
                  }}
                  onBoxSelect={boxSelect}
                />
                {cursor && (
                  <div className="spectrum-cursor-readout">
                    <span>{cursor.curveLabel}</span>
                    <strong>{cursor.datum.x.toFixed(3)}</strong>
                    <span>
                      点 {cursor.datum.point.point_index + 1} · 强度 {cursor.datum.y.toFixed(3)}
                    </span>
                    <span>{locked ? <LockKeyhole size={12} /> : <UnlockKeyhole size={12} />}</span>
                  </div>
                )}
              </div>
              {raw && cursor && <section className="spectrum-same-point" aria-label="多样品同点强度">
                <h3>同点强度 · CCD {Number(active.ccd?.index ?? ccd) + 1} · 点 {cursor.datum.point.point_index + 1}</h3>
                <div className="table-scroll"><table><thead><tr><th>样品</th><th>波长 / 横轴</th><th>强度</th></tr></thead>
                  <tbody>{curves.map((curve) => {
                    const sameCcd = details[curve.id]?.ccd?.index === active.ccd?.index
                    const datum = sameCcd ? curve.data.find((item) => item.point.point_index === cursor.datum.point.point_index) : null
                    return <tr key={curve.id}><td>{curve.label}</td><td>{datum?.x.toFixed(5) ?? 'CCD 不可比'}</td>
                      <td>{datum?.y.toFixed(6) ?? '无同点数据'}</td></tr>
                  })}</tbody></table></div>
                <SpectrumPointDetails token={token} recordId={cursor.curveId} ccd={details[cursor.curveId]?.ccd?.position ?? ccd}
                  point={cursor.datum.point.point_index} onToast={onToast} />
              </section>}
              <div className="spectrum-pan">
                <button
                  className="icon-button"
                  aria-label="水平平移"
                  onClick={() => setPanX((value) => Math.max(-1, value - 0.2))}
                >
                  <ChevronLeft size={15} />
                </button>
                <button
                  className="icon-button"
                  aria-label="垂直平移"
                  onClick={() => setPanY((value) => Math.max(-1, value - 0.2))}
                >
                  ↑
                </button>
                <span>
                  可见范围 X {xStart.toFixed(3)}–{xEnd.toFixed(3)} · Y {yStart.toFixed(2)}–{yEnd.toFixed(2)}
                </span>
                <button
                  className="icon-button"
                  aria-label="垂直平移"
                  onClick={() => setPanY((value) => Math.min(1, value + 0.2))}
                >
                  ↓
                </button>
                <button
                  className="icon-button"
                  aria-label="水平平移"
                  onClick={() => setPanX((value) => Math.min(1, value + 0.2))}
                >
                  <ChevronRight size={15} />
                </button>
              </div>
              {selected?.available?.burn === false && raw && (
                <p className="spectrum-overlay-note">
                  此记录仅保存均值，原始帧不可用；旧 CDT 未记录的曝光帧数不作推断。
                </p>
              )}
              <div className="spectrum-facts">
                <div>
                  <span>来源 SHA-256</span>
                  <CopyableCode value={active.source_sha256} visibleLength={18} />
                </div>
                <div>
                  <span>样品</span>
                  <ExpandableValue value={active.sample_name || active.sample_names?.join(' / ') || '—'} />
                </div>
                <div>
                  <span>转角 / CCD</span>
                  <strong>
                    {active.angle_deg == null ? '未记录' : `${active.angle_deg}°`} / {raw ? ccd + 1 : '—'}
                  </strong>
                </div>
                <div>
                  <span>曝光</span>
                  <strong>
                    {active.exposure_segment
                      ? `${active.exposure_segment.start}–${active.exposure_segment.end}`
                      : frameVisible
                        ? `${framePhase} #${frameIndex + 1}`
                        : '均值'}
                  </strong>
                </div>
                <div>
                  <span>可见点 / 曲线</span>
                  <strong>
                    {curves.reduce(
                      (sum, curve) => sum + curve.data.filter((item) => item.x >= xStart && item.x <= xEnd).length,
                      0
                    )}{' '}
                    / {curves.length}
                  </strong>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
