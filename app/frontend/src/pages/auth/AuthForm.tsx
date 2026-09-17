import { useState, type FormEvent } from 'react'
import { AlertTriangle, KeyRound, Sparkles } from 'lucide-react'

export function AuthForm({ mode, error, onSubmit, onRetry }: { mode: 'login' | 'bootstrap'; error: string | null; onSubmit: (username: string, password: string) => Promise<void>; onRetry?: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const isBootstrap = mode === 'bootstrap'
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setLocalError(null)
    if (isBootstrap && password !== confirm) { setLocalError('两次输入的密码不一致'); return }
    setSubmitting(true)
    await onSubmit(username, password)
    setSubmitting(false)
  }
  return <main className="auth-shell"><section className="auth-panel auth-form-panel"><div className="auth-brand"><div className="brand-mark"><Sparkles size={20} /></div><div><strong>GeoSpectrum</strong><span>本地光谱分析工作台</span></div></div><span className="section-kicker">{isBootstrap ? 'FIRST RUN' : 'LOCAL SIGN IN'}</span><h1>{isBootstrap ? '初始化本地管理员' : '登录工作台'}</h1><p>{isBootstrap ? '创建首个系统管理员账户，密码只以 Argon2id 哈希保存。' : '使用本机账户进入分析工作台。'}</p><form onSubmit={submit} className="auth-form"><label className="field"><span>用户名</span><input autoFocus value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label className="field"><span>密码</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={isBootstrap ? 'new-password' : 'current-password'} minLength={8} required /></label>{isBootstrap && <label className="field"><span>确认密码</span><input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" minLength={8} required /></label>}{(localError || error) && <div className="auth-error"><AlertTriangle size={15} />{localError || error}</div>}<button className="primary-button auth-submit" disabled={submitting}>{submitting ? '处理中…' : isBootstrap ? '创建管理员' : '登录'}<KeyRound size={15} /></button>{!isBootstrap && onRetry && <button type="button" className="secondary-button auth-retry" onClick={onRetry}>重新检查账户状态</button>}</form></section></main>
}
