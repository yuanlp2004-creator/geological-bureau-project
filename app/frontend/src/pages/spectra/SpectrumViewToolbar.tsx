import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  RotateCcw,
  ZoomIn,
  ZoomOut
} from 'lucide-react'
import { type SpectrumRecord, type SpectrumRecordSummary } from '../../api'

// State and request ownership remain in the page.
type PanelProps = {
  moveRecord: (delta: number) => void
  visibleRecords: SpectrumRecordSummary[]
  selectedId: string | null
  moveBand: (delta: number) => void
  raw: boolean
  ccd: number
  active: SpectrumRecord
  line: number
  resetView: (resetCorrection?: boolean) => void
  setZoomX: React.Dispatch<React.SetStateAction<number>>
  setPanX: React.Dispatch<React.SetStateAction<number>>
  setZoomY: React.Dispatch<React.SetStateAction<number>>
  recordLocked: boolean
  setRecordLocked: React.Dispatch<React.SetStateAction<boolean>>
  pixelScale: (mode: 1 | 4 | 10) => void
}

export function SpectrumViewToolbar({
  moveRecord,
  visibleRecords,
  selectedId,
  moveBand,
  raw,
  ccd,
  active,
  line,
  resetView,
  setZoomX,
  setZoomY,
  recordLocked,
  setRecordLocked,
  pixelScale,
}: PanelProps) {
  return (
    <div className="spectrum-toolbar">
      <div className="spectrum-toolbar-group">
        <button className="icon-button" disabled={recordLocked} onClick={() => moveRecord(-1)} title="上一条记录">
          <ChevronLeft size={16} />
        </button>
        <span className="spectrum-position">
          记录 {Math.max(1, visibleRecords.findIndex((item) => item.id === selectedId) + 1)} /{' '}
          {visibleRecords.length}
        </span>
        <button className="icon-button" disabled={recordLocked} onClick={() => moveRecord(1)} title="下一条记录">
          <ChevronRight size={16} />
        </button>
        <button className={`tool-button ${recordLocked?'active':''}`} onClick={() => setRecordLocked(v => !v)} aria-pressed={recordLocked}>
          {recordLocked?'解锁谱带记录':'锁定谱带记录'}</button>
        <span className="toolbar-rule" />
        <button className="icon-button" onClick={() => moveBand(-1)} title={raw ? '上一 CCD' : '上一谱线'}>
          <ChevronLeft size={16} />
        </button>
        <span className="spectrum-position">
          {raw
            ? `CCD ${ccd + 1} / ${active.layout?.ccd_count ?? 0}`
            : `谱线 ${line + 1} / ${active.line_count ?? 0}`}
        </span>
        <button className="icon-button" onClick={() => moveBand(1)} title={raw ? '下一 CCD' : '下一谱线'}>
          <ChevronRight size={16} />
        </button>
      </div>
      <div className="spectrum-toolbar-group">
        <button className="tool-button" onClick={() => resetView()}>
          <Maximize2 size={14} />
          适合图像
        </button>
        <button
          className="tool-button"
          onClick={() => {
            pixelScale(1)
          }}
        >
          100%
        </button>
        <button className="tool-button" onClick={() => pixelScale(4)}>
          400%
        </button>
        <button className="tool-button" disabled={!raw} onClick={() => pixelScale(10)}>十倍 CCD</button>
        <button
          className="icon-button"
          onClick={() => setZoomX((value) => Math.min(32, value * 2))}
          title="横向放大"
        >
          <ZoomIn size={15} />
        </button>
        <button
          className="icon-button"
          onClick={() => setZoomX((value) => Math.max(1, value / 2))}
          title="横向缩小"
        >
          <ZoomOut size={15} />
        </button>
        <button
          className="icon-button"
          onClick={() => setZoomY((value) => Math.min(32, value * 2))}
          title="纵向放大"
        >
          Y+
        </button>
        <button
          className="icon-button"
          onClick={() => setZoomY((value) => Math.max(1, value / 2))}
          title="纵向缩小"
        >
          Y−
        </button>
        <button className="icon-button" onClick={() => resetView(true)} title="还原视图与参考校正">
          <RotateCcw size={15} />
        </button>
      </div>
    </div>
  )
}
