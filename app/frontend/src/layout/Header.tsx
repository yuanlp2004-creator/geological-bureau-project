import { ChevronRight, LogOut, RefreshCw } from 'lucide-react'
import { type AuthUser, type CurrentMethodState } from '../api'
import { type NavigationEntry, type Page } from '../navigation'

export function Header({ activeEntry, extensionTitle, onRefresh, loading, onNavigate, user, currentMethod, onLogout }: { activeEntry?: NavigationEntry; extensionTitle?: string; onRefresh: () => void; loading: boolean; onNavigate: (page: Page) => void; user: AuthUser; currentMethod: CurrentMethodState | null; onLogout: () => void }) {
  const title = activeEntry?.page === 'extension' ? extensionTitle ?? '测试模块' : activeEntry?.label ?? '工作台'
  return <header className="topbar">
    <div className="breadcrumbs"><span>GeoSpectrum</span><ChevronRight size={13} /><strong>{title}</strong></div>
    <div className="topbar-actions"><button className="workspace-method" onClick={() => onNavigate('methods')} disabled={!user.permissions.includes('methods.read')} title={`当前方法 · ${currentMethod?.work_type || '未选择'} · ${currentMethod?.title || '请选择已发布方法'}`}><span>当前方法 · {currentMethod?.work_type || '未选择'}</span><strong>{currentMethod?.title || '请选择已发布方法'}</strong></button><button className="icon-button" title="刷新服务状态" onClick={onRefresh} disabled={loading}><RefreshCw size={17} className={loading ? 'spin' : ''} /></button><button className="icon-button" title="退出登录" onClick={onLogout}><LogOut size={15} /></button><button className="avatar" title={`${user.username} · ${user.roles.join(' / ') || '无角色'}`} onClick={() => onNavigate('about')}>{user.username.slice(0, 2).toUpperCase()}</button></div>
  </header>
}
