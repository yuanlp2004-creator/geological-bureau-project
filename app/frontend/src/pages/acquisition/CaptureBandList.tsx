import { useContext } from 'react'
import { LegacyDeskDock } from './legacyDesk'

type RecordRow = { id: number; name: string; detail: string; sequence?: number }
export function CaptureBandList({ title, rows, selected, disabled, onChoose, variant = 'sample' }:
  { title: string; rows: RecordRow[]; selected: number | null; disabled: boolean;
    onChoose: (id: number | null) => void; variant?: 'sample' | 'band' }) {
  const dock = useContext(LegacyDeskDock)
  return <aside className="spectroscopy-records" data-record-kind={variant} aria-label={title}>
    <header className="legacy-dock-caption"><h2>{title}</h2>{dock.closeRecords && <button type="button" className="legacy-dock-close" aria-label="隐藏样品面板" onClick={dock.closeRecords}>×</button>}</header>
    <div className="capture-record-table"><table><colgroup><col className="record-indicator"/>{variant === 'sample' && <col className="record-number"/>}<col className="record-name"/>{variant === 'sample' && <col className="record-sequence"/>}</colgroup>
      <thead><tr><th aria-label="当前记录"/>{variant === 'sample' ? <><th>记录号</th><th>样品编号</th><th>样品序号</th></> : <th>谱带名称</th>}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.id} aria-selected={selected === row.id}>
        <td className="record-indicator">{selected === row.id && <i />}</td>{variant === 'sample' && <td>{index + 1}</td>}<td><button type="button" title={`${row.name} · ${row.detail}`}
          aria-pressed={selected === row.id} disabled={disabled} onClick={() => onChoose(row.id)}>
          <strong>{row.name}</strong>{variant === 'band' && <small>{row.detail}</small>}</button></td>{variant === 'sample' && <td title={row.detail}>{row.sequence ?? index + 1}</td>}
      </tr>)}{!rows.length && <tr className="legacy-empty-record"><td className="record-indicator"><i /></td><td/>{variant === 'sample' && <><td/><td/></>}</tr>}</tbody></table></div>
    {selected !== null && rows.some(row => row.id === selected) && <button type="button" className="capture-record-return"
      disabled={disabled} onClick={() => onChoose(null)}>返回当前谱图</button>}
    <div className="legacy-record-footer" />
  </aside>
}
