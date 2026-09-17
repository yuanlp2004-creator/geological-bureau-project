import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, ChevronRight, CircleHelp, FileBarChart, LayoutDashboard, Settings2, SlidersHorizontal, Sparkles, TestTube2, Wrench } from 'lucide-react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { type CurrentMethodState } from '../api'
import { groupedNavigation, navigationAvailability, type NavigationEntry, type NavigationGroupId } from '../navigation'

const navigationGroupIcons: Record<NavigationGroupId, typeof LayoutDashboard> = {
  workspace: LayoutDashboard,
  methods: SlidersHorizontal,
  'analysis-tests': TestTube2,
  data: FileBarChart,
  tools: Wrench,
  system: Settings2,
  help: CircleHelp,
}

export function Sidebar({ activeEntry, entries, onNavigate, currentMethod, health, showStatusBar, onToast }: { activeEntry?: NavigationEntry; entries: NavigationEntry[]; onNavigate: (entry: NavigationEntry) => void; currentMethod: CurrentMethodState | null; health: 'online' | 'offline'; showStatusBar: boolean; onToast: (message: string) => void }) {
  const [hoveredGroup, setHoveredGroup] = useState<NavigationGroupId | null>(null)
  const [pinnedGroup, setPinnedGroup] = useState<NavigationGroupId | null>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const openTimer = useRef<number | null>(null)
  const closeTimer = useRef<number | null>(null)
  const groups = useMemo(() => groupedNavigation(entries), [entries])
  const openGroup = pinnedGroup ?? hoveredGroup
  const opened = groups.find((group) => group.id === openGroup)

  const clearTimers = () => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current)
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
    openTimer.current = null
    closeTimer.current = null
  }
  const scheduleOpen = (group: NavigationGroupId) => {
    if (pinnedGroup) return
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current)
    openTimer.current = window.setTimeout(() => setHoveredGroup(group), 250)
  }
  const scheduleClose = () => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current)
    if (!pinnedGroup) closeTimer.current = window.setTimeout(() => setHoveredGroup(null), 200)
  }
  const closeMenu = () => { clearTimers(); setHoveredGroup(null); setPinnedGroup(null) }
  const toggleGroup = (group: NavigationGroupId) => {
    clearTimers()
    setHoveredGroup(null)
    setPinnedGroup((current) => current === group ? null : group)
  }
  const activate = (entry: NavigationEntry) => {
    const availability = navigationAvailability(entry, currentMethod)
    if (availability.disabled) { onToast(availability.reason ?? '当前入口不可用'); return }
    onNavigate(entry)
    if (!pinnedGroup) setHoveredGroup(null)
  }
  const focusFirstEntry = (group: NavigationGroupId) => {
    setPinnedGroup(group)
    setHoveredGroup(null)
    window.setTimeout(() => document.querySelector<HTMLButtonElement>(`#navigation-panel-${group} .navigation-entry`)?.focus(), 0)
  }
  const handleGroupKey = (event: ReactKeyboardEvent<HTMLButtonElement>, group: NavigationGroupId) => {
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') { event.preventDefault(); focusFirstEntry(group) }
    if (event.key === 'Escape') closeMenu()
  }
  const handleEntryKey = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const buttons = Array.from(event.currentTarget.closest('.navigation-panel')?.querySelectorAll<HTMLButtonElement>('.navigation-entry') ?? [])
    const index = buttons.indexOf(event.currentTarget)
    if (event.key === 'ArrowDown') { event.preventDefault(); buttons[(index + 1) % buttons.length]?.focus() }
    if (event.key === 'ArrowUp') { event.preventDefault(); buttons[(index - 1 + buttons.length) % buttons.length]?.focus() }
    if (event.key === 'Escape') { event.preventDefault(); const group = openGroup; closeMenu(); document.querySelector<HTMLButtonElement>(`[data-navigation-group="${group}"]`)?.focus() }
  }

  useEffect(() => {
    const outside = (event: PointerEvent) => { if (!sidebarRef.current?.contains(event.target as Node)) closeMenu() }
    document.addEventListener('pointerdown', outside)
    return () => { document.removeEventListener('pointerdown', outside); clearTimers() }
  }, [])

  return <aside className="sidebar" ref={sidebarRef}>
    <div className="brand"><div className="brand-mark"><Sparkles size={19} /></div><div><strong>GeoSpectrum</strong><span>地质光谱分析平台</span></div></div>
    <div className="sidebar-section-label">功能导航</div>
    <div className="navigation-shell" onMouseEnter={() => { if (closeTimer.current !== null) window.clearTimeout(closeTimer.current) }} onMouseLeave={scheduleClose}>
      <nav className="nav-list" aria-label="业务域导航">{groups.map((group) => {
        const Icon = navigationGroupIcons[group.id]
        const direct = group.id === 'workspace' ? group.entries[0] : null
        const active = activeEntry?.group === group.id
        const groupOpened = opened?.id === group.id && group.id !== 'workspace'
        return <div key={group.id} className={`navigation-group-item ${groupOpened ? 'open' : ''}`}>
          <button type="button" data-navigation-group={group.id} className={`nav-item navigation-group ${active ? 'active' : ''} ${openGroup === group.id ? 'open' : ''}`} aria-expanded={direct ? undefined : openGroup === group.id} aria-controls={direct ? undefined : `navigation-panel-${group.id}`} aria-current={direct && active ? 'page' : undefined} onMouseEnter={() => scheduleOpen(group.id)} onClick={() => direct ? activate(direct) : toggleGroup(group.id)} onKeyDown={(event) => handleGroupKey(event, group.id)} title={group.description}><Icon size={17} /><span>{group.label}</span>{!direct && <ChevronRight size={14} className="navigation-chevron" />}</button>
          {groupOpened && <div id={`navigation-panel-${group.id}`} className="navigation-panel" role="menu" aria-label={group.label} onMouseEnter={() => { if (closeTimer.current !== null) window.clearTimeout(closeTimer.current) }}>
            <div className="navigation-panel-scroll">{group.entries.map((entry, index) => {
              const previous = group.entries[index - 1]
              const availability = navigationAvailability(entry, currentMethod)
              const sectionChanged = entry.section_label && entry.section_label !== previous?.section_label
              return <div key={entry.key}>{sectionChanged && <div className="navigation-section-label">{entry.section_label}</div>}<button type="button" role="menuitem" className={`navigation-entry ${activeEntry?.key === entry.key ? 'active' : ''} ${availability.disabled ? 'disabled' : ''}`} aria-current={activeEntry?.key === entry.key ? 'page' : undefined} aria-disabled={availability.disabled} title={availability.reason ?? entry.description} onKeyDown={handleEntryKey} onClick={() => activate(entry)}><span><strong>{entry.label}</strong><small>{availability.reason ?? entry.description}</small></span>{entry.status === 'deferred_external' && <em>需真实设备</em>}<ChevronRight size={13} /></button></div>
            })}</div>
            {group.entries.some((entry) => navigationAvailability(entry, currentMethod).reason?.includes('当前方法')) && <button type="button" className="navigation-method-shortcut" onClick={() => { const methodEntry = entries.find((entry) => entry.key === 'methods.lifecycle'); if (methodEntry) { closeMenu(); onNavigate(methodEntry) } }}><SlidersHorizontal size={14} />选择当前方法</button>}
          </div>}
        </div>
      })}</nav>
    </div>
    <div className="sidebar-spacer" />
    {showStatusBar && <div className="side-status"><span className={`status-dot ${health}`} /><div><span>本地服务</span><strong>{health === 'online' ? '已连接' : '等待连接'}</strong></div><Activity size={15} /></div>}
    <div className="sidebar-method-state"><span>当前方法</span><strong title={currentMethod?.title ?? '尚未选择当前方法'}>{currentMethod?.method_id ? `${currentMethod.title}${currentMethod.status === 'active' ? '' : ' · 已暂停'}` : '尚未选择'}</strong></div>
    {showStatusBar && <div className="sidebar-footer"><span>桌面基础</span><span>v0.1.0</span></div>}
  </aside>
}
