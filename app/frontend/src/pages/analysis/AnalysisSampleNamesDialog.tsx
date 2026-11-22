import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, saveFile } from '../../api'
import type { AnalysisRepeatDefaults, AnalysisSampleNumber } from '../../api/analysis'
import { readSampleClipboard, sampleClipboardHint, samplePasteCells, useSampleGrid, type SampleCell, type SampleMatrix } from '../../components/useSampleGrid'
import { ViewerDialog } from '../spectra/ViewerDialog'
import { useSamImport } from '../sampleQueues/useSamImport'

type Props = {
  token: string
  initialEntries: AnalysisSampleNumber[]
  capacity: number
  repeatDefaults?: AnalysisRepeatDefaults
  busy: boolean
  onSave: (entries: AnalysisSampleNumber[]) => Promise<boolean>
  onClose: () => void
}

const bandCount = (entries: AnalysisSampleNumber[]) => entries.reduce((count, entry) => count + Math.max(entry.repeats, 1), 0)
const gridColumns = 10
const gridRows = Array.from({ length: 100 }, (_, row) => row)
const columns = Array.from({ length: gridColumns }, (_, column) => column)
const positionFor = ({ row, column }: SampleCell) => row * gridColumns + column
const cellFor = (position: number): SampleCell => ({ row: Math.floor(position / gridColumns), column: position % gridColumns })
const blankEntry = () => ({ name: '', repeats: 0 })

function editorValue(entries: AnalysisSampleNumber[], index: number, repeats: number) {
  if (entries[index]) return entries[index]
  const previous = [...entries].reverse().find((entry) => /^\d+$/.test(entry.name))
  const next = previous ? String(BigInt(previous.name) + 1n) : '1'
  return { name: next.length <= 20 ? next : '', repeats }
}

