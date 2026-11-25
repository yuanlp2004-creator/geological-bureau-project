import { useCallback, useEffect, useState } from 'react'
import { AppIcon } from './components/AppIcon'
import { api, ApiError, type AuthUser } from './api'
import { AuthForm } from './pages/auth/AuthForm'
import { WorkspaceApp } from './layout/WorkspaceApp'
import { themeStore } from './stores/themeStore'
import { workbenchStore } from './stores/workbenchStore'

function App() {
  const [mode, setMode] = useState<'loading' | 'bootstrap' | 'login' | 'authenticated'>('loading')
  const [token, setToken] = useState<string | null>(null)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authError, setAuthError] = useState<string | null>(null)

  const showAuthScreen = useCallback((nextMode: 'loading' | 'bootstrap' | 'login') => {
    themeStore.deactivate()
    setMode(nextMode)
  }, [])

  const startAuth = useCallback(async () => {
    showAuthScreen('loading')
    setAuthError(null)
    try {
      const status = await api.authStatus()
      if (!status.bootstrapped) {
        showAuthScreen('bootstrap')
        return
      }
      const savedToken = window.sessionStorage.getItem('geospectrum.token')
      if (savedToken) {
        try {
          const savedUser = await api.me(savedToken)
          themeStore.activateUser(savedUser.id)
          setToken(savedToken)
          setUser(savedUser)
          setMode('authenticated')
          return
        } catch {
          window.sessionStorage.removeItem('geospectrum.token')
        }
      }
      showAuthScreen('login')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '无法读取本地账户状态')
      showAuthScreen('login')
    }
  }, [showAuthScreen])

  useEffect(() => {
    void startAuth()
  }, [startAuth])

  const handleLogin = async (username: string, password: string) => {
    setAuthError(null)
    try {
      const result = await api.login(username, password)
      window.sessionStorage.setItem('geospectrum.token', result.access_token)
      themeStore.activateUser(result.user.id)
      setToken(result.access_token)
      setUser(result.user)
      setMode('authenticated')
    } catch (error) {
      setAuthError(
        error instanceof ApiError && error.code === 'auth_invalid_credentials'
          ? '用户名或密码错误'
          : '登录失败，请稍后重试'
      )
    }
  }

  const handleBootstrap = async (username: string, password: string) => {
    setAuthError(null)
    try {
      await api.bootstrap(username, password)
      showAuthScreen('login')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '初始化失败')
    }
  }

  const handleLogout = async () => {
    window.sessionStorage.removeItem('geospectrum.token')
    workbenchStore.clearAll()
    setToken(null)
    setUser(null)
    showAuthScreen('login')
    if (token) await api.logout(token).catch(() => undefined)
  }

  if (mode === 'loading')
    return (
      <div className="auth-shell">
        <div className="auth-panel">
          <AppIcon size={48} />
          <strong>GeoSpectrum</strong>
          <span>正在连接本地账户服务…</span>
        </div>
      </div>
    )
  if (mode === 'bootstrap') return <AuthForm mode="bootstrap" error={authError} onSubmit={handleBootstrap} />
  if (mode === 'login') return <AuthForm mode="login" error={authError} onSubmit={handleLogin} onRetry={startAuth} />
  return token && user ? <WorkspaceApp key={user.id} token={token} user={user} onLogout={handleLogout} /> : null
}

export default App
