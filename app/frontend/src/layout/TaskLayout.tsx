import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'

/** Presentation only: collapsing never unmounts task controls or editable fields. */
export function TaskLayout({ className, hasItems, current, children }: { className: string; hasItems: boolean; current: string; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const id = useId()
  return <div className="task-layout">
    {hasItems && <div className="task-context"><button className="secondary-button" aria-expanded={!collapsed} aria-controls={id} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}{collapsed ? '展开列表' : '收起列表'}</button><strong title={current}>{current}</strong></div>}
    <div id={id} className={`${className} task-columns ${collapsed || !hasItems ? 'rail-hidden' : ''}`}>{children}</div>
  </div>
}

export function FormDisclosure({ title, hasItems = true, objectKey, error, children }: { title: string; hasItems?: boolean; objectKey?: string | number; error?: string | null; children: ReactNode }) {
  const [open, setOpen] = useState(!hasItems)
  const interacted = useRef(false)
  const previousKey = useRef(objectKey)
  const id = useId()
  useLayoutEffect(() => {
    // Initial data arriving must not close a form the user has already opened.
    if (!interacted.current || (previousKey.current !== undefined && previousKey.current !== objectKey)) setOpen(!hasItems)
    previousKey.current = objectKey
  }, [hasItems, objectKey])
  return <div className="form-disclosure">
    <button type="button" className="secondary-button disclosure-toggle" aria-expanded={open} aria-controls={id} onClick={() => { interacted.current = true; setOpen(!open) }}>{open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}{title}</button>
    {error && <div className="auth-error" role="alert">{error}{!open && <button className="secondary-button" onClick={() => setOpen(true)}>展开并修正</button>}</div>}
    <div id={id} hidden={!open} className="disclosure-body" onInvalidCapture={() => setOpen(true)}>{children}</div>
  </div>
}
