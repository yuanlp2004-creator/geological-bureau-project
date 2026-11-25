import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { flushSync } from 'react-dom'
import { api, saveFile } from '../../api'
import type { AnalysisRepeatDefaults, AnalysisSampleFileFormat, AnalysisSampleNumber } from '../../api/analysis'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import {
  ANALYSIS_SAMPLE_COLUMNS as gridColumns, analysisSampleBandCount as bandCount, analysisSampleCapacityError,
  analysisSampleCommand, incrementalSampleFill, isSampleComposition, isSampleFillKey,
  nextSampleGridPosition, rowMajorPosition as positionFor, sampleTypingKey, type SampleGridChange,
} from '../../components/sampleGridFlow'
import { resolveSampleSemanticRole, sampleRoleLabels, type SampleRoleEvidence } from '../../components/sampleSemanticRole'
import { readSampleClipboard, sampleClipboardHint, samplePasteCells, useSampleGrid, type SampleCell, type SampleMatrix } from '../../components/useSampleGrid'
import { ViewerDialog } from '../spectra/ViewerDialog'
import { useSamImport } from '../sampleQueues/useSamImport'

type Props = {
  token: string
  initialEntries: AnalysisSampleNumber[]
  capacity: number
  repeatDefaults?: AnalysisRepeatDefaults
  methodStandardNames: ReadonlySet<string>
  bandEvidence: readonly SampleRoleEvidence[]
  busy: boolean
  onSave: (entries: AnalysisSampleNumber[]) => Promise<boolean>
  onClose: () => void
}

const gridRows = Array.from({ length: 100 }, (_, row) => row)
const columns = Array.from({ length: gridColumns }, (_, column) => column)
const cellFor = (position: number): SampleCell => ({ row: Math.floor(position / gridColumns), column: position % gridColumns })
const blankEntry = () => ({ name: '', repeats: 0 })

function editorValue(entries: AnalysisSampleNumber[], index: number, repeats: number) {
  if (entries[index]) return entries[index]
  const previous = [...entries].reverse().find((entry) => /^\d+$/.test(entry.name))
  const next = previous ? String(BigInt(previous.name) + 1n) : '1'
  return { name: next.length <= 20 ? next : '', repeats }
}

