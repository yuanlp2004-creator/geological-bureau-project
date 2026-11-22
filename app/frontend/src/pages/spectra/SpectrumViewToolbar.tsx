import type { SpectrumRecord, SpectrumRecordSummary } from '../../api'
import { ObservationToolbar } from '../../components/ObservationToolbar'
import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { LegacyCcdPicker } from '../../components/LegacyCcdPicker'
import type { SpectrumAxis } from '../../components/spectrumZoom'

type Props = {
  moveRecord: (delta: number) => void; visibleRecords: SpectrumRecordSummary[]; selectedId: string | null
  moveBand: (delta: number) => void; raw: boolean; ccd: number; active: SpectrumRecord; line: number
  resetView: (resetCorrection?: boolean, horizontalOnly?: boolean) => void
  zoom: (axis: SpectrumAxis, factor: number) => void
  resetY: () => void
  recordLocked: boolean; multiView: boolean
  pixelScale: (mode: 1 | 4 | 10) => void; pixelMode: 1 | 4 | 10 | null
  tool: 'crosshair' | 'pan' | 'box'; setTool: (value: 'crosshair' | 'pan' | 'box') => void
  print: () => void; busy: boolean
}
export function SpectrumViewToolbar(p: Props) {
  const position = p.visibleRecords.findIndex(item => item.id === p.selectedId)
  const count = p.raw ? Number(p.active.layout?.ccd_count ?? 0) : p.active.line_count ?? 0
  const index = p.raw ? p.ccd : p.line
  const bandLabels = p.active.layout?.band_labels as string[] | undefined
  return <ObservationToolbar disabled={p.busy} tool={p.tool} setTool={p.setTool} fit={() => p.resetView(false,true)} showPan={!p.multiView}
      navigation={<>
        <SpectroscopyToolButton icon="previous-band" label="上一条记录" disabled={p.busy || p.recordLocked || position <= 0} onClick={() => p.moveRecord(-1)} />
        <SpectroscopyToolButton icon="next-band" label="下一条记录" disabled={p.busy || p.recordLocked || position < 0 || position >= p.visibleRecords.length - 1} onClick={() => p.moveRecord(1)} />
        <SpectroscopyToolButton icon="previous-ccd" label={p.raw ? '上一 CCD' : '上一谱线'} disabled={p.busy || index <= 0} onClick={() => p.moveBand(-1)} />
        <SpectroscopyToolButton icon="next-ccd" label={p.raw ? '下一 CCD' : '下一谱线'} disabled={p.busy || index >= count - 1} onClick={() => p.moveBand(1)} />
        <LegacyCcdPicker aria-label={p.raw ? '选择CCD' : '选择结果谱线'} title={`${p.raw ? 'CCD' : '谱线'} ${index + 1}`} value={index} disabled={p.busy || !count}
          onChange={event => p.moveBand(Number(event.target.value) - index)}>
          {Array.from({ length: count }, (_, i) => <option key={i} value={i}>{p.raw ? bandLabels?.[i] ?? `CCD ${i + 1}` : `谱线 ${i + 1}`}</option>)}
        </LegacyCcdPicker>
      </>}
      scales={<>{([1, 4, 10] as const).map(value => <SpectroscopyToolButton key={value}
        icon={value === 1 ? 'scale-1' : value === 4 ? 'scale-4' : 'scale-10'}
        label={value === 1 ? '100%' : value === 4 ? '400%' : '十倍 CCD'}
        description={value === 1 ? '一线一点（100%）' : value === 4 ? '一线四点（400%）' : '十倍 CCD'}
        disabled={!p.raw || p.busy} aria-pressed={p.pixelMode === value} onClick={() => p.pixelScale(value)} />)}</>}
      zoom={p.zoom} resetY={p.resetY} print={p.print} />
}
