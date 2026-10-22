import { SectionHeading } from '../../components/SectionHeading'
import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import { Check, LogOut, RefreshCw, ShieldCheck, UserCog, UserPlus } from 'lucide-react'
import { api, type AuthUser, type Capability, type ManagedRole, type ManagedUser } from '../../api'
import { PermissionPicker, permissionGroupLabel, permissionLabel } from './PermissionPicker'

const builtinLabels: Record<string, { name: string; purpose: string }> = {
  system_administrator: { name: '系统管理员', purpose: '管理账户、系统设置、设备与全部业务功能。' },
  method_administrator: { name: '方法管理员', purpose: '管理方法、谱线、旧方法迁移与色散校准。' },
  analyst: { name: '分析员', purpose: '执行摄谱、分析、质控、数据后处理与报告。' },
  read_only_auditor: { name: '只读审计员', purpose: '查阅及导出已有结果、谱图与审计记录。' }
}
const roleLabel = (name: string) => builtinLabels[name]?.name ?? name

export function UsersPage({
  token,
  currentUser,
  onToast
}: {
  token: string
  currentUser: AuthUser
  onToast: (message: string) => void
}) {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [roles, setRoles] = useState<ManagedRole[]>([])
  const [loading, setLoading] = useState(false)
  const [creatingUser, setCreatingUser] = useState(false)
  const [creatingRole, setCreatingRole] = useState(false)
  const [showUserForm, setShowUserForm] = useState(false)
  const [showRoleForm, setShowRoleForm] = useState(false)
  const [templateId, setTemplateId] = useState('')
  const [roleDraftInitialized, setRoleDraftInitialized] = useState(false)
  const userFormId = useId()
  const roleFormId = useId()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [roleId, setRoleId] = useState('')
  const [roleName, setRoleName] = useState('')
  const [rolePermissions, setRolePermissions] = useState<string[]>([])
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const permissionKeys = [...new Set([...capabilities.flatMap((item) => item.permissions),
    ...roles.flatMap((role) => role.permission_keys), ...currentUser.permissions])].sort()
  const canWriteUsers = currentUser.permissions.includes('users.write')
  const canWriteRoles = currentUser.permissions.includes('roles.write')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [nextUsers, nextRoles, manifest] = await Promise.all([api.users(token), api.roles(token), api.capabilities()])
      setUsers(nextUsers)
      setRoles(nextRoles)
      setCapabilities(manifest.capabilities)
      setRoleId((current) => current || (nextRoles[0] ? String(nextRoles[0].id) : ''))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取用户和角色')
    } finally {
      setLoading(false)
    }
  }, [onToast, token])
  useEffect(() => {
    void load()
  }, [load])

  const createUser = async (event: FormEvent) => {
    event.preventDefault()
    if (creatingUser) return
    setCreatingUser(true)
    try {
      await api.createUser(token, { username, password, role_ids: roleId ? [Number(roleId)] : [] })
      setUsername('')
      setPassword('')
      await load()
      onToast('用户已创建并写入审计记录')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '创建用户失败')
    } finally {
      setCreatingUser(false)
    }
  }
  const toggleUser = async (item: ManagedUser) => {
    try {
      await api.updateUser(token, item.id, { enabled: !item.enabled })
      await load()
      onToast('用户状态已更新')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '更新用户失败')
    }
  }
  const chooseTemplate = (value: string) => {
    setTemplateId(value)
    setRolePermissions([...new Set(roles.find((role) => String(role.id) === value)?.permission_keys ?? [])].sort())
  }
  const toggleRoleForm = () => {
    if (!showRoleForm && !roleDraftInitialized) {
      const template = roles.find((role) => role.name === 'analyst')
      chooseTemplate(template ? String(template.id) : '')
      setRoleDraftInitialized(true)
    }
    setShowRoleForm((value) => !value)
  }
  const createRole = async (event: FormEvent) => {
    event.preventDefault()
    if (creatingRole) return
    setCreatingRole(true)
    try {
      const template = roles.find((role) => String(role.id) === templateId)
      await api.createRole(token, {
        name: roleName,
        description: template ? `基于${roleLabel(template.name)}调整的权限组合` : '自定义权限组合',
        permission_keys: rolePermissions
      })
      setRoleName('')
      setRolePermissions([])
      setTemplateId('')
      setRoleDraftInitialized(false)
      setShowRoleForm(false)
      await load()
      onToast('角色已创建，可在创建用户时选择此角色')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '创建角色失败')
    } finally {
      setCreatingRole(false)
    }
  }

  return (
    <div className="page-content auth-page refined-page remaining-page">
      
      <div className="auth-grid">
        <section className="surface auth-section">
          <div className="surface-heading">
            <SectionHeading title={<> 账户列表  <span className="count-badge">{users.length}</span> </>} />
            <div className="file-actions"> <button className="secondary-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          {loading ? '刷新中…' : '刷新'}
        </button> {canWriteUsers && <button className="secondary-button" aria-expanded={showUserForm}
              aria-controls={userFormId} onClick={() => setShowUserForm((value) => !value)} disabled={loading}>
              <UserPlus size={15} />{showUserForm ? '收起创建用户' : '创建用户'}
            </button>}</div>
          </div>
          {canWriteUsers && <div id={userFormId} hidden={!showUserForm}>
              <form className="inline-form user-create-form" onSubmit={createUser}>
                <label className="field">
                  <span>用户名</span>
                  <input value={username} onChange={(event) => setUsername(event.target.value)} required disabled={creatingUser} />
                </label>
                <label className="field">
                  <span>初始密码</span>
                  <input
                    type="password"
                    minLength={8}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    required disabled={creatingUser}
                  />
                </label>
                <label className="field">
                  <span>角色</span>
                  <select aria-label="新用户角色" disabled={creatingUser} value={roleId} onChange={(event) => setRoleId(event.target.value)}>
                    <option value="">无角色</option>
                    {roles.map((role) => (
                      <option value={role.id} key={role.id}>
                        {roleLabel(role.name)}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="primary-button" type="submit" disabled={loading || creatingUser}>
                  <UserPlus size={15} />
                  {creatingUser ? '创建中…' : '创建用户'}
                </button>
              </form>
          </div>}

          <div className="auth-table-wrap">
            <table className="auth-table">
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.username}</strong>
                      <small>{item.username === currentUser.username ? '当前会话' : `ID ${item.id}`}</small>
                    </td>
                    <td>
                      {item.roles.length ? (
                        item.roles.map((role) => (
                          <span className="role-chip" key={role}>
                            {roleLabel(role)}
                          </span>
                        ))
                      ) : (
                        <span className="muted">无角色</span>
                      )}
                    </td>
                    <td>
                      <span className={`state-chip ${item.enabled ? 'enabled' : 'disabled'}`}>
                        {item.enabled ? '已启用' : '已停用'}
                      </span>
                    </td>
                    <td>
                      {canWriteUsers && item.id !== currentUser.id && (
                        <button
                          className="icon-button compact"
                          title={item.enabled ? '停用用户' : '启用用户'}
                          onClick={() => void toggleUser(item)}
                        >
                          {item.enabled ? <LogOut size={14} /> : <Check size={14} />}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="surface auth-section">
          <div className="surface-heading">
            <div>
              <h2><ShieldCheck size={17} /> 角色与权限</h2>
            </div>
            {canWriteRoles && <button className="secondary-button" aria-expanded={showRoleForm}
              aria-controls={roleFormId} onClick={toggleRoleForm} disabled={loading || creatingRole}>
              {showRoleForm ? '收起自定义角色' : '自定义角色'}
            </button>}
          </div>
          <div className="auth-role-list">
            {roles.map((role) => {
              const labels = [...new Set(role.permission_keys.map((key) => permissionGroupLabel(key, capabilities)))]
              return <article className="auth-role-card" key={role.id} data-role-name={role.name}>
                <div className="auth-role-title"><strong>{roleLabel(role.name)}</strong>
                  <small>{role.built_in ? '系统内置' : '自定义'} · {role.permission_keys.length} 项权限</small></div>
                <p>{(role.built_in && builtinLabels[role.name]?.purpose) || role.description || '自定义权限组合'}</p>
                <small className="auth-role-summary">{labels.slice(0, 4).join('、') || '无权限'}
                  {labels.length > 4 ? ` 等 ${labels.length} 组` : ''}</small>
                <details className="auth-role-details"><summary>查看权限明细</summary>
                  <ul>{role.permission_keys.map((key) => <li key={key} title={key}>{permissionLabel(key, capabilities)}</li>)}</ul>
                  {!role.permission_keys.length && <p>此角色未分配权限。</p>}
                </details>
              </article>
            })}
          </div>
          {canWriteRoles && <div id={roleFormId} hidden={!showRoleForm}>
            <form className="inline-form role-create-form" onSubmit={createRole}>
              <div className="role-template-fields">
                <label className="field"><span>权限模板</span>
                  <select aria-label="角色权限模板" value={templateId} onChange={(event) => chooseTemplate(event.target.value)} disabled={creatingRole}>
                    <option value="">从空白开始</option>
                    {roles.map((role) => <option value={role.id} key={role.id}>{roleLabel(role.name)}（{role.permission_keys.length} 项）</option>)}
                  </select>
                </label>
                <label className="field"><span>新角色名称</span>
                  <input value={roleName} onChange={(event) => setRoleName(event.target.value)} required disabled={creatingRole} />
                </label>
              </div>
              <p className="field-hint">模板复制当前权限。更换模板会替换下方选择；收起表单会保留草稿。</p>
              <PermissionPicker keys={permissionKeys} selected={rolePermissions} onChange={setRolePermissions}
                capabilities={capabilities} disabled={loading || creatingRole} />
              <button className="primary-button" type="submit" disabled={loading || creatingRole}>
                <ShieldCheck size={15} />{creatingRole ? '创建中…' : '创建角色'}
              </button>
            </form>
          </div>}
        </section>
      </div>
    </div>
  )
}
