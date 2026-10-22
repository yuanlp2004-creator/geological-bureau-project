import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import './open-legacy-file.css'

/** Embedded workspaces put actions in their owning page's header. */
export function PageFileActions({ children, target, hidden = false }: {
  children: ReactNode; target?: HTMLElement | null; hidden?: boolean
}) {
  if (hidden) return null
  const actions = <div className="file-actions">{children}</div>
  return target ? createPortal(actions, target) : actions
}
