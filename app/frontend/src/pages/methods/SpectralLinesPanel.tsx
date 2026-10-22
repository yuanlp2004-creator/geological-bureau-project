import { convertLineUnit } from '../../components/analysisUnits'
import { confirmAction } from '../../platform/dialogs'
import { AlertTriangle } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  type LineDetectability,
  type MethodLineCollection,
  type SpectralLine,
  type SpectralLineInput,
  type SpectralLineOptions
} from '../../api'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { SpectralLineEditor } from './SpectralLineEditor'
import { SpectralLineList } from './SpectralLineList'
import { defaultLine, lineToInput, methodExposureMode } from './spectralLineDraft'

export function SpectralLinesPanel({
  methodId,
  token,
  canWrite,
  onChanged,
  onToast
}: {
  methodId: number
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
  const [detectability, setDetectability] = useState<LineDetectability | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const linesRequest = useRef(0)
  const currentMethod = useRef({ methodId, token })
  currentMethod.current = { methodId, token }
  const loadLines = useCallback(async () => {
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
      setCollection(nextCollection)
      setOptions(nextOptions)
      setSelectedId((previous) =>
        nextCollection.lines.some((line) => line.id === previous) ? previous : (nextCollection.lines[0]?.id ?? null)
      )
      setError(null)
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof Error ? cause.message : '无法读取谱线')
    }
  }, [methodId, token])

  useEffect(() => {
    setCollection(null)
    void loadLines()
    return () => {
      linesRequest.current++
    }
  }, [loadLines])
  useEffect(() => {
    setCreating(false)
    setSelectedId(null)
    setBusy(false)
    saving.current = null
  }, [methodId, token])

  const selected = collection?.lines.find((line) => line.id === selectedId) ?? null
  useEffect(() => {
    if (creating || !selected) return
    setDraft(lineToInput(selected))
    setDetectability(selected.detectability ?? null)
  }, [creating, selected])

  useEffect(() => {
    if (!Number.isFinite(draft.wavelength_nm)) return
    let active = true
    const timer = window.setTimeout(() => {
      void api
        .detectLine(token, methodId, {
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
  }, [draft.actual_wavelength_nm, draft.scan_width_points, draft.wavelength_nm, methodId, token])

  const updateDraft = <K extends keyof SpectralLineInput>(key: K, value: SpectralLineInput[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }))
  const edit = (line: SpectralLine) => {
    setCreating(false)
    setSelectedId(line.id)
    setDraft(lineToInput(line))
    setDetectability(line.detectability ?? null)
  }
  const beginCreate = () => {
    setCreating(true)
    setSelectedId(null)
    setDraft(convertLineUnit(defaultLine(), collection?.lines.find((line) => line.line_type === 'baseline')?.unit ?? 'ug/g'))
    setDetectability(null)
  }

  const mutate = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await action()
      await Promise.all([loadLines(), onChanged()])
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
    if (!reportInvalidNumericInput(document.querySelector('.spectral-editor-surface')))
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
      const next = { method_id: methodId, version: revision.version, state: revision.state,
        lines: revision.lines.map((line) => line.id === (result.changed_line_id ?? selectedId)
          ? { ...line, detectability: detectability ?? undefined } : line),
        exposure_mode: methodExposureMode(revision.conditions, revision.lines), frame_count: revision.conditions.frame_count }
      setCollection(next)
      const saved = next.lines.find((line) => line.id === (result.changed_line_id ?? selectedId))
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
    void mutate(
      () =>
        api.reorderLines(
          token,
          methodId,
          ordered.map((line) => line.id)
        ),
      success
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
    <div className={`spectral-workbench ${listCollapsed ? 'list-collapsed' : ''}`} data-testid="spectral-lines-panel">
      {error && (
        <div className="auth-error">
          <AlertTriangle size={15} />
          {error}
        </div>
      )}
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
