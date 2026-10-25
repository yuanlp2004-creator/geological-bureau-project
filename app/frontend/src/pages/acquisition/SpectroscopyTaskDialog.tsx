import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

/** The page owns the draft; closing this dialog keeps its fields mounted. */
export function SpectroscopyTaskDialog({ open, title, busy, error, actions, onCancel, children }: {
  open: boolean
  title: string
  busy: boolean
  error?: string | null
  actions?: ReactNode
  onCancel: () => void
  children: ReactNode
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const previousFocus = useRef<Element | null>(null)
  const titleId = useId()
  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (open && !element.open) {
      previousFocus.current = document.activeElement
      element.showModal()
      element.querySelector<HTMLElement>('input:not(:disabled), select:not(:disabled)')?.focus()
    } else if (!open && element.open) {
      element.close()
      const previous = previousFocus.current
      if (previous instanceof HTMLElement && previous.isConnected && previous.getClientRects().length) previous.focus()
    }
  }, [open])
  useEffect(() => () => { dialog.current?.close() }, [])
  return <dialog ref={dialog} className="spectroscopy-task-dialog refined-page remaining-page"
    aria-labelledby={titleId} onCancel={event => { event.preventDefault(); if (!busy) onCancel() }}>
    <header><h2 id={titleId}>{title}</h2>
      <button type="button" className="icon-button" aria-label="取消新建任务" disabled={busy}
        onMouseDown={event => event.preventDefault()} onClick={onCancel}><X size={17} /></button>
    </header>
    <div className="spectroscopy-task-fields">
      {error && <p className="auth-error" role="alert">{error}</p>}
      {children}
    </div>
    <footer><button type="button" className="secondary-button" disabled={busy}
      onMouseDown={event => event.preventDefault()} onClick={onCancel}>取消</button>{actions}</footer>
  </dialog>
}
