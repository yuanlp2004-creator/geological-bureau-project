import { ChevronDown, ChevronRight, LogOut, Maximize, Minimize, Moon, RefreshCw, Sun } from 'lucide-react'
import { type AuthUser, type CurrentMethodState } from '../api'
import { type NavigationEntry, type Page } from '../navigation'
import type { MethodShortcutAction } from '../pages/methods/methodShortcuts'
import type { Theme } from '../stores/themeStoreCore'
import { QuickAccessBar } from './QuickAccessBar'
import { hardwareLockStore, useHardwareLock } from '../stores/hardwareLockStore'

export function Header({
  activeEntry,
  onRefresh,
  loading,
  onNavigate,
  entries,
  onNavigateEntry,
  onMethodShortcut,
  onSwitchMethod,
  user,
  currentMethod,
  theme,
  onToggleTheme,
  focusMode,
  onToggleFocusMode,
  onLogout
}: {
  activeEntry?: NavigationEntry
  onRefresh: () => void
  loading: boolean
  onNavigate: (page: Page) => void | Promise<boolean>
  entries: NavigationEntry[]
  onNavigateEntry: (entry: NavigationEntry) => void | Promise<boolean>
  onMethodShortcut: (action: MethodShortcutAction) => void | Promise<boolean>
  onSwitchMethod: () => void | Promise<boolean>
  user: AuthUser
  currentMethod: CurrentMethodState | null
  theme: Theme
  onToggleTheme: () => void
  focusMode: boolean
  onToggleFocusMode: () => void
  onLogout: () => void
}) {
  const title = activeEntry?.label ?? '工作台'
  const canReadMethods = user.permissions.includes('methods.read')
  const method = canReadMethods ? currentMethod : null
  const paused = method?.method_id && method.status !== 'active'
  const methodStatus = `当前方法 · ${method?.work_type || '未选择'}${paused ? ' · 已暂停' : ''}`
  const methodTitle = canReadMethods ? method?.title || '请选择已发布方法' : '无方法读取权限'
  const hardware = useHardwareLock()
  const hardwareReason = hardware.operation || !['idle', 'connected_idle'].includes(hardware.status)
    ? hardwareLockStore.blockedReason() ?? undefined : undefined
  return (
    <>
    <header className="topbar">
      <div className="breadcrumbs">
        <span>GeoSpectrum</span>
        <ChevronRight size={13} />
        <strong>{title}</strong>
      </div>
      <div className="topbar-actions">
        <div className="workspace-method-split">
          <button type="button" className="workspace-method" onClick={() => onNavigate('methods')}
            disabled={!canReadMethods} title={`${methodStatus} · ${methodTitle}`}>
            <span>{methodStatus}</span>
            <strong>{methodTitle}</strong>
          </button>
          <button type="button" className="workspace-method-switch" aria-label="切换当前方法" aria-haspopup="dialog"
            title="快速打开并切换运行方法" aria-description={hardwareReason} onClick={onSwitchMethod} disabled={!user.permissions.includes('methods.write')}>
            <ChevronDown size={15} aria-hidden="true" />
          </button>
        </div>
        <button className="icon-button" title="刷新服务状态" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={17} className={loading ? 'spin' : ''} />
        </button>
        <button type="button" className="icon-button focus-mode-button" aria-label="切换专注模式"
          aria-pressed={focusMode} aria-keyshortcuts="Control+Shift+F"
          title={focusMode ? '退出专注模式 (Ctrl+Shift+F)' : '专注模式 (Ctrl+Shift+F)'} onClick={onToggleFocusMode}>
          {focusMode ? <Minimize size={16} aria-hidden="true" /> : <Maximize size={16} aria-hidden="true" />}
        </button>
        <button
          type="button"
          className="icon-button"
          title={theme === 'dark' ? '切换至浅色主题' : '切换至暗室深色主题'}
          aria-label="切换明暗主题"
          aria-pressed={theme === 'dark'}
          onClick={onToggleTheme}
        >
          {theme === 'dark' ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
        </button>
        <button className="icon-button" title="退出登录" aria-description={hardwareReason} onClick={onLogout}>
          <LogOut size={15} />
        </button>
        <button
          className="avatar"
          title={`${user.username} · ${user.roles.join(' / ') || '无角色'}`}
          onClick={() => onNavigate('about')}
        >
          {user.username.slice(0, 2).toUpperCase()}
        </button>
      </div>
    </header>
    <QuickAccessBar entries={entries} permissions={user.permissions} currentMethod={currentMethod}
      activeEntry={activeEntry} onNavigate={onNavigateEntry} onMethodShortcut={onMethodShortcut} />
    </>
  )
}
