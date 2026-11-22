import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { PageFileActions } from '../../components/PageFileActions'
import { Activity, Download, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, saveFile, type SpectrumRecord, type SpectrumRecordSummary } from '../../api'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'
import { ExposureIntervalInput } from '../../components/ExposureIntervalInput'
import { SpectrumPlot, type SpectrumPlotCursor, type SpectrumPlotCurve, type SpectrumContextHandler } from '../../components/SpectrumPlot'
import { ContextMenu, useContextMenu, type MenuGroup } from '../../components/ContextMenu'
import { spectralLineMenuGroups, spectrumMenuGroups } from '../../components/spectrumMenu'
import { SpectrumRecordList } from './SpectrumRecordList'
import { SpectrumViewToolbar } from './SpectrumViewToolbar'
import { SpectrumPointPanel, useSpectrumPointFollow } from '../../components/SpectrumPointPanel'
import { LegacyViewingDesk } from '../../components/LegacyViewingDesk'
import { LegacySpectrumSurface } from '../../components/LegacySpectrumSurface'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import type { SpectrumCalibrationPosition, SpectrumFileSummary } from '../../api/spectrumViewer'
import type { SpectralLine } from '../../api/methods'
import { parseCcdCoordinate } from '../../components/legacyObservation'
import { ViewerDialog } from './ViewerDialog'
import { EvaporationFrameStatistics } from '../acquisition/EvaporationFrameStatistics'
import { clampSpectrumZoom, limitSpectrumRange, stepSpectrumRange, type SpectrumAxis, type SpectrumViewRange } from '../../components/spectrumZoom'

const groupKey = (item: SpectrumRecordSummary) => item.file_group_key || (item.task_id ? `task:${item.task_id}` : `${item.kind}:${item.source_sha256}`)
const compareRecords = (a: SpectrumRecordSummary, b: SpectrumRecordSummary) =>
  (a.turn_index ?? 0) - (b.turn_index ?? 0) || (a.repeat_index ?? a.record_index) - (b.repeat_index ?? b.record_index)

