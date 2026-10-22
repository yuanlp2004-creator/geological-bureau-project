import {
  ArrowLeft,
  ArrowRight,
  Crosshair,
  Plus,
  RefreshCw,
  Save,
  Trash2
} from 'lucide-react'
import {
  type DispersionLine,
  type DispersionTask
} from '../../api'
import { NumericInput } from '../../components/NumericInput'
import { useEffect, useState } from 'react'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  locateAll: () => Promise<DispersionTask | undefined> | undefined
  canWrite: boolean
  active: DispersionTask
  element: string
  setElement: React.Dispatch<React.SetStateAction<string>>
  wavelength: number
  setWavelength: React.Dispatch<React.SetStateAction<number>>
  lineCcd: number
  setLineCcd: React.Dispatch<React.SetStateAction<number>>
  addLine: () => void | Promise<DispersionTask | undefined>
  updateLine: (line: DispersionLine, action: "locate" | "short" | "long" | "save" | "restore") => Promise<DispersionTask | undefined> | undefined
  removeLine: (lineId: number) => Promise<DispersionTask | undefined> | undefined
  changeWavelength: (lineId: number, wavelength: number) => void
  changeGap: (gap: number, gapUm: number) => void
}

export function DispersionLines({
  locateAll,
  canWrite,
  active,
  element,
  setElement,
  wavelength,
  setWavelength,
  lineCcd,
  setLineCcd,
  addLine,
  updateLine,
  removeLine,
  changeWavelength,
  changeGap,
}: PanelProps) {
  const [gap, setGap] = useState(0)
  const [increment, setIncrement] = useState(1)
  const [gapUm, setGapUm] = useState(0)
  useEffect(() => { setGapUm((active.layout.gap_points?.[gap] ?? 0) * active.layout.point_width_um) }, [active.id, active.layout, gap])
  return (
    <section className="surface dispersion-lines-panel">
      <div className="surface-heading">
        <div>
          <h2>谱线定位与位置</h2>
        </div>
        <button
          className="secondary-button"
          onClick={() => void locateAll()}
          disabled={!canWrite || active.lines.length === 0 || active.burn_frames_captured === 0}
        >
          <Crosshair size={15} />
          全部定位
        </button>
      </div>
      <div className="dispersion-line-form">
        <label className="field"><span>CCD 间隔</span><select value={gap} onChange={e => setGap(Number(e.target.value))}>
          {(active.layout.gap_points ?? []).map((_, index) => <option key={index} value={index}>CCD {index + 1}–{index + 2}</option>)}
        </select></label>
        <label className="field"><span>增量 (μm)</span><select value={increment} onChange={e => setIncrement(Number(e.target.value))}>
          {[1,2,5,10].map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="field"><span>间隔 (μm)</span><NumericInput min={0} max={10000} step={increment} value={gapUm} onValueChange={setGapUm} /></label>
        <button className="secondary-button" disabled={!canWrite || !active.layout.gap_points?.length || !['draft','completed','stopped','failed'].includes(active.status)}
          onClick={() => changeGap(gap, gapUm)}>应用间隔并重算</button>
      </div>
      {active.condition.original_layout_id != null && <p className="field-help">已生成修正后的 CCD 布局；发布色散后，方法请选择此布局与色散曲线。已有方法和结果保持。</p>}
      <div className="dispersion-line-form">
        <label className="field">
          <span>元素</span>
          <input value={element} onChange={(event) => setElement(event.target.value)} />
        </label>
        <label className="field">
          <span>波长 (nm)</span>
          <NumericInput min={0} step={0.0001} value={wavelength} onValueChange={setWavelength} />
        </label>
        <label className="field">
          <span>CCD</span>
          <select value={lineCcd} onChange={(event) => setLineCcd(Number(event.target.value))}>
            {active.ccd_indices.map((ccd) => (
              <option key={ccd} value={ccd}>
                CCD {ccd + 1}
              </option>
            ))}
          </select>
        </label>
        <button className="primary-button" onClick={() => void addLine()} disabled={!canWrite}>
          <Plus size={15} />
          添加
        </button>
      </div>
      <div className="dispersion-line-table">
        <table>
          <thead>
            <tr>
              <th>谱线</th>
              <th>CCD</th>
              <th>预期位置</th>
              <th>实测 / 保存</th>
              <th>定位操作</th>
            </tr>
          </thead>
          <tbody>
            {active.lines.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty-cell">
                  添加至少 3 条已知谱线后可拟合色散曲线。
                </td>
              </tr>
            ) : (
              active.lines.map((line) => (
                <tr key={line.id}>
                  <td>
                    <strong>{line.element}</strong>
                    <WavelengthEdit key={`${line.id}-${line.wavelength_nm}`} line={line} disabled={!canWrite} save={changeWavelength} />
                  </td>
                  <td>CCD {line.ccd_index + 1}</td>
                  <td>{line.expected_position?.toFixed(2) ?? '越界'}</td>
                  <td>
                    <strong>{line.located_position?.toFixed(2) ?? '--'}</strong>
                    <small>保存 {line.saved_position?.toFixed(2) ?? '--'}</small>
                  </td>
                  <td>
                    <div className="line-actions">
                      <button
                        title="定位"
                        onClick={() => void updateLine(line, 'locate')}
                        disabled={!canWrite || active.burn_frames_captured === 0}
                      >
                        <Crosshair size={14} />
                      </button>
                      <button
                        title="向短波移动"
                        onClick={() => void updateLine(line, 'short')}
                        disabled={!canWrite}
                      >
                        <ArrowLeft size={14} />
                      </button>
                      <button
                        title="向长波移动"
                        onClick={() => void updateLine(line, 'long')}
                        disabled={!canWrite}
                      >
                        <ArrowRight size={14} />
                      </button>
                      <button
                        title="保存实测位置"
                        onClick={() => void updateLine(line, 'save')}
                        disabled={!canWrite || line.located_position === null}
                      >
                        <Save size={14} />
                      </button>
                      <button
                        title="恢复保存位置"
                        onClick={() => void updateLine(line, 'restore')}
                        disabled={!canWrite || line.saved_position === null}
                      >
                        <RefreshCw size={14} />
                      </button>
                      <button title="删除谱线" onClick={() => void removeLine(line.id)} disabled={!canWrite}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function WavelengthEdit({line,disabled,save}: {line: DispersionLine;disabled: boolean;save: (id: number,value: number) => void}) {
  const [value,setValue] = useState(line.wavelength_nm)
  return <div className="line-actions"><NumericInput aria-label={`${line.element} 波长`} min={0.0001} max={2000} step={0.0001}
    value={value} onValueChange={setValue} disabled={disabled} />
    <button title="保存波长" disabled={disabled || value === line.wavelength_nm} onClick={() => save(line.id,value)}><Save size={14}/></button></div>
}
