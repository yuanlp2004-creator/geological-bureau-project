import { useEffect, useRef, useState } from 'react'

type Props = {
  start: number
  end: number
  max: number
  disabled?: boolean
  onCommit: (start: number, end: number) => void
}

export function ExposureIntervalInput({ start, end, max, disabled, onCommit }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState('')

  const clear = () => {
    setDraft(null)
    setError('')
    input.current?.setCustomValidity('')
  }
  useEffect(clear, [start, end])

  const commit = (showError = false) => {
    if (disabled || draft === null) return
    const match = draft.match(/^\s*(\d+)\s*[-–－]\s*(\d+)\s*$/)
    const nextStart = Number(match?.[1]), nextEnd = Number(match?.[2])
    if (!match || !Number.isSafeInteger(nextEnd) || nextStart < 1 || nextStart > nextEnd || nextEnd > max) {
      const message = `请输入有效的曝光区间（例如 1-${max}）`
      setError(message)
      input.current?.setCustomValidity(message)
      if (showError) input.current?.reportValidity()
      return
    }
    clear()
    if (nextStart !== start || nextEnd !== end) onCommit(nextStart, nextEnd)
  }

  return <input ref={input} type="text" aria-label="曝光区间" data-observation-input="true"
    aria-invalid={Boolean(error)} title={error || '输入起止帧，例如 1-20，按回车生效'}
    value={draft ?? `${start}-${end}`} disabled={disabled} onBlur={() => commit()}
    onChange={event => {
      setDraft(event.currentTarget.value)
      setError('')
      event.currentTarget.setCustomValidity('')
    }}
    onKeyDown={event => {
      if (event.nativeEvent.isComposing) return
      if (event.key === 'Enter') { event.preventDefault(); commit(true) }
      if (event.key === 'Escape') { event.preventDefault(); clear() }
    }} />
}
