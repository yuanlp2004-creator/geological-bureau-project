import { useRef, useState, type HTMLAttributes } from 'react'

export type SampleCell = { row: number; column: number }
export type SampleMatrix = string[][]

const sameCell = (one: SampleCell, other: SampleCell) => one.row === other.row && one.column === other.column
const cellKey = ({ row, column }: SampleCell) => `${row}:${column}`
const arrowSteps: Record<string, [number, number] | undefined> = {
  ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
}
export const sampleClipboardHint = '拖选或 Shift 扩选，Ctrl+C 复制，Ctrl+V 粘贴'

const suffixParts = (value: string) => /^(.*?)([0-9]+)$/u.exec(value)
const numberedName = (prefix: string, value: bigint, width: number) =>
  prefix + (value < 0n ? '-' : '') + (value < 0n ? -value : value).toString().padStart(width, '0')

export function nextSampleName(value: string) {
  const parts = suffixParts(value)
  return parts ? numberedName(parts[1], BigInt(parts[2]) + 1n, parts[2].length) : ''
}

function fillValue(values: string[], offset: number) {
  const parts = values.map(suffixParts)
  const first = parts[0]
  if (first && parts.every(part => part?.[1] === first[1])) {
    const initial = BigInt(first[2])
    const step = parts.length === 1 ? 1n : BigInt(parts[1]![2]) - initial
    if (parts.every((part, index) => BigInt(part![2]) === initial + BigInt(index) * step)) {
      const width = parts.some(part => part![2].startsWith('0')) ? Math.max(...parts.map(part => part![2].length)) : 1
      return numberedName(first[1], initial + BigInt(offset) * step, width)
    }
  }
  return values[(offset % values.length + values.length) % values.length]
}

const escapeCellHtml = (value: string) => value.replace(/[&<>"']/g, char =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)

export function readSampleClipboard(text: string): SampleMatrix {
  if (!text) return []
  if (text.length > 130_000) throw new Error('剪贴板内容过长。')
  const rows: SampleMatrix = [[]]
  const field = /"((?:[^"]|"")*)"(?=[\t\r\n]|$)|([^\t\r\n]*)/y
  let offset = 0
  let count = 0
  while (true) {
    if (++count > 1000) throw new Error('一次最多粘贴 1000 个样号位置。')
    field.lastIndex = offset
    const match = field.exec(text)!
    rows[rows.length - 1].push(match[1] === undefined ? match[2] : match[1].replace(/""/g, '"'))
    const end = field.lastIndex
    if (end === text.length) return rows
    const separator = text[end]
    offset = end + (separator === '\r' && text[end + 1] === '\n' ? 2 : 1)
    if (separator === '\t') continue
    if (offset === text.length) return rows
    rows.push([])
  }
}

