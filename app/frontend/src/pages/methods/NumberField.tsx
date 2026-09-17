import { type InputHTMLAttributes } from 'react'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'

export function NumberField({ label, value, min, max, step = 1, disabled, onChange }: { label: string; value: number; min?: number; max?: number; step?: number; disabled?: InputHTMLAttributes<HTMLInputElement>['disabled']; onChange: (value: number) => void }) {
  return <label className="field"><span>{label}</span><EmptyableNumberInput value={value} min={min} max={max} step={step} disabled={disabled} onValueChange={onChange} /></label>
}