export function AnalysisSampleNamesDialog({ token, initialEntries, capacity, repeatDefaults, methodStandardNames, bandEvidence, busy, onSave, onClose }: Props) {
  const sampleRepeats = repeatDefaults?.sample_repeats ?? 1
  const [entries, setEntries] = useState(initialEntries)
  const [index, setIndex] = useState(Math.min(initialEntries.length, Math.max(0, capacity - 1)))
  const [draft, setDraft] = useState(() => editorValue(initialEntries, index, sampleRepeats))
  const [repeatEditorVersion, setRepeatEditorVersion] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [menu, setMenu] = useState(false)
  const [fileBusy, setFileBusy] = useState(false)
  const { importSam, samPreview } = useSamImport()
  const [error, setError] = useState('')
  const form = useRef<HTMLFormElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const file = useRef<HTMLInputElement>(null)
  const grid = useRef<HTMLDivElement>(null)
  const composing = useRef(false)
  const locked = busy || fileBusy
  const command = analysisSampleCommand(draft.name)
  const repeatsFor = (name: string) => {
    const prefix = name[0]?.toUpperCase()
    return prefix === 'S' ? repeatDefaults?.standard_repeats ?? 1
      : prefix === 'D' ? repeatDefaults?.control_repeats ?? 1 : sampleRepeats
  }
  const editorComposition = {
    onCompositionStart: () => { composing.current = true },
    onCompositionEnd: () => { composing.current = false },
  }
  const focusInput = (position: number, select = true) => {
    input.current?.focus()
    if (select) input.current?.select()
    else if (input.current) input.current.setSelectionRange(input.current.value.length, input.current.value.length)
    grid.current?.querySelector(`[data-sample-slot="${position}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }
  const initialIndex = useRef(index)
  useEffect(() => {
    const focus = requestAnimationFrame(() => focusInput(initialIndex.current))
    return () => cancelAnimationFrame(focus)
  }, [])

  const move = (next: AnalysisSampleNumber[], position: number, focusEditor = true) => {
    const target = Math.max(0, Math.min(position, capacity - 1))
    setEntries(next)
    setIndex(target)
    setDraft(editorValue(next, target, sampleRepeats))
    setRepeatEditorVersion(version => version + 1)
    setDirty(false)
    setMenu(false)
    setError('')
    if (focusEditor) {
      selection.clearRange()
      requestAnimationFrame(() => focusInput(target))
    }
  }

  const validateCapacity = (next: AnalysisSampleNumber[]) => {
    const message = analysisSampleCapacityError(next, capacity)
    if (message) setError(message)
    return !message
  }

  const setEntry = () => {
    const name = draft.name.trim()
    if (name && !reportInvalidNumericInput(form.current)) return null
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
    applyNames(entries, cells, beginning, sequential)
  }

  const applyNames = (original: AnalysisSampleNumber[], cells: SampleGridChange[], beginning: number, focusEditor: boolean) => {
    const last = Math.max(...cells.map(cell => cell.position))
    if (last >= capacity) throw new Error(`粘贴范围超过当前的 ${capacity} 条谱带。`)
    const next = [...original]
    while (next.length <= last) next.push(blankEntry())
    for (const { position, name: text } of cells) {
      const name = text.trim()
      if ([...name].length > 20 || /[\t\r\n]/.test(name)) {
        throw new Error(`第 ${position + 1} 项样号须在 20 个字符以内，且不能包含换行或制表符。`)
      }
      const previous = original[position]
      next[position] = { name, repeats: name ? previous?.repeats || repeatsFor(name) : 0 }
    }
    if (validateCapacity(next)) move(next, beginning, focusEditor)
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

  const blockComposition = (event: KeyboardEvent<HTMLElement>) => {
    if (!isSampleComposition(event.nativeEvent, composing.current)) return false
    if (event.key === 'Enter' || event.key === 'Tab' || event.key === 'Escape' || isSampleFillKey(event.nativeEvent)) {
      event.preventDefault()
    }
    return true
  }

  const advance = (event: KeyboardEvent<HTMLElement>, fromGrid = false) => {
    const tab = event.key === 'Tab'
    const target = nextSampleGridPosition(index, tab && event.shiftKey ? -1 : 1, capacity)
    const next = dirty || !tab ? setEntry() : entries
    if (!next) {
      event.preventDefault()
      return
    }
    if (target === null) {
      if (!tab) event.preventDefault()
      if (next !== entries) move(next, index, false)
      return
    }
    event.preventDefault()
    selection.clearRange()
    move(next, target, !fromGrid)
    if (fromGrid) requestAnimationFrame(() => {
      const button = grid.current?.querySelector<HTMLButtonElement>(`[data-sample-slot="${target}"] button`)
      button?.focus({ preventScroll: true })
      button?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    })
  }

  const changeName = (name: string) => {
    const trimmed = name.trim()
    const repeats = trimmed && analysisSampleCommand(trimmed) === 'entry' ? repeatsFor(trimmed) : 0
    setDraft({ name, repeats })
    setRepeatEditorVersion(version => version + 1)
    setDirty(true)
  }

  const startGridEdit = (position: number, typed?: string) => {
    const select = () => {
      if (position !== index) selection.select(cellFor(position))
    }
    if (typed === undefined) {
      select()
      requestAnimationFrame(() => focusInput(position))
    } else {
      flushSync(() => {
        select()
        if (typed) changeName(typed)
      })
      focusInput(position, !typed)
    }
  }

  const fillDown = () => {
    const next = dirty ? setEntry() : entries
    if (!next) return
    try {
      const changes = incrementalSampleFill(selection.selectedCells().map(positionFor), capacity,
        position => next[position]?.name ?? '')
      applyNames(next, changes, index, false)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '填充样号失败，请重试。')
    }
  }

  const confirm = async (event?: FormEvent) => {
    event?.preventDefault()
    if (locked || composing.current) return
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

  const openSampleFile = async (selected: File) => {
    const workbook = /\.xlsx$/i.test(selected.name)
    if (selected.size > (workbook ? 5_000_000 : 70_000)) {
      setError('样号文件过大。')
      return
    }
    setFileBusy(true)
    try {
      const bytes = new Uint8Array(await selected.arrayBuffer())
      const result = workbook ? await api.readAnalysisSampleNumbers(token, bytes, undefined, 'xlsx')
        : await importSam(selected.name, encoding => api.readAnalysisSampleNumbers(token, bytes, encoding))
      if (!result) return
      const next = workbook ? result.entries : result.entries.map(entry => entry.repeats ? entry : blankEntry())
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

  const saveSampleFile = async (format: AnalysisSampleFileFormat) => {
    setFileBusy(true)
    setError('')
    try {
      await saveFile(await api.writeAnalysisSampleNumbers(token, entries, format), `样品号.${format}`)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '无法保存样号文件。')
    } finally {
      setFileBusy(false)
    }
  }

  let firstBand = 0
  const entryRoles = entries.map(entry => {
    const count = Math.max(entry.repeats, 1)
    const sources = bandEvidence.slice(firstBand, firstBand + count)
    firstBand += count
    if (!entry.name.trim()) return 'neutral'
    const all = (matches: (source: SampleRoleEvidence) => boolean) => sources.length === count && sources.every(matches)
    return resolveSampleSemanticRole({
      name: entry.name, methodStandardNames,
      explicitManagementTask: all(source => source.explicitManagementTask === true),
      qualityManagementSample: all(source => source.qualityManagementSample === true),
      sourceKind: all(source => source.sourceKind === 'standard') ? 'standard' : undefined,
      sampleNumbering: sources.some(source => source.sampleNumbering),
    })
  })

  return <><ViewerDialog title="输入样号" onClose={onClose}>
    <form ref={form} className="analysis-numbering" noValidate onSubmit={(event) => void confirm(event)}>
      <div className="analysis-numbering-toolbar" aria-label="样号录入工具">
        <label>样号输入
          <input ref={input} aria-label="样号输入" value={draft.name} maxLength={20} disabled={locked}
            {...editorComposition} onChange={event => changeName(event.target.value)}
            onPaste={event => {
              const text = event.clipboardData.getData('text/plain')
              if (!/[\t\r\n]/.test(text)) return
              event.preventDefault()
              if (locked) return
              try { paste(readSampleClipboard(text), cellFor(index), true) }
              catch (failure) { setError(failure instanceof Error ? failure.message : '粘贴样号失败，请重试。') }
            }}
            onKeyDown={(event) => {
              if (blockComposition(event)) return
              if (event.key === 'Tab') { advance(event); return }
              if (event.key !== 'Enter') return
              event.preventDefault()
              switch (command) {
                case 'insert': insertBlank(); break
                case 'remove': remove(); break
                case 'save': void saveEntries(entries); break
                case 'entry': advance(event); break
              }
            }} />
        </label>
        <label>重复摄谱
          <NumericInput key={repeatEditorVersion} min={1} max={10} step={1} stepWithArrows aria-label="重复摄谱"
            value={draft.repeats} disabled={locked || !draft.name.trim() || command !== 'entry'}
            {...editorComposition}
            onInput={() => setDirty(true)}
            onValueChange={(repeats) => {
              if (repeats === draft.repeats) return
              setDraft({ ...draft, repeats })
              setDirty(true)
            }}
            onKeyDown={(event) => {
              if (blockComposition(event)) {
                if (event.key.startsWith('Arrow')) event.preventDefault()
                return
              }
              if (event.key === 'Escape') {
                event.preventDefault()
                onClose()
                return
              }
              if (event.key === 'Enter' || event.key === 'Tab') advance(event)
            }} />
        </label>
        <input ref={file} hidden type="file" accept=".xlsx,.sam" onChange={(event) => {
          const selected = event.target.files?.[0]
          event.target.value = ''
          if (selected) void openSampleFile(selected)
        }} />
        <button type="button" disabled={locked} onClick={() => file.current?.click()}>打开样品号</button>
        <button type="button" disabled={locked || !entries.length} onClick={() => void saveSampleFile('xlsx')}>导出 Excel</button>
        <button type="button" disabled={locked || !entries.length} onClick={() => void saveSampleFile('sam')}>保存样品号</button>
        <button type="submit" disabled={locked}>确定</button>
        <button type="button" disabled={locked} onClick={onClose}>退出</button>
      </div>
      {menu && <div className="analysis-numbering-toolbar" aria-label="样号表操作">
        <button type="button" disabled={locked || bandCount(entries) >= capacity} onClick={insertBlank}>插入空样</button>
        <button type="button" disabled={locked || !entries.length} onClick={remove}>删除样品号</button>
        <button type="button" disabled={locked || !entries.length} onClick={() => move([], 0)}>全部清除</button>
      </div>}
      <small className="analysis-numbering-clipboard-hint">{sampleClipboardHint}。单列名单也可粘贴到样号输入框，按顺序录入。</small>
      <div className="analysis-numbering-grid" ref={grid} {...selection.events} onKeyDown={event => {
        if (locked || event.defaultPrevented || blockComposition(event)) return
        if (event.key === 'Tab') advance(event, true)
        else if (isSampleFillKey(event.nativeEvent)) {
          event.preventDefault()
          fillDown()
        } else selection.events.onKeyDown?.(event)
      }}>
        <table aria-label="样号顺序表">
          <thead><tr><th>顺序号</th>{columns.map(column => <th key={column}>{column + 1}</th>)}</tr></thead>
          <tbody>{gridRows.map((row) => <tr key={row}><th scope="row">{row * gridColumns}</th>
            {columns.map((column) => {
              const cell = { row, column }
              const position = positionFor(cell)
              const entry = entries[position]
              const role = entryRoles[position] ?? 'neutral'
              const available = canSelect(cell)
              return <td key={column} data-sample-slot={position} data-sample-role={role}
                className={available && selection.isSelected(cell) ? 'selected' : undefined}
                onContextMenu={event => {
                  event.preventDefault()
                  if (!locked && available && position <= entries.length) {
                    move(entries, position)
                    setMenu(true)
                  }
                }}>
                {available && <button type="button" disabled={locked} aria-label={`样号位置 ${position + 1}`}
                  {...selection.cellProps(cell)} aria-pressed={selection.isSelected(cell)}
                  title={entry?.name ? `${entry.name} · 重复 ${entry.repeats} 次${role === 'neutral' ? '' : ` · ${sampleRoleLabels[role]}`}` : undefined}
                  onDoubleClick={() => startGridEdit(position)} onKeyDown={event => {
                    const typed = sampleTypingKey(event.nativeEvent)
                    if (typed !== undefined || event.key === 'F2' || event.key === 'Enter') {
                      if (typed !== '') event.preventDefault()
                      startGridEdit(position, typed)
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

