import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Pencil, Trash2 } from 'lucide-react'
import type { SampleQueueItem } from '../../api/sampleQueues'

const ROWS = 20
const ROW_HEADING_WIDTH = 28
const CHARACTER_WIDTH = 7.2

export function SampleNumberTable({ items, nameLength, onDelete, onEdit, onEditingChange, busy }: {
  items: SampleQueueItem[]
  nameLength: 10 | 12 | 20
  onDelete: (id: number) => Promise<void>
  onEdit: (id: number, name: string) => Promise<void>
  onEditingChange: (editing: boolean) => void
  busy: boolean
}) {
  const [pageAnchor, setPageAnchor] = useState(0)
  const [columns, setColumns] = useState(1)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [editError, setEditError] = useState('')
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
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
  const pages = Math.max(1, Math.ceil(items.length / pageSize))
  const anchor = editingId === null ? pageAnchor : Math.max(0, items.findIndex(item => item.id === editingId))
  const currentPage = Math.min(Math.floor(anchor / pageSize), pages - 1)
  const start = currentPage * pageSize
  const visible = items.slice(start, start + pageSize)
  const selected = visible.find(item => item.id === selectedId) ?? visible[0]
  useEffect(() => {
    if (editingId !== null) { inputRef.current?.focus(); inputRef.current?.select() }
  }, [editingId, start, columns])

  const beginEdit = (item: SampleQueueItem) => {
    if (busy || deleting || editingId !== null || item.spectrum_hash) return
    setSelectedId(item.id)
    setDraftName(item.pre_name)
    setEditError('')
    setEditingId(item.id)
    onEditingChange(true)
  }
  const finishEdit = () => {
    const id = editingId
    setPageAnchor(start)
    setEditingId(null)
    setEditError('')
    onEditingChange(false)
    requestAnimationFrame(() => scrollRef.current?.querySelector<HTMLButtonElement>(`[data-sample-id="${id}"]`)?.focus())
  }
  const saveEdit = async () => {
    if (editingId === null || savingRef.current) return
    savingRef.current = true
    setSaving(true)
    setEditError('')
    try { await onEdit(editingId, draftName); finishEdit() }
    catch (error) { setEditError(error instanceof Error ? error.message : '样号修改失败') }
    finally { savingRef.current = false; setSaving(false) }
  }

  const turnPage = (next: number) => {
    setPageAnchor(next * pageSize)
    setSelectedId(null)
  }

  return <div className="sample-number-sheet" data-name-length={nameLength} data-rows={ROWS}
    data-columns={columns} data-page-size={pageSize}>
    <div className="sample-number-toolbar">
      <small>每列 {ROWS} 个样号，先向下再向右排列；双击或按 F2 修改，回车保存，Esc 取消</small>
      <nav aria-label="样号分页">
        <span>第 {currentPage + 1} / {pages} 页 · 共 {items.length} 项</span>
        <button className="icon-button compact" aria-label="上一页样号" disabled={currentPage === 0 || deleting || busy || editingId !== null}
          onClick={() => turnPage(currentPage - 1)}><ChevronLeft size={15} /></button>
        <button className="icon-button compact" aria-label="下一页样号" disabled={currentPage + 1 >= pages || deleting || busy || editingId !== null}
          onClick={() => turnPage(currentPage + 1)}><ChevronRight size={15} /></button>
      </nav>
    </div>
    <div ref={scrollRef} className="sample-number-scroll" tabIndex={0} role="region" aria-label="样号表格">
      <table className="sample-number-table" aria-label="样号按列排列表格"
        style={{ minWidth: ROW_HEADING_WIDTH + cellWidth }}>
        <colgroup><col className="sample-number-row-heading" />{Array.from({ length: columns }, (_, col) => <col key={col} />)}</colgroup>
        <thead><tr><th scope="col">行</th>{Array.from({ length: columns }, (_, col) =>
          <th scope="col" key={col}>{start + col * ROWS + 1}–{start + (col + 1) * ROWS}</th>)}</tr></thead>
        <tbody>{Array.from({ length: ROWS }, (_, row) => <tr key={row}>
          <th scope="row">{row + 1}</th>
          {Array.from({ length: columns }, (_, col) => {
            const item = visible[col * ROWS + row]
            return <td key={col}>{item ? editingId === item.id ? <input ref={inputRef}
              className="sample-number-edit" aria-label={`修改样号 ${item.position + 1}`} value={draftName}
              aria-invalid={!!editError} aria-describedby={editError ? 'sample-name-edit-error' : undefined}
              disabled={saving} onChange={event => setDraftName(event.target.value)}
              onKeyDown={event => {
                if (event.nativeEvent.isComposing) return
                if (event.key === 'Enter') { event.preventDefault(); void saveEdit() }
                if (event.key === 'Escape' && !savingRef.current) { event.preventDefault(); finishEdit() }
              }} /> : <button className="sample-number-cell"
              data-sample-id={item.id} data-sample-position={item.position + 1}
              aria-label={`样品 ${item.position + 1}：${item.pre_name || '空样'}`}
              title={`第 ${item.position + 1} 项：${item.pre_name || '空样'}`}
              disabled={busy || deleting || editingId !== null}
              aria-pressed={selected?.id === item.id} onClick={() => setSelectedId(item.id)}
              onDoubleClick={() => beginEdit(item)} onKeyDown={event => {
                if (event.key === 'F2') { event.preventDefault(); beginEdit(item) }
              }}>
              <strong>{item.pre_name || '空样'}</strong>
            </button> : <span className="sample-number-empty" aria-label="空位置" />}</td>
          })}
        </tr>)}</tbody>
      </table>
    </div>
    <section className="sample-number-detail" aria-label="选中样品详情">
      {selected ? <>
        <dl>
          <div><dt>预录名称</dt><dd>{selected.pre_name || '空样'}</dd></div>
          <div><dt>重复次数</dt><dd>{selected.repeats || '空样'}</dd></div>
          <div><dt>展开谱带</dt><dd>{selected.expanded_bands}</dd></div>
          <div><dt>采集后名称</dt><dd>{selected.post_name ?? '待采集'}</dd></div>
        </dl>
        <div className="sample-number-detail-actions">
          {editingId !== null ? <>
            <button className="primary-button" disabled={saving} onClick={() => void saveEdit()}>{saving ? '正在保存…' : '保存样号'}</button>
            <button className="secondary-button" disabled={saving} onClick={finishEdit}>取消修改</button>
          </> : <button className="secondary-button" disabled={busy || deleting || !!selected.spectrum_hash}
            onClick={() => beginEdit(selected)}><Pencil size={14} />修改样号</button>}
          <button className="icon-button compact danger" title="删除样品"
          aria-label={`删除样品 ${selected.position + 1}`} disabled={deleting || busy || editingId !== null}
          onClick={async () => {
            if (deleting) return
            setDeleting(true)
            try { await onDelete(selected.id) } finally { setDeleting(false) }
          }}><Trash2 size={14} /></button>
        </div>
      </> : <p>暂无样品，请在上方录入样号。</p>}
    </section>
    {editError && <p className="sample-number-edit-error" id="sample-name-edit-error" role="alert">{editError}</p>}
    {selected?.spectrum_hash && <small>已关联采集的样品请通过采集后命名修改名称。</small>}
  </div>
}
