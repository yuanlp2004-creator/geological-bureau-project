import { convertLineUnit } from '../../components/analysisUnits'
import { confirmAction } from '../../platform/dialogs'
import { AlertTriangle } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type LineDetectability,
  type MethodConditions,
  type MethodLineCollection,
  type MethodOptions,
  type SpectralLine,
  type SpectralLineInput,
  type SpectralLineOptions
} from '../../api'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { SpectralLineEditor } from './SpectralLineEditor'
import { SpectralLineList } from './SpectralLineList'
import { SpectralCcdCoverage } from './SpectralCcdCoverage'
import { defaultLine, lineToInput, methodExposureMode } from './spectralLineDraft'
import { buildCcdCoverageSummary, defaultSpectralLineFilters, filterSpectralLines, locateSpectralLine } from './spectralLineFilters'
import { availableId } from '../../stores/workbenchRestore'
import { lineFormIsDirty } from '../../layout/navigationGuard'

export function SpectralLinesPanel({
  methodId,
  conditions,
  methodOptions,
  initialLineId,
  onSelectedLineChange,
  onDirtyChange,
  token,
  canWrite,
  onChanged,
  onToast
}: {
  methodId: number
  conditions: MethodConditions | null
  methodOptions: MethodOptions | null
  initialLineId?: string | null
  onSelectedLineChange?: (lineId: string | null) => void
  onDirtyChange?: (dirty: boolean) => void
  token: string
  canWrite: boolean
  onChanged: () => Promise<void>
  onToast: (message: string) => void
}) {
  const [listCollapsed, setListCollapsed] = useState(false)
  const [collection, setCollection] = useState<MethodLineCollection | null>(null)
  const [options, setOptions] = useState<SpectralLineOptions | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<SpectralLineInput>(defaultLine)
  const [creating, setCreating] = useState(false)
  const [createBaseline, setCreateBaseline] = useState<SpectralLineInput | null>(null)
  const [detectability, setDetectability] = useState<LineDetectability | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState(defaultSpectralLineFilters)
  const [batchSelectedIds, setBatchSelectedIds] = useState<ReadonlySet<string>>(() => new Set())
  const [location, setLocation] = useState<{ id: string; focus: boolean } | null>(null)

  const workbench = useRef<HTMLDivElement>(null)
  const linesRequest = useRef(0)
  const initialSelection = useRef(initialLineId)
  const lineSelection = useRef<string | null>(null)
  const currentMethod = useRef({ methodId, token })
  currentMethod.current = { methodId, token }
  useLayoutEffect(() => {
    lineSelection.current = selectedId
  }, [selectedId])
  useLayoutEffect(() => () => { linesRequest.current++ }, [methodId, token])
  const loadLines = useCallback(async (preserveEditor = false) => {
    if (currentMethod.current.methodId !== methodId || currentMethod.current.token !== token) return
    const requestId = ++linesRequest.current
    const isCurrent = () =>
      requestId === linesRequest.current &&
      currentMethod.current.methodId === methodId &&
      currentMethod.current.token === token
    try {
      const [nextCollection, nextOptions] = await Promise.all([
        api.methodLines(token, methodId),
        api.spectralLineOptions(token)
      ])
      if (!isCurrent()) return
      const nextId = availableId(nextCollection.lines.map(line => line.id), initialSelection.current ?? lineSelection.current)
      const nextLine = nextCollection.lines.find(line => line.id === nextId)
      initialSelection.current = undefined
      setCollection(nextCollection)
      setOptions(nextOptions)
      setError(null)
      if (preserveEditor && (!lineSelection.current || nextLine?.id === lineSelection.current)) return
      setCreating(false)
      setSelectedId(nextId ?? null)
      setDraft(nextLine ? lineToInput(nextLine) : defaultLine())
      setDetectability(nextLine?.detectability ?? null)
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : '无法读取谱线')
    }
  }, [methodId, token])

  useEffect(() => {
    setCollection(null)
    void loadLines()
  }, [loadLines])
  useEffect(() => {
    setCreating(false)
    setSelectedId(null)
    setBusy(false)
    setFilters(defaultSpectralLineFilters)
    setBatchSelectedIds(new Set())
    setLocation(null)
    saving.current = null
  }, [methodId, token])

  useEffect(() => {
    if (!collection) return
    const lineIds = new Set(collection.lines.map(line => line.id))
    setBatchSelectedIds(previous => {
      const available = new Set([...previous].filter(id => lineIds.has(id)))
      return available.size === previous.size ? previous : available
    })
  }, [collection])

  const selected = collection?.lines.find((line) => line.id === selectedId) ?? null
  const visibleLines = useMemo(() => filterSpectralLines(collection?.lines ?? [], filters), [collection, filters])
  const ccdLayout = methodOptions?.ccd_layouts.find(layout =>
    String(layout.id) === String(conditions?.ccd_layout_id) || layout.name === conditions?.ccd_layout_id)
  const calibration = methodOptions?.dispersion_calibrations.find(item =>
    item.ccd_layout_id === ccdLayout?.id && (
      String(item.id) === String(conditions?.dispersion_calibration_id) || item.name === conditions?.dispersion_calibration_id
    ))
  const coverage = useMemo(() => conditions && collection
    ? buildCcdCoverageSummary({ lines: collection.lines, conditions, calibration, ccdLayout }) : null,
  [collection, conditions, calibration, ccdLayout])
  const savedInput = useMemo(() => selected ? lineToInput(selected) : null, [selected])
  const dirty = lineFormIsDirty(draft, creating ? createBaseline : savedInput)
  useLayoutEffect(() => {
    if (collection) onSelectedLineChange?.(selected?.id ?? null)
  }, [collection, selected?.id, onSelectedLineChange])
  useLayoutEffect(() => {
    onDirtyChange?.(dirty)
    return () => onDirtyChange?.(false)
  }, [dirty, onDirtyChange])

  useEffect(() => {
    if (!creating && (!savedInput || (
      savedInput.wavelength_nm === draft.wavelength_nm &&
      savedInput.actual_wavelength_nm === draft.actual_wavelength_nm &&
      savedInput.scan_width_points === draft.scan_width_points
    ))) {
      setDetectability(selected?.detectability ?? null)
      return
    }
    setDetectability(null)
    if (!Number.isFinite(draft.wavelength_nm)) return
    let active = true
    const timer = window.setTimeout(() => {
      void api
        .detectLine(token, methodId, {
          line_id: creating ? undefined : selected?.id,
          wavelength_nm: draft.wavelength_nm,
          actual_wavelength_nm: draft.actual_wavelength_nm,
          scan_width_points: draft.scan_width_points
        })
        .then((result) => {
          if (active) setDetectability(result)
        })
        .catch(() => {
          if (active) setDetectability(null)
        })
    }, 220)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [creating, savedInput, selected, draft.actual_wavelength_nm, draft.scan_width_points, draft.wavelength_nm, methodId, token])

  const updateDraft = <K extends keyof SpectralLineInput>(key: K, value: SpectralLineInput[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }))
  const edit = (line: SpectralLine) => {
    if (line.id === selectedId && !creating) return
    setCreating(false)
    setSelectedId(line.id)
    setDraft(lineToInput(line))
    setDetectability(line.detectability ?? null)
  }
  const revealLine = (id: string, focus: boolean) => {
    const target = locateSpectralLine(collection?.lines ?? [], id, filters)
    if (!target) return
    setFilters(target.filters)
    setLocation({ id, focus })
    return target.line
  }
  const locateFromOverview = (id: string) => {
    const line = revealLine(id, true)
    if (!line) return
    setListCollapsed(false)
    // 输入框里的无效原文也属于草稿，即使尚未写入 draft。
    const invalidInput = workbench.current?.querySelector(
      '.spectral-editor-surface [data-numeric-input][aria-invalid="true"]:invalid:not(:disabled)'
    )
    if (!busy && !creating && !dirty && !invalidInput) edit(line)
  }
  const toggleBatchSelection = (id: string) => setBatchSelectedIds(previous => {
    const next = new Set(previous)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const beginCreate = () => {
    const next = convertLineUnit(defaultLine(), collection?.lines.find((line) => line.line_type === 'baseline')?.unit ?? 'ug/g')
    setCreating(true)
    setSelectedId(null)
    setCreateBaseline(next)
    setDraft(next)
    setDetectability(null)
  }

  const mutate = async (action: () => Promise<unknown>, success: string, preserveEditor = false) => {
    setBusy(true)
    try {
      await action()
      await Promise.all([loadLines(preserveEditor), onChanged()])
      onToast(success)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '谱线操作失败')
    } finally {
      setBusy(false)
    }
  }

  const saving = useRef<object | null>(null)
  const save = async () => {
    if (saving.current || !canWrite || selected?.line_type === 'baseline') return
    if (!reportInvalidNumericInput(workbench.current?.querySelector('.spectral-editor-surface')))
      return onToast('请先修正谱线中的无效数值')
    const creatingNow = creating
    const requestEpoch = linesRequest.current
    const valid = () =>
      currentMethod.current.methodId === methodId &&
      currentMethod.current.token === token &&
      requestEpoch === linesRequest.current
    const submission = {}
    saving.current = submission
    setBusy(true)
    try {
      // 背景内标自动引用唯一参考基线；已有引用和其他隐藏值保持原样。
      const input = draft.internal_standard_mode === 'background' && !draft.background_line_id
        ? { ...draft, background_line_id: collection?.lines.find((line) => line.line_type === 'baseline' && line.enabled)?.id ?? null }
        : draft
      const result = creatingNow
        ? await api.createLine(token, methodId, input)
        : selectedId
          ? await api.updateLine(token, methodId, selectedId, input)
          : null
      if (!result) throw new Error('请选择谱线')
      if (!valid()) return
      const revision = result.version
      if (!revision) throw new Error('保存已完成，请刷新读取方法版本后继续编辑')
      const changedId = result.changed_line_id ?? selectedId
      const previousDetection = new Map(collection?.lines.map(line => [line.id, line.detectability]))
      const next = { method_id: methodId, version: revision.version, state: revision.state,
        lines: revision.lines.map(line => ({ ...line, detectability: line.detectability ?? (
          line.id === changedId ? detectability ?? undefined : previousDetection.get(line.id)
        ) })),
        exposure_mode: methodExposureMode(revision.conditions, revision.lines), frame_count: revision.conditions.frame_count }
      setCollection(next)
      const saved = next.lines.find(line => line.id === changedId)
      if (saved) {
        setSelectedId(saved.id)
        setDraft(lineToInput(saved))
      }
      setCreating(false)
      setError(null)
      onToast(creatingNow ? '谱线已添加，请保存方法使修改生效' : '谱线已更新，请保存方法使修改生效')
      await onChanged()
    } catch (cause) {
      if (valid()) setError(cause instanceof Error ? cause.message : '谱线保存失败')
    } finally {
      if (saving.current === submission) saving.current = null
      if (valid()) setBusy(false)
    }
  }

  const toggle = (line: SpectralLine) => {
    const input = lineToInput(line)
    input.enabled = !input.enabled
    void mutate(() => api.updateLine(token, methodId, line.id, input), input.enabled ? '谱线已启用' : '谱线已停用')
  }

  const remove = async (line: SpectralLine) => {
    if (!(await confirmAction(`确认删除 ${line.element} ${line.wavelength_nm.toFixed(4)} nm？`))) return
    void mutate(() => api.deleteLine(token, methodId, line.id), '谱线已删除')
  }

  const reorder = (ordered: SpectralLine[], success: string) => {
    if (selectedId) revealLine(selectedId, false)
    void mutate(
      () =>
        api.reorderLines(
          token,
          methodId,
          ordered.map((line) => line.id)
        ),
      success,
      true
    )
  }

  const movable = collection?.lines.filter((line) => line.line_type !== 'baseline') ?? []
  const sortBy = (key: 'element' | 'wavelength_nm') =>
    reorder(
      [...movable].sort((left, right) =>
        key === 'element'
          ? left.element.localeCompare(right.element) || left.wavelength_nm - right.wavelength_nm
          : left.wavelength_nm - right.wavelength_nm
      ),
      key === 'element' ? '已按元素排序' : '已按波长排序'
    )
  const move = (line: SpectralLine, offset: number) => {
    const index = movable.findIndex((item) => item.id === line.id)
    const target = index + offset
    if (index < 0 || target < 0 || target >= movable.length) return
    const ordered = [...movable]
      ;[ordered[index], ordered[target]] = [ordered[target], ordered[index]]
    reorder(ordered, '谱线顺序已更新')
  }

  const setLineType = (lineType: SpectralLineInput['line_type']) =>
    setDraft((previous) => ({
      ...previous,
      line_type: lineType,
      standard_points:
        lineType === 'analysis'
          ? previous.standard_points.length >= 4
            ? previous.standard_points
            : defaultLine().standard_points
          : [],
      internal_standard_mode: lineType === 'analysis' ? previous.internal_standard_mode : 'none',
      internal_standard_line_id: lineType === 'analysis' ? previous.internal_standard_line_id : null
    }))

  const backgroundLines = collection?.lines.filter((line) => line.line_type === 'baseline' && line.enabled) ?? []
  const alignmentLines =
    collection?.lines.filter(
      (line) => ['positioning', 'internal_standard'].includes(line.line_type) && line.enabled && line.id !== selectedId
    ) ?? []
  const internalLines =
    collection?.lines.filter(
      (line) => line.line_type === 'internal_standard' && line.enabled && line.id !== selectedId
    ) ?? []
  const isBaseline = !creating && selected?.line_type === 'baseline'

  return (
    <div ref={workbench} className={`spectral-workbench ${listCollapsed ? 'list-collapsed' : ''}`} data-testid="spectral-lines-panel">
      {error && (
        <div className="auth-error">
          <AlertTriangle size={15} />
          {error}
        </div>
      )}
      {coverage && <SpectralCcdCoverage coverage={coverage} onLocate={locateFromOverview} />}
      <SpectralLineList
        listCollapsed={listCollapsed}
        collection={collection}
        canWrite={canWrite}
        beginCreate={beginCreate}
        busy={busy}
        sortBy={sortBy}
        movable={movable}
        selectedId={selectedId}
        creating={creating}
        edit={edit}
        visibleLines={visibleLines}
        filters={filters}
        setFilters={setFilters}
        ccdLayout={ccdLayout}
        batchSelectedIds={batchSelectedIds}
        toggleBatchSelection={toggleBatchSelection}
        clearBatchSelection={() => setBatchSelectedIds(new Set())}
        location={location}
        onLocate={locateFromOverview}
      />

      <SpectralLineEditor
        exposureEnabled={collection?.exposure_mode === 'line_interval'}
        frameCount={collection?.frame_count ?? 20}
        listCollapsed={listCollapsed}
        setListCollapsed={setListCollapsed}
        creating={creating}
        selected={selected}
        isBaseline={isBaseline}
        canWrite={canWrite}
        move={move}
        busy={busy}
        movable={movable}
        toggle={toggle}
        remove={remove}
        draft={draft}
        setLineType={setLineType}
        updateDraft={updateDraft}
        options={options}
        setDraft={setDraft}
        detectability={detectability}
        backgroundLines={backgroundLines}
        alignmentLines={alignmentLines}
        internalLines={internalLines}
        save={save}
      />
    </div>
  )
}
