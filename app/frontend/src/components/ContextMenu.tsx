import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import './context-menu.css'

export type MenuItem = { label: string; run?: () => void; checked?: boolean; disabled?: boolean; children?: MenuGroup[] }
export type MenuGroup = MenuItem[]

export function useContextMenu<T>() {
  const [target, setTarget] = useState<{ x: number; y: number; element: Element; data: T } | null>(null)
  const open = (event: MouseEvent | KeyboardEvent, data: T) => {
    event.preventDefault()
    event.stopPropagation()
    const element = event.currentTarget
    const bounds = element.getBoundingClientRect()
    const x = 'clientX' in event && (event.clientX || event.clientY) ? event.clientX : bounds.left + 8
    const y = 'clientY' in event && (event.clientX || event.clientY) ? event.clientY : bounds.top + 8
    setTarget({ x, y, element, data })
  }
  const close = useCallback(() => setTarget(null), [])
  return { target, open, close }
}

export function ContextMenu({ target, groups, label, close }: {
  target: { x: number; y: number; element: Element }; groups: MenuGroup[]; label: string; close: () => void
}) {
  const root = useRef<HTMLDivElement>(null)
  const [submenu, setSubmenu] = useState<string | null>(null)
  const current = groups.flat().find(item => item.label === submenu && item.children)
  const visibleGroups = (current?.children ?? groups).filter(group => group.length)
  const focusOrigin = () => {
    if (target.element instanceof HTMLElement || target.element instanceof SVGElement) target.element.focus({ preventScroll: true })
  }
  useLayoutEffect(() => { setSubmenu(null) }, [target])
  useLayoutEffect(() => {
    const menu = root.current
    if (!menu) return
    const { width, height } = menu.getBoundingClientRect()
    menu.style.left = `${Math.max(4, Math.min(target.x, window.innerWidth - width - 4))}px`
    menu.style.top = `${Math.max(4, Math.min(target.y, window.innerHeight - height - 4))}px`
    menu.focus({ preventScroll: true })
  }, [target, current?.label, visibleGroups.map(group => group.length).join(',')])
  useEffect(() => {
    const outside = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) close()
    }
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('wheel', outside, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('pointerdown', outside, true)
      document.removeEventListener('wheel', outside, true)
      window.removeEventListener('resize', close)
    }
  }, [close])
  return createPortal(<div ref={root} className="workbench-context-menu" role="menu" aria-label={current?.label ?? label} tabIndex={-1}
    onContextMenu={event => { event.preventDefault(); event.stopPropagation() }} onClick={event => event.stopPropagation()}
    onKeyDown={event => {
      const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')]
      const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
      if (event.key === 'Tab') { close(); return }
      if (!['Escape', 'ArrowLeft', 'ArrowRight', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
      event.preventDefault(); event.stopPropagation()
      if (event.key === 'Escape' && !current) { close(); focusOrigin() }
      else if (event.key === 'ArrowLeft' || event.key === 'Escape') setSubmenu(null)
      else if (event.key === 'ArrowRight') { if (buttons[index]?.getAttribute('aria-haspopup') === 'menu') buttons[index].click() }
      else if (buttons.length) {
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
          : event.key === 'ArrowDown' ? (index + 1) % buttons.length : index <= 0 ? buttons.length - 1 : index - 1
        buttons[next].focus()
      }
    }}>
    {current && <button type="button" role="menuitem" onClick={() => setSubmenu(null)}><span aria-hidden="true">‹</span><span>返回</span></button>}
    {visibleGroups.map((group, index) => <div className="workbench-menu-group" role="group" key={index}>
      {group.map(item => <button type="button" key={item.label} role={item.checked === undefined ? 'menuitem' : 'menuitemcheckbox'}
        aria-checked={item.checked} aria-haspopup={item.children ? 'menu' : undefined} disabled={item.disabled} onClick={() => {
          if (item.children) setSubmenu(item.label)
          else { close(); focusOrigin(); item.run?.() }
        }}><span aria-hidden="true">{item.checked ? '✓' : ''}</span><span>{item.label}</span>{item.children && <span aria-hidden="true">›</span>}</button>)}
    </div>)}
  </div>, target.element.closest('dialog[open]') ?? target.element.closest('.app-shell') ?? document.body)
}
