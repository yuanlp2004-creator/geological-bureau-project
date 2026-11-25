import { ChevronRight, LogOut, Moon, RefreshCw, Sun } from 'lucide-react'
import { type AuthUser, type CurrentMethodState } from '../api'
import { type NavigationEntry, type Page } from '../navigation'
import type { MethodShortcutAction } from '../pages/methods/methodShortcuts'
import type { Theme } from '../stores/themeStoreCore'
import { QuickAccessBar } from './QuickAccessBar'

export function Header({
  activeEntry,
  extensionTitle,
  onRefresh,
  loading,
  onNavigate,
  entries,
  onNavigateEntry,
  onMethodShortcut,
  user,
  currentMethod,
  theme,
  onToggleTheme,
  onLogout
}: {
  activeEntry?: NavigationEntry
  extensionTitle?: string
  onRefresh: () => void
  loading: boolean
  onNavigate: (page: Page) => void
  entries: NavigationEntry[]
  onNavigateEntry: (entry: NavigationEntry) => void
  onMethodShortcut: (action: MethodShortcutAction) => void
  user: AuthUser
  currentMethod: CurrentMethodState | null
  theme: Theme
  onToggleTheme: () => void
  onLogout: () => void
}) {
  const title = activeEntry?.page === 'extension' ? (extensionTitle ?? '测试模块') : (activeEntry?.label ?? '工作台')
  const paused = currentMethod?.method_id && currentMethod.status !== 'active'
  const methodStatus = `当前方法 · ${currentMethod?.work_type || '未选择'}${paused ? ' · 已暂停' : ''}`
  return (
    <>
    <header className="topbar">
      <div className="breadcrumbs">
        <span>GeoSpectrum</span>
        <ChevronRight size={13} />
        <strong>{title}</strong>
      </div>
      <div className="topbar-actions">
        <button
          className="workspace-method"
          onClick={() => onNavigate('methods')}
          disabled={!user.permissions.includes('methods.read')}
          title={`${methodStatus} · ${currentMethod?.title || '请选择已发布方法'}`}
        >
          <span>{methodStatus}</span>
          <strong>{currentMethod?.title || '请选择已发布方法'}</strong>
        </button>
        <button className="icon-button" title="刷新服务状态" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={17} className={loading ? 'spin' : ''} />
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
        <button className="icon-button" title="退出登录" onClick={onLogout}>
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
