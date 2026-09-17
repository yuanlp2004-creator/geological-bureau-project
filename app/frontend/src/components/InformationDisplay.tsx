import { Copy } from 'lucide-react'

type CopyableCodeProps = {
  value?: string | null
  visibleLength?: number
  empty?: string
  className?: string
}

export function CopyableCode({ value, visibleLength = 18, empty = '—', className = '' }: CopyableCodeProps) {
  const fullValue = value || ''
  if (!fullValue) return <code className={className}>{empty}</code>
  const visibleValue = fullValue.length > visibleLength ? `${fullValue.slice(0, visibleLength)}…` : fullValue
  return <button
    type="button"
    className={`copyable-code ${className}`.trim()}
    title={`${fullValue}\n点击复制完整内容`}
    aria-label={`复制完整内容：${fullValue}`}
    onClick={() => void navigator.clipboard.writeText(fullValue)}
  ><code>{visibleValue}</code><Copy size={11} aria-hidden="true" /></button>
}

type ExpandableValueProps = {
  value?: string | null
  summary?: string
  code?: boolean
  className?: string
}

export function ExpandableValue({ value, summary, code = false, className = '' }: ExpandableValueProps) {
  const fullValue = value || '—'
  const summaryValue = summary || fullValue
  const content = code ? <code>{fullValue}</code> : fullValue
  return <details className={`expandable-value ${className}`.trim()}>
    <summary title={fullValue}>{summaryValue}</summary>
    <div>{content}</div>
  </details>
}
