import { analysisUnits } from './analysisUnits'
import { useId } from 'react'

export function AnalysisUnitSelect({ label, value, onChange, disabled }: {
  label: string; value: string; onChange: (value: string) => void; disabled: boolean
}) {
  const custom = !analysisUnits.includes(value)
  const id = useId()
  return <div className="field">
      <span id={id}>{label}</span>
      <select aria-label={label} value={custom ? '__custom__' : value} disabled={disabled}
        aria-labelledby={id}
        onChange={(event) => onChange(event.target.value === '__custom__' ? '' : event.target.value)}>
        {analysisUnits.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
        <option value="__custom__">自定义</option>
      </select>
    {custom && <input aria-label={`${label}自定义值`} value={value} maxLength={32} disabled={disabled}
      onChange={(event) => onChange(event.target.value)} />}
    {custom && <small>自定义单位不自动换算，请按该单位填写数值。</small>}
  </div>
}
