export const MAX_SAMPLE_QUEUE_ITEMS = 1000
export const SAMPLE_QUEUE_ROWS = 20
export const ANALYSIS_SAMPLE_COLUMNS = 10

export type SampleCell = { row: number; column: number }
export type SampleGridChange = { position: number; name: string }

export const columnMajorPosition = ({ row, column }: SampleCell, start: number, rows: number) => start + column * rows + row
export const rowMajorPosition = ({ row, column }: SampleCell) => row * ANALYSIS_SAMPLE_COLUMNS + column

export function nextSampleGridPosition(position: number, direction: -1 | 1, capacity: number): number | null {
  const target = position + direction
  return target >= 0 && target < capacity ? target : null
}

export async function commitSampleGridMove(
  position: number, direction: -1 | 1, capacity: number, commit: () => Promise<void>,
) {
  await commit()
  return nextSampleGridPosition(position, direction, capacity)
}

export function analysisSampleCommand(name: string): 'insert' | 'remove' | 'save' | 'entry' {
  switch (name.trim()[0]) {
    case ',': return 'insert'
    case '/': return 'remove'
    case '.': return 'save'
    default: return 'entry'
  }
}

export function analysisSampleBandCount(entries: readonly { repeats: number }[]) {
  return entries.reduce((count, entry) => count + Math.max(entry.repeats, 1), 0)
}

export function analysisSampleCapacityError(entries: readonly { repeats: number }[], capacity: number) {
  const bands = analysisSampleBandCount(entries)
  return bands <= capacity ? '' : `样号占用 ${bands} 条谱带，超过当前的 ${capacity} 条。`
}

type SampleKey = { key: string; keyCode: number; isComposing: boolean; ctrlKey: boolean; metaKey: boolean; altKey: boolean }

export function isSampleComposition(event: Pick<SampleKey, 'key' | 'keyCode' | 'isComposing'>, composing = false) {
  return composing || event.isComposing || event.key === 'Process' || event.keyCode === 229
}

export function sampleTypingKey(event: SampleKey): string | undefined {
  if (event.ctrlKey || event.metaKey || event.altKey) return undefined
  if (isSampleComposition(event)) return ''
  return [...event.key].length === 1 ? event.key : undefined
}

export const isSampleFillKey = (event: SampleKey) =>
  event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === 'd'

const suffixParts = (value: string) => /^(.*?)([0-9]+)$/u.exec(value)
const numberedName = (prefix: string, value: bigint, width: number) =>
  prefix + (value < 0n ? '-' : '') + (value < 0n ? -value : value).toString().padStart(width, '0')

export function nextSampleName(value: string) {
  const parts = suffixParts(value)
  return parts ? numberedName(parts[1], BigInt(parts[2]) + 1n, parts[2].length) : ''
}

export function sampleDragFillValue(values: string[], offset: number) {
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

export function assertSampleGridWritable(targets: readonly number[], items: readonly { spectrum_hash?: string | null }[]) {
  const protectedPosition = targets.find(position => items[position]?.spectrum_hash)
  if (protectedPosition !== undefined) {
    throw new Error(`第 ${protectedPosition + 1} 项已关联采集，整批样号未保存。`)
  }
}

export function incrementalSampleFill(
  selection: readonly number[], capacity: number, read: (position: number) => string,
  items: readonly { spectrum_hash?: string | null }[] = [],
): SampleGridChange[] {
  const [source, ...rest] = [...selection].sort((left, right) => left - right)
  if (source === undefined) return []
  const targets = rest.length ? rest : [source + 1]
  if (source < 0 || targets.some(position => position >= capacity)) throw new Error('填充范围超出表格边界。')
  assertSampleGridWritable(targets, items)
  let name = read(source).trim()
  return targets.map(position => {
    name = nextSampleName(name)
    if (!name) throw new Error('起始样号须以数字结尾才能递增填充。')
    return { position, name }
  })
}
