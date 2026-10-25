import { type SpectrumRecord, type SpectrumRecordSummary } from '../../api'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'

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
          <SpectroscopyIcon name="previous-band" />
        </button>
        <span className="spectrum-position">
          记录 {Math.max(1, visibleRecords.findIndex((item) => item.id === selectedId) + 1)} /{' '}
          {visibleRecords.length}
        </span>
        <button className="icon-button" disabled={recordLocked} onClick={() => moveRecord(1)} title="下一条记录">
          <SpectroscopyIcon name="next-band" />
        </button>
        <button className={`tool-button ${recordLocked?'active':''}`} onClick={() => setRecordLocked(v => !v)} aria-pressed={recordLocked}>
          <SpectroscopyIcon name={recordLocked ? 'record-unlock' : 'record-lock'} />{recordLocked?'解锁谱带记录':'锁定谱带记录'}</button>
        <span className="toolbar-rule" />
        <button className="icon-button" onClick={() => moveBand(-1)} title={raw ? '上一 CCD' : '上一谱线'}>
          <SpectroscopyIcon name="previous-ccd" />
        </button>
        <span className="spectrum-position">
          {raw
            ? `CCD ${ccd + 1} / ${active.layout?.ccd_count ?? 0}`
            : `谱线 ${line + 1} / ${active.line_count ?? 0}`}
        </span>
        <button className="icon-button" onClick={() => moveBand(1)} title={raw ? '下一 CCD' : '下一谱线'}>
          <SpectroscopyIcon name="next-ccd" />
        </button>
      </div>
      <div className="spectrum-toolbar-group">
        <button className="icon-button" title="适合图像" aria-label="适合图像" onClick={() => resetView()}>
          <SpectroscopyIcon name="fit" />
        </button>
        <button
          className="icon-button" title="一线一点（100%）" aria-label="100%"
          onClick={() => {
            pixelScale(1)
          }}
        >
          <SpectroscopyIcon name="scale-1" />
        </button>
        <button className="icon-button" title="一线四点（400%）" aria-label="400%" onClick={() => pixelScale(4)}>
          <SpectroscopyIcon name="scale-4" />
        </button>
        <button className="icon-button" title="十倍 CCD" aria-label="十倍 CCD" disabled={!raw} onClick={() => pixelScale(10)}><SpectroscopyIcon name="scale-10" /></button>
        <button
          className="icon-button"
          onClick={() => setZoomX((value) => Math.min(32, value * 2))}
          title="横向放大"
        >
          <SpectroscopyIcon name="zoom-x-in" />
        </button>
        <button
          className="icon-button"
          onClick={() => setZoomX((value) => Math.max(1, value / 2))}
          title="横向缩小"
        >
          <SpectroscopyIcon name="zoom-x-out" />
        </button>
        <button
          className="icon-button"
          onClick={() => setZoomY((value) => Math.min(32, value * 2))}
          title="纵向放大"
        >
          <SpectroscopyIcon name="zoom-y-in" />
        </button>
        <button
          className="icon-button"
          onClick={() => setZoomY((value) => Math.max(1, value / 2))}
          title="纵向缩小"
        >
          <SpectroscopyIcon name="zoom-y-out" />
        </button>
        <button className="icon-button" onClick={() => resetView(true)} title="还原视图与参考校正">
          <SpectroscopyIcon name="reset-y" />
        </button>
      </div>
    </div>
  )
}
