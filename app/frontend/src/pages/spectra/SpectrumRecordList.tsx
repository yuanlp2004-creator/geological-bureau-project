import {
  ChevronRight,
  Database
} from 'lucide-react'
import { type SpectrumRecordSummary } from '../../api'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'

// State and request ownership remain in the page.
type PanelProps = {
  visibleRecords: SpectrumRecordSummary[]
  angleFilter: string
  setAngleFilter: React.Dispatch<React.SetStateAction<string>>
  angles: number[]
  selectedId: string | null
  displayIds: string[]
  toggleOverlay: (id: string) => void
  selectRecord: (record: SpectrumRecordSummary) => void
  recordLocked: boolean
}

export function SpectrumRecordList({
  visibleRecords,
  angleFilter,
  setAngleFilter,
  angles,
  selectedId,
  displayIds,
  toggleOverlay,
  selectRecord,
  recordLocked,
}: PanelProps) {
  return (
    <aside className="surface spectrum-records">
      <div className="surface-heading">
        <div>
          <h2>
            谱图记录 <span className="count-badge">{visibleRecords.length}</span>
          </h2>
        </div>
        <Database size={17} />
      </div>
      <label className="spectrum-angle-filter">
        <span>转角</span>
        <select value={angleFilter} onChange={(event) => setAngleFilter(event.target.value)}>
          <option value="all">全部（含未记录）</option>
          {angles.map((angle) => (
            <option value={String(angle)} key={angle}>
              {angle}°
            </option>
          ))}
        </select>
      </label>
      <div className="spectrum-record-list">
        {visibleRecords.map((record) => {
          const name = record.sample_name || record.band_name || record.id
          const metadata =
            record.kind !== 'result'
              ? `${record.ccd_count} CCD · ${record.points_per_ccd} 点 · ${record.angle_deg == null ? '转角未记录' : `${record.angle_deg}°`}`
              : `${record.sample_count} 样品 · ${record.line_count} 谱线`
          return (
            <div className={`spectrum-record-row ${record.id === selectedId ? 'active' : ''}`} key={record.id}>
              <label className="spectrum-overlay-check" title="加入多样品叠加">
                <input
                  type="checkbox"
                  checked={displayIds.includes(record.id)}
                  disabled={record.kind === 'result'}
                  onChange={() => toggleOverlay(record.id)}
                />
              </label>
              <button disabled={recordLocked && record.id !== selectedId} onClick={() => selectRecord(record)}>
                <span className={`spectrum-kind ${record.kind}`}>
                  {record.kind === 'sample'
                    ? '采集'
                    : record.kind !== 'result'
                      ? 'RAW'
                      : record.format.toUpperCase()}
                </span>
                <div>
                  <strong title={name}>{name}</strong>
                  <small title={metadata}>{metadata}</small>
                </div>
                <ChevronRight size={14} />
              </button>
            </div>
          )
        })}
      </div>
      <small className="spectrum-overlay-note"><SpectroscopyIcon name="multi-view" />可叠加 1–8 个原始样品；点击图例设置优先曲线。</small>
    </aside>
  )
}
