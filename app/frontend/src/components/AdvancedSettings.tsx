import { type ReactNode } from 'react'
import './advanced-settings.css'

// 原生 details 保留挂载的输入与草稿，收起不重置参数。
export function AdvancedSettings({ title, children, className = '' }: {
  title: string
  children: ReactNode
  className?: string
}) {
  return (
    <details className={`advanced-settings ${className}`}
      onInvalidCapture={(event) => { event.currentTarget.open = true }}>
      <summary>{title}</summary>
      <div className="advanced-settings-body">{children}</div>
    </details>
  )
}
