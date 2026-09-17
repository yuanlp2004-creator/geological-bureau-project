import { FormDisclosure } from '../../layout/TaskLayout'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Check, LogOut, RefreshCw, ShieldCheck, UserCog, UserPlus } from 'lucide-react'
import { api, type AuthUser, type ManagedRole, type ManagedUser } from '../../api'

export function UsersPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [roles, setRoles] = useState<ManagedRole[]>([])
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [roleId, setRoleId] = useState('')
  const [roleName, setRoleName] = useState('')
  const [rolePermissions, setRolePermissions] = useState('')
  const canWriteUsers = currentUser.permissions.includes('users.write')
  const canWriteRoles = currentUser.permissions.includes('roles.write')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextUsers, nextRoles] = await Promise.all([api.users(token), api.roles(token)])
      setUsers(nextUsers)
      setRoles(nextRoles)
      setRoleId((current) => current || (nextRoles[0] ? String(nextRoles[0].id) : ''))
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取用户和角色') }
    finally { setLoading(false) }
  }, [onToast, token])
  useEffect(() => { void load() }, [load])

  const createUser = async (event: FormEvent) => {
    event.preventDefault()
    try {
      await api.createUser(token, { username, password, role_ids: roleId ? [Number(roleId)] : [] })
      setUsername(''); setPassword(''); await load(); onToast('用户已创建并写入审计记录')
    } catch (error) { onToast(error instanceof Error ? error.message : '创建用户失败') }
  }
  const toggleUser = async (item: ManagedUser) => {
    try { await api.updateUser(token, item.id, { enabled: !item.enabled }); await load(); onToast('用户状态已更新') }
    catch (error) { onToast(error instanceof Error ? error.message : '更新用户失败') }
  }
  const createRole = async (event: FormEvent) => {
    event.preventDefault()
    try {
      await api.createRole(token, { name: roleName, description: 'Local custom role', permission_keys: rolePermissions.split(',').map((key) => key.trim()).filter(Boolean) })
      setRoleName(''); setRolePermissions(''); await load(); onToast('角色已创建并写入审计记录')
    } catch (error) { onToast(error instanceof Error ? error.message : '创建角色失败') }
  }

  return <div className="page-content auth-page refined-page remaining-page"><section className="hero-row compact-hero"><div><h1>用户与权限</h1><p>管理本机账户、角色授权和启用状态。每次变更都会留下审计记录。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? '刷新中…' : '刷新'}</button></section><div className="auth-grid"><section className="surface auth-section"><div className="surface-heading"><div><h2>账户列表 <span className="count-badge">{users.length}</span></h2></div><UserCog size={17} /></div><div className="auth-table-wrap"><table className="auth-table"><thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>{users.map((item) => <tr key={item.id}><td><strong>{item.username}</strong><small>{item.username === currentUser.username ? '当前会话' : `ID ${item.id}`}</small></td><td>{item.roles.length ? item.roles.map((role) => <span className="role-chip" key={role}>{role}</span>) : <span className="muted">无角色</span>}</td><td><span className={`state-chip ${item.enabled ? 'enabled' : 'disabled'}`}>{item.enabled ? '已启用' : '已停用'}</span></td><td>{canWriteUsers && item.id !== currentUser.id && <button className="icon-button compact" title={item.enabled ? '停用用户' : '启用用户'} onClick={() => void toggleUser(item)}>{item.enabled ? <LogOut size={14} /> : <Check size={14} />}</button>}</td></tr>)}</tbody></table></div></section><section className="surface auth-section"><div className="surface-heading"><div><h2>角色与权限</h2></div><ShieldCheck size={17} /></div><FormDisclosure title="查阅角色与权限"><div className="role-list">{roles.map((role) => <div className="role-row" key={role.id}><div><strong>{role.name}</strong><small>{role.description}{role.built_in ? ' · 系统内置' : ''}</small></div><code>{role.permission_keys.join('、') || '无权限'}</code></div>)}</div></FormDisclosure>{canWriteUsers && <FormDisclosure title="创建用户" objectKey={users.length}><form className="inline-form" onSubmit={createUser}><label className="field"><span>用户名</span><input value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label className="field"><span>初始密码</span><input type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required /></label><label className="field"><span>角色</span><select value={roleId} onChange={(event) => setRoleId(event.target.value)}><option value="">无角色</option>{roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label><button className="primary-button" type="submit"><UserPlus size={15} />创建用户</button></form></FormDisclosure>}{canWriteRoles && <FormDisclosure title="创建角色" objectKey={roles.length}><form className="inline-form role-create-form" onSubmit={createRole}><label className="field"><span>角色名称</span><input value={roleName} onChange={(event) => setRoleName(event.target.value)} required /></label><label className="field"><span>权限键（逗号分隔）</span><input value={rolePermissions} onChange={(event) => setRolePermissions(event.target.value)} placeholder="audit.read, results.read" /></label><button className="secondary-button" type="submit"><ShieldCheck size={15} />创建角色</button></form></FormDisclosure>}</section></div></div>
}
