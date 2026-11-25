import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { ChevronLeft, ChevronRight, Pencil, Trash2 } from 'lucide-react'
import type { SampleQueueItem } from '../../api/sampleQueues'
import {
  columnMajorPosition, commitSampleGridMove, incrementalSampleFill, isSampleComposition, isSampleFillKey,
  MAX_SAMPLE_QUEUE_ITEMS as MAX_ITEMS, SAMPLE_QUEUE_ROWS as ROWS, sampleTypingKey,
} from '../../components/sampleGridFlow'
import { resolveSampleSemanticRole, sampleRoleLabels } from '../../components/sampleSemanticRole'
import { samplePasteCells, useSampleGrid, type SampleCell } from '../../components/useSampleGrid'

const ROW_HEADING_WIDTH = 28
const CHARACTER_WIDTH = 7.2

export function SampleNumberTable({ items, nameLength, onDelete, onCommitCell, onPaste, onEditingChange, busy, initialSelectedId, onSelectionChange, methodStandardNames }: {
  items: SampleQueueItem[]
  nameLength: 10 | 12 | 20
  onDelete: (id: number) => Promise<void>
  onCommitCell: (position: number, name: string) => Promise<void>
  onPaste: (changes: Array<{ position: number; name: string }>, action: 'paste' | 'fill') => Promise<void>
  onEditingChange: (editing: boolean) => void
  busy: boolean
  initialSelectedId?: number
  onSelectionChange?: (id:number|null)=>void
  methodStandardNames: ReadonlySet<string>
}) {
  const [pageAnchor, setPageAnchor] = useState(Math.max(0,items.findIndex(item=>item.id===initialSelectedId)))
  const [columns, setColumns] = useState(1)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [selection, setSelection] = useState({ id: initialSelectedId ?? null, position: 0 })
  const [deleting, setDeleting] = useState(false)
  const [editingPosition, setEditingPosition] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [editError, setEditError] = useState('')
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const composing = useRef(false)
  const selectDraft = useRef(true)
  const pendingFocus = useRef<number | 'editor' | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Consolas digits/letters occupy 0.6em; wider names wrap in a fixed-height cell.
  const cellWidth = nameLength * CHARACTER_WIDTH + 12
  useLayoutEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const resize = () => setColumns(Math.max(1, Math.floor((element.clientWidth - ROW_HEADING_WIDTH) / cellWidth)))
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [cellWidth])
  const pageSize = ROWS * columns
  const currentPage = Math.floor((editingPosition ?? pageAnchor) / pageSize)
  const pages = Math.max(currentPage + 1, Math.ceil(items.length / pageSize))
  const start = currentPage * pageSize
  const positionFor = (cell: SampleCell) => columnMajorPosition(cell, start, ROWS)
  const selectedPosition = selection.id === null ? selection.position : items.findIndex(item => item.id === selection.id)
  const selectedOffset = selectedPosition >= start && selectedPosition < start + pageSize ? selectedPosition - start : 0
  const selected = items[start + selectedOffset]
  const locked = busy || deleting || saving || editingPosition !== null
  const applyCells = async (matrix: string[][], origin: SampleCell, action: 'paste' | 'fill') => {
    const position = positionFor(origin)
    const changes = action === 'paste' && matrix.every(row => row.length === 1)
      ? matrix.map(([name], offset) => ({ position: position + offset, name }))
      : samplePasteCells(matrix, origin, ROWS, columns).map(cell => ({ position: positionFor(cell), name: cell.name }))
    if (changes.some(cell => cell.position >= MAX_ITEMS)) throw new Error('队列最多可录入 1000 条样号。')
    setEditError('')
    scrollRef.current?.focus({ preventScroll: true })
    await onPaste(changes, action)
  }
  const grid = useSampleGrid({
    active: { row: selectedOffset % ROWS, column: Math.floor(selectedOffset / ROWS) },
    disabled: locked,
    canSelect: cell => cell.row >= 0 && cell.row < ROWS && cell.column >= 0 && cell.column < columns && positionFor(cell) < MAX_ITEMS,
    onActivate: cell => {
      const position = positionFor(cell)
      setSelection({ id: items[position]?.id ?? null, position })
      setEditError('')
    },
    read: cell => items[positionFor(cell)]?.pre_name ?? '',
    onPaste: (matrix, origin) => applyCells(matrix, origin, 'paste'),
    onFill: (matrix, origin) => applyCells(matrix, origin, 'fill'),
    onError: setEditError,
  })
  useEffect(()=>onSelectionChange?.(selected?.id??null),[selected?.id,onSelectionChange])
  useLayoutEffect(() => {
    if (editingPosition === null) return
    const input = inputRef.current
    input?.focus()
    if (selectDraft.current) input?.select()
    else if (input) input.setSelectionRange(input.value.length, input.value.length)
  }, [editingPosition, start, columns])
  useLayoutEffect(() => {
    const target = pendingFocus.current
    if (target === null || saving || busy || deleting) return
    pendingFocus.current = null
    if (target === 'editor') inputRef.current?.focus()
    else scrollRef.current?.querySelector<HTMLButtonElement>(`[data-sample-grid-position="${target}"]`)?.focus()
  })

  const beginEdit = (position: number, typed?: string) => {
    const item = items[position]
    if (locked || position >= MAX_ITEMS || item?.spectrum_hash) return
    setSelection({ id: item?.id ?? null, position })
    grid.clearRange()
    composing.current = false
    selectDraft.current = !typed
    setDraftName(typed || item?.pre_name || '')
    setEditError('')
    setEditingPosition(position)
    onEditingChange(true)
  }
  const finishEdit = (position: number) => {
    pendingFocus.current = position
    setPageAnchor(position)
    setSelection({ id: null, position })
    setEditingPosition(null)
    setEditError('')
    composing.current = false
    grid.clearRange()
    onEditingChange(false)
  }
  const saveEdit = async (direction?: -1 | 1) => {
    if (editingPosition === null || savingRef.current || composing.current) return
    const position = editingPosition
    const item = items[position]
    const commit = async () => {
      if (item ? draftName !== item.pre_name : draftName.trim()) await onCommitCell(position, draftName)
    }
    savingRef.current = true
    setSaving(true)
    setEditError('')
    try {
      if (direction === undefined) {
        await commit()
        finishEdit(position)
      } else {
        const target = await commitSampleGridMove(position, direction, MAX_ITEMS, commit)
        finishEdit(target ?? position)
      }
    } catch (error) {
      pendingFocus.current = 'editor'
      setEditError(error instanceof Error ? error.message : '样号修改失败')
    }
    finally { savingRef.current = false; setSaving(false) }
  }

  const fillDown = async (fromEditor = false) => {
    if (busy || deleting || savingRef.current) return
    const positions = fromEditor && editingPosition !== null ? [editingPosition] : grid.selectedCells().map(positionFor)
    setEditError('')
    try {
      const changes = incrementalSampleFill(positions, MAX_ITEMS,
        position => fromEditor ? draftName : items[position]?.pre_name ?? '', items)
      savingRef.current = true
      setSaving(true)
      await onPaste(changes, 'fill')
    } catch (error) {
      setEditError(error instanceof Error ? error.message : '填充样号失败，请重试。')
    } finally {
      if (savingRef.current) pendingFocus.current = fromEditor ? 'editor' : start + selectedOffset
      savingRef.current = false
      setSaving(false)
    }
  }

  const turnPage = (next: number) => {
    setPageAnchor(next * pageSize)
    setSelection({ id: null, position: next * pageSize })
    grid.clearRange()
    setEditError('')
  }

  return <div className="sample-number-sheet" data-name-length={nameLength} data-rows={ROWS}
    data-columns={columns} data-page-size={pageSize}>
    <div className="sample-number-toolbar">
      <nav aria-label="样号分页">
        <span>第 {currentPage + 1} / {pages} 页 · 共 {items.length} 项</span>
        <button className="icon-button compact" aria-label="上一页样号" disabled={currentPage === 0 || locked}
          onClick={() => turnPage(currentPage - 1)}><ChevronLeft size={15} /></button>
        <button className="icon-button compact" aria-label="下一页样号" disabled={currentPage + 1 >= pages || locked}
          onClick={() => turnPage(currentPage + 1)}><ChevronRight size={15} /></button>
      </nav>
    </div>
    <div ref={scrollRef} className="sample-number-scroll" tabIndex={0} role="region" aria-label="样号表格" {...grid.events}
      onKeyDown={event => {
        if (!locked && !event.defaultPrevented && !isSampleComposition(event.nativeEvent) && isSampleFillKey(event.nativeEvent)) {
          event.preventDefault()
          void fillDown()
        } else grid.events.onKeyDown?.(event)
      }}>
      <table className="sample-number-table" aria-label="样号按列排列表格"
        style={{ minWidth: ROW_HEADING_WIDTH + cellWidth }}>
        <colgroup><col className="sample-number-row-heading" />{Array.from({ length: columns }, (_, col) => <col key={col} />)}</colgroup>
        <thead><tr><th scope="col">行</th>{Array.from({ length: columns }, (_, col) =>
          <th scope="col" key={col}>{start + col * ROWS + 1}–{start + (col + 1) * ROWS}</th>)}</tr></thead>
        <tbody>{Array.from({ length: ROWS }, (_, row) => <tr key={row}>
          <th scope="row">{row + 1}</th>
          {Array.from({ length: columns }, (_, col) => {
            const cell = { row, column: col }
            const position = positionFor(cell)
            const item = items[position]
            const fill = grid.fillHandle(cell)
            const role = resolveSampleSemanticRole({ name: item?.pre_name ?? '', methodStandardNames })
            return <td key={col} data-sample-fill-preview={grid.isFilling(cell) || undefined}>{editingPosition === position ? <input ref={inputRef}
              className="sample-number-edit" aria-label={`修改样号 ${position + 1}`} value={draftName}
              data-sample-role={role} data-sample-active="true"
              aria-invalid={!!editError} aria-describedby={editError ? 'sample-name-edit-error' : undefined}
              onCompositionStart={() => { composing.current = true }} onCompositionEnd={() => { composing.current = false }}
              disabled={saving} onChange={event => setDraftName(event.target.value)}
              onKeyDown={event => {
                if (isSampleComposition(event.nativeEvent, composing.current)) {
                  if (event.key === 'Enter' || event.key === 'Tab' || isSampleFillKey(event.nativeEvent)) event.preventDefault()
                  return
                }
                if (event.key === 'Enter' || event.key === 'Tab') {
                  event.preventDefault()
                  void saveEdit(event.key === 'Tab' && event.shiftKey ? -1 : 1)
                } else if (event.key === 'Escape' && !savingRef.current) {
                  event.preventDefault()
                  finishEdit(position)
                } else if (isSampleFillKey(event.nativeEvent)) {
                  event.preventDefault()
                  void fillDown(true)
                }
            }} /> : position < MAX_ITEMS ? <><button type="button" className="sample-number-cell" {...grid.cellProps(cell)}
              data-sample-id={item?.id} data-sample-position={item ? position + 1 : undefined}
              data-sample-grid-position={position} data-sample-role={role}
              aria-label={item ? `样品 ${position + 1}：${item.pre_name || '空样'}` : `样号位置 ${position + 1}（空位置）`}
              title={item ? `第 ${position + 1} 项：${item.pre_name || '空样'}${role === 'neutral' ? '' : ` · ${sampleRoleLabels[role]}`}` : undefined}
              disabled={locked}
              aria-pressed={grid.isSelected(cell)}
              onDoubleClick={() => beginEdit(position)} onKeyDown={event => {
                const typed = sampleTypingKey(event.nativeEvent)
                if (typed === '') flushSync(() => beginEdit(position, typed))
                else if (typed !== undefined || event.key === 'F2' || event.key === 'Enter') {
                  event.preventDefault()
                  beginEdit(position, typed)
                }
              }}>
              {item && <strong>{item.pre_name || '空样'}</strong>}
            </button>{fill && <button type="button" className="sample-fill-handle" tabIndex={-1}
              title="拖动填充样号" aria-label="拖动填充样号" {...fill} />}</> : <span className="sample-number-empty" aria-label="空位置" />}</td>
          })}
        </tr>)}</tbody>
      </table>
    </div>
    <section className="sample-number-detail" aria-label="选中样品详情">
      {selected && (
        <dl>
          <div><dt>预录名称</dt><dd>{selected.pre_name || '空样'}</dd></div>
          <div><dt>重复次数</dt><dd>{selected.repeats || '空样'}</dd></div>
          <div><dt>展开谱带</dt><dd>{selected.expanded_bands}</dd></div>
          <div><dt>采集后名称</dt><dd>{selected.post_name ?? '待采集'}</dd></div>
        </dl>
      )}
      {(selected || editingPosition !== null) ? <div className="sample-number-detail-actions">
          {editingPosition !== null ? <>
            <button className="primary-button" disabled={saving} onClick={() => void saveEdit()}>{saving ? '正在保存…' : '保存样号'}</button>
            <button className="secondary-button" disabled={saving} onClick={() => finishEdit(editingPosition)}>取消修改</button>
          </> : selected && <button className="secondary-button" disabled={locked || !!selected.spectrum_hash}
            onClick={() => beginEdit(start + selectedOffset)}><Pencil size={14} />修改样号</button>}
          {selected && <button className="icon-button compact danger" title="删除样品"
          aria-label={`删除样品 ${selected.position + 1}`} disabled={locked}
          onClick={async () => {
            if (deleting) return
            setDeleting(true)
            try { await onDelete(selected.id) } finally { setDeleting(false) }
          }}><Trash2 size={14} /></button>}
        </div> : <p>可在上方录入样号，或选中表格中的位置后录入或粘贴。</p>}
    </section>
    {editError && <p className="sample-number-edit-error" id="sample-name-edit-error" role="alert">{editError}</p>}
    {selected?.spectrum_hash && <small>已关联采集的样品请通过采集后命名修改名称。</small>}
  </div>
}
