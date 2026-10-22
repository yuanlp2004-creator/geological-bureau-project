import { Plus } from 'lucide-react'
import {
  type MethodLineCollection,
  type SpectralLine
} from '../../api'
import { lineTypeLabel } from './spectralLineDraft'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  listCollapsed: boolean
  collection: MethodLineCollection | null
  canWrite: boolean
  beginCreate: () => void
  busy: boolean
  sortBy: (key: "element" | "wavelength_nm") => void
  movable: SpectralLine[]
  selectedId: string | null
  creating: boolean
  edit: (line: SpectralLine) => void
}

export function SpectralLineList({
  listCollapsed,
  collection,
  canWrite,
  beginCreate,
  busy,
  sortBy,
  movable,
  selectedId,
  creating,
  edit,
}: PanelProps) {
  return (
    <section className="surface spectral-list-surface" id="method-spectral-list" hidden={listCollapsed}>
      <div className="surface-heading spectral-heading">
        <div>
          <h2>
            谱线清单 <span className="count-badge">{collection?.lines.length ?? 0}/300</span>
          </h2>
        </div>
        {canWrite && (
          <button className="primary-button" onClick={beginCreate} disabled={busy}>
            <Plus size={15} />
            添加谱线
          </button>
        )}
      </div>
      <div className="spectral-sortbar">
        <span>排序</span>
        <button onClick={() => sortBy('element')} disabled={!canWrite || busy || movable.length < 2}>
          按元素
        </button>
        <button onClick={() => sortBy('wavelength_nm')} disabled={!canWrite || busy || movable.length < 2}>
          按波长
        </button>
      </div>
      <div className="spectral-line-list">
        {collection?.lines.map((line) => (
          <button
            key={line.id}
            className={`spectral-line-card ${line.id === selectedId && !creating ? 'active' : ''} ${line.enabled ? '' : 'disabled'}`}
            onClick={() => edit(line)}
          >
            <span className={`line-type-mark ${line.line_type}`} />
            <span className="line-main">
              <strong title={`${line.element} ${line.wavelength_nm.toFixed(4)} nm`}>
                {line.element} <b>{line.wavelength_nm.toFixed(4)}</b> nm
              </strong>
              <small
                title={`${lineTypeLabel[line.line_type]} · ${line.detectability?.detectable ? `${line.detectability.ccd_label} / 角度位 ${line.detectability.angle_slot}` : line.detectability?.message}`}
              >
                {lineTypeLabel[line.line_type]} ·{' '}
                {line.detectability?.detectable
                  ? `${line.detectability.ccd_label} / 角度位 ${line.detectability.angle_slot}`
                  : line.detectability?.message}
              </small>
            </span>
            <span className="line-badges">
              {line.reference_baseline && <i>基线</i>}
              {line.critical_band && <i className="critical">关键</i>}
              {!line.enabled && <i className="off">停用</i>}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
