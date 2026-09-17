import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, RefreshCw, ClipboardList } from 'lucide-react'
import { api, type AuditEvent } from '../../api'
import { ExpandableValue } from '../../components/InformationDisplay'
import { formatTime } from '../../components/dateFormat'

export function AuditPage({ token }: { token: string }) {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    try { setEvents(await api.audit(token)); setError(null) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取审计记录') }
    finally { setLoading(false) }
  }, [token])
  useEffect(() => { void load() }, [load])
  return <div className="page-content auth-page refined-page remaining-page"><section className="hero-row compact-hero"><div><h1>审计记录</h1><p>账户、角色、权限和登录事件按时间倒序保存在本地数据库。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? '刷新中…' : '刷新'}</button></section><section className="surface auth-section audit-section"><div className="surface-heading"><div><h2>变更记录 <span className="count-badge">{events.length}</span></h2></div><ClipboardList size={17} /></div>{error ? <div className="auth-error"><AlertTriangle size={15} />{error}</div> : <div className="auth-table-wrap"><table className="auth-table audit-table"><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>详情</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>{formatTime(event.created_at)}</td><td>{event.actor_user_id ?? 'system'}</td><td><strong>{event.action}</strong></td><td>{event.target_type} {event.target_id ?? ''}</td><td><ExpandableValue value={event.details_json} summary={event.details_json} code className="audit-details" /></td></tr>)}</tbody></table></div>}</section></div>
}
