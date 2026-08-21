export type NumericValidationOptions = {
  min?: number | string
  max?: number | string
  step?: number | string
  required?: boolean
}

export type NumericValidation = { value: number | null; message: string | null }

export const COMPLETE_NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
export const PARTIAL_NUMBER = /^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d*)?(?:[eE][+-]?\d*)?)?$/

function numericBound(value: number | string | undefined): number | null {
  if (value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function stepMismatch(value: number, min: number | null, step: number | string | undefined): boolean {
  if (step === undefined || step === 'any') return false
  const amount = Number(step)
  if (!Number.isFinite(amount) || amount <= 0) return false
  const quotient = (value - (min ?? 0)) / amount
  return Math.abs(quotient - Math.round(quotient)) > 1e-9 * Math.max(1, Math.abs(quotient))
}

export function validateNumericText(text: string, options: NumericValidationOptions): NumericValidation {
  const normalized = text.trim()
  if (normalized === '') {
    return options.required === false
      ? { value: null, message: null }
      : { value: null, message: '此项为必填项' }
  }
  if (!COMPLETE_NUMBER.test(normalized)) return { value: null, message: '请输入完整数字' }
  const value = Number(normalized)
  if (!Number.isFinite(value)) return { value: null, message: '请输入有限数字' }
  const min = numericBound(options.min)
  const max = numericBound(options.max)
  if (min !== null && value < min) return { value: null, message: `数值不能小于 ${min}` }
  if (max !== null && value > max) return { value: null, message: `数值不能大于 ${max}` }
  if (stepMismatch(value, min, options.step)) return { value: null, message: `请输入符合步进 ${options.step} 的数值` }
  return { value, message: null }
}