export function AnalysisSampleNamesDialog({ token, initialEntries, capacity, repeatDefaults, busy, onSave, onClose }: Props) {
  const sampleRepeats = repeatDefaults?.sample_repeats ?? 1
  const [entries, setEntries] = useState(initialEntries)
  const [index, setIndex] = useState(Math.min(initialEntries.length, Math.max(0, capacity - 1)))
  const [draft, setDraft] = useState(() => editorValue(initialEntries, index, sampleRepeats))
  const [dirty, setDirty] = useState(false)
  const [menu, setMenu] = useState(false)
  const [fileBusy, setFileBusy] = useState(false)
  const { importSam, samPreview } = useSamImport()
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const file = useRef<HTMLInputElement>(null)
  const grid = useRef<HTMLDivElement>(null)
  const locked = busy || fileBusy
  const command = /^[,./]/.test(draft.name.trim())
  const repeatsFor = (name: string) => {
    const prefix = name[0]?.toUpperCase()
    return prefix === 'S' ? repeatDefaults?.standard_repeats ?? 1
      : prefix === 'D' ? repeatDefaults?.control_repeats ?? 1 : sampleRepeats
  }
  const focusInput = () => {
    input.current?.focus()
    input.current?.select()
  }
  useEffect(() => {
    const focus = requestAnimationFrame(focusInput)
    return () => cancelAnimationFrame(focus)
  }, [])

  const move = (next: AnalysisSampleNumber[], position: number, focusEditor = true) => {
    const target = Math.max(0, Math.min(position, capacity - 1))
    setEntries(next)
    setIndex(target)
    setDraft(editorValue(next, target, sampleRepeats))
    setDirty(false)
    setMenu(false)
    setError('')
    if (focusEditor) {
      selection.clearRange()
      requestAnimationFrame(() => {
        focusInput()
        grid.current?.querySelector(`[data-sample-slot="${target}"]`)?.scrollIntoView({ block: 'nearest' })
      })
    }
  }

  const validateCapacity = (next: AnalysisSampleNumber[]) => {
    if (bandCount(next) <= capacity) return true
    setError(`样号占用 ${bandCount(next)} 条谱带，超过当前的 ${capacity} 条。`)
    return false
  }

  const setEntry = () => {
    const name = draft.name.trim()
    if (name && (draft.repeats < 1 || draft.repeats > 10 || !Number.isInteger(draft.repeats))) {
      setError('有效样号的重复摄谱次数须为 1 至 10 的整数。')
      return null
    }
    const next = [...entries]
    while (next.length < index) next.push(blankEntry())
    next[index] = { name, repeats: name ? draft.repeats : 0 }
    return validateCapacity(next) ? next : null
  }

  const insertBlank = () => {
    const next = [...entries]
    while (next.length < index) next.push(blankEntry())
    next.splice(index, 0, blankEntry())
    if (validateCapacity(next)) move(next, index + 1)
  }

  const remove = () => {
    const target = Math.min(index, entries.length - 1)
    move(entries.filter((_, position) => position !== target), target)
  }

  const paste = (matrix: SampleMatrix, origin: SampleCell, sequential = false) => {
    const beginning = positionFor(origin)
    const cells = sequential && matrix.every(row => row.length === 1)
      ? matrix.map(([name], offset) => ({ position: beginning + offset, name }))
      : samplePasteCells(matrix, origin, gridRows.length, gridColumns).map(cell => ({ position: positionFor(cell), name: cell.name }))
    const last = Math.max(...cells.map(cell => cell.position))
    if (last >= capacity) throw new Error(`粘贴范围超过当前的 ${capacity} 条谱带。`)
    const next = [...entries]
    while (next.length <= last) next.push(blankEntry())
    for (const { position, name: text } of cells) {
      const name = text.trim()
      if ([...name].length > 20 || /[\t\r\n]/.test(name)) {
        throw new Error(`第 ${position + 1} 项样号须在 20 个字符以内，且不能包含换行或制表符。`)
      }
      const previous = entries[position]
      next[position] = { name, repeats: name ? previous?.repeats || repeatsFor(name) : 0 }
    }
    if (validateCapacity(next)) move(next, beginning, sequential)
  }

  const canSelect = (cell: SampleCell) =>
    cell.row >= 0 && cell.row < gridRows.length && cell.column >= 0 && cell.column < gridColumns && positionFor(cell) < capacity
  const selection = useSampleGrid({
    active: cellFor(index),
    disabled: locked,
    canSelect,
    onActivate: cell => move(entries, positionFor(cell), false),
    read: cell => entries[positionFor(cell)]?.name ?? '',
    onPaste: paste,
    onError: setError,
  })

  const confirm = async (event?: FormEvent) => {
    event?.preventDefault()
    if (locked) return
    const next = dirty ? setEntry() : entries
    if (next) await saveEntries(next)
  }

  const saveEntries = async (next: AnalysisSampleNumber[]) => {
    if (!next.some(entry => entry.name)) {
      setError('请先录入至少一个有效样号。')
      return
    }
    setError('')
    if (await onSave(next)) onClose()
    else setError('保存样号失败，请重试。')
  }

  const openSam = async (selected: File) => {
    if (selected.size > 70_000) {
      setError('样号文件过大。')
      return
    }
    setFileBusy(true)
    try {
      const bytes = new Uint8Array(await selected.arrayBuffer())
      const result = await importSam(selected.name, encoding => api.readAnalysisSampleNumbers(token, bytes, encoding))
      if (!result) return
      const next = result.entries.map(entry => entry.repeats ? entry : { name: '', repeats: 0 })
      if (next.some(entry => !entry.name && entry.repeats > 0)) {
        setError('样号文件含有未填写编号的重复记录。')
        return
      }
      if (validateCapacity(next)) move(next, next.length)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法打开样号文件。')
    } finally {
      setFileBusy(false)
    }
  }

  const saveSam = async () => {
    setFileBusy(true)
    setError('')
    try {
      await saveFile(await api.writeAnalysisSampleNumbers(token, entries), '样品号.sam')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法保存样号文件。')
    } finally {
      setFileBusy(false)
    }
  }

  return <><ViewerDialog title="输入样号" onClose={onClose}>
    <form className="analysis-numbering" noValidate onSubmit={(event) => void confirm(event)}>
      <div className="analysis-numbering-toolbar" aria-label="样号录入工具">
        <label>样号输入
          <input ref={input} aria-label="样号输入" value={draft.name} maxLength={20} disabled={locked}
            onChange={(event) => {
              const name = event.target.value
              const trimmed = name.trim()
              const repeats = !trimmed || /^[,./]/.test(trimmed) ? 0 : repeatsFor(trimmed)
              setDraft({ name, repeats }); setDirty(true)
            }}
            onPaste={event => {
              const text = event.clipboardData.getData('text/plain')
              if (!/[\t\r\n]/.test(text)) return
              event.preventDefault()
              if (locked) return
              try { paste(readSampleClipboard(text), cellFor(index), true) }
              catch (failure) { setError(failure instanceof Error ? failure.message : '粘贴样号失败，请重试。') }
            }}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' || event.nativeEvent.isComposing) return
              event.preventDefault()
              if (draft.name.trim().startsWith(',')) insertBlank()
              else if (draft.name.trim().startsWith('/')) remove()
              else if (draft.name.trim().startsWith('.')) void saveEntries(entries)
              else {
                const next = setEntry()
                if (next) move(next, index + 1)
              }
            }} />
        </label>
        <label>重复摄谱
          <input type="number" min="1" max="10" step="1" aria-label="重复摄谱"
            value={draft.repeats} disabled={locked || !draft.name.trim() || command}
            onChange={(event) => { setDraft({ ...draft, repeats: Number(event.target.value) }); setDirty(true) }}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              event.preventDefault()
              const next = setEntry()
              if (next) move(next, index + 1)
            }} />
        </label>
        <input ref={file} hidden type="file" accept=".sam" onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ''
          if (selected) void openSam(selected)
        }} />
        <button type="button" disabled={locked} onClick={() => file.current?.click()}>打开样品号</button>
        <button type="button" disabled={locked || !entries.length} onClick={() => void saveSam()}>保存样品号</button>
        <button type="submit" disabled={locked}>确定</button>
        <button type="button" disabled={locked} onClick={onClose}>退出</button>
      </div>
      {menu && <div className="analysis-numbering-toolbar" aria-label="样号表操作">
        <button type="button" disabled={locked || bandCount(entries) >= capacity} onClick={insertBlank}>插入空样</button>
        <button type="button" disabled={locked || !entries.length} onClick={remove}>删除样品号</button>
        <button type="button" disabled={locked || !entries.length} onClick={() => move([], 0)}>全部清除</button>
      </div>}
      <small className="analysis-numbering-clipboard-hint">{sampleClipboardHint}。单列名单也可粘贴到样号输入框，按顺序录入。</small>
      <div className="analysis-numbering-grid" ref={grid} {...selection.events}>
        <table aria-label="样号顺序表">
          <thead><tr><th>顺序号</th>{columns.map(column => <th key={column}>{column + 1}</th>)}</tr></thead>
          <tbody>{gridRows.map((row) => <tr key={row}><th scope="row">{row * gridColumns}</th>
            {columns.map((column) => {
              const position = row * gridColumns + column
              const entry = entries[position]
              const cell = { row, column }
              const available = canSelect(cell)
              return <td key={column} data-sample-slot={position} className={available && selection.isSelected(cell) ? 'selected' : undefined}
                onContextMenu={event => {
                  event.preventDefault()
                  if (!locked && available && position <= entries.length) {
                    move(entries, position)
                    setMenu(true)
                  }
                }}>
                {available && <button type="button" disabled={locked} aria-label={`样号位置 ${position + 1}`}
                  {...selection.cellProps(cell)} aria-pressed={selection.isSelected(cell)}
                  title={entry?.name ? `${entry.name} · 重复 ${entry.repeats} 次` : undefined}
                  onDoubleClick={focusInput} onKeyDown={event => {
                    if (event.key === 'F2' || event.key === 'Enter') {
                      event.preventDefault()
                      selection.select(cell)
                      requestAnimationFrame(focusInput)
                    }
                  }}>{entry?.name || (entry ? '空样' : '')}</button>}
              </td>
            })}
          </tr>)}</tbody>
        </table>
      </div>
      {error && <p role="alert" className="auth-error">{error}</p>}
      <output className="analysis-numbering-status">谱带限制 {capacity}　谱带数量 {bandCount(entries)}　样号总数 {entries.length}　有效样数 {entries.filter(entry => entry.name).length}</output>
    </form>
  </ViewerDialog>{samPreview}</>
}

