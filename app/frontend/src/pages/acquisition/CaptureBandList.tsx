import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'
import { useContext } from 'react'
import { LegacyDeskDock } from './legacyDesk'

type RecordRow = { id: number; name: string; detail: string; sequence?: number }
export function CaptureBandList({ title, rows, selected, locked, disabled, onChoose, onLockChange }:
  { title: string; rows: RecordRow[]; selected: number | null; locked: boolean; disabled: boolean;
    onChoose: (id: number | null) => void; onLockChange: (value: boolean) => void }) {
  const dock = useContext(LegacyDeskDock)
  return <aside className="spectroscopy-records" aria-label={title}>
    <header className="legacy-dock-caption"><h2>{title}</h2>{dock.closeRecords && <button type="button" className="legacy-dock-close" aria-label="隐藏样品面板" onClick={dock.closeRecords}>×</button>}</header>
    <div className="capture-record-toolbar"><SpectroscopyToolButton icon="sample-list-input" label="显示最新谱带"
      disabled={locked || disabled || !rows.length} onClick={() => onChoose(rows[rows.length - 1]?.id ?? null)} />
      <SpectroscopyToolButton icon="sample-list-clear" label="返回实时谱图" disabled={locked || disabled || !rows.length} onClick={() => onChoose(null)} />
      <SpectroscopyToolButton icon={locked ? 'record-unlock' : 'record-lock'}
      label={locked ? '解锁谱带记录' : '锁定谱带记录'} aria-pressed={locked}
      disabled={disabled || !rows.length} onClick={() => onLockChange(!locked)} /></div>
    <div className="capture-record-table"><table><colgroup><col className="record-indicator"/><col className="record-number"/><col className="record-name"/><col className="record-sequence"/></colgroup><thead><tr><th aria-label="当前记录"/><th>记录号</th><th>样品编号</th><th>样品序号</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.id} aria-selected={selected === row.id}>
        <td className="record-indicator">{selected === row.id && <i />}</td><td>{index + 1}</td><td><button type="button" title={`${row.name} · ${row.detail}`}
          aria-pressed={selected === row.id} disabled={locked || disabled} onClick={() => onChoose(row.id)}>
          <strong>{row.name}</strong></button></td><td title={row.detail}>{row.sequence ?? index + 1}</td>
      </tr>)}{!rows.length && <tr className="legacy-empty-record"><td className="record-indicator"><i /></td><td/><td/><td/></tr>}</tbody></table></div>
    <div className="legacy-record-footer" />
  </aside>
}