export function SpectrumViewerPage({ token, onToast, onClose, actionsTarget, viewing = 'spectra', initialFileGroup = '', initialRecordId, canExport = true }: { token: string; onToast: (message: string) => void; onClose?:()=>void; actionsTarget?: HTMLElement | null; viewing?:'spectra'|'evaporation'; initialFileGroup?:string; initialRecordId?:string; canExport?: boolean }) {
  const [showRecords,setShowRecords]=useState(true)
  const [fileGroup,setFileGroup]=useState(initialFileGroup)
  const [fileSources,setFileSources]=useState<SpectrumFileSummary[]>([])
  const [fileNames,setFileNames]=useState<Record<string,string>>({})
  const [multiMode,setMultiMode]=useState<'auto'|'single'|'multi'>('auto')
  const [operation,setOperation]=useState<'files'|'reference'|'frames'|'print'|'evaporation'|null>(null)
  const [methodLines,setMethodLines]=useState<SpectralLine[]>([])
  const [viewLine,setViewLine]=useState('')
  const [detailError,setDetailError]=useState('')
  const [pageRecords, setPageRecords] = useState<SpectrumRecordSummary[]>([])
  const [sourceKind, setSourceKind] = useState('all')
  const [search, setSearch] = useState('')
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
  const [[exposureStart, exposureEnd], setExposure] = useState<[number, number]>([1, 1])
  const [manualReferenceShift, setReferenceShift] = useState(0)
  const [calibrations, setCalibrations] = useState<Record<string, {
    shift?: number; positions: Record<string, SpectrumCalibrationPosition>
  }>>({})
  const [calibrating, setCalibrating] = useState(false)
  const calibrationRequest = useRef(0)
  const [manualZoomX, setZoomX] = useState(1)
  const [zoomY, setZoomY] = useState(1)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [locked, setLocked] = useState(false)
  const [recordLocked,setRecordLocked] = useState(false)
  const [pixelMode,setPixelMode] = useState<1|4|10|null>(null)
  const [pointCoordinates, setPointCoordinates] = useState(false)
  const plotRef=useRef<HTMLDivElement>(null)
  const [plotWidth,setPlotWidth]=useState(872)
  const [screenProfiles,setScreenProfiles]=useState<Array<{id:number;name:string;screen_width_mm:number;screen_resolution_px:number}>>([])
  const [screenProfileId,setScreenProfileId]=useState(0)
  useEffect(() => { let live=true;void api.spectrumDisplayProfiles(token).then(next => {if(live){setScreenProfiles(next);setScreenProfileId(next[0]?.id ?? 0)}}).catch(() => {});return () => {live=false} },[token])
  const [locateValue, setLocateValue] = useState('')
  const pendingCoordinate = useRef<{ recordId: string; ccd: number; point: number } | null>(null)
  const pendingLine = useRef<{ recordId: string; lineId: string } | null>(null)
  const [framePhase, setFramePhase] = useState<'burn' | 'dark'>('burn')
  const [frameNumber, setFrameNumber] = useState(1)
  const [frameVisible, setFrameVisible] = useState(false)
  const [followPoint, setFollowPoint] = useState(viewing === 'evaporation')
  const [fixedView, setFixedView] = useState(true)
  const [priorityLine, setPriorityLine] = useState(true)
  const menu = useContextMenu<{ recordId: string; point: SpectrumPlotCursor | null; marker?: string }>()
  const fileMenu = useContextMenu<null>()
  const [printScope, setPrintScope] = useState<'visible' | 'ccd'>('visible')
  const [printLayers, setPrintLayers] = useState<Array<'curve' | 'grayscale'>>(['curve'])
  const [printScale, setPrintScale] = useState<'fit_long' | 'fit_short' | 'ccd_10x'>('fit_long')
  const [printPaper, setPrintPaper] = useState<'A4' | 'A3' | 'Letter'>('A4')
  const [busy, setBusy] = useState(false)
  const detailRequest = useRef(0)
  const palette = ['#1c68b2', '#c75b39', '#27805d', '#8b5bb5', '#d18b22', '#247c8b', '#b54769', '#58677a']
  const openingRequestedGroup = Boolean(initialFileGroup && fileGroup === initialFileGroup &&
    sourceKind === 'all' && !search && angleFilter === 'all')

  const loadRecords = useCallback(async () => {
    const requestId = ++listRequest.current
    setBusy(true)
    try {
      const scope=viewing==='evaporation'?'evaporation':'all', angle=angleFilter==='all'?undefined:Number(angleFilter)
      const files=await api.spectrumFiles(token,scope,sourceKind,search,angle)
      let chosen=files.find(item=>item.key===fileGroup)??(openingRequestedGroup ? undefined : files[0])
      let requestedId = openingRequestedGroup ? initialRecordId : undefined
      if (!chosen && openingRequestedGroup && fileGroup.startsWith('task:')) {
        const matching = await api.spectrumRecords(token, sourceKind, angle, 0, search, scope, fileGroup)
        if (requestId !== listRequest.current) return
        const first = matching.sort(compareRecords)[0]
        if (first) {
          chosen = files.find(item => item.key === groupKey(first))
          requestedId ??= first.id
        }
      }
      const next:SpectrumRecordSummary[]=[]
      if(chosen){
        for(let offset=0;;offset+=100){
          const page=await api.spectrumRecords(token,sourceKind,angle,offset,search,scope,chosen.key)
          if(requestId!==listRequest.current)return
          next.push(...page)
          if(page.length<100)break
        }
      }
      if(requestId===listRequest.current)setFileSources(files)
      if (requestId !== listRequest.current) return
      const filtered = viewing==='evaporation' ? next.filter(item=>item.format==='edt'||item.task_kind==='evaporation') : next
      setPageRecords(filtered)
      setRecords((current) => [...current.filter((item) => !next.some((fresh) => fresh.id === item.id)), ...next])
      const first = requestedId
        ? filtered.find(item => item.id === requestedId)?.id ?? null
        : [...filtered].sort(compareRecords)[0]?.id ?? null
      setSelectedId(current => filtered.some(item=>item.id===current) ? current : first)
      setPriorityId(current => filtered.some(item=>item.id===current) ? current : first)
    } catch (error) {
      if (requestId === listRequest.current) onToast(error instanceof Error ? error.message : '无法读取谱图记录')
    } finally {
      if (requestId === listRequest.current) setBusy(false)
    }
  }, [token, onToast, sourceKind, angleFilter, search, viewing, fileGroup, openingRequestedGroup, initialRecordId])

  useEffect(() => {
    void loadRecords()
    return () => {
      listRequest.current++
    }
  }, [loadRecords])
  const selected = records.find((item) => item.id === selectedId) ?? null
  const raw = selected != null && selected.kind !== 'result'
  const exposureEnabled = raw && Boolean(selected?.available?.burn)
  useEffect(()=>{
    setOverlayIds([]);setViewLine('')
    setExposure([1, Math.max(1, selected?.burn_count ?? 1)])
  },[selectedId])

  const displayIds = useMemo(() => {
    if (!selectedId) return []
    if (!raw) return [selectedId]
    return Array.from(new Set([selectedId, ...overlayIds])).slice(0, 8)
  }, [selectedId, overlayIds, raw])

  const loadDetails = useCallback(async () => {
    if (!displayIds.length) return
    const requestId = ++detailRequest.current
    setBusy(true);setDetails({});setDetailError('');setCursor(null);setLocked(false)
    try {
      const loaded = await Promise.all(
        displayIds.map(async (id) => {
          const summary = records.find((item) => item.id === id)
          const nextCcd = Math.max(0, Math.min((summary?.ccd_count ?? 1) - 1, ccd))
          const params = {
            ccd: nextCcd,
            line,
            detail: 'summary' as const,
            intensityMode: summary?.kind==='raw'?'legacy_2_0_2' as const:'stored' as const,
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
      if (requestId === detailRequest.current) {setDetailError(error instanceof Error ? error.message : '无法读取谱图数据');onToast(error instanceof Error ? error.message : '无法读取谱图数据')}
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

  const loadedActive = selectedId ? (details[selectedId] ?? null) : null
  const active = loadedActive && (loadedActive.kind==='result'||loadedActive.ccd?.position===ccd) ? loadedActive : null
  const selectedGroupKey = fileSources.some(item => item.key === fileGroup) ? fileGroup : selected ? groupKey(selected) : ''
  const requestedGroupMissing = openingRequestedGroup && !selectedGroupKey
  const currentGroup = selectedGroupKey || (openingRequestedGroup ? '' : fileSources[0]?.key ?? '')
  const visibleRecords = useMemo(() => pageRecords.filter(item => groupKey(item) === currentGroup)
    .sort(compareRecords), [pageRecords, currentGroup])
  const multiTableScroll = useRef(0)
  const attachMultiTable = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    node.scrollTop = multiTableScroll.current
    const step = (direction: number) => {
      const rowHeight = node.querySelector<HTMLTableRowElement>('tbody tr')?.offsetHeight
      if (rowHeight) node.scrollTop = (Math.round(node.scrollTop / rowHeight) + direction) * rowHeight
    }
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || !event.deltaY) return
      event.preventDefault()
      step(Math.sign(event.deltaY))
    }
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
      event.preventDefault()
      step(event.key === 'ArrowUp' ? -1 : 1)
    }
    node.addEventListener('wheel', wheel, { passive: false })
    node.addEventListener('keydown', keydown)
    return () => {
      node.removeEventListener('wheel', wheel)
      node.removeEventListener('keydown', keydown)
    }
  }, [])
  const groups=fileSources
  const multiView=raw&&(multiMode==='multi'||(multiMode==='auto'&&(active?.format==='cmt'||active?.storage_mode==='full_interval'&&active?.task_kind!=='evaporation')))
  useEffect(()=>{if(multiView)setTool(current=>current==='pan'?'crosshair':current)},[multiView])
  useEffect(()=>{
    setMethodLines([]);setViewLine('')
    if(!selected||selected.kind==='sample')return
    let cancelled=false
    void api.currentMethod(token).then(current=>{if(!cancelled)setMethodLines(current.referenced_version?.lines??[])}).catch(()=>{})
    return ()=>{cancelled=true}
  },[token,selected?.id])
  const maxExposure = Math.max(1, Number(active?.ignition?.burn_count ?? selected?.burn_count ?? 1))
  const visibleFrame = frameVisible ? active?.frame_detail : null
  const availableFrames = Number(active?.ignition?.[framePhase === 'burn' ? 'burn_count' : 'dark_count'] ?? 0)
  const validFrameNumber = Number.isInteger(frameNumber) && frameNumber >= 1 && frameNumber <= availableFrames
  const turnIndices = active?.layout?.band_turn_indices as Array<number | null> | undefined
  const calibrationKey = `${selectedId}:${turnIndices?.[ccd] ?? ''}`
  const calibration = calibrations[calibrationKey]
  const referenceShift = calibration?.shift ?? manualReferenceShift

  useEffect(() => {
    setCalibrations({})
    setCalibrating(false)
  }, [selectedId, token])
  useEffect(() => () => { calibrationRequest.current++ }, [selectedId, token])

  const curves = useMemo<SpectrumPlotCurve[]>(
    () =>
      displayIds.filter(id=>!frameVisible||id===selectedId).flatMap((id, index) => {
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
            const x = pointCoordinates && record.kind !== 'result' ? Number(point.point_index ?? pointIndex) :
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
    [displayIds, details, selectedId, frameVisible, referenceShift, mode, records, priorityId,pointCoordinates]
  )

  useEffect(() => {
    const host=plotRef.current;if(!host)return
    const resize=() => {const svg=host.querySelector('svg');if(svg)setPlotWidth((svg.getScreenCTM()?.a ?? 1)*(Number(svg.getAttribute('viewBox')?.split(' ')[2]??960)-88))}
    const observer=new ResizeObserver(resize);observer.observe(host);resize();return () => observer.disconnect()
  },[active?.id])
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
  const profile = screenProfiles.find(p => p.id === screenProfileId)
  const pointWidth = Number(active?.layout?.point_width_um ?? active?.layout?.point_width ?? 0)
  const spacing = (pixelMode === 10
    ? pointWidth / 1000 * 10 * (profile ? profile.screen_resolution_px / profile.screen_width_mm : 0)
    : pixelMode ?? 0) / (window.devicePixelRatio || 1)
  const zoomX = raw && spacing > 0 ? clampSpectrumZoom(fullXSpan * spacing / Math.max(1, plotWidth)) : manualZoomX
  const xSpan = fullXSpan / zoomX
  const ySpan = fullYSpan / zoomY
  const xStart = fullRange.xMin + ((panX + 1) / 2) * Math.max(0, fullXSpan - xSpan)
  const xEnd = xStart + xSpan
  const yStart = fullRange.yMin + ((panY + 1) / 2) * Math.max(0, fullYSpan - ySpan)
  const yEnd = yStart + ySpan
  const view = { xMin: xStart, xMax: xEnd, yMin: yStart, yMax: yEnd }

  const setAxisRange = (axis: SpectrumAxis, next: SpectrumViewRange) => {
    const isX = axis === 'x'
    const fullSpan = isX ? fullXSpan : fullYSpan
    const start = isX ? next.xMin : next.yMin
    const end = isX ? next.xMax : next.yMax
    const zoom = clampSpectrumZoom(fullSpan / (end - start))
    const room = fullSpan - fullSpan / zoom
    const pan = room > 0 ? Math.max(-1, Math.min(1, 2 * (start - (isX ? fullRange.xMin : fullRange.yMin)) / room - 1)) : 0
    if (isX) {
      setPixelMode(null)
      setZoomX(zoom)
      setPanX(pan)
    } else {
      setZoomY(zoom)
      setPanY(pan)
    }
  }
  const zoomView = (axis: SpectrumAxis, factor: number) => setAxisRange(axis, stepSpectrumRange(view, fullRange, axis, factor))

  const resetView = (resetCorrection = false, horizontalOnly = false) => {
    setPixelMode(null)
    setPointCoordinates(false)
    setZoomX(1)
    setPanX(0)
    if(horizontalOnly)return
    setZoomY(1)
    setPanY(0)
    setCursor(null)
    setLocked(false)
    if (resetCorrection) {
      setReferenceShift(0)
      setCalibrations({})
    }
  }
  const previousView = useRef<{ id: string | null; group: string; ccd: number; line: number; mode: string } | null>(null)
  const selectedGroup = selected ? groupKey(selected) : ''
  useEffect(() => {
    const previous = previousView.current
    previousView.current = { id: selectedId, group: selectedGroup, ccd, line, mode }
    const preserveX = fixedView && previous && raw && previous.id !== selectedId
      && previous.group === selectedGroup && previous.ccd === ccd && previous.line === line && previous.mode === mode
    if (preserveX) {
      setZoomY(1); setPanY(0); setCursor(null); setLocked(false)
    } else resetView()
    setLocateValue('')
  }, [selectedId, selectedGroup, ccd, line, mode])

  const selectRecord = (record: SpectrumRecordSummary, additive = false) => {
    if(recordLocked && record.id!==selectedId)return
    if(additive && record.kind!=='result') { toggleOverlay(record.id); return }
    pendingLine.current = priorityLine && viewLine && selectedGroup === groupKey(record) && record.id !== selectedId
      ? { recordId: record.id, lineId: viewLine } : null
    detailRequest.current++
    setOverlayIds([])
    setSelectedId(record.id)
    setPriorityId(record.id)
    setCcd(fixedView && record.kind !== 'result' && selectedGroup === groupKey(record) ? Math.min(ccd, Math.max(0, (record.ccd_count ?? 1) - 1)) : 0)
    setLine(0)
    setFrameVisible(false)
    setMode(record.kind !== 'result' ? 'mean' : record.matrix_kind === 'peak_back' ? 'peak' : 'value')
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
    if (!active || !raw || !selectedId || !validFrameNumber) return
    const requestId = ++detailRequest.current
    setBusy(true)
    setCursor(null);setLocked(false)
    try {
      const next = await api.spectrum(token, active.id, {
        ccd,
        line,
        detail: 'frame',
        phase: framePhase,
        frame: frameNumber - 1
      })
      if (requestId !== detailRequest.current) return
      setDetails((current) => ({ ...current, [selectedId]: next }))
      setFrameVisible(true)
      setMode('mean')
      return true
    } catch (error) {
      if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '原始帧不可用')
    } finally {
      if (requestId === detailRequest.current) setBusy(false)
    }
  }
  const boxSelect = (range: SpectrumViewRange) => {
    const next = limitSpectrumRange(range, fullRange)
    setAxisRange('x', next)
    setAxisRange('y', next)
    setTool('crosshair')
  }
  const locateDatum = (curve: SpectrumPlotCurve, datum: SpectrumPlotCurve['data'][number]) => {
    const half = fullXSpan / Math.max(4, zoomX) / 2
    setAxisRange('x', limitSpectrumRange({ ...view, xMin: datum.x - half, xMax: datum.x + half }, fullRange))
    setCursor({ curveId: curve.id, curveLabel: curve.label, x: 54 + ((datum.x - xStart) / (xEnd - xStart || 1)) * 872,
      y: 330 - ((datum.y - yStart) / (yEnd - yStart || 1)) * 288, datum })
    setLocked(true)
    setTool('crosshair')
  }
  useEffect(() => {
    const pending = pendingCoordinate.current
    if (!pending || pending.recordId !== selectedId || pending.ccd !== ccd || busy || calibrating
      || !selectedId || details[selectedId]?.ccd?.position !== pending.ccd) return
    const curve = curves.find((item) => item.id === selectedId)
    const datum = curve?.data.find((item) => item.point.point_index === pending.point)
    if (!curve || !datum) return
    pendingCoordinate.current = null
    locateDatum(curve, datum)
  }, [curves, selectedId, ccd, busy, calibrating])
  const locate = () => {
    if (locateValue.includes(',')) {
      const coordinate = parseCcdCoordinate(locateValue)
      const indices = Array.isArray(active?.layout?.ccd_indices) ? active.layout.ccd_indices as number[]
        : Array.from({ length: Number(active?.layout?.ccd_count ?? 0) }, (_, index) => index)
      const turnIndices = active?.layout?.band_turn_indices as Array<number | null> | undefined
      const currentTurn = turnIndices?.[ccd]
      const position = coordinate ? indices.findIndex((physical, index) => physical === coordinate.ccd && (!turnIndices || turnIndices[index] === currentTurn)) : -1
      if (!coordinate || position < 0 || coordinate.point >= Number(active?.layout?.points_per_ccd ?? 0))
        {onToast('CCD 坐标超出安装范围，请输入 CCD序号,点位，例如 2,123');return false}
      if (!selectedId) return false
      pendingCoordinate.current = { recordId: selectedId, ccd: position, point: coordinate.point }
      if (position === ccd && !busy && details[selectedId]?.ccd?.position === position) {
        const curve = curves.find((item) => item.id === selectedId)
        const datum = curve?.data.find((item) => item.point.point_index === coordinate.point)
        if (curve && datum) { pendingCoordinate.current = null; locateDatum(curve, datum) }
      } else setCcd(position)
      return true
    }
    if(!locateValue.trim())return false
    const target = Number(locateValue)
    const curve = curves.find((item) => item.priority) ?? curves[0]
    if (!curve?.data.length || !Number.isFinite(target)) return false
    const datum = curve.data.reduce((best, item) =>
      Math.abs(Number(pointCoordinates ? item.point.wavelength_nm ?? item.point.point_index ?? item.x : item.x) - target)
        < Math.abs(Number(pointCoordinates ? best.point.wavelength_nm ?? best.point.point_index ?? best.x : best.x) - target) ? item : best
    )
    locateDatum(curve, datum)
    return true
  }
  const nativeX = (x: number) => {
    if (!pointCoordinates || !raw)return x
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
    setPointCoordinates(true);setPixelMode(mode);setPanX(0);setCursor(null);setLocked(false)
  }
  const exportVisible = async () => {
    if (!active || busy) return
    const requestId = detailRequest.current
    try {
      const result = await api.exportSpectrum(token, active.id, {
        ccd,
        line,
        detail: visibleFrame ? 'frame' : 'summary',
        phase: visibleFrame?.phase === 'dark' ? 'dark' : 'burn',
        frame: visibleFrame?.index ?? 0,
        exposureStart: !visibleFrame && raw && exposureEnabled ? exposureStart : undefined,
        exposureEnd: !visibleFrame && raw && exposureEnabled ? exposureEnd : undefined,
        xMin: nativeX(xStart),
        xMax: nativeX(xEnd),
        referenceShift, intensityMode:active.intensity_mode
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
        intensity_mode: active.intensity_mode,
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
        selected_record_ids: frameVisible?[active.id]:displayIds,
        priority_record_id: priorityId ?? selectedId ?? undefined,
        frame_phase: visibleFrame?.phase === 'dark' ? 'dark' : 'burn',
        frame_index: visibleFrame?.index ?? 0,
        exposure_start: !visibleFrame && raw && exposureEnabled ? exposureStart : undefined,
        exposure_end: !visibleFrame && raw && exposureEnabled ? exposureEnd : undefined
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

  const observationLines=active?.observation_lines??methodLines.map(item=>({id:item.id,element:item.element,wavelength_nm:item.actual_wavelength_nm??item.wavelength_nm,ccd_index:null,point_index:null,exposure_start_frame:item.exposure_start_frame,exposure_end_frame:item.exposure_end_frame}))
  const canCalibrate = viewing === 'spectra' && raw && active && !busy && !frameVisible && !calibrating
  const correct = async (scope: 'reference' | 'all') => {
    if (!canCalibrate || !selectedId) return
    const requestId = ++calibrationRequest.current
    const detailId = detailRequest.current
    setCalibrating(true)
    try {
      const result = await api.calibrateSpectrum(token, selectedId, ccd, scope,
        exposureEnabled ? [exposureStart, exposureEnd] : undefined)
      if (requestId !== calibrationRequest.current || detailId !== detailRequest.current) return
      const found = result.positions.filter(item => item.ccd !== null && item.point !== null)
      const failed = result.positions.filter(item => item.point === null)
      const reference = found.find(item => item.reference)
      if (found.length) {
        setCalibrations(prior => ({
          ...prior,
          [calibrationKey]: {
            shift: reference?.reference_shift ?? prior[calibrationKey]?.shift,
            positions: { ...prior[calibrationKey]?.positions, ...Object.fromEntries(found.map(item => [item.id, item])) }
          }
        }))
        const target = found.find(item => item.id === viewLine) ??
          (scope === 'all' ? found.find(item => !item.reference) : reference) ?? found[0]
        if (target.ccd !== null && target.point !== null) {
          pendingCoordinate.current = { recordId: selectedId, ccd: target.ccd, point: target.point }
          if (observationLines.some(item => item.id === target.id)) setViewLine(target.id)
          setCcd(target.ccd)
        }
      }
      const label = scope === 'reference' ? '参考线已校正' : `已校正 ${found.length} 条谱线`
      onToast(failed.length
        ? `${found.length ? label + '，' : ''}${failed.length === 1 ? failed[0].element : `${failed.length} 条谱线`}未找到有效峰，保留原位置`
        : label)
    } catch (error) {
      if (requestId === calibrationRequest.current && detailId === detailRequest.current) {
        onToast(error instanceof Error ? error.message : '谱线校正失败')
      }
    } finally {
      if (requestId === calibrationRequest.current) setCalibrating(false)
    }
  }
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (viewing !== 'spectra' || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return
      if (event.key === 'F5' || event.key === 'F6') {
        event.preventDefault()
        if (!operation && !event.repeat) void correct(event.key === 'F5' ? 'reference' : 'all')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  type ObservationLine = typeof observationLines[number]
  const linePosition = (item: ObservationLine, ignoreCorrection = false) => {
    const corrected = ignoreCorrection ? undefined : calibration?.positions[item.id]
    const indices = (active?.layout?.ccd_indices as number[] | undefined) ?? []
    let physical = corrected?.ccd != null ? indices[corrected.ccd] ?? corrected.ccd : item.ccd_index
    let point = corrected?.point ?? item.point_index
    const count = Number(active?.layout?.points_per_ccd ?? 0)
    if (physical == null || point == null) {
      const coefficients = active?.layout?.ws_cof as number[] | undefined
      const gaps = active?.layout?.gap_points as number[] | undefined
      if (coefficients?.length && count) {
        const step = coefficients[0] * item.wavelength_nm ** 2 + coefficients[1] * item.wavelength_nm + coefficients[2]
        for (const index of indices) {
          const left = index * count + (gaps ?? []).slice(0, index).reduce((sum, value) => sum + value, 0)
          if (step < left || step > left + count - 1) continue
          physical = index; point = Math.round(step - left)
          break
        }
      }
    }
    if (physical == null || point == null) return null
    const position = indices.findIndex((index, slot) => index === physical && (!turnIndices || turnIndices[slot] === turnIndices[ccd]))
    const target = Math.round(point)
    return position >= 0 && target >= 0 && target < count ? { position, target } : null
  }
  const chooseLine = (id: string, restore = false) => {
    setViewLine(id)
    const item = observationLines.find(item => item.id === id)
    setLocateValue(item ? String(item.wavelength_nm) : '')
    if (!item || !active || !selectedId) return
    const location = linePosition(item, restore)
    if (!location) return onToast('当前谱图没有可用于该谱线的有效 CCD 点位')
    const { position, target } = location
    pendingCoordinate.current = { recordId: selectedId, ccd: position, point: target }
    if (position === ccd) {
      const curve = curves.find(curve => curve.id === selectedId)
      const datum = curve?.data.find(item => item.point.point_index === target)
      if (curve && datum) { pendingCoordinate.current = null; locateDatum(curve, datum) }
    } else setCcd(position)
    if (item.exposure_start_frame && item.exposure_end_frame && selected?.available?.burn) {
      setExposure([item.exposure_start_frame, item.exposure_end_frame])
    }
  }
  useEffect(() => {
    const pending = pendingLine.current
    if (!pending || pending.recordId !== active?.id || busy || !observationLines.some(item => item.id === pending.lineId)) return
    pendingLine.current = null
    chooseLine(pending.lineId)
  }, [active, busy, observationLines])
  const observerCurve = curves.find(curve => curve.id === selectedId)
  const markers = raw ? observationLines.flatMap(item => {
    const location = linePosition(item)
    const datum = location?.position === ccd && observerCurve?.data.find(value => value.point.point_index === location.target)
    return datum ? [{ key: item.id, position: datum.x, kind: 'located' as const,
      label: `${item.element} ${item.wavelength_nm.toFixed(4)} nm`, selected: viewLine === item.id, select: () => chooseLine(item.id) }] : []
  }) : []
  const hasRawFrames = Boolean(active && raw && selected?.storage_mode !== 'averaged' &&
    (selected?.available?.burn || selected?.available?.dark))
  const canFollowPoint = viewing === 'evaporation' && hasRawFrames && selected?.format !== 'cdt' && !multiView
  const following = followPoint && canFollowPoint
  const follow = useSpectrumPointFollow(following && Boolean(active) && !detailError, `${active?.id}:${ccd}`,
    cursor?.curveId === active?.id ? cursor?.datum.point.point_index ?? null : null, locked)
  const openSpectrumMenu: SpectrumContextHandler = (event, point, marker) => {
    if (!active) return
    if (marker) setViewLine(marker)
    menu.open(event, { recordId: active.id, point, marker })
  }
  const menuLine = observationLines.find(item => item.id === menu.target?.data.marker)
  const restorePosition = (id: string, all: boolean) => {
    const restoredReference = all || calibration?.positions[id]?.reference
    setCalibrations(prior => {
      const next = { ...prior }
      if (all) delete next[calibrationKey]
      else if (calibration) next[calibrationKey] = { shift: restoredReference ? undefined : calibration.shift,
        positions: Object.fromEntries(Object.entries(calibration.positions).filter(([key]) => key !== id)) }
      return next
    })
    if (restoredReference) setReferenceShift(0)
    chooseLine(id, true)
  }
  const extraMenu: MenuGroup = canFollowPoint ? [{ label: '显示分时', checked: following, run: () => {
    if (!following) {
      const point = locked ? cursor : menu.target?.data.point ?? null
      setCursor(point)
      follow.openAt(point?.datum.point.point_index ?? null)
    }
    setFollowPoint(!following)
  } }] : []
  const frameActions: MenuGroup = []
  if (hasRawFrames) frameActions.push({ label: '查看原始帧', disabled: busy, run: () => {
    setFramePhase(visibleFrame ? (visibleFrame.phase === 'dark' ? 'dark' : 'burn') : selected?.available?.burn ? 'burn' : 'dark')
    setFrameNumber((visibleFrame?.index ?? 0) + 1)
    setOperation('frames')
  } })
  if (viewing === 'evaporation') frameActions.push({
    label: '蒸发帧统计', disabled: busy, run: () => setOperation('evaporation')
  })
  const openFileMenu = (event: React.MouseEvent) => fileMenu.open(event, null)
  const menuGroups = menuLine ? spectralLineMenuGroups(observationLines, menuLine, item => chooseLine(item.id),
    { label: '优先显示', checked: priorityLine, run: () => {
      setPriorityLine(!priorityLine)
      if (!priorityLine) chooseLine(menuLine.id)
      else setLocked(false)
    } }, [], [
      { label: '还原实际位置', run: () => restorePosition(menuLine.id, false) },
      { label: '还原全部位置', run: () => restorePosition(menuLine.id, true) }
    ]) : spectrumMenuGroups(raw && active ? {
      current: ccd, indices: Array.from({ length: Number(active.layout?.ccd_count ?? 0) }, (_, index) => index),
      choose: index => moveBand(index - ccd)
    } : undefined, view, fullRange, zoomView, { label: '固定视图', checked: fixedView, run: () => setFixedView(value => !value) }, extraMenu)
  const plottedCurves = new Map(curves.map(curve => [curve.id, curve]))
  const multiTable = multiView && (
    <div className="legacy-multi-point-table" role="region" aria-label="多样品同点强度" tabIndex={0}
      ref={attachMultiTable} onScroll={event => { multiTableScroll.current = event.currentTarget.scrollTop }}>
      <table className="legacy-view-table">
        <thead><tr><th>记录号</th><th>样品编号</th><th>样品序号</th><th>积分强度</th></tr></thead>
        <tbody>{visibleRecords.map(record => {
          const curve = plottedCurves.get(record.id)
          const sameCcd = details[record.id]?.ccd?.index === active?.ccd?.index
          const datum = cursor && sameCcd ? curve?.data.find(item => item.point.point_index === cursor.datum.point.point_index) : null
          const choose = () => curve ? setPriorityId(record.id) : selectRecord(record)
          return <tr key={record.id} aria-selected={record.id === (priorityId ?? selectedId)} onClick={choose}>
            <td>{record.band_id ?? record.record_index}</td>
            <td>{record.sample_name || record.band_name || record.id}</td>
            <td>{record.sample_no ?? (record.repeat_index == null ? '—' : record.repeat_index + 1)}</td>
            <td data-record-id={record.id}>{datum?.y.toFixed(6) ?? ''}</td>
          </tr>
        })}</tbody>
      </table>
    </div>
  )
  return <div className="page-content spectrum-viewer-page legacy-viewing-page" data-viewing={viewing} data-source-sha={active?.source_sha256??''} data-file-group={currentGroup} data-testid={viewing==='evaporation'?'evaporation-spectrum-page':'spectrum-viewer-page'}>
    {menu.target && active?.id === menu.target.data.recordId && <ContextMenu target={menu.target} close={menu.close}
      label={menuLine ? '谱线位置菜单' : '谱图菜单'} groups={menuLine ? menuGroups : [...menuGroups, frameActions]} />}
    {fileMenu.target && <ContextMenu target={fileMenu.target} close={fileMenu.close} label="谱文件菜单" groups={[[
      { label: '选择谱文件', disabled: recordLocked, run: () => setOperation('files') },
      ...(!showRecords ? [{ label: '显示样品列表', run: () => setShowRecords(true) }] : [])
    ]]} />}
    <PageFileActions target={actionsTarget}>
      <OpenLegacyFile onBusyChange={setBusy} token={token} purpose={viewing==='evaporation'?'evaporation':'spectra'} label={viewing==='evaporation'?'打开蒸发文件':'打开谱文件'} disabled={busy||recordLocked} onOpened={async(result,path)=>{
        setFileNames(current=>({...current,[result.source_sha256]:path.split(/[\\/]/).pop()||path}))
        setFileGroup(`raw:${result.source_sha256}`);setSourceKind('raw');setSearch(result.source_sha256);setAngleFilter('all');setOverlayIds([]);setMultiMode('auto')
        const next=await api.spectrumRecords(token,'raw',undefined,0,result.source_sha256)
        setRecords(current=>[...current.filter(item=>!next.some(fresh=>fresh.id===item.id)),...next]);setPageRecords(next);setSelectedId(next[0]?.id??null);setPriorityId(next[0]?.id??null);setCcd(0);setLine(0)
      }}/><button className="secondary-button" disabled={!active||busy} onClick={()=>void exportVisible()}><Download size={14}/>导出</button>
      <button className="secondary-button" disabled={busy} onClick={()=>void loadRecords()}><RefreshCw size={14}/>刷新</button>
    </PageFileActions>
    <LegacyViewingDesk>
      <div className="legacy-view-top" role="toolbar" aria-label="谱线与曝光操作" tabIndex={showRecords ? undefined : 0}
        onContextMenu={showRecords ? undefined : event => {
          if (!(event.target as Element).closest('input,select')) openFileMenu(event)
        }}>
        <label>选择谱线:<select aria-label="选择谱线" value={viewLine} disabled={!observationLines.length||busy} onChange={event=>chooseLine(event.target.value)}><option value=""/>{observationLines.map(item=><option value={item.id} key={item.id}>{item.element} {item.wavelength_nm}</option>)}</select></label>
        <label>定位谱线:<input aria-label="定位谱线" value={locateValue} disabled={!active||busy||calibrating}
          title="输入波长、点位或 CCD,点位，按回车定位" onChange={event=>setLocateValue(event.target.value)}
          onKeyDown={event=>{if(event.key==='Enter'&&locateValue.trim()){event.preventDefault();locate()}}}/></label>
        {raw&&<label>曝光区间:<ExposureIntervalInput key={selectedId} start={exposureStart} end={exposureEnd}
          max={maxExposure} disabled={busy||!exposureEnabled} onCommit={(start, end) => setExposure([start, end])}/></label>}
        <span className="legacy-toolbar-separator" aria-hidden="true"/>
        <SpectroscopyToolButton icon="sample-input" label="录入样品编号" disabled description="查看页只读；样品编号请在样品队列或摄谱任务中录入"/>
        {viewing === 'spectra' && raw && <>
          <SpectroscopyToolButton icon="reference-correction" label="校参考线" description="校参考线（F5）"
            aria-keyshortcuts="F5" disabled={!canCalibrate} onClick={() => void correct('reference')} />
          <SpectroscopyToolButton icon="line-correction" label="校正谱线" description="校正谱线（F6）"
            aria-keyshortcuts="F6" disabled={!canCalibrate} onClick={() => void correct('all')} />
        </>}
        <SpectroscopyToolButton icon="reference-correction" label="参考校正设置" disabled={!active||calibrating} onClick={()=>setOperation('reference')}/>
        <SpectroscopyToolButton icon="measure" label="开始测量" disabled description="查看页没有运行中的测量任务"/>
        <SpectroscopyToolButton icon="pause" label="暂停测量" disabled description="查看页没有运行中的测量任务"/>
        <span className="legacy-toolbar-separator" aria-hidden="true"/>
        <SpectroscopyToolButton icon="finish" label="关闭谱图查看" disabled={!onClose} onClick={onClose}/>
        {!raw&&active?.matrix_kind==='peak_back'&&<label>显示<select aria-label="结果数据显示" value={mode} onChange={event=>setMode(event.target.value as typeof mode)}><option value="peak">峰值</option><option value="back">背景</option></select></label>}
      </div>
      <div className={`legacy-view-body spectrum-viewer-layout${showRecords?'':' left-hidden'}`}>
        {showRecords&&<SpectrumRecordList key={currentGroup} token={token} visibleRecords={visibleRecords} selectedId={selectedId} displayIds={displayIds} selectRecord={selectRecord} recordLocked={recordLocked}
          multiView={multiView} toggleMulti={()=>{setMultiMode(multiView?'single':'multi');setTool('crosshair')}} toggleLock={()=>setRecordLocked(value=>!value)} onHide={()=>setShowRecords(false)} onContextMenu={openFileMenu}/>}
        <section className="legacy-view-center spectrum-workbench">
          {detailError?<div className="auth-error" role="alert">{detailError}<button onClick={()=>void loadDetails()}>重试读取</button></div>:!active?<div className="method-empty"><Activity size={24}/><p>{busy?'正在读取谱图…':'选择一条谱图记录'}</p></div>:<>
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
                zoom={zoomView}
                resetY={() => { setZoomY(1); setPanY(0) }}
                recordLocked={recordLocked}
                multiView={multiView}
                pixelScale={pixelScale} pixelMode={pixelMode} tool={tool} setTool={setTool}
                busy={busy} print={()=>setOperation('print')}
              />

          <div className="spectrum-point-layout">
            <div className="spectrum-point-plot">
          <LegacySpectrumSurface fitPlot title={`${multiView?'':`记录号：[${selected?.band_id??active.record_index}] ${active.band_name?'谱带名称':'样品编号'}：[${active.band_name||active.sample_name||''}] `}CCD序号：[${Number(active.ccd?.index??ccd)+1}] ${visibleFrame?`${visibleFrame.phase==='burn'?'燃烧':'暗'}帧：[${visibleFrame.index+1}]`:`曝光区间：[${active.exposure_segment?.start??1}-${active.exposure_segment?.end??maxExposure}]`}`}
            curves={curves} xMin={xStart} xMax={xEnd} yMin={yStart} yMax={yEnd} cursor={cursor} locked={locked} tool={tool} onCursor={setCursor} onToggleLock={picked=>{if(picked)setCursor(picked);setLocked(value=>!value)}}
            onPointerPresence={follow.plotPresence}
            onPan={(dx,dy)=>{setPanX(value=>Math.max(-1,Math.min(1,value-dx*2)));setPanY(value=>Math.max(-1,Math.min(1,value+dy*2)))}} onBox={boxSelect}
            onSpectrumContext={openSpectrumMenu} upperTable={!raw?<div className="observation-status">结果数据 · {curves[0]?.label}</div>:multiView?multiTable:undefined}>
                <SpectrumPlot fitContainer stretch fractionalX={!pointCoordinates && xSpan < 5}
                  curves={curves}
                  xStart={xStart}
                  xEnd={xEnd}
                  yStart={yStart}
                  yEnd={yEnd}
                  tool={tool}
                  cursor={cursor}
                  locked={locked}
                  xAxisLabel={
                    pointCoordinates && raw ? 'CCD 点位' : curves.some((curve) => curve.data.some((item) => item.point.wavelength_nm != null))
                      ? '波长 (nm)'
                      : raw
                        ? 'CCD 点位'
                        : '步长 / 点位'
                  }
                  yAxisLabel={
                    mode === 'peak' ? '峰值' : mode === 'back' ? '背景' : mode === 'value' ? '结果值' : active.intensity_mode==='legacy_2_0_2'&&!frameVisible ? '旧版积分强度' : '强度 (ADC)'
                  }
                  onCursor={setCursor}
                  onPointerPresence={follow.plotPresence}
                  onToggleLock={() => setLocked((value) => !value)}
                  onPan={(dx, dy) => {
                    setPanX((value) => Math.max(-1, Math.min(1, value - dx * 2)))
                    setPanY((value) => Math.max(-1, Math.min(1, value + dy * 2)))
                  }}
                  onBoxSelect={boxSelect}
                  onZoomY={factor => zoomView('y', factor)} markers={markers} onSpectrumContext={openSpectrumMenu}
                />
          </LegacySpectrumSurface>
            </div>
            {following && <SpectrumPointPanel target={{ token, recordId: active.id, ccd: active.ccd?.position ?? ccd,
              sampleName: active.sample_name ?? '', bandName: active.band_name ?? '', onToast, canOutput: canExport }}
              follow={follow} onClose={() => setFollowPoint(false)} />}
          </div>
          </>}
        </section>
      </div>
    </LegacyViewingDesk>
    {operation&&<ViewerDialog title={{files:'选择谱文件',reference:'参考校正',frames:'原始帧',print:'显示与打印',evaporation:'蒸发帧统计'}[operation]} onClose={()=>setOperation(null)}>
      {operation==='files'&&<div className="viewer-dialog-fields">
        <label>谱文件<select aria-label="当前谱文件" value={currentGroup} disabled={busy||recordLocked} onChange={event=>{
          if(event.target.value===currentGroup)return
          multiTableScroll.current=0;setDetails({});setSelectedId(null);setPriorityId(null);setPageRecords([]);setCursor(null);setLocked(false);setOverlayIds([]);setMultiMode('auto');setFileGroup(event.target.value);setCcd(0);setLine(0)
          setOperation(null)
        }}>
          {requestedGroupMissing ? <option value="" disabled>{busy ? '正在读取谱图' : '所选谱图已不可用'}</option>
            : !groups.length && <option value="">尚无谱文件</option>}
          {groups.map(item=><option key={item.key} value={item.key}>{item.task_name||fileNames[item.source_sha256]||item.source_filename||`${item.format.toUpperCase()} · ${item.source_sha256.slice(0,10)}`} · {item.record_count} 条</option>)}
        </select></label>
        <label>来源<select aria-label="谱图来源" value={sourceKind} disabled={busy} onChange={event=>setSourceKind(event.target.value)}>
          <option value="all">全部</option><option value="raw">原始谱图</option><option value="result">旧结果</option><option value="sample">新采集样品</option>
        </select></label>
        <label>检索<input aria-label="检索谱图" value={search} onChange={event=>setSearch(event.target.value)}/></label>
        <label>转角<input aria-label="检索转角" value={angleFilter==='all'?'':angleFilter} onChange={event=>setAngleFilter(event.target.value||'all')}/></label>
      </div>}
      {operation==='reference'&&<>
        <div className="viewer-dialog-fields"><label>参考校正偏移<EmptyableNumberInput aria-label="参考校正偏移" step="0.001" value={referenceShift} onValueChange={value => {
          setReferenceShift(value)
          if (calibration) setCalibrations(prior => ({ ...prior, [calibrationKey]: { ...calibration, shift: undefined } }))
        }}/></label></div>
        <button className="secondary-button" onClick={()=>resetView(true)}>还原校正与视图</button>
      </>}
      {operation==='frames'&&<>
        <div className="viewer-dialog-fields"><label>阶段<select aria-label="原始帧阶段" value={framePhase} onChange={event=>{setFramePhase(event.target.value as typeof framePhase);setFrameNumber(1)}}><option value="burn">燃烧帧</option><option value="dark">暗帧</option></select></label>
          <label>帧序号（1起）<EmptyableNumberInput aria-label="原始帧序号" min={1} max={Math.max(1, availableFrames)} step={1}
            disabled={!availableFrames || busy} value={frameNumber} onValueChange={setFrameNumber}/></label></div>
        <div className="viewer-dialog-actions"><button className="primary-button" disabled={busy||!validFrameNumber||selected?.available?.[framePhase]===false} onClick={async()=>{if(await loadFrame())setOperation(null)}}>显示原始帧</button>
          <button className="secondary-button" disabled={busy} onClick={()=>void loadDetails().then(()=>setOperation(null))}>返回区间均值</button></div>
      </>}
      {operation==='print'&&<>
        <div className="viewer-dialog-fields">
          {raw&&<label>屏幕比例档案<select aria-label="屏幕比例档案" value={screenProfileId} onChange={event=>setScreenProfileId(Number(event.target.value))}>{screenProfiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name} · {profile.screen_width_mm} mm / {profile.screen_resolution_px} px</option>)}</select></label>}
          <label>打印范围<select aria-label="CCD 打印范围" value={printScope} disabled={!raw} onChange={event=>setPrintScope(event.target.value as typeof printScope)}><option value="visible">当前图像</option><option value="ccd">当前 CCD</option></select></label>
          <label>打印内容<select aria-label="CCD 打印内容" value={printLayers.join(',')} disabled={!raw} onChange={event=>setPrintLayers(event.target.value.split(',') as typeof printLayers)}><option value="curve">峰形</option><option value="grayscale">灰度谱带</option><option value="grayscale,curve">灰度与峰形</option></select></label>
          <label>打印比例<select aria-label="CCD 打印比例" value={printScale} disabled={!raw} onChange={event=>setPrintScale(event.target.value as typeof printScale)}><option value="fit_long">纸张宽边</option><option value="fit_short">纸张窄边</option><option value="ccd_10x">十倍 CCD</option></select></label>
          <label>纸型<select aria-label="CCD 打印纸型" value={printPaper} onChange={event=>setPrintPaper(event.target.value as typeof printPaper)}><option>A4</option><option>A3</option><option>Letter</option></select></label>
        </div>
        <button className="primary-button" disabled={!active||busy} onClick={()=>void printVisible()}>保存谱图 PDF</button>
      </>}
      {operation==='evaporation'&&active&&<EvaporationFrameStatistics token={token} taskId={active.task_id} legacyId={active.kind==='raw'?Number(active.id.split(':')[1]):undefined} initialCcd={Number(active.ccd?.index??ccd)}/>}
    </ViewerDialog>}
  </div>
}