function writeSampleClipboard(rows: SampleMatrix) {
  return rows.map(row => row.map(value =>
    /["\t\r\n]/.test(value) || (row.length === 1 && !value) ? `"${value.replace(/"/g, '""')}"` : value
  ).join('\t')).join('\r\n')
}

export function samplePasteCells(matrix: SampleMatrix, origin: SampleCell, rows: number, columns: number) {
  return matrix.flatMap((line, y) => line.map((name, x) => {
    const row = origin.row + y
    const column = origin.column + x
    if (row >= rows || column >= columns) throw new Error('粘贴范围超出表格边界，请调整起始位置或选取较小范围。')
    return { row, column, name }
  }))
}

type Options = {
  active: SampleCell
  disabled: boolean
  canSelect: (cell: SampleCell) => boolean
  onActivate: (cell: SampleCell) => void
  read: (cell: SampleCell) => string
  onPaste: (matrix: SampleMatrix, origin: SampleCell) => void | Promise<void>
  onFill?: (matrix: SampleMatrix, origin: SampleCell) => void | Promise<void>
  onError: (message: string) => void
}

export function useSampleGrid({ active, disabled, canSelect, onActivate, read, onPaste, onFill, onError }: Options) {
  const [range, setRange] = useState<{ anchor: SampleCell; end: SampleCell } | null>(null)
  const drag = useRef<SampleCell | null>(null)
  const [fillTarget, setFillTarget] = useState<SampleCell | null>(null)
  const filling = useRef(false)
  const end = range && sameCell(range.anchor, active) && canSelect(range.end) ? range.end : active
  const first = { row: Math.min(active.row, end.row), column: Math.min(active.column, end.column) }
  const last = { row: Math.max(active.row, end.row), column: Math.max(active.column, end.column) }
  const clearFill = () => { filling.current = false; setFillTarget(null) }
  const clearRange = () => { drag.current = null; setRange(null); clearFill() }
  const select = (cell: SampleCell) => { clearRange(); onActivate(cell) }

  const clipboardTarget = (target: EventTarget) =>
    target instanceof HTMLElement && !target.closest('input, textarea, [contenteditable="true"]')

  const fillArea = (target: SampleCell) => {
    const dy = target.row < first.row ? target.row - first.row : Math.max(0, target.row - last.row)
    const dx = target.column < first.column ? target.column - first.column : Math.max(0, target.column - last.column)
    if (!dy && !dx) return null
    const vertical = Math.abs(dy) >= Math.abs(dx)
    return vertical
      ? { start: { row: dy < 0 ? target.row : last.row + 1, column: first.column },
          end: { row: dy < 0 ? first.row - 1 : target.row, column: last.column }, vertical }
      : { start: { row: first.row, column: dx < 0 ? target.column : last.column + 1 },
          end: { row: last.row, column: dx < 0 ? first.column - 1 : target.column }, vertical }
  }
  const preview = fillTarget ? fillArea(fillTarget) : null

  const finishFill = async () => {
    clearFill()
    if (!preview || disabled || !onFill) return
    const { start, end: limit, vertical } = preview
    if (!canSelect(start) || !canSelect(limit)) return onError('填充范围超出表格边界。')
    const sourceLength = vertical ? last.row - first.row + 1 : last.column - first.column + 1
    const matrix = Array.from({ length: limit.row - start.row + 1 }, (_, y) =>
      Array.from({ length: limit.column - start.column + 1 }, (_, x) => {
        const row = start.row + y, column = start.column + x
        const values = Array.from({ length: sourceLength }, (_, index) => read(vertical
          ? { row: first.row + index, column } : { row, column: first.column + index }))
        return fillValue(values, vertical ? row - first.row : column - first.column)
      }))
    try { await onFill(matrix, start) }
    catch (error) { onError(error instanceof Error ? error.message : '填充样号失败，请重试。') }
  }

  const events: HTMLAttributes<HTMLDivElement> = {
    onPointerMove: event => {
      if (!(event.buttons & 1)) drag.current = null
      const anchor = drag.current
      if ((!anchor && !filling.current) || disabled) return
      const button = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLButtonElement>('button[data-sample-cell]')
      if (!button) return
      const [row, column] = button.dataset.sampleCell!.split(':').map(Number)
      const next = { row, column }
      if (!canSelect(next)) return
      if (filling.current) setFillTarget(next)
      else if (anchor && !sameCell(end, next)) setRange({ anchor, end: next })
    },
    onPointerUp: () => {
      drag.current = null
      if (filling.current) void finishFill()
    },
    onPointerCancel: () => { drag.current = null; clearFill() },
    onKeyDown: event => {
      if (disabled || !clipboardTarget(event.target) || event.altKey || event.ctrlKey || event.metaKey) return
      const delta = arrowSteps[event.key]
      if (!delta) return
      event.preventDefault()
      const origin = event.shiftKey ? end : active
      const next = { row: origin.row + delta[0], column: origin.column + delta[1] }
      if (!canSelect(next)) return
      if (event.shiftKey) setRange({ anchor: active, end: next })
      else select(next)
      const target = event.currentTarget.querySelector<HTMLButtonElement>(`[data-sample-cell="${cellKey(next)}"]`)
      target?.focus({ preventScroll: true })
      target?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    },
    onCopy: event => {
      if (disabled || !canSelect(active) || !clipboardTarget(event.target)) return
      const rows = Array.from({ length: last.row - first.row + 1 }, (_, y) =>
        Array.from({ length: last.column - first.column + 1 }, (_, x) => read({ row: first.row + y, column: first.column + x })))
      event.preventDefault()
      event.clipboardData.setData('text/plain', writeSampleClipboard(rows))
      event.clipboardData.setData('text/html', '<table>' + rows.map(row => '<tr>' +
        row.map(value => `<td style="mso-number-format:'\\@'" x:str>${escapeCellHtml(value)}</td>`).join('') +
        '</tr>').join('') + '</table>')
    },
    onPaste: async event => {
      if (!clipboardTarget(event.target)) return
      event.preventDefault()
      if (disabled || !canSelect(active)) return
      try {
        const matrix = readSampleClipboard(event.clipboardData.getData('text/plain'))
        if (matrix.length) await onPaste(matrix, first)
      } catch (error) {
        onError(error instanceof Error ? error.message : '粘贴样号失败，请重试。')
      }
    },
  }

  const cellProps = (cell: SampleCell): HTMLAttributes<HTMLButtonElement> & { 'data-sample-cell': string; 'data-sample-active': boolean } => ({
    'data-sample-cell': cellKey(cell),
    'data-sample-active': sameCell(cell, active),
    tabIndex: sameCell(cell, active) ? 0 : -1,
    onPointerDown: event => {
      if (event.button !== 0 || disabled) return
      if (event.shiftKey) {
        drag.current = active
        setRange({ anchor: active, end: cell })
        event.preventDefault()
        event.currentTarget.focus()
      } else {
        select(cell)
        drag.current = cell
      }
    },
    onClick: event => { if (event.detail === 0) select(cell) },
  })
  const isSelected = ({ row, column }: SampleCell) =>
    row >= first.row && row <= last.row && column >= first.column && column <= last.column
  const fillHandle = (cell: SampleCell): HTMLAttributes<HTMLButtonElement> | undefined =>
    onFill && !disabled && sameCell(cell, last) && canSelect(cell) && read(active) ? {
      onPointerDown: event => {
        if (event.button !== 0) return
        event.preventDefault()
        drag.current = null
        filling.current = true
        event.currentTarget.setPointerCapture(event.pointerId)
      },
      onLostPointerCapture: clearFill,
    } : undefined
  const isFilling = ({ row, column }: SampleCell) => !!preview
    && row >= preview.start.row && row <= preview.end.row && column >= preview.start.column && column <= preview.end.column
  return { events, cellProps, isSelected, isFilling, fillHandle, clearRange, select }
}
