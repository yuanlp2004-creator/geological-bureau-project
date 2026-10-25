import { SpectroscopyToolButton } from '../../components/SpectroscopyToolButton'

type RecordRow = { id: number; name: string; detail: string }
export function CaptureBandList({ title, rows, selected, locked, disabled, onChoose, onLockChange }:
  { title: string; rows: RecordRow[]; selected: number | null; locked: boolean; disabled: boolean;
    onChoose: (id: number | null) => void; onLockChange: (value: boolean) => void }) {
  return <aside className="spectroscopy-records" aria-label={title}>
    <header><h2>{title}</h2><SpectroscopyToolButton icon={locked ? 'record-unlock' : 'record-lock'}
      label={locked ? '解锁谱带记录' : '锁定谱带记录'} aria-pressed={locked}
      disabled={disabled || !rows.length} onClick={() => onLockChange(!locked)} /></header>
    <button type="button" className={`capture-live-record ${selected === null ? 'active' : ''}`}
      aria-pressed={selected === null} disabled={locked || disabled} onClick={() => onChoose(null)}>实时 / 最新帧</button>
    <div className="capture-record-table"><table><thead><tr><th>记录号</th><th>样品 / 谱带</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.id} aria-selected={selected === row.id}>
        <td>{index + 1}</td><td><button type="button" title={`${row.name} · ${row.detail}`}
          aria-pressed={selected === row.id} disabled={locked || disabled} onClick={() => onChoose(row.id)}>
          <strong>{row.name}</strong><small>{row.detail}</small></button></td>
      </tr>)}</tbody></table>{!rows.length && <p className="capture-record-empty">摄谱完成后显示已保存记录</p>}</div>
  </aside>
}
