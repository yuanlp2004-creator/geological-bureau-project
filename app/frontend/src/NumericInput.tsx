import { useEffect, useId, useRef, useState, type FocusEvent, type InputHTMLAttributes, type KeyboardEvent } from 'react'
import { PARTIAL_NUMBER, validateNumericText } from './numericInputModel'

type CommonProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'defaultValue' | 'onChange' | 'min' | 'max' | 'step' | 'required'> & {
  min?: number | string
  max?: number | string
  step?: number | string
}

type RequiredNumericInputProps = CommonProps & {
  value: number
  required?: true
  onValueChange: (value: number) => void
}

type OptionalNumericInputProps = CommonProps & {
  value: number | null | undefined
  required: false
  onValueChange: (value: number | null) => void
}

export type NumericInputProps = RequiredNumericInputProps | OptionalNumericInputProps

export function reportInvalidNumericInput(root: ParentNode | null = document): boolean {
  const invalid = root?.querySelector<HTMLInputElement>('[data-numeric-input]:invalid:not(:disabled)')
  if (!invalid) return true
  invalid.focus()
  invalid.reportValidity()
  return false
}

function valueText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

export function NumericInput(props: NumericInputProps) {
  const {
    value,
    onValueChange,
    min,
    max,
    step,
    required = true,
    className,
    onBlur,
    onFocus,
    onKeyDown,
    'aria-describedby': describedBy,
    ...inputProps
  } = props
  const [text, setText] = useState(() => valueText(value))
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const editing = useRef(false)
  const focusValue = useRef<number | null>(typeof value === 'number' && Number.isFinite(value) ? value : null)
  const errorId = useId()

  const validationOptions = { min, max, step, required }
  const applyValidity = (nextText: string, reveal: boolean) => {
    const result = validateNumericText(nextText, validationOptions)
    inputRef.current?.setCustomValidity(result.message ?? '')
    if (reveal) setTouched(true)
    setError(result.message)
    return result
  }
  const commit = (nextText: string, reveal: boolean): boolean => {
    const result = applyValidity(nextText, reveal)
    if (result.message) return false
    if (result.value === null) {
      if (required === false) (onValueChange as (next: number | null) => void)(null)
    } else {
      (onValueChange as (next: number) => void)(result.value)
    }
    return true
  }

  useEffect(() => {
    if (!editing.current) setText(valueText(value))
  }, [value])

  useEffect(() => {
    const result = validateNumericText(text, validationOptions)
    inputRef.current?.setCustomValidity(result.message ?? '')
  }, [max, min, required, step, text])

  const handleFocus = (event: FocusEvent<HTMLInputElement>) => {
    editing.current = true
    focusValue.current = typeof value === 'number' && Number.isFinite(value) ? value : null
    setTouched(false)
    onFocus?.(event)
  }
  const handleBlur = (event: FocusEvent<HTMLInputElement>) => {
    editing.current = false
    commit(text, true)
    onBlur?.(event)
  }
  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    onKeyDown?.(event)
    if (event.defaultPrevented) return
    if (event.key === 'Enter') {
      event.preventDefault()
      if (!commit(text, true)) inputRef.current?.reportValidity()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      const restored = valueText(focusValue.current)
      setText(restored)
      setTouched(false)
      setError(null)
      inputRef.current?.setCustomValidity('')
      if (focusValue.current === null) {
        if (required === false) (onValueChange as (next: number | null) => void)(null)
      } else {
        (onValueChange as (next: number) => void)(focusValue.current)
      }
    }
  }

  const errorVisible = touched && error
  return <>
    <input
      {...inputProps}
      ref={inputRef}
      type="text"
      inputMode="decimal"
      className={[className, 'numeric-input', errorVisible ? 'numeric-input-invalid' : ''].filter(Boolean).join(' ')}
      value={text}
      required={required}
      aria-invalid={Boolean(errorVisible)}
      aria-describedby={[describedBy, errorVisible ? errorId : null].filter(Boolean).join(' ') || undefined}
      data-numeric-input="true"
      onFocus={handleFocus}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      onChange={(event) => {
        const nextText = event.target.value
        if (!PARTIAL_NUMBER.test(nextText.trim())) return
        setText(nextText)
        const result = applyValidity(nextText, false)
        if (!result.message && result.value !== null) (onValueChange as (next: number) => void)(result.value)
      }}
    />
    {errorVisible && <small className="numeric-input-error" id={errorId} role="alert">{error}</small>}
  </>
}
