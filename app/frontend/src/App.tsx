import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type InputHTMLAttributes, type MouseEvent } from 'react'
import {
  Activity,
  AlertTriangle,
  Archive,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  CircleHelp,
  Clipboard,
  ClipboardCheck,
  Clock3,
  Copy,
  Database,
  Download,
  FileBarChart,
  FileText,
  FolderOpen,
  Gauge,
  Info,
  Crosshair,
  LockKeyhole,
  UnlockKeyhole,
  Maximize2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
  KeyRound,
  LayoutDashboard,
  Lightbulb,
  ListFilter,
  LogOut,
  MessageSquareText,
  PauseCircle,
  PlayCircle,
  Plus,
  Printer,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SquareTerminal,
  TestTube2,
  Trash2,
  UserCog,
  UserPlus,
  ClipboardList,
  CircleX,
  Upload,
  Wrench,
  X,
} from 'lucide-react'
import {
  api,
  type About,
  type AngleExposure,
  type AuditEvent,
  type AuthUser,
  type Capability,
  type CurrentMethodState,
  type Diagnostics,
  type ManagedRole,
  type ManagedUser,
  type LineDetectability,
  type LegacyMigrationDiagnostic,
  type LegacyMigrationRun,
  type SpectrumMigrationDiagnostic,
  type SpectrumMigrationRun,
  type ResultMigrationDiagnostic,
  type ResultMigrationRun,
  type MethodConditions,
  type MethodLineCollection,
  type MethodOptions,
  type MethodPrintSettings,
  type MethodRecord,
  type PrinterOption,
  type PrintJob,
  type RuntimeEvent,
  type Settings,
  type SpectralLine,
  type SpectralLineInput,
  type SpectralLineOptions,
  type SampleQueue,
  type SpectrumRecordSummary,
  type SpectrumRecord,
  type SpectrumPoint,
} from './api'
import { SpectrumPlot, type SpectrumPlotCurve, type SpectrumPlotCursor } from './SpectrumPlot'
import { CopyableCode, ExpandableValue } from './InformationDisplay'
import { AcquisitionPage } from './AcquisitionPage'
import { DispersionPage } from './DispersionPage'
import { SampleAcquisitionPage } from './SampleAcquisitionPage'
import { HardwareAcquisitionPage } from './HardwareAcquisitionPage'
import { MercuryCalibrationPage } from './MercuryCalibrationPage'
import { AnalysisPage } from './AnalysisPage'

type Page = 'workspace' | 'methods' | 'migration' | 'spectrum-migration' | 'result-migration' | 'spectra' | 'samples' | 'acquisition' | 'dispersion' | 'sample-acquisition' | 'hardware-acquisition' | 'mercury-calibration' | 'analysis' | 'reports' | 'settings' | 'about' | 'users' | 'audit'

const navItems: Array<{ id: Page; label: string; icon: typeof LayoutDashboard; enabled: boolean; hint: string }> = [
  { id: 'workspace', label: '工作台', icon: LayoutDashboard, enabled: true, hint: '系统状态与运行消息' },
  { id: 'methods', label: '方法', icon: SlidersHorizontal, enabled: true, hint: '方法版本、条件与分析谱线' },
  { id: 'migration', label: '旧版迁移', icon: Archive, enabled: true, hint: '只读暂存 DIRECT.MTD、CFG 与 OPT' },
  { id: 'spectrum-migration', label: '旧谱数据', icon: Database, enabled: true, hint: '只读暂存 .CDT、.CMT、.EDT 与 .WDT' },
  { id: 'result-migration', label: '谱图结果', icon: FileBarChart, enabled: true, hint: '只读暂存 .DAT 与 .PDT 结果矩阵' },
  { id: 'spectra', label: '谱图查看', icon: Activity, enabled: true, hint: '查看已导入谱带、结果矩阵和原始帧' },
  { id: 'samples', label: '样品队列', icon: TestTube2, enabled: true, hint: '样品录入、重复展开与 SAM 文件' },
  { id: 'acquisition', label: '采集', icon: Activity, enabled: true, hint: '设备档案、连接诊断与实时调试' },
  { id: 'dispersion', label: '色散校准', icon: Crosshair, enabled: true, hint: '色散采集、谱线定位与方法绑定' },
  { id: 'sample-acquisition', label: '样品采集', icon: TestTube2, enabled: true, hint: '蒸发全帧、样品队列与采集后命名' },
  { id: 'hardware-acquisition', label: '自动转角', icon: RotateCcw, enabled: true, hint: '短波到长波转角、CCD 采集与异常安全闭环' },
  { id: 'mercury-calibration', label: '汞灯校准', icon: Lightbulb, enabled: true, hint: '汞线选线、峰位偏移与光学调整版本' },
  { id: 'analysis', label: '分析', icon: BarChart3, enabled: true, hint: '定量分析、结果矩阵与慢进人工干预' },
  { id: 'reports', label: '报告', icon: FileBarChart, enabled: false, hint: '将在 S19 启用' },
  { id: 'users', label: '用户与权限', icon: UserCog, enabled: true, hint: '本地账户、角色和权限' },
  { id: 'audit', label: '审计记录', icon: ClipboardList, enabled: true, hint: '查看权限和账户变更记录' },
]

const severityLabel: Record<string, string> = {
  debug: '调试', info: '信息', success: '完成', warning: '警告', error: '错误',
}

const categoryLabel: Record<string, string> = {
  system: '系统', action: '操作', import: '导入', acquisition: '采集', analysis: '分析',
}

type FeedbackTone = 'success' | 'info' | 'warning' | 'error'
type ToastNotice = { message: string; tone: FeedbackTone }

const feedbackToneFor = (message: string): FeedbackTone => {
  if (/(失败|错误|不一致|无法|不能|不可|拒绝|损坏|异常|无效|超时|故障|未通过|未找到|没有.+权限|不支持|回滚|failed|error|invalid|mismatch|forbidden|unauthorized|not found|conflict)/i.test(message)) return 'error'
  if (/(警告|超过阈值|超限|已暂停|安全停止|已停止|已删除|已停用|取消|放弃|待连接|等待|请至少|请选择|只有.+权限|后续步骤|未生成|未应用|未完成|未确认|延后)/.test(message)) return 'warning'
  if (/(成功|完成|通过|正常|在线|就绪|已保存|已创建|已建立|已连接|已开始|已继续|已添加|已更新|已确认|已记录|已锁定|已发布|已绑定|已应用|已恢复|已导出|已生成|已复制|已清空|已标记|已暂存|已提交|已收尾)/.test(message)) return 'success'
  return 'info'
}

const configuredTimeZone = () => document.documentElement.dataset.timezone || 'Asia/Shanghai'
const formatDate = (value: string | number | Date, options: Intl.DateTimeFormatOptions) => {
  try {
    return new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: configuredTimeZone() }).format(new Date(value))
  } catch {
    return new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: 'Asia/Shanghai' }).format(new Date(value))
  }
}
const formatTime = (value: string | number | Date) => formatDate(value, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const formatDateTime = (value: string | number | Date) => formatDate(value, {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
})

function WorkspaceApp({ token, user, onLogout }: { token: string; user: AuthUser; onLogout: () => void }) {
  const [page, setPage] = useState<Page>('workspace')
  const [events, setEvents] = useState<RuntimeEvent[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [about, setAbout] = useState<About | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null)
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [health, setHealth] = useState<'online' | 'offline'>('offline')
  const [currentMethod, setCurrentMethod] = useState<CurrentMethodState | null>(null)
  const [toast, setToast] = useState<ToastNotice | null>(null)
  const [loading, setLoading] = useState(true)
  const showToast = useCallback((message: string) => setToast({ message, tone: feedbackToneFor(message) }), [])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const currentPromise = user.permissions.includes('methods.read') ? api.currentMethod(token) : Promise.resolve(null)
      const [nextHealth, nextEvents, nextSettings, nextAbout, nextCapabilities, nextDiagnostics, nextCurrentMethod] = await Promise.all([
        api.health(), api.logs(token), api.settings(token), api.about(), api.capabilities(), api.diagnostics(),
        currentPromise,
      ])
      setHealth(nextHealth.status === 'ok' ? 'online' : 'offline')
      setEvents(nextEvents)
      setSettings(nextSettings)
      setAbout(nextAbout)
      setCapabilities(nextCapabilities.capabilities)
      setDiagnostics(nextDiagnostics)
      setCurrentMethod(nextCurrentMethod)
    } catch {
      setHealth('offline')
    } finally {
      setLoading(false)
    }
  }, [token, user.permissions])

  useEffect(() => { void loadData() }, [loadData])
  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = settings?.display.theme === 'dark' ? 'dark' : 'light'
    root.dataset.density = settings?.display.density === 'compact' ? 'compact' : 'comfortable'
    root.dataset.timezone = settings?.time.timezone || 'Asia/Shanghai'
  }, [settings])
  useEffect(() => {
    if (page !== 'settings') return
    void api.settings(token).then(setSettings).catch((error) => showToast(error instanceof Error ? error.message : '无法刷新软件设置'))
  }, [page, showToast, token])
  useEffect(() => {
    const interval = window.setInterval(() => { void api.logs(token).then(setEvents).catch(() => undefined) }, 10000)
    return () => window.clearInterval(interval)
  }, [token])
  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const handlePage = (nextPage: Page) => {
    const item = navItems.find((nav) => nav.id === nextPage)
    if (item && !item.enabled) {
      showToast(`${item.label}将在后续步骤启用`)
      return
    }
    setPage(nextPage)
  }

  const saveSettings = async (nextSettings: Settings) => {
    try {
      const saved = await api.saveSettings(token, nextSettings)
      setSettings(saved)
      showToast('软件设置已保存')
    } catch (error) {
      showToast(error instanceof Error ? error.message : '保存失败')
    }
  }

  const resetSettings = async () => {
    try {
      const defaults = await api.resetSettings(token)
      setSettings(defaults)
      showToast('软件设置已恢复默认值')
    } catch (error) {
      showToast(error instanceof Error ? error.message : '恢复失败')
    }
  }

  return (
    <div className="app-shell" data-testid="app-shell" data-theme={settings?.display.theme ?? 'light'} data-density={settings?.display.density ?? 'comfortable'}>
      {health === 'offline' && !loading && !about ? <ErrorPage onRetry={loadData} /> : <><Sidebar page={page} onNavigate={handlePage} health={health} user={user} showStatusBar={settings?.display.show_status_bar !== false} />
        <main className="main-area">
          <Header page={page} onRefresh={loadData} loading={loading} onNavigate={handlePage} user={user} currentMethod={currentMethod} onLogout={onLogout} />
          {page === 'workspace' && <Workspace token={token} health={health} canClearEvents={user.permissions.includes('runtime-events.write')} events={events} currentMethod={currentMethod} diagnostics={diagnostics} capabilities={capabilities} onNavigate={handlePage} onEventsChange={setEvents} onToast={showToast} />}
          {page === 'methods' && <MethodsPage token={token} currentUser={user} currentMethod={currentMethod} onCurrentMethodChange={setCurrentMethod} onToast={showToast} />}
          {page === 'migration' && <LegacyMigrationPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'spectrum-migration' && <SpectrumMigrationPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'result-migration' && <ResultMigrationPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'spectra' && <SpectrumViewerPage token={token} onToast={showToast} />}
          {page === 'samples' && <SampleQueuePage token={token} onToast={showToast} />}
          {page === 'acquisition' && <AcquisitionPage token={token} canWrite={user.permissions.includes('devices.write')} canExecute={user.permissions.includes('devices.execute')} onToast={showToast} />}
          {page === 'dispersion' && <DispersionPage token={token} canWrite={user.permissions.includes('dispersion.write')} canExecute={user.permissions.includes('dispersion.execute')} onToast={showToast} />}
          {page === 'sample-acquisition' && <SampleAcquisitionPage token={token} canWrite={user.permissions.includes('acquisition.write')} canExecute={user.permissions.includes('acquisition.execute')} onToast={showToast} />}
          {page === 'hardware-acquisition' && <HardwareAcquisitionPage token={token} canWrite={user.permissions.includes('hardware-acquisition.write')} canExecute={user.permissions.includes('hardware-acquisition.execute')} onToast={showToast} />}
          {page === 'mercury-calibration' && <MercuryCalibrationPage token={token} canWrite={user.permissions.includes('mercury-calibration.write')} canExecute={user.permissions.includes('mercury-calibration.execute')} onToast={showToast} />}
          {page === 'analysis' && <AnalysisPage token={token} canExecute={user.permissions.includes('analysis.execute')} canIntervene={user.permissions.includes('analysis.intervene')} onToast={showToast} />}
          {page === 'settings' && settings && <SettingsPage settings={settings} onSave={saveSettings} onReset={resetSettings} />}
          {page === 'about' && <AboutPage about={about} diagnostics={diagnostics} capabilities={capabilities} health={health} onRefresh={loadData} />}
          {page === 'users' && <UsersPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'audit' && <AuditPage token={token} />}
          {page !== 'workspace' && page !== 'methods' && page !== 'migration' && page !== 'spectrum-migration' && page !== 'result-migration' && page !== 'spectra' && page !== 'samples' && page !== 'acquisition' && page !== 'dispersion' && page !== 'sample-acquisition' && page !== 'hardware-acquisition' && page !== 'mercury-calibration' && page !== 'analysis' && page !== 'settings' && page !== 'about' && page !== 'users' && page !== 'audit' && <DisabledPage item={navItems.find((item) => item.id === page)!} />}
        </main></>}
      {toast && <div className={`toast ${toast.tone}`} role={toast.tone === 'error' ? 'alert' : 'status'} aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}>
        {toast.tone === 'success' ? <CheckCircle2 size={17} /> : toast.tone === 'error' ? <CircleX size={17} /> : toast.tone === 'warning' ? <AlertTriangle size={17} /> : <Info size={17} />}
        <span>{toast.message}</span><button title="关闭" onClick={() => setToast(null)}><X size={14} /></button>
      </div>}
    </div>
  )
}

function App() {
  const [mode, setMode] = useState<'loading' | 'bootstrap' | 'login' | 'authenticated'>('loading')
  const [token, setToken] = useState<string | null>(null)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authError, setAuthError] = useState<string | null>(null)

  const startAuth = useCallback(async () => {
    setMode('loading')
    setAuthError(null)
    try {
      const status = await api.authStatus()
      if (!status.bootstrapped) {
        setMode('bootstrap')
        return
      }
      const savedToken = window.sessionStorage.getItem('geospectrum.token')
      if (savedToken) {
        try {
          const savedUser = await api.me(savedToken)
          setToken(savedToken)
          setUser(savedUser)
          setMode('authenticated')
          return
        } catch {
          window.sessionStorage.removeItem('geospectrum.token')
        }
      }
      setMode('login')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '无法读取本地账户状态')
      setMode('login')
    }
  }, [])

  useEffect(() => { void startAuth() }, [startAuth])

  const handleLogin = async (username: string, password: string) => {
    setAuthError(null)
    try {
      const result = await api.login(username, password)
      window.sessionStorage.setItem('geospectrum.token', result.access_token)
      setToken(result.access_token)
      setUser(result.user)
      setMode('authenticated')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '登录失败')
    }
  }

  const handleBootstrap = async (username: string, password: string) => {
    setAuthError(null)
    try {
      await api.bootstrap(username, password)
      setMode('login')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '初始化失败')
    }
  }

  const handleLogout = async () => {
    if (token) await api.logout(token).catch(() => undefined)
    window.sessionStorage.removeItem('geospectrum.token')
    setToken(null)
    setUser(null)
    setMode('login')
  }

  if (mode === 'loading') return <div className="auth-shell"><div className="auth-panel"><Sparkles size={24} /><strong>GeoSpectrum</strong><span>正在连接本地账户服务…</span></div></div>
  if (mode === 'bootstrap') return <AuthForm mode="bootstrap" error={authError} onSubmit={handleBootstrap} />
  if (mode === 'login') return <AuthForm mode="login" error={authError} onSubmit={handleLogin} onRetry={startAuth} />
  return token && user ? <WorkspaceApp token={token} user={user} onLogout={handleLogout} /> : null
}

function AuthForm({ mode, error, onSubmit, onRetry }: { mode: 'login' | 'bootstrap'; error: string | null; onSubmit: (username: string, password: string) => Promise<void>; onRetry?: () => void }) {
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

function Sidebar({ page, onNavigate, health, user, showStatusBar }: { page: Page; onNavigate: (page: Page) => void; health: 'online' | 'offline'; user: AuthUser; showStatusBar: boolean }) {
  return <aside className="sidebar">
    <div className="brand">
      <div className="brand-mark"><Sparkles size={19} /></div>
      <div><strong>GeoSpectrum</strong><span>地质光谱分析平台</span></div>
    </div>
    <div className="sidebar-section-label">工作区</div>
    <nav className="nav-list" aria-label="业务域导航">
      {navItems.filter((item) => item.id !== 'methods' || user.permissions.includes('methods.read')).filter((item) => item.id !== 'migration' || user.permissions.includes('migration.read')).filter((item) => item.id !== 'spectrum-migration' || user.permissions.includes('spectrum-migration.read')).filter((item) => item.id !== 'result-migration' || user.permissions.includes('result-migration.read')).filter((item) => item.id !== 'spectra' || user.permissions.includes('spectra.read')).filter((item) => item.id !== 'acquisition' || user.permissions.includes('devices.read')).filter((item) => item.id !== 'dispersion' || user.permissions.includes('dispersion.read')).filter((item) => item.id !== 'sample-acquisition' || user.permissions.includes('acquisition.read')).filter((item) => item.id !== 'hardware-acquisition' || user.permissions.includes('hardware-acquisition.read')).filter((item) => item.id !== 'mercury-calibration' || user.permissions.includes('mercury-calibration.read')).filter((item) => item.id !== 'users' || user.permissions.includes('users.read')).filter((item) => item.id !== 'audit' || user.permissions.includes('audit.read')).map((item) => {
        const Icon = item.icon
        return <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''} ${!item.enabled ? 'disabled' : ''}`} onClick={() => onNavigate(item.id)} title={item.hint}>
          <Icon size={17} /><span>{item.label}</span>{!item.enabled && <span className="nav-dot" />}
        </button>
      })}
    </nav>
    <div className="sidebar-spacer" />
    {showStatusBar && <div className="side-status"><span className={`status-dot ${health}`} /><div><span>本地服务</span><strong>{health === 'online' ? '已连接' : '等待连接'}</strong></div><Activity size={15} /></div>}
    <button className={`nav-item utility ${page === 'settings' ? 'active' : ''}`} onClick={() => onNavigate('settings')}><Settings2 size={17} /><span>软件设置</span></button>
    <button className={`nav-item utility ${page === 'about' ? 'active' : ''}`} onClick={() => onNavigate('about')}><CircleHelp size={17} /><span>关于与诊断</span></button>
    {showStatusBar && <div className="sidebar-footer"><span>桌面基础</span><span>v0.1.0</span></div>}
  </aside>
}

function Header({ page, onRefresh, loading, onNavigate, user, currentMethod, onLogout }: { page: Page; onRefresh: () => void; loading: boolean; onNavigate: (page: Page) => void; user: AuthUser; currentMethod: CurrentMethodState | null; onLogout: () => void }) {
  const current = navItems.find((item) => item.id === page)
  const title = page === 'settings' ? '软件设置' : page === 'about' ? '关于与诊断' : current?.label ?? '工作台'
  return <header className="topbar">
    <div className="breadcrumbs"><span>GeoSpectrum</span><ChevronRight size={13} /><strong>{title}</strong></div>
    <div className="topbar-actions"><button className="workspace-method" onClick={() => onNavigate('methods')} disabled={!user.permissions.includes('methods.read')} title={`当前方法 · ${currentMethod?.work_type || '未选择'} · ${currentMethod?.title || '请选择已发布方法'}`}><span>当前方法 · {currentMethod?.work_type || '未选择'}</span><strong>{currentMethod?.title || '请选择已发布方法'}</strong></button><button className="icon-button" title="刷新服务状态" onClick={onRefresh} disabled={loading}><RefreshCw size={17} className={loading ? 'spin' : ''} /></button><button className="icon-button" title="退出登录" onClick={onLogout}><LogOut size={15} /></button><button className="avatar" title={`${user.username} · ${user.roles.join(' / ') || '无角色'}`} onClick={() => onNavigate('about')}>{user.username.slice(0, 2).toUpperCase()}</button></div>
  </header>
}

function Workspace({ token, health, canClearEvents, events, currentMethod, diagnostics, capabilities, onNavigate, onEventsChange, onToast }: { token: string; health: 'online' | 'offline'; canClearEvents: boolean; events: RuntimeEvent[]; currentMethod: CurrentMethodState | null; diagnostics: Diagnostics | null; capabilities: Capability[]; onNavigate: (page: Page) => void; onEventsChange: (events: RuntimeEvent[]) => void; onToast: (message: string) => void }) {
  const [eventFilter, setEventFilter] = useState('all')
  const [selected, setSelected] = useState<number[]>([])
  const filteredEvents = useMemo(() => eventFilter === 'all' ? events : events.filter((event) => event.severity === eventFilter), [eventFilter, events])
  const selectAll = selected.length === filteredEvents.length && filteredEvents.length > 0
  const hasCurrentMethod = currentMethod?.method_id != null

  const clearEvents = async () => {
    if (!canClearEvents) { onToast('当前账号只有运行消息读取权限'); return }
    try { await api.clearLogs(token); onEventsChange([]); setSelected([]); onToast('运行消息已清空') } catch { onToast('清空消息失败') }
  }
  const copyEvents = async () => {
    const selectedEvents = filteredEvents.filter((event) => selected.includes(event.id))
    const content = (selectedEvents.length ? selectedEvents : filteredEvents).map((event) => `[${formatTime(event.created_at)}] ${event.message}`).join('\n')
    try { await navigator.clipboard.writeText(content); onToast('消息已复制到剪贴板') } catch { onToast('当前环境不支持剪贴板') }
  }
  const saveEvents = () => {
    const content = filteredEvents.map((event) => `${event.created_at}\t${categoryLabel[event.category] ?? event.category}\t${event.message}`).join('\n')
    const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' })); link.download = `geospectrum-events-${new Date().toISOString().slice(0, 10)}.log`; link.click(); URL.revokeObjectURL(link.href); onToast('消息日志已保存')
  }
  return <div className="page-content workspace-page" data-testid="workspace">
    <section className="hero-row"><div><span className="eyebrow"><span className="eyebrow-line" />S07 · SAMPLE QUEUE</span><h1>分析工作台</h1><p>管理方法版本、样品队列与 SpecDirect 旧数据的只读迁移。</p></div><div className="hero-actions"><span className={`live-pill ${health}`}><span className={`pulse ${health}`} />{health === 'online' ? '本地运行' : '本地服务离线'}</span><button className="secondary-button" onClick={() => onNavigate('samples')}><TestTube2 size={16} />样品队列</button></div></section>
    <section className="stat-grid">
      <StatCard icon={Database} label="SQLite 状态" value={diagnostics?.journal_mode?.toUpperCase() ?? '待诊断'} note={diagnostics?.foreign_keys === 1 ? '外键已启用' : diagnostics ? '外键未启用' : '等待数据库诊断'} tone={diagnostics?.journal_mode === 'wal' && diagnostics?.foreign_keys === 1 ? 'blue' : diagnostics ? 'red' : 'amber'} />
      <StatCard icon={ShieldCheck} label="注册模块" value={String(capabilities.length)} note={diagnostics?.manifest_valid ? '清单验证通过' : '等待清单验证'} tone={diagnostics?.manifest_valid ? 'green' : 'amber'} />
      <StatCard icon={MessageSquareText} label="运行消息" value={String(events.length)} note="最近 500 条以内" tone="amber" />
      <StatCard icon={Gauge} label="服务延迟" value="本地" note="随机端口握手" tone="violet" />
    </section>
    <section className="workspace-grid">
      <div className="primary-column">
        <section className="surface status-surface"><div className="surface-heading"><div><span className="section-kicker">CURRENT METHOD</span><h2>{currentMethod?.title || '尚未选择运行方法'}</h2></div><span className={`ready-badge ${hasCurrentMethod ? '' : 'pending'}`}>{hasCurrentMethod ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}{hasCurrentMethod ? `版本 ${currentMethod?.version}` : '等待选择'}</span></div><div className="readiness-grid"><ReadinessItem icon={Database} title="数据存储" detail={diagnostics ? `SQLite schema v${diagnostics.schema_version}` : '等待数据库诊断'} done={diagnostics?.sqlite_integrity === 'ok'} /><ReadinessItem icon={SquareTerminal} title="API 服务" detail={health === 'online' ? 'FastAPI /api/v1 · 在线' : 'FastAPI /api/v1 · 离线'} done={health === 'online'} /><ReadinessItem icon={Archive} title="模块清单" detail={`${capabilities.length} 个模块已注册`} done={diagnostics?.manifest_valid === true} /><ReadinessItem icon={SlidersHorizontal} title="运行方法" detail={hasCurrentMethod ? `${currentMethod?.work_type} · 已发布` : '打开已发布方法后就绪'} done={hasCurrentMethod} /></div><div className="surface-note"><Info size={16} /><span>方法草稿可保留字段错误；只有验证通过并发布的不可变版本才能成为当前运行方法。</span></div></section>
        <MessagePanel events={events} filteredEvents={filteredEvents} selected={selected} setSelected={setSelected} selectAll={selectAll} setSelectAll={() => setSelected(selectAll ? [] : filteredEvents.map((event) => event.id))} filter={eventFilter} setFilter={setEventFilter} onClear={clearEvents} onCopy={copyEvents} onSave={saveEvents} />
      </div>
      <aside className="secondary-column"><section className="surface quick-surface"><div className="surface-heading"><div><span className="section-kicker">QUICK ACCESS</span><h2>常用入口</h2></div><Clipboard size={16} /></div><QuickAction icon={SlidersHorizontal} label="方法管理" detail="版本、条件与当前方法" onClick={() => onNavigate('methods')} /><QuickAction icon={Settings2} label="软件设置" detail="目录、显示、日志与打印" onClick={() => onNavigate('settings')} /><QuickAction icon={CircleHelp} label="关于与诊断" detail="版本、接口和能力清单" onClick={() => onNavigate('about')} /></section><section className="surface protocol-surface"><div className="surface-heading"><div><span className="section-kicker">SERVICE</span><h2>服务通道</h2></div><Activity size={16} /></div><div className="protocol-row"><span>REST API</span><code>127.0.0.1</code><span className={health === 'online' ? 'protocol-ok' : 'protocol-error'}>{health === 'online' ? '在线' : '离线'}</span></div><div className="protocol-row"><span>事件流</span><code>/ws/events</code><span className="protocol-pending">待连接</span></div><div className="protocol-row"><span>桌面壳</span><code>Tauri 2</code><span className="protocol-pending">构建中</span></div></section></aside>
    </section>
  </div>
}

function StatCard({ icon: Icon, label, value, note, tone }: { icon: typeof Database; label: string; value: string; note: string; tone: string }) { return <div className={`stat-card ${tone}`}><div className="stat-icon"><Icon size={17} /></div><div><span>{label}</span><strong>{value}</strong><small>{note}</small></div></div> }
function ReadinessItem({ icon: Icon, title, detail, done = false }: { icon: typeof Database; title: string; detail: string; done?: boolean }) { return <div className="readiness-item"><div className={`readiness-icon ${done ? 'done' : 'pending'}`}><Icon size={16} /></div><div><strong>{title}</strong><span>{detail}</span></div>{done ? <Check size={15} className="check" /> : <Clock3 size={15} className="pending-icon" />}</div> }
function QuickAction({ icon: Icon, label, detail, onClick }: { icon: typeof Database; label: string; detail: string; onClick: () => void }) { return <button className="quick-action" onClick={onClick}><span className="quick-icon"><Icon size={16} /></span><span><strong>{label}</strong><small>{detail}</small></span><ChevronRight size={15} /></button> }

function MessagePanel({ events, filteredEvents, selected, setSelected, selectAll, setSelectAll, filter, setFilter, onClear, onCopy, onSave }: { events: RuntimeEvent[]; filteredEvents: RuntimeEvent[]; selected: number[]; setSelected: (ids: number[]) => void; selectAll: boolean; setSelectAll: () => void; filter: string; setFilter: (filter: string) => void; onClear: () => void; onCopy: () => void; onSave: () => void }) {
  return <section className="surface message-surface" data-testid="runtime-messages"><div className="surface-heading message-heading"><div><span className="section-kicker">RUNTIME MESSAGES</span><h2>运行消息 <span className="count-badge">{events.length}</span></h2></div><div className="message-tools"><select aria-label="按状态过滤" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">全部状态</option><option value="success">完成</option><option value="info">信息</option><option value="warning">警告</option><option value="error">错误</option></select><button className="icon-button compact" title="保存消息" onClick={onSave}><Download size={15} /></button><button className="icon-button compact" title="复制选中消息" onClick={onCopy}><Copy size={15} /></button><button className="icon-button compact danger" title="清空消息" onClick={onClear}><Trash2 size={15} /></button></div></div><div className="message-toolbar"><label className="checkbox-row"><input type="checkbox" checked={selectAll} onChange={setSelectAll} /><span>全选</span></label><span>{selected.length ? `已选 ${selected.length} 条` : '选择消息后可复制'}</span><div className="toolbar-rule" /><ListFilter size={14} /><span>{filter === 'all' ? '全部类别' : severityLabel[filter]}</span></div><div className="message-list">{filteredEvents.length === 0 && <div className="empty-state"><MessageSquareText size={24} /><span>暂无运行消息</span><small>服务启动后的状态会显示在这里</small></div>}{filteredEvents.map((event) => { const metadata = `${categoryLabel[event.category] ?? event.category} · ${event.correlation_id ?? '本地事件'}`; return <label className="message-row" key={event.id}><input type="checkbox" checked={selected.includes(event.id)} onChange={() => setSelected(selected.includes(event.id) ? selected.filter((id) => id !== event.id) : [...selected, event.id])} /><span className={`severity-mark ${event.severity}`} /><span className="message-main"><strong title={event.message}>{event.message}</strong><small title={metadata}>{metadata}</small></span><span className={`severity-label ${event.severity}`}>{severityLabel[event.severity] ?? event.severity}</span><time>{formatTime(event.created_at)}</time></label> })}</div></section>
}

function UsersPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
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

  return <div className="page-content auth-page"><section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />IDENTITY & ACCESS</span><h1>用户与权限</h1><p>管理本机账户、角色授权和启用状态。每次变更都会留下审计记录。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? '刷新中…' : '刷新'}</button></section><div className="auth-grid"><section className="surface auth-section"><div className="surface-heading"><div><span className="section-kicker">LOCAL USERS</span><h2>账户列表 <span className="count-badge">{users.length}</span></h2></div><UserCog size={17} /></div><div className="auth-table-wrap"><table className="auth-table"><thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>{users.map((item) => <tr key={item.id}><td><strong>{item.username}</strong><small>{item.username === currentUser.username ? '当前会话' : `ID ${item.id}`}</small></td><td>{item.roles.length ? item.roles.map((role) => <span className="role-chip" key={role}>{role}</span>) : <span className="muted">无角色</span>}</td><td><span className={`state-chip ${item.enabled ? 'enabled' : 'disabled'}`}>{item.enabled ? '已启用' : '已停用'}</span></td><td>{canWriteUsers && item.id !== currentUser.id && <button className="icon-button compact" title={item.enabled ? '停用用户' : '启用用户'} onClick={() => void toggleUser(item)}>{item.enabled ? <LogOut size={14} /> : <Check size={14} />}</button>}</td></tr>)}</tbody></table></div></section><section className="surface auth-section"><div className="surface-heading"><div><span className="section-kicker">ROLES</span><h2>角色与权限</h2></div><ShieldCheck size={17} /></div><div className="role-list">{roles.map((role) => <div className="role-row" key={role.id}><div><strong>{role.name}</strong><small>{role.description}{role.built_in ? ' · 系统内置' : ''}</small></div><code>{role.permission_keys.join('、') || '无权限'}</code></div>)}</div>{canWriteUsers && <form className="inline-form" onSubmit={createUser}><span className="section-kicker">CREATE USER</span><label className="field"><span>用户名</span><input value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label className="field"><span>初始密码</span><input type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required /></label><label className="field"><span>角色</span><select value={roleId} onChange={(event) => setRoleId(event.target.value)}><option value="">无角色</option>{roles.map((role) => <option value={role.id} key={role.id}>{role.name}</option>)}</select></label><button className="primary-button" type="submit"><UserPlus size={15} />创建用户</button></form>}{canWriteRoles && <form className="inline-form role-create-form" onSubmit={createRole}><span className="section-kicker">CREATE ROLE</span><label className="field"><span>角色名称</span><input value={roleName} onChange={(event) => setRoleName(event.target.value)} required /></label><label className="field"><span>权限键（逗号分隔）</span><input value={rolePermissions} onChange={(event) => setRolePermissions(event.target.value)} placeholder="audit.read, results.read" /></label><button className="secondary-button" type="submit"><ShieldCheck size={15} />创建角色</button></form>}</section></div></div>
}

function AuditPage({ token }: { token: string }) {
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
  return <div className="page-content auth-page"><section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />AUDIT TRAIL</span><h1>审计记录</h1><p>账户、角色、权限和登录事件按时间倒序保存在本地数据库。</p></div><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? '刷新中…' : '刷新'}</button></section><section className="surface auth-section audit-section"><div className="surface-heading"><div><span className="section-kicker">LOCAL AUDIT EVENTS</span><h2>变更记录 <span className="count-badge">{events.length}</span></h2></div><ClipboardList size={17} /></div>{error ? <div className="auth-error"><AlertTriangle size={15} />{error}</div> : <div className="auth-table-wrap"><table className="auth-table audit-table"><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>详情</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>{formatTime(event.created_at)}</td><td>{event.actor_user_id ?? 'system'}</td><td><strong>{event.action}</strong></td><td>{event.target_type} {event.target_id ?? ''}</td><td><ExpandableValue value={event.details_json} summary={event.details_json} code className="audit-details" /></td></tr>)}</tbody></table></div>}</section></div>
}

function MethodsPage({ token, currentUser, currentMethod, onCurrentMethodChange, onToast }: { token: string; currentUser: AuthUser; currentMethod: CurrentMethodState | null; onCurrentMethodChange: (method: CurrentMethodState) => void; onToast: (message: string) => void }) {
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [options, setOptions] = useState<MethodOptions | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  const [draftWorkType, setDraftWorkType] = useState('routine')
  const [conditions, setConditions] = useState<MethodConditions | null>(null)
  const [composer, setComposer] = useState<'create' | 'copy' | null>(null)
  const [composerName, setComposerName] = useState('')
  const [editorSection, setEditorSection] = useState<'conditions' | 'lines' | 'print'>('conditions')
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const canWrite = currentUser.permissions.includes('methods.write')

  const load = useCallback(async () => {
    try {
      const [nextMethods, nextOptions, nextCurrent] = await Promise.all([api.methods(token), api.methodOptions(token), api.currentMethod(token)])
      setMethods(nextMethods)
      setOptions(nextOptions)
      setSelectedId((previous) => nextMethods.some((item) => item.id === previous) ? previous : (nextCurrent.method_id ?? nextMethods[0]?.id ?? null))
      onCurrentMethodChange(nextCurrent)
      setLoadError(null)
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法读取方法数据')
    }
  }, [onCurrentMethodChange, token])

  useEffect(() => { void load() }, [load])
  const selected = methods.find((item) => item.id === selectedId) ?? null
  const selectedVersion = selected?.version ?? null
  const issues = selectedVersion?.validation_errors ?? []

  useEffect(() => {
    if (!selected?.version) return
    setDraftName(selected.name)
    setDraftDescription(selected.description)
    setDraftWorkType(selected.work_type)
    setConditions(structuredClone(selected.version.conditions))
  }, [selected])

  const setCondition = <K extends keyof MethodConditions>(key: K, value: MethodConditions[K]) => {
    setConditions((previous) => previous ? { ...previous, [key]: value } : previous)
  }
  const hasIssue = (field: string) => issues.some((issue) => issue.field === field || issue.field.startsWith(`${field}.`) || issue.field.startsWith(`${field}[`))
  const notifyError = (error: unknown, fallback: string) => onToast(error instanceof Error ? error.message : fallback)

  const runAction = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await action()
      await load()
      onToast(success)
    } catch (error) {
      notifyError(error, '方法操作失败')
    } finally {
      setBusy(false)
    }
  }

  const saveDraft = () => {
    if (!selected || !conditions) return
    void runAction(() => api.updateMethod(token, selected.id, { name: draftName, description: draftDescription, work_type: draftWorkType, conditions }), '方法草稿已保存；已发布版本未改变')
  }

  const submitComposer = (event: FormEvent) => {
    event.preventDefault()
    if (!composerName.trim()) return
    const action = composer === 'copy' && selected ? api.copyMethod(token, selected.id, composerName) : api.createMethod(token, { name: composerName })
    setBusy(true)
    void action.then(async (created) => {
      setComposer(null)
      setComposerName('')
      await load()
      setSelectedId(created.id)
      onToast(composer === 'copy' ? '方法副本已创建' : '新方法草稿已创建')
    }).catch((error) => notifyError(error, '创建方法失败')).finally(() => setBusy(false))
  }

  const currentLayout = options?.ccd_layouts.find((item) => item.id === Number(conditions?.ccd_layout_id) || item.name === String(conditions?.ccd_layout_id))
  const matchingCalibrations = options?.dispersion_calibrations.filter((item) => item.ccd_layout_id === currentLayout?.id) ?? []
  const currentCalibration = matchingCalibrations.find((item) => item.id === Number(conditions?.dispersion_calibration_id) || item.name === String(conditions?.dispersion_calibration_id))

  const changeLayout = (layoutId: number) => {
    const layout = options?.ccd_layouts.find((item) => item.id === layoutId)
    const calibration = options?.dispersion_calibrations.find((item) => item.ccd_layout_id === layoutId && item.enabled)
    if (!layout) return
    setConditions((previous) => previous ? { ...previous, ccd_layout_id: layoutId, selected_ccds: [...layout.ccd_indices], dispersion_calibration_id: calibration?.id ?? previous.dispersion_calibration_id } : previous)
  }

  const toggleCcd = (ccdIndex: number) => {
    if (!conditions) return
    const selectedCcds = conditions.selected_ccds.includes(ccdIndex) ? conditions.selected_ccds.filter((item) => item !== ccdIndex) : [...conditions.selected_ccds, ccdIndex].sort((a, b) => a - b)
    setCondition('selected_ccds', selectedCcds)
  }

  const updateAngle = (index: number, patch: Partial<AngleExposure>) => {
    if (!conditions) return
    setCondition('angle_exposures', conditions.angle_exposures.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  }

  const removeAngle = (index: number) => {
    if (!conditions || conditions.angle_exposures.length === 1) return
    setCondition('angle_exposures', conditions.angle_exposures.filter((_, itemIndex) => itemIndex !== index))
  }

  const addAngle = () => {
    if (!conditions) return
    const previousAngle = conditions.angle_exposures[conditions.angle_exposures.length - 1]?.angle_deg ?? -10
    setCondition('angle_exposures', [...conditions.angle_exposures, { angle_deg: previousAngle + 10, storage_mode: 'averaged', start_frame: 1, end_frame: Math.max(2, conditions.frame_count) }])
  }

  return <div className="page-content methods-page" data-testid="methods-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />METHODS & SPECTRAL LINES</span><h1>方法管理</h1><p>在同一个不可变版本中维护采集条件、谱线引用和标准点。</p></div><div className="hero-actions"><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={16} />刷新</button>{canWrite && <button className="primary-button" onClick={() => { setComposer('create'); setComposerName('') }}><Plus size={16} />新建方法</button>}</div></section>
    {loadError && <div className="auth-error"><AlertTriangle size={15} />{loadError}</div>}
    {composer && <form className="surface method-composer" onSubmit={submitComposer}><div><span className="section-kicker">{composer === 'copy' ? 'COPY METHOD' : 'NEW METHOD'}</span><strong>{composer === 'copy' ? `复制“${selected?.name ?? ''}”` : '创建方法草稿'}</strong></div><label className="field"><span>新方法名称</span><input autoFocus maxLength={20} value={composerName} onChange={(event) => setComposerName(event.target.value)} placeholder="GB18030 不超过 20 字节" required /></label><button className="primary-button" disabled={busy}><Check size={15} />确认</button><button type="button" className="icon-button" title="取消" onClick={() => setComposer(null)}><X size={15} /></button></form>}
    <div className="method-workbench">
      <aside className="surface method-browser"><div className="surface-heading"><div><span className="section-kicker">METHODS</span><h2>方法列表 <span className="count-badge">{methods.length}</span></h2></div><SlidersHorizontal size={17} /></div><div className="method-list">{methods.length === 0 && <div className="empty-state"><FileText size={24} /><span>暂无方法</span><small>新建第一个方法草稿</small></div>}{methods.map((item) => { const metadata = `${item.work_type} · ${item.current_version ? `已发布 v${item.current_version}` : '仅草稿'} · 最新 v${item.latest_version}`; return <button key={item.id} className={`method-list-item ${item.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(item.id)}><span className={`method-state-dot ${item.status}`} /><span><strong title={item.name}>{item.name}</strong><small title={metadata}>{metadata}</small></span>{item.is_current && <span className="current-chip">当前</span>}</button> })}</div>{selected && <div className="method-browser-footer"><div><span>状态</span><strong>{selected.status === 'active' ? '启用' : selected.status === 'paused' ? '暂停' : '已删除'}</strong></div><div><span>已发布版本</span><strong>{selected.current_version ? `v${selected.current_version}` : '—'}</strong></div><div><span>最新内容摘要</span><CopyableCode value={selectedVersion?.content_sha256} visibleLength={10} /></div></div>}</aside>
      <main className="method-editor">
        {!selected || !conditions ? <section className="surface method-empty"><SlidersHorizontal size={30} /><h2>选择或新建方法</h2><p>方法条件、版本状态和运行操作会显示在这里。</p></section> : <>
          <section className="surface method-action-bar"><div><span className="section-kicker">SELECTED METHOD</span><h2>{selected.name} <span className={`version-chip ${selectedVersion?.state}`}>v{selectedVersion?.version} · {selectedVersion?.state === 'published' ? '已发布' : '草稿'}</span>{issues.length > 0 && <span className="issue-chip"><AlertTriangle size={13} />{issues.length} 项待修正</span>}</h2></div><div className="method-actions">{canWrite && <><button className="secondary-button" onClick={() => { setComposer('copy'); setComposerName(`${selected.name}-副本`) }} disabled={busy}><Copy size={15} />复制</button><button className="secondary-button" onClick={saveDraft} disabled={busy || selected.status === 'deleted'}><Save size={15} />保存草稿</button><button className="primary-button" onClick={() => void runAction(() => api.publishMethod(token, selected.id), '有效草稿已发布为不可变版本')} disabled={busy || selectedVersion?.state !== 'draft' || issues.length > 0}><CheckCircle2 size={15} />发布</button>{selected.published_version && !selected.is_current && selected.status === 'active' && <button className="primary-button" onClick={() => void runAction(() => api.openMethod(token, selected.id), '当前运行方法已切换')} disabled={busy}><PlayCircle size={15} />设为当前</button>}{selected.status === 'active' && <button className="icon-button" title="暂停方法" onClick={() => void runAction(() => api.pauseMethod(token, selected.id), '方法已暂停')} disabled={busy}><PauseCircle size={15} /></button>}{selected.status === 'paused' && <button className="icon-button" title="恢复方法" onClick={() => void runAction(() => api.resumeMethod(token, selected.id), '方法已恢复')} disabled={busy}><PlayCircle size={15} /></button>}<button className="icon-button danger" title="软删除方法" onClick={() => { if (window.confirm(`确认删除方法“${selected.name}”？历史版本仍会保留。`)) void runAction(() => api.deleteMethod(token, selected.id), '方法已软删除') }} disabled={busy}><Trash2 size={15} /></button></>}</div></section>
          <div className="method-editor-tabs" role="tablist"><button className={editorSection === 'conditions' ? 'active' : ''} onClick={() => setEditorSection('conditions')}>方法条件</button><button className={editorSection === 'lines' ? 'active' : ''} onClick={() => setEditorSection('lines')}>分析谱线 <span>{selectedVersion?.lines?.length ?? 1}</span></button><button className={editorSection === 'print' ? 'active' : ''} onClick={() => setEditorSection('print')}><Printer size={13} />预览与打印</button></div>
          {editorSection === 'conditions' && <>
          {issues.length > 0 && <section className="surface method-issues"><div><AlertTriangle size={17} /><strong>草稿尚不能发布</strong><span>错误已随草稿保留，不影响当前有效版本。</span></div><ul>{issues.map((issue, index) => <li key={`${issue.field}-${index}`}><code>{issue.field}</code><span>{issue.message}</span></li>)}</ul></section>}
          <section className="surface method-section"><div className="surface-heading"><div><span className="section-kicker">IDENTITY</span><h2>基本信息</h2></div><FileText size={17} /></div><div className="method-field-grid"><label className="field"><span>方法名称</span><input value={draftName} onChange={(event) => setDraftName(event.target.value)} disabled={!canWrite} /><small>{new TextEncoder().encode(draftName).length} UTF-8 字节；保存时按 GB18030 验证 20 字节边界</small></label><label className="field"><span>工作类型</span><input value={draftWorkType} onChange={(event) => setDraftWorkType(event.target.value)} disabled={!canWrite} /></label><label className="field span-2"><span>说明</span><textarea rows={2} value={draftDescription} onChange={(event) => setDraftDescription(event.target.value)} disabled={!canWrite} /></label></div></section>
          <section className={`surface method-section ${hasIssue('selected_ccds') || hasIssue('reference_wavelength_nm') || hasIssue('actual_reference_wavelength_nm') ? 'has-errors' : ''}`}><div className="surface-heading"><div><span className="section-kicker">CCD & DISPERSION</span><h2>CCD 布局与参考线</h2></div><Database size={17} /></div><div className="method-field-grid"><label className="field"><span>CCD 布局</span><select value={String(currentLayout?.id ?? '')} onChange={(event) => changeLayout(Number(event.target.value))} disabled={!canWrite}>{options?.ccd_layouts.map((layout) => <option key={layout.id} value={layout.id}>{layout.name} · {layout.frame_count}×{layout.ccds_per_frame}</option>)}</select></label><label className="field"><span>色散标定</span><select value={String(currentCalibration?.id ?? '')} onChange={(event) => setCondition('dispersion_calibration_id', Number(event.target.value))} disabled={!canWrite}>{matchingCalibrations.map((calibration) => <option key={calibration.id} value={calibration.id}>{calibration.name}</option>)}</select></label><div className="field span-2"><span>启用 CCD</span><div className="ccd-selector">{currentLayout?.ccd_indices.map((index, itemIndex) => <label key={index} className={conditions.selected_ccds.includes(index) ? 'selected' : ''}><input type="checkbox" checked={conditions.selected_ccds.includes(index)} onChange={() => toggleCcd(index)} disabled={!canWrite} /><strong>{currentLayout.ccd_labels[itemIndex] ?? `CCD ${index}`}</strong><small>索引 {index}</small></label>)}</div></div><label className="field"><span>参考波长 (nm)</span><EmptyableNumberInput step="0.0001" value={conditions.reference_wavelength_nm} onValueChange={(value) => setCondition('reference_wavelength_nm', value)} disabled={!canWrite} /></label><label className="field"><span>实际参考波长 (nm)</span><EmptyableNumberInput step="0.0001" value={conditions.actual_reference_wavelength_nm} onValueChange={(value) => setCondition('actual_reference_wavelength_nm', value)} disabled={!canWrite} /></label><label className="field"><span>参考线宽（点）</span><EmptyableNumberInput min="11" max="50" value={conditions.reference_width_points} onValueChange={(value) => setCondition('reference_width_points', value)} disabled={!canWrite} /></label><label className="field"><span>分析单位</span><select value={conditions.analysis_unit} onChange={(event) => setCondition('analysis_unit', event.target.value as MethodConditions['analysis_unit'])} disabled={!canWrite}><option value="ug/g">ug/g</option><option value="mg/g">mg/g</option><option value="%">%</option></select></label></div>{currentCalibration && <div className="ccd-ranges">{currentCalibration.ccd_ranges.map((range) => <div key={range.ccd_index} className={conditions.selected_ccds.includes(range.ccd_index) ? 'active' : ''}><strong>CCD {range.ccd_index}</strong><span>{range.safe_start_nm.toFixed(3)} — {range.safe_end_nm.toFixed(3)} nm</span></div>)}</div>}</section>
          <section className={`surface method-section ${hasIssue('frame_count') || hasIssue('dark_frame_count') ? 'has-errors' : ''}`}><div className="surface-heading"><div><span className="section-kicker">ACQUISITION</span><h2>激发与采集</h2></div><Activity size={17} /></div><div className="numeric-grid"><NumberField label="预激发 (s)" value={conditions.pre_excitation_seconds} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('pre_excitation_seconds', value)} /><NumberField label="采样周期 (s)" value={conditions.sampling_period_seconds} min={1} max={2} disabled={!canWrite} onChange={(value) => setCondition('sampling_period_seconds', value)} /><NumberField label="采集帧数" value={conditions.frame_count} min={1} max={255} disabled={!canWrite} onChange={(value) => setCondition('frame_count', value)} /><NumberField label="暗帧数" value={conditions.dark_frame_count} min={0} max={20} disabled={!canWrite} onChange={(value) => setCondition('dark_frame_count', value)} /></div></section>
          <section className={`surface method-section ${hasIssue('sample_repeats') || hasIssue('maximum_id_deviation') || hasIssue('rsd_threshold') ? 'has-errors' : ''}`}><div className="surface-heading"><div><span className="section-kicker">REPEAT & QUALITY</span><h2>重复测量与质量阈值</h2></div><ShieldCheck size={17} /></div><div className="numeric-grid"><NumberField label="样品重复次数" value={conditions.sample_repeats} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('sample_repeats', value)} /><NumberField label="标样重复次数" value={conditions.standard_repeats} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('standard_repeats', value)} /><NumberField label="控制样重复次数" value={conditions.control_repeats} min={1} max={10} disabled={!canWrite} onChange={(value) => setCondition('control_repeats', value)} /><NumberField label="最大 ID 偏差" value={conditions.maximum_id_deviation} min={0} max={20} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('maximum_id_deviation', value)} /><NumberField label="RSD 阈值" value={conditions.rsd_threshold} min={0} max={20} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('rsd_threshold', value)} /><NumberField label="校准阈值" value={conditions.calibration_threshold} min={0} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('calibration_threshold', value)} /><NumberField label="质控阈值" value={conditions.qc_threshold} min={0} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('qc_threshold', value)} /><NumberField label="异常阈值" value={conditions.abnormal_threshold} min={0} step={0.1} disabled={!canWrite} onChange={(value) => setCondition('abnormal_threshold', value)} /><label className="field"><span>标准样品</span><input value={conditions.standard_sample_name} onChange={(event) => setCondition('standard_sample_name', event.target.value)} disabled={!canWrite} /></label><label className="toggle-row compact-toggle"><input type="checkbox" checked={conditions.rsd_enabled} onChange={(event) => setCondition('rsd_enabled', event.target.checked)} disabled={!canWrite} /><span><strong>启用 RSD 检查</strong><small>按阈值标记重复性异常</small></span></label></div></section>
          <section className={`surface method-section ${hasIssue('angle_exposures') ? 'has-errors' : ''}`}><div className="surface-heading"><div><span className="section-kicker">ANGLE EXPOSURES</span><h2>分角度存储区间</h2></div>{canWrite && <button className="secondary-button" onClick={addAngle}><Plus size={15} />添加角度</button>}</div><div className="angle-table-wrap"><table className="angle-table"><thead><tr><th>角度 (°)</th><th>存储模式</th><th>起始帧</th><th>结束帧</th><th>范围规则</th><th /></tr></thead><tbody>{conditions.angle_exposures.map((angle, index) => <tr key={`${angle.angle_deg}-${index}`}><td><EmptyableNumberInput step="0.1" value={angle.angle_deg} onValueChange={(value) => updateAngle(index, { angle_deg: value })} disabled={!canWrite} /></td><td><select value={angle.storage_mode} onChange={(event) => updateAngle(index, { storage_mode: event.target.value as AngleExposure['storage_mode'] })} disabled={!canWrite}>{options?.storage_modes.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}</select></td><td><EmptyableNumberInput min="1" max={conditions.frame_count} value={angle.start_frame} onValueChange={(value) => updateAngle(index, { start_frame: value })} disabled={!canWrite} /></td><td><EmptyableNumberInput min="1" max={conditions.frame_count} value={angle.end_frame} onValueChange={(value) => updateAngle(index, { end_frame: value })} disabled={!canWrite} /></td><td><span className="rule-note">{angle.storage_mode === 'full_interval' ? '至少 2 帧，完整保存' : '区间求均值后保存'}</span></td><td>{canWrite && <button className="icon-button compact danger" title="移除此角度" onClick={() => removeAngle(index)} disabled={conditions.angle_exposures.length === 1}><Trash2 size={14} /></button>}</td></tr>)}</tbody></table></div></section>
          {canWrite && <div className="method-save-footer"><span>{selected.is_current ? `当前运行引用已发布 v${currentMethod?.version}` : '编辑内容只会生成新草稿版本'}</span><button className="primary-button" onClick={saveDraft} disabled={busy}><Save size={16} />保存方法草稿</button></div>}
          </>}
          {editorSection === 'lines' && <SpectralLinesPanel methodId={selected.id} token={token} canWrite={canWrite} onChanged={load} onToast={onToast} />}
          {editorSection === 'print' && <MethodPrintPanel methodId={selected.id} methodName={selected.name} version={selectedVersion?.version ?? null} token={token} canWrite={canWrite} onToast={onToast} />}
        </>}
      </main>
    </div>
  </div>
}

type EmptyableNumberInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value' | 'onChange'> & {
  value: number
  onValueChange: (value: number) => void
}

function EmptyableNumberInput({ value, onValueChange, onBlur, ...inputProps }: EmptyableNumberInputProps) {
  const [text, setText] = useState(() => Number.isFinite(value) ? String(value) : '')
  const lastValue = useRef(value)

  useEffect(() => {
    if (Object.is(lastValue.current, value)) return
    lastValue.current = value
    setText(Number.isFinite(value) ? String(value) : '')
  }, [value])

  return <input {...inputProps} type="number" value={text} onBlur={(event) => {
    if (text === '') setText(Number.isFinite(lastValue.current) ? String(lastValue.current) : '')
    onBlur?.(event)
  }} onChange={(event) => {
    const nextText = event.target.value
    setText(nextText)
    if (nextText === '') return
    const nextValue = Number(nextText)
    if (!Number.isFinite(nextValue)) return
    lastValue.current = nextValue
    onValueChange(nextValue)
  }} />
}

function NumberField({ label, value, min, max, step = 1, disabled, onChange }: { label: string; value: number; min?: number; max?: number; step?: number; disabled?: boolean; onChange: (value: number) => void }) {
  return <label className="field"><span>{label}</span><EmptyableNumberInput value={value} min={min} max={max} step={step} disabled={disabled} onValueChange={onChange} /></label>
}

function MethodPrintPanel({ methodId, methodName, version, token, canWrite, onToast }: { methodId: number; methodName: string; version: number | null; token: string; canWrite: boolean; onToast: (message: string) => void }) {
  const [settings, setSettings] = useState<MethodPrintSettings | null>(null)
  const [printers, setPrinters] = useState<PrinterOption[]>([])
  const [jobs, setJobs] = useState<PrintJob[]>([])
  const [previewHtml, setPreviewHtml] = useState('')
  const [metrics, setMetrics] = useState({ pageCount: 0, fieldCount: 0 })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reportError = (cause: unknown, fallback: string) => {
    const message = cause instanceof Error ? cause.message : fallback
    setError(message)
    onToast(message)
  }

  const refreshPreview = useCallback(async (applied: MethodPrintSettings) => {
    const result = await api.methodPreview(token, methodId, version, applied)
    setPreviewHtml(result.html)
    setMetrics({ pageCount: result.pageCount, fieldCount: result.fieldCount })
    setError(null)
  }, [methodId, token, version])

  const load = useCallback(async () => {
    setBusy(true)
    try {
      const [nextSettings, printerResult, jobResult] = await Promise.all([
        api.methodPrintSettings(token),
        api.methodPrinters(token),
        api.methodPrintJobs(token, methodId),
      ])
      setSettings(nextSettings)
      setPrinters(printerResult.printers)
      setJobs(jobResult.jobs)
      await refreshPreview(nextSettings)
    } catch (cause) {
      reportError(cause, '无法加载方法预览')
    } finally {
      setBusy(false)
    }
  }, [methodId, refreshPreview, token])

  useEffect(() => { void load() }, [load])

  const update = <K extends keyof MethodPrintSettings>(key: K, value: MethodPrintSettings[K]) => {
    setSettings((previous) => previous ? { ...previous, [key]: value } : previous)
  }

  const preview = async () => {
    if (!settings) return
    setBusy(true)
    try { await refreshPreview(settings) } catch (cause) { reportError(cause, '预览生成失败') } finally { setBusy(false) }
  }

  const saveDefaults = async () => {
    if (!settings) return
    setBusy(true)
    try {
      const saved = await api.saveMethodPrintSettings(token, settings)
      setSettings(saved)
      await refreshPreview(saved)
      onToast('打印机、纸张、方向、边距与版式默认值已保存')
    } catch (cause) { reportError(cause, '打印设置保存失败') } finally { setBusy(false) }
  }

  const exportPdf = async () => {
    if (!settings) return
    setBusy(true)
    try {
      const result = await api.methodPdf(token, methodId, version, settings)
      const url = URL.createObjectURL(result.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${methodName}-v${version ?? 'latest'}-方法参数.pdf`
      link.click()
      URL.revokeObjectURL(url)
      setMetrics({ pageCount: result.pageCount, fieldCount: result.fieldCount })
      onToast(`PDF 已生成：${result.pageCount} 页、${result.fieldCount} 个字段`)
    } catch (cause) { reportError(cause, 'PDF 导出失败') } finally { setBusy(false) }
  }

  const submitPrint = async () => {
    if (!settings) return
    setBusy(true)
    try {
      if (settings.preview_before_print) await refreshPreview(settings)
      const job = await api.printMethod(token, methodId, version, settings, settings.default_printer)
      setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)])
      onToast(job.status === 'completed' ? `虚拟打印完成：${job.page_count} 页` : '打印任务已提交到系统队列')
    } catch (cause) { reportError(cause, '打印任务提交失败') } finally { setBusy(false) }
  }

  if (!settings) return <section className="surface method-empty compact"><Printer size={26} /><h2>正在准备打印工作区</h2><p>{error ?? '读取打印机、页面默认值与方法版本。'}</p></section>

  return <div className="print-workbench" data-testid="method-print-panel">
    {error && <div className="auth-error"><AlertTriangle size={15} />{error}</div>}
    <aside className="surface print-settings-panel">
      <div className="surface-heading"><div><span className="section-kicker">PAGE & PRINTER</span><h2>打印设置</h2></div><Printer size={17} /></div>
      <div className="print-setting-grid">
        <label className="field span-2"><span>打印机</span><select value={settings.default_printer} onChange={(event) => update('default_printer', event.target.value)}>{printers.map((item) => <option value={item.name} key={item.name}>{item.display_name}{item.virtual ? ' · 可自动验收' : ''}</option>)}</select></label>
        <label className="field"><span>纸张</span><select value={settings.paper} onChange={(event) => update('paper', event.target.value as MethodPrintSettings['paper'])}><option>A4</option><option>A3</option><option>Letter</option></select></label>
        <label className="field"><span>方向</span><select value={settings.orientation} onChange={(event) => update('orientation', event.target.value as MethodPrintSettings['orientation'])}><option value="portrait">纵向</option><option value="landscape">横向</option></select></label>
        <label className="field"><span>版式</span><select value={settings.layout} onChange={(event) => update('layout', event.target.value as MethodPrintSettings['layout'])}><option value="standard">标准</option><option value="compact">紧凑</option></select></label>
        <NumberField label="字号 (pt)" value={settings.font_size_pt} min={8} max={12} disabled={busy} onChange={(value) => update('font_size_pt', value)} />
        <NumberField label="上边距 (mm)" value={settings.margin_top_mm} min={5} max={40} step={0.5} disabled={busy} onChange={(value) => update('margin_top_mm', value)} />
        <NumberField label="右边距 (mm)" value={settings.margin_right_mm} min={5} max={40} step={0.5} disabled={busy} onChange={(value) => update('margin_right_mm', value)} />
        <NumberField label="下边距 (mm)" value={settings.margin_bottom_mm} min={5} max={40} step={0.5} disabled={busy} onChange={(value) => update('margin_bottom_mm', value)} />
        <NumberField label="左边距 (mm)" value={settings.margin_left_mm} min={5} max={40} step={0.5} disabled={busy} onChange={(value) => update('margin_left_mm', value)} />
        <NumberField label="份数" value={settings.copies} min={1} max={99} disabled={busy} onChange={(value) => update('copies', value)} />
        <label className="field"><span>双面</span><select value={settings.duplex} onChange={(event) => update('duplex', event.target.value as MethodPrintSettings['duplex'])}><option value="none">单面</option><option value="long_edge">长边翻转</option><option value="short_edge">短边翻转</option></select></label>
      </div>
      <label className="toggle-row"><input type="checkbox" checked={settings.color} onChange={(event) => update('color', event.target.checked)} /><span><strong>彩色打印</strong><small>随任务保存到渲染输入</small></span></label>
      <label className="toggle-row"><input type="checkbox" checked={settings.preview_before_print} onChange={(event) => update('preview_before_print', event.target.checked)} /><span><strong>打印前刷新预览</strong><small>保证预览和本次任务使用同一输入</small></span></label>
      <div className="print-setting-actions"><button className="secondary-button" onClick={() => void preview()} disabled={busy}><RefreshCw size={15} />更新预览</button>{canWrite && <button className="primary-button" onClick={() => void saveDefaults()} disabled={busy}><Save size={15} />保存默认值</button>}</div>
      <div className="print-fact-note"><Info size={14} /><span>这里打印方法条件、谱线和标准点；分析结果报告不在 S05 范围内。</span></div>
    </aside>
    <main className="surface print-preview-panel">
      <div className="surface-heading"><div><span className="section-kicker">HTML PREVIEW</span><h2>方法参数预览 <span className="count-badge">{metrics.pageCount} 页</span></h2></div><div className="preview-actions"><span>{metrics.fieldCount} 个字段 · v{version ?? 'latest'}</span><button className="secondary-button" onClick={() => void exportPdf()} disabled={busy}><Download size={15} />导出 PDF</button>{canWrite && <button className="primary-button" onClick={() => void submitPrint()} disabled={busy}><Printer size={15} />打印</button>}</div></div>
      <div className="preview-frame-shell">{previewHtml ? <iframe className={settings.orientation} title={`${methodName} 方法参数预览`} srcDoc={previewHtml} sandbox="" /> : <div className="method-empty compact"><FileText size={24} /><p>等待生成 HTML 预览</p></div>}</div>
      <div className="print-jobs"><div className="print-jobs-heading"><strong>最近打印任务 <span className="count-badge">{jobs.length}</span></strong><span>失败任务会保留渲染输入和错误 PDF</span></div>{jobs.length === 0 ? <div className="empty-job">尚无打印记录</div> : <div className="full-list">{jobs.map((job) => { const metadata = `v${job.method_version} · ${job.page_count} 页 · ${formatDateTime(job.created_at)}`; return <div className={`print-job ${job.status}`} key={job.id}><span className="job-status">{({ completed: '已完成', queued: '已排队', rendered: '已渲染', failed: '失败' } as Record<string, string>)[job.status]}</span><div><strong title={job.printer_name}>{job.printer_name}</strong><small title={metadata}>{metadata}</small></div><CopyableCode value={job.output_path ?? job.error_code ?? job.id} visibleLength={28} /></div> })}</div>}</div>
    </main>
  </div>
}

const lineTypeLabel: Record<SpectralLineInput['line_type'], string> = {
  baseline: '参考基线',
  analysis: '分析线',
  internal_standard: '内标线',
  positioning: '定位线',
}

const defaultLine = (): SpectralLineInput => ({
  line_type: 'analysis', element: 'Fe', wavelength_nm: 254, actual_wavelength_nm: 254,
  enabled: true, critical_band: false, priority: 0, background_line_id: 'reference-baseline',
  alignment_line_id: null, internal_standard_mode: 'none', internal_standard_line_id: null,
  scan_width_points: 9, background_offset_points: 0, peak_mode: 'max_single_point', peak_width_points: 1,
  fit_mode: 'linear', coordinate_type: 'normal', unit: 'ug/g', value_kind: 'content',
  decimal_places: 2, lower_peak: 300, minimum_peak_ratio: 1.5, valid_range_min: 0,
  valid_range_max: 1000, over_limit_tolerance_percent: 0,
  standard_points: [1, 2, 3, 4].map((value) => ({ name: `S${value}`, value, active: true })),
})

function lineToInput(line: SpectralLine): SpectralLineInput {
  const { id: _id, order: _order, reference_baseline: _reference, detectability: _detectability, ...input } = line
  return structuredClone(input)
}

function SpectralLinesPanel({ methodId, token, canWrite, onChanged, onToast }: { methodId: number; token: string; canWrite: boolean; onChanged: () => Promise<void>; onToast: (message: string) => void }) {
  const [collection, setCollection] = useState<MethodLineCollection | null>(null)
  const [options, setOptions] = useState<SpectralLineOptions | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<SpectralLineInput>(defaultLine)
  const [creating, setCreating] = useState(false)
  const [detectability, setDetectability] = useState<LineDetectability | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadLines = useCallback(async () => {
    try {
      const [nextCollection, nextOptions] = await Promise.all([
        api.methodLines(token, methodId), api.spectralLineOptions(token),
      ])
      setCollection(nextCollection)
      setOptions(nextOptions)
      setSelectedId((previous) => nextCollection.lines.some((line) => line.id === previous) ? previous : nextCollection.lines[0]?.id ?? null)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取谱线')
    }
  }, [methodId, token])

  useEffect(() => { void loadLines() }, [loadLines])
  useEffect(() => {
    setCreating(false)
    setSelectedId(null)
  }, [methodId])

  const selected = collection?.lines.find((line) => line.id === selectedId) ?? null
  useEffect(() => {
    if (creating || !selected) return
    setDraft(lineToInput(selected))
    setDetectability(selected.detectability ?? null)
  }, [creating, selected])

  useEffect(() => {
    if (!Number.isFinite(draft.wavelength_nm)) return
    let active = true
    const timer = window.setTimeout(() => {
      void api.detectLine(token, methodId, {
        wavelength_nm: draft.wavelength_nm,
        actual_wavelength_nm: draft.actual_wavelength_nm,
        scan_width_points: draft.scan_width_points,
      }).then((result) => { if (active) setDetectability(result) }).catch(() => { if (active) setDetectability(null) })
    }, 220)
    return () => { active = false; window.clearTimeout(timer) }
  }, [draft.actual_wavelength_nm, draft.scan_width_points, draft.wavelength_nm, methodId, token])

  const updateDraft = <K extends keyof SpectralLineInput>(key: K, value: SpectralLineInput[K]) => setDraft((previous) => ({ ...previous, [key]: value }))
  const edit = (line: SpectralLine) => { setCreating(false); setSelectedId(line.id); setDraft(lineToInput(line)); setDetectability(line.detectability ?? null) }
  const beginCreate = () => { setCreating(true); setSelectedId(null); setDraft(defaultLine()); setDetectability(null) }

  const mutate = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true)
    try {
      await action()
      await Promise.all([loadLines(), onChanged()])
      onToast(success)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '谱线操作失败')
    } finally {
      setBusy(false)
    }
  }

  const save = () => {
    if (!canWrite || selected?.line_type === 'baseline') return
    const action = creating
      ? api.createLine(token, methodId, draft)
      : selectedId ? api.updateLine(token, methodId, selectedId, draft) : Promise.reject(new Error('请选择谱线'))
    void mutate(() => action, creating ? '谱线已添加到新草稿版本' : '谱线已更新，已发布版本未改变')
    setCreating(false)
  }

  const toggle = (line: SpectralLine) => {
    const input = lineToInput(line)
    input.enabled = !input.enabled
    void mutate(() => api.updateLine(token, methodId, line.id, input), input.enabled ? '谱线已启用' : '谱线已停用')
  }

  const remove = (line: SpectralLine) => {
    if (!window.confirm(`确认删除 ${line.element} ${line.wavelength_nm.toFixed(4)} nm？`)) return
    void mutate(() => api.deleteLine(token, methodId, line.id), '谱线已删除')
  }

  const reorder = (ordered: SpectralLine[], success: string) => {
    void mutate(() => api.reorderLines(token, methodId, ordered.map((line) => line.id)), success)
  }

  const movable = collection?.lines.filter((line) => line.line_type !== 'baseline') ?? []
  const sortBy = (key: 'element' | 'wavelength_nm') => reorder(
    [...movable].sort((left, right) => key === 'element' ? left.element.localeCompare(right.element) || left.wavelength_nm - right.wavelength_nm : left.wavelength_nm - right.wavelength_nm),
    key === 'element' ? '已按元素排序' : '已按波长排序',
  )
  const move = (line: SpectralLine, offset: number) => {
    const index = movable.findIndex((item) => item.id === line.id)
    const target = index + offset
    if (index < 0 || target < 0 || target >= movable.length) return
    const ordered = [...movable]
    ;[ordered[index], ordered[target]] = [ordered[target], ordered[index]]
    reorder(ordered, '谱线顺序已更新')
  }

  const setLineType = (lineType: SpectralLineInput['line_type']) => setDraft((previous) => ({
    ...previous,
    line_type: lineType,
    standard_points: lineType === 'analysis' ? (previous.standard_points.length >= 4 ? previous.standard_points : defaultLine().standard_points) : [],
    internal_standard_mode: lineType === 'analysis' ? previous.internal_standard_mode : 'none',
    internal_standard_line_id: lineType === 'analysis' ? previous.internal_standard_line_id : null,
  }))

  const backgroundLines = collection?.lines.filter((line) => line.line_type === 'baseline' && line.enabled) ?? []
  const alignmentLines = collection?.lines.filter((line) => ['positioning', 'internal_standard'].includes(line.line_type) && line.enabled && line.id !== selectedId) ?? []
  const internalLines = collection?.lines.filter((line) => line.line_type === 'internal_standard' && line.enabled && line.id !== selectedId) ?? []
  const isBaseline = !creating && selected?.line_type === 'baseline'

  return <div className="spectral-workbench" data-testid="spectral-lines-panel">
    {error && <div className="auth-error"><AlertTriangle size={15} />{error}</div>}
    <section className="surface spectral-list-surface">
      <div className="surface-heading spectral-heading"><div><span className="section-kicker">SPECTRAL LINES</span><h2>谱线清单 <span className="count-badge">{collection?.lines.length ?? 0}/300</span></h2></div>{canWrite && <button className="primary-button" onClick={beginCreate} disabled={busy}><Plus size={15} />添加谱线</button>}</div>
      <div className="spectral-sortbar"><span>排序</span><button onClick={() => sortBy('element')} disabled={!canWrite || busy || movable.length < 2}>按元素</button><button onClick={() => sortBy('wavelength_nm')} disabled={!canWrite || busy || movable.length < 2}>按波长</button></div>
      <div className="spectral-line-list">{collection?.lines.map((line) => <button key={line.id} className={`spectral-line-card ${line.id === selectedId && !creating ? 'active' : ''} ${line.enabled ? '' : 'disabled'}`} onClick={() => edit(line)}>
        <span className={`line-type-mark ${line.line_type}`} />
        <span className="line-main"><strong title={`${line.element} ${line.wavelength_nm.toFixed(4)} nm`}>{line.element} <b>{line.wavelength_nm.toFixed(4)}</b> nm</strong><small title={`${lineTypeLabel[line.line_type]} · ${line.detectability?.detectable ? `${line.detectability.ccd_label} / 角度位 ${line.detectability.angle_slot}` : line.detectability?.message}`}>{lineTypeLabel[line.line_type]} · {line.detectability?.detectable ? `${line.detectability.ccd_label} / 角度位 ${line.detectability.angle_slot}` : line.detectability?.message}</small></span>
        <span className="line-badges">{line.reference_baseline && <i>基线</i>}{line.critical_band && <i className="critical">关键</i>}{line.priority > 0 && <i>P{line.priority}</i>}{!line.enabled && <i className="off">停用</i>}</span>
      </button>)}</div>
    </section>

    <section className="surface spectral-editor-surface">
      <div className="surface-heading"><div><span className="section-kicker">{creating ? 'NEW LINE' : 'LINE DETAIL'}</span><h2>{creating ? '添加谱线' : selected ? `${selected.element} ${selected.wavelength_nm.toFixed(4)} nm` : '选择谱线'}</h2></div>{selected && !isBaseline && canWrite && <div className="line-toolbar"><button className="icon-button compact" title="上移" onClick={() => move(selected, -1)} disabled={busy || movable[0]?.id === selected.id}>↑</button><button className="icon-button compact" title="下移" onClick={() => move(selected, 1)} disabled={busy || movable[movable.length - 1]?.id === selected.id}>↓</button><button className="icon-button compact" title={selected.enabled ? '停用' : '启用'} onClick={() => toggle(selected)} disabled={busy}>{selected.enabled ? '●' : '○'}</button><button className="icon-button compact danger" title="删除" onClick={() => remove(selected)} disabled={busy}><Trash2 size={14} /></button></div>}</div>
      {!selected && !creating ? <div className="method-empty compact"><SlidersHorizontal size={25} /><p>选择一条谱线查看完整参数。</p></div> : <>
        {isBaseline && <div className="baseline-notice"><Info size={16} /><span>参考基线全方法唯一，波长、实际波长、线宽和单位由“方法条件”维护。</span></div>}
        <div className="spectral-form-grid">
          <label className="field"><span>谱线类型</span><select value={draft.line_type} onChange={(event) => setLineType(event.target.value as SpectralLineInput['line_type'])} disabled={!canWrite || isBaseline}><option value="analysis">分析线</option><option value="internal_standard">内标线</option><option value="positioning">定位线</option>{isBaseline && <option value="baseline">参考基线</option>}</select></label>
          <label className="field"><span>元素</span><select value={draft.element} onChange={(event) => updateDraft('element', event.target.value)} disabled={!canWrite || isBaseline}>{options?.element_symbols.map((element) => <option key={element}>{element}</option>)}</select></label>
          <NumberField label="理论波长 (nm)" value={draft.wavelength_nm} min={160} max={800} step={0.0001} disabled={!canWrite || isBaseline} onChange={(value) => setDraft((previous) => ({ ...previous, wavelength_nm: value, actual_wavelength_nm: previous.actual_wavelength_nm === previous.wavelength_nm ? value : previous.actual_wavelength_nm }))} />
          <NumberField label="实际波长 (nm)" value={draft.actual_wavelength_nm ?? draft.wavelength_nm} min={160} max={800} step={0.0001} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('actual_wavelength_nm', value)} />
        </div>
        <div className={`detectability-card ${detectability == null ? 'checking' : detectability.detectable ? 'detectable' : 'undetectable'}`}><span className="detect-icon">{detectability?.detectable ? <CheckCircle2 size={18} /> : detectability ? <CircleX size={18} /> : <Clock3 size={18} />}</span><div><strong>{detectability?.detectable ? '当前条件可检测' : detectability ? '当前条件不可检测' : '正在检查检测条件'}</strong><span>{detectability?.detectable ? `${detectability.ccd_label} · 点位 ${detectability.point_index} · 角度位 ${detectability.angle_slot}${detectability.angle_deg == null ? '' : ` (${detectability.angle_deg}°)`}` : detectability?.message ?? '正在计算 CCD 落点…'}</span></div><code>{detectability?.reason_code ?? 'checking'}</code></div>
        <div className="spectral-toggle-grid"><label><input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft('enabled', event.target.checked)} disabled={!canWrite || isBaseline} /><span><strong>启用谱线</strong><small>停用后不参与后续分析</small></span></label><label><input type="checkbox" checked={draft.critical_band} onChange={(event) => updateDraft('critical_band', event.target.checked)} disabled={!canWrite || isBaseline} /><span><strong>关键波段</strong><small>随方法版本固化</small></span></label><NumberField label="优先级" value={draft.priority} min={0} max={100} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('priority', value)} /></div>

        <div className="spectral-section-title"><span>REFERENCES</span><strong>引用与内标</strong></div>
        <div className="spectral-form-grid">
          <label className="field"><span>背景线</span><select value={draft.background_line_id ?? ''} onChange={(event) => updateDraft('background_line_id', event.target.value || null)} disabled={!canWrite || isBaseline}><option value="">不引用</option>{backgroundLines.map((line) => <option key={line.id} value={line.id}>{line.element} {line.wavelength_nm.toFixed(4)}</option>)}</select></label>
          <label className="field"><span>定位参考</span><select value={draft.alignment_line_id ?? ''} onChange={(event) => updateDraft('alignment_line_id', event.target.value || null)} disabled={!canWrite || isBaseline}><option value="">不引用</option>{alignmentLines.map((line) => <option key={line.id} value={line.id}>{lineTypeLabel[line.line_type]} · {line.element} {line.wavelength_nm.toFixed(4)}</option>)}</select></label>
          <label className="field"><span>内标方式</span><select value={draft.internal_standard_mode} onChange={(event) => updateDraft('internal_standard_mode', event.target.value as SpectralLineInput['internal_standard_mode'])} disabled={!canWrite || isBaseline || draft.line_type !== 'analysis'}><option value="none">无内标</option><option value="background">背景内标</option><option value="line">普通内标线</option></select></label>
          <label className="field"><span>内标线引用</span><select value={draft.internal_standard_line_id ?? ''} onChange={(event) => updateDraft('internal_standard_line_id', event.target.value || null)} disabled={!canWrite || isBaseline || draft.internal_standard_mode !== 'line'}><option value="">请选择</option>{internalLines.map((line) => <option key={line.id} value={line.id}>{line.element} {line.wavelength_nm.toFixed(4)}</option>)}</select></label>
        </div>

        <div className="spectral-section-title"><span>PEAK & FIT</span><strong>峰值、拟合与结果规则</strong></div>
        <div className="spectral-form-grid dense">
          <NumberField label="扫描宽度（点）" value={draft.scan_width_points} min={5} max={31} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('scan_width_points', value)} />
          <NumberField label="背景偏移（点）" value={draft.background_offset_points} min={-100} max={100} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('background_offset_points', value)} />
          <label className="field"><span>峰值方式</span><select value={draft.peak_mode} onChange={(event) => setDraft((previous) => ({ ...previous, peak_mode: event.target.value as SpectralLineInput['peak_mode'], peak_width_points: event.target.value === 'max_single_point' ? 1 : Math.max(3, previous.peak_width_points | 1) }))} disabled={!canWrite || isBaseline}><option value="max_single_point">最大值</option><option value="gaussian">高斯曲线</option></select></label>
          <NumberField label="计算点数" value={draft.peak_width_points} min={1} max={9} step={draft.peak_mode === 'gaussian' ? 2 : 1} disabled={!canWrite || isBaseline || draft.peak_mode === 'max_single_point'} onChange={(value) => updateDraft('peak_width_points', value)} />
          <label className="field"><span>拟合方式</span><select value={draft.fit_mode} onChange={(event) => updateDraft('fit_mode', event.target.value as SpectralLineInput['fit_mode'])} disabled={!canWrite || isBaseline}><option value="linear">直线函数</option><option value="quadratic">二次曲线</option><option value="cubic">三次曲线</option><option value="spline">样条函数</option></select></label>
          <label className="field"><span>拟合坐标</span><select value={draft.coordinate_type} onChange={(event) => updateDraft('coordinate_type', event.target.value as SpectralLineInput['coordinate_type'])} disabled={!canWrite || isBaseline}><option value="normal">普通坐标</option><option value="logarithmic">对数坐标</option></select></label>
          <label className="field"><span>单位</span><select value={draft.unit} onChange={(event) => updateDraft('unit', event.target.value as SpectralLineInput['unit'])} disabled={!canWrite || isBaseline}><option value="ug/g">ug/g</option><option value="mg/g">mg/g</option><option value="%">%</option></select></label>
          <label className="field"><span>数值类型</span><select value={draft.value_kind} onChange={(event) => updateDraft('value_kind', event.target.value as SpectralLineInput['value_kind'])} disabled={!canWrite || isBaseline}><option value="content">含量</option><option value="concentration">浓度</option></select></label>
          <NumberField label="小数位" value={draft.decimal_places} min={0} max={6} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('decimal_places', value)} />
          <NumberField label="低峰阈值" value={draft.lower_peak} min={100} max={600} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('lower_peak', value)} />
          <NumberField label="最小峰侧比" value={draft.minimum_peak_ratio} min={1.1} max={2.5} step={0.1} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('minimum_peak_ratio', value)} />
          <NumberField label="有效下限" value={draft.valid_range_min} min={0} max={9999999} step={0.01} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('valid_range_min', value)} />
          <NumberField label="有效上限" value={draft.valid_range_max} min={0} max={9999999} step={0.01} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('valid_range_max', value)} />
          <NumberField label="超限容差 (%)" value={draft.over_limit_tolerance_percent} min={0} max={100} step={0.1} disabled={!canWrite || isBaseline} onChange={(value) => updateDraft('over_limit_tolerance_percent', value)} />
        </div>

        {draft.line_type === 'analysis' && <><div className="spectral-section-title"><span>STANDARD POINTS</span><strong>标准点 <i>{draft.standard_points.length}/50</i></strong>{canWrite && <button className="secondary-button compact" onClick={() => updateDraft('standard_points', [...draft.standard_points, { name: `S${draft.standard_points.length + 1}`, value: draft.standard_points.length + 1, active: true }])} disabled={isBaseline || draft.standard_points.length >= 50}><Plus size={14} />添加</button>}</div><div className="standard-points-wrap"><table className="standard-points-table"><thead><tr><th>启用</th><th>名称</th><th>含量 / 浓度</th><th /></tr></thead><tbody>{draft.standard_points.map((point, index) => <tr key={index}><td><input type="checkbox" checked={point.active} onChange={(event) => updateDraft('standard_points', draft.standard_points.map((item, itemIndex) => itemIndex === index ? { ...item, active: event.target.checked } : item))} disabled={!canWrite || isBaseline} /></td><td><input value={point.name} maxLength={50} onChange={(event) => updateDraft('standard_points', draft.standard_points.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} disabled={!canWrite || isBaseline} /></td><td><EmptyableNumberInput min="0.00000099" max="9999999" step="any" value={point.value} onValueChange={(value) => updateDraft('standard_points', draft.standard_points.map((item, itemIndex) => itemIndex === index ? { ...item, value } : item))} disabled={!canWrite || isBaseline} /></td><td><button className="icon-button compact danger" title="删除标准点" onClick={() => updateDraft('standard_points', draft.standard_points.filter((_, itemIndex) => itemIndex !== index))} disabled={!canWrite || isBaseline || draft.standard_points.length <= 4}><Trash2 size={13} /></button></td></tr>)}</tbody></table></div></>}
        {canWrite && !isBaseline && <div className="spectral-savebar"><span>保存会校验全部引用，成功后生成新草稿版本。</span><button className="primary-button" onClick={save} disabled={busy || !detectability?.detectable}><Save size={15} />{creating ? '添加谱线' : '保存谱线'}</button></div>}
      </>}
    </section>
  </div>
}

function SettingsPage({ settings, onSave, onReset }: { settings: Settings; onSave: (settings: Settings) => void; onReset: () => void }) {
  const [draft, setDraft] = useState(settings)
  const [pickerTarget, setPickerTarget] = useState<string | null>(null)
  const pickerRef = useRef<HTMLInputElement>(null)
  useEffect(() => setDraft(settings), [settings])
  const changeDirectory = (key: string, value: string) => setDraft({ ...draft, directories: { ...draft.directories, [key]: value } })
  const chooseDirectory = (key: string) => { setPickerTarget(key); pickerRef.current?.click() }
  const onPickedDirectory = (files: FileList | null) => {
    const relativePath = files?.[0]?.webkitRelativePath
    if (pickerTarget && relativePath) changeDirectory(pickerTarget, relativePath.split('/')[0])
    setPickerTarget(null)
  }
  return <div className="page-content settings-page" data-testid="settings"><section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />APPLICATION SETTINGS</span><h1>软件设置</h1><p>保存后立即应用显示、日志、打印与时间设置；目录作为桌面文件操作的默认位置。</p></div><div className="hero-actions"><span className="settings-live-badge"><CheckCircle2 size={14} />保存后生效</span><button className="secondary-button" onClick={onReset}><RefreshCw size={16} />恢复默认</button><button className="primary-button" data-testid="settings-save" onClick={() => onSave(draft)}><Save size={16} />保存设置</button></div></section><input ref={pickerRef} className="hidden-picker" type="file" multiple onChange={(event) => onPickedDirectory(event.target.files)} {...({ webkitdirectory: '' } as Record<string, string>)} /><div className="settings-layout"><section className="surface settings-section"><div className="surface-heading"><div><span className="section-kicker">DIRECTORIES</span><h2>默认目录</h2></div><FolderOpen size={17} /></div><p className="settings-effect-note">供桌面文件选择、导出与备份使用；浏览器开发模式仍由浏览器管理下载位置。</p><div className="field-grid">{Object.entries(draft.directories).map(([key, value]) => <label className="field" key={key}><span>{({ data: '数据目录', methods: '方法目录', samples: '样品目录', exports: '导出目录', backups: '备份目录' } as Record<string, string>)[key] ?? key}</span><div className="field-with-action"><input value={value} onChange={(event) => changeDirectory(key, event.target.value)} /><button className="icon-button compact" title="选择目录" onClick={() => chooseDirectory(key)}><FolderOpen size={15} /></button></div></label>)}</div></section><section className="surface settings-section"><div className="surface-heading"><div><span className="section-kicker">DISPLAY & LOGGING</span><h2>显示与日志</h2></div><SlidersHorizontal size={17} /></div><p className="settings-effect-note">主题、密度和状态区立即影响界面；日志级别、大小与保留期影响运行日志文件。</p><div className="field-grid"><label className="field"><span>界面主题</span><select value={draft.display.theme} onChange={(event) => setDraft({ ...draft, display: { ...draft.display, theme: event.target.value } })}><option value="light">浅色工作区</option><option value="dark">深色工作区</option></select></label><label className="field"><span>信息密度</span><select value={draft.display.density} onChange={(event) => setDraft({ ...draft, display: { ...draft.display, density: event.target.value } })}><option value="comfortable">舒适</option><option value="compact">紧凑</option></select></label><label className="field"><span>日志级别</span><select value={draft.logging.level} onChange={(event) => setDraft({ ...draft, logging: { ...draft.logging, level: event.target.value } })}><option value="debug">调试</option><option value="info">信息</option><option value="warning">警告</option></select></label><label className="field"><span>日志保留天数</span><EmptyableNumberInput min="1" max="365" value={draft.logging.retention_days} onValueChange={(value) => setDraft({ ...draft, logging: { ...draft.logging, retention_days: value } })} /></label><label className="field"><span>日志上限（字节）</span><EmptyableNumberInput min="1024" max="1073741824" value={draft.logging.max_bytes} onValueChange={(value) => setDraft({ ...draft, logging: { ...draft.logging, max_bytes: value } })} /></label></div><label className="toggle-row"><input type="checkbox" checked={draft.display.show_status_bar} onChange={(event) => setDraft({ ...draft, display: { ...draft.display, show_status_bar: event.target.checked } })} /><span><strong>显示侧栏运行状态</strong><small>显示本地服务连接状态和版本</small></span></label></section><section className="surface settings-section"><div className="surface-heading"><div><span className="section-kicker">PRINTING & TIME</span><h2>打印与时间</h2></div><Clock3 size={17} /></div><p className="settings-effect-note">纸张与预览选项作为“预览与打印”的默认值；时区应用于运行消息、审计和迁移时间。</p><div className="field-grid"><label className="field"><span>纸张</span><select value={draft.printing.paper} onChange={(event) => setDraft({ ...draft, printing: { ...draft.printing, paper: event.target.value as MethodPrintSettings['paper'] } })}><option>A4</option><option>A3</option><option>Letter</option></select></label><label className="field"><span>时区</span><select value={draft.time.timezone} onChange={(event) => setDraft({ ...draft, time: { ...draft.time, timezone: event.target.value } })}><option>Asia/Shanghai</option><option>UTC</option></select></label></div><label className="toggle-row"><input type="checkbox" checked={draft.printing.preview_before_print} onChange={(event) => setDraft({ ...draft, printing: { ...draft.printing, preview_before_print: event.target.checked } })} /><span><strong>打印前预览</strong><small>在方法的“预览与打印”页签生效</small></span></label></section></div></div>
}

function MigrationCheckList({ checks, status }: { checks: Record<string, boolean | null>; status?: string }) {
  return <div className="migration-check-list">{Object.entries(checks).map(([key, passed]) => {
    const pending = passed === null || (key === 'atomic_commit' && passed === false && status === 'staged')
    return <div key={key}><span className={pending ? 'pending' : passed ? 'pass' : 'fail'}>{pending ? <Clock3 size={13} /> : passed ? <Check size={13} /> : <X size={13} />}</span><code>{key}</code><strong>{pending ? '待提交' : passed ? '通过' : '失败'}</strong></div>
  })}</div>
}

function LegacyMigrationPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [diagnostic, setDiagnostic] = useState<LegacyMigrationDiagnostic | null>(null)
  const [runs, setRuns] = useState<LegacyMigrationRun[]>([])
  const [activeRun, setActiveRun] = useState<LegacyMigrationRun | null>(null)
  const [paths, setPaths] = useState({ mtd_path: '', cfg_path: '', opt_path: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canWrite = currentUser.permissions.includes('migration.write')

  const load = useCallback(async () => {
    try {
      const [nextDiagnostic, history] = await Promise.all([
        api.legacyMigrationDiagnostics(token),
        api.legacyMigrationRuns(token),
      ])
      setDiagnostic(nextDiagnostic)
      setRuns(history.runs)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取迁移状态')
    }
  }, [token])

  useEffect(() => { void load() }, [load])

  const stage = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const run = await api.stageLegacyMigration(token, paths)
      setActiveRun(run)
      await load()
      onToast(run.already_committed ? '相同源文件已经提交，没有创建重复数据' : '旧版文件已只读暂存并通过结构校验')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂存失败')
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    if (!activeRun || !window.confirm('确认把本次暂存的方法、谱线、色散和配置快照原子写入当前项目？')) return
    setBusy(true)
    setError(null)
    try {
      const run = await api.commitLegacyMigration(token, activeRun.id)
      setActiveRun(run)
      await load()
      onToast(run.already_committed ? '迁移已提交；本次未生成重复记录' : '旧版方法与配置已完成原子迁移')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提交失败，目标写入已回滚')
    } finally {
      setBusy(false)
    }
  }

  const openRun = async (run: LegacyMigrationRun) => {
    setBusy(true)
    try {
      setActiveRun(await api.legacyMigrationRun(token, run.id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取迁移报告')
    } finally {
      setBusy(false)
    }
  }

  const counts = activeRun?.report.counts
  const issues = activeRun?.report.issues ?? []
  const sourceEntries = Object.entries(activeRun?.source_files ?? {})
  return <div className="page-content migration-page" data-testid="legacy-migration-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S06 · LEGACY MIGRATION</span><h1>旧版方法迁移</h1><p>用 32 位 Jet 读取系统临时副本，校验后一次性提交方法、谱线、色散与配置快照。</p></div><div className="hero-actions"><span className={`migration-reader-pill ${diagnostic?.available ? 'ready' : 'unavailable'}`}><span className={`status-dot ${diagnostic?.available ? 'online' : 'offline'}`} />{diagnostic?.available ? 'Jet 读取器就绪' : '读取器不可用'}</span><button className="secondary-button" onClick={load} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />重新检测</button></div></section>
    {error && <div className="auth-error migration-error"><AlertTriangle size={15} />{error}</div>}
    <div className="migration-top-grid">
      <form className="surface migration-source-surface" onSubmit={stage}>
        <div className="surface-heading"><div><span className="section-kicker">SOURCE SET</span><h2>选择旧版源文件</h2></div><FolderOpen size={17} /></div>
        <p className="migration-note"><Info size={14} />源文件不会由 Jet 直接打开；服务先复制到操作系统临时目录，并在前后核对 SHA-256、大小和修改时间。</p>
        <div className="migration-paths">
          <label className="field"><span>方法库 · DIRECT.MTD</span><input value={paths.mtd_path} onChange={(event) => setPaths({ ...paths, mtd_path: event.target.value })} placeholder="C:\\...\\DIRECT.MTD" required disabled={!canWrite || busy} /></label>
          <label className="field"><span>设备配置 · DIRECT.CFG</span><input value={paths.cfg_path} onChange={(event) => setPaths({ ...paths, cfg_path: event.target.value })} placeholder="C:\\...\\DIRECT.CFG" required disabled={!canWrite || busy} /></label>
          <label className="field"><span>软件选项 · DIRECT.OPT</span><input value={paths.opt_path} onChange={(event) => setPaths({ ...paths, opt_path: event.target.value })} placeholder="C:\\...\\DIRECT.OPT" required disabled={!canWrite || busy} /></label>
        </div>
        <div className="migration-form-footer"><span>暂存阶段不会写入正式方法表。</span><button className="primary-button" type="submit" disabled={!canWrite || busy || !diagnostic?.available}><Database size={15} />{busy ? '正在校验…' : '只读暂存并校验'}</button></div>
      </form>
      <section className="surface migration-reader-surface">
        <div className="surface-heading"><div><span className="section-kicker">READER DIAGNOSTIC</span><h2>32 位读取通道</h2></div><SquareTerminal size={17} /></div>
        <div className={`reader-state ${diagnostic?.available ? 'ready' : 'unavailable'}`}>{diagnostic?.available ? <CheckCircle2 size={21} /> : <AlertTriangle size={21} />}<div><strong>{diagnostic?.message ?? '正在检测读取器…'}</strong><span>{diagnostic?.reader ?? '未选择读取后端'}</span></div></div>
        <dl className="reader-facts"><div><dt>Provider</dt><dd>{diagnostic?.provider ?? 'Microsoft.Jet.OLEDB.4.0'}</dd></div><div><dt>进程位数</dt><dd>{diagnostic?.process_bits ? `${diagnostic.process_bits}-bit` : '—'}</dd></div><div><dt>缺失时影响</dt><dd>仅禁用旧版迁移</dd></div><div><dt>读取模式</dt><dd>临时副本 · Read</dd></div></dl>
      </section>
    </div>

    {activeRun && <section className="surface migration-report-surface" data-testid="migration-report">
      <div className="surface-heading"><div><span className="section-kicker">MIGRATION REPORT</span><h2>迁移报告 <span className={`migration-status ${activeRun.status}`}>{activeRun.status === 'committed' ? '已提交' : activeRun.status === 'failed' ? '已回滚' : '待提交'}</span></h2></div><CopyableCode value={activeRun.fingerprint} visibleLength={16} /></div>
      <div className="migration-count-grid"><div><span>方法</span><strong>{counts?.methods ?? 0}</strong><small>已配对 MTD_PRIM / BURN / WSTC</small></div><div><span>旧谱线</span><strong>{counts?.spectral_lines ?? 0}</strong><small>不含每方法自动生成的参考基线</small></div><div><span>色散曲线</span><strong>{counts?.dispersion_curves ?? 0}</strong><small>系数与 CCD BLOB 已校验</small></div><div><span>配置文件</span><strong>2</strong><small>CFG / OPT 保存为非激活快照</small></div></div>
      <div className="migration-report-grid">
        <div><h3>一致性检查</h3><MigrationCheckList checks={activeRun.report.checks} status={activeRun.status} /></div>
        <div><h3>源文件指纹</h3><div className="migration-source-list">{sourceEntries.map(([kind, source]) => <div key={kind}><span>{kind.toUpperCase()}</span><div><strong title={source.path}>{source.name}</strong><code title={source.sha256}>{source.sha256.slice(0, 18)}…</code></div><small>{(source.size / 1024).toFixed(1)} KB</small></div>)}</div></div>
      </div>
      {issues.length > 0 && <div className="migration-issues"><h3>兼容性说明</h3>{issues.map((issue) => <div key={`${issue.code}-${issue.field ?? ''}`}><AlertTriangle size={14} /><span><strong>{issue.message}</strong><code>{issue.code}{issue.field ? ` · ${issue.field}` : ''}</code></span></div>)}</div>}
      {activeRun.error && <div className="migration-failure"><AlertTriangle size={15} /><span><strong>{activeRun.error.message}</strong><code>{activeRun.error.code}</code></span></div>}
      <div className="migration-commit-bar"><span>{activeRun.status === 'staged' ? '提交使用单个 SQLite 事务；任一目标记录失败都会完整回滚。' : activeRun.status === 'committed' ? `提交时间 ${activeRun.committed_at ? formatDateTime(activeRun.committed_at) : '—'}；相同源指纹再次导入不会创建重复数据。` : '上次提交已回滚，可重新暂存后再试。'}</span>{activeRun.status === 'staged' && <button className="primary-button" onClick={commit} disabled={!canWrite || busy}><CheckCircle2 size={15} />原子提交</button>}</div>
    </section>}

    <section className="surface migration-history-surface"><div className="surface-heading"><div><span className="section-kicker">HISTORY</span><h2>最近迁移</h2></div><Archive size={17} /></div>{runs.length === 0 ? <div className="method-empty compact"><Archive size={24} /><p>还没有旧版迁移记录。</p></div> : <div className="migration-history-list">{runs.map((run) => { const sourceName = run.source_files.mtd?.name ?? 'DIRECT.MTD'; return <button key={run.id} onClick={() => openRun(run)} className={activeRun?.id === run.id ? 'active' : ''}><span className={`migration-status ${run.status}`}>{run.status === 'committed' ? '已提交' : run.status === 'failed' ? '已回滚' : '待提交'}</span><div><strong title={sourceName}>{sourceName}</strong><small>{formatDateTime(run.created_at)} · {run.report.counts.methods} 方法 / {run.report.counts.spectral_lines} 谱线</small></div><code title={run.fingerprint}>{run.fingerprint.slice(0, 12)}</code><ChevronRight size={15} /></button> })}</div>}</section>
  </div>
}

function SpectrumMigrationPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [diagnostic, setDiagnostic] = useState<SpectrumMigrationDiagnostic | null>(null)
  const [runs, setRuns] = useState<SpectrumMigrationRun[]>([])
  const [activeRun, setActiveRun] = useState<SpectrumMigrationRun | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canWrite = currentUser.permissions.includes('spectrum-migration.write')

  const load = useCallback(async () => {
    try {
      const [nextDiagnostic, history] = await Promise.all([api.spectrumMigrationDiagnostics(token), api.spectrumMigrationRuns(token)])
      setDiagnostic(nextDiagnostic)
      setRuns(history.runs)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取旧谱迁移状态') }
  }, [token])

  useEffect(() => { void load() }, [load])

  const stage = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      const run = await api.stageSpectrumMigration(token, path)
      setActiveRun(run); await load(); onToast(run.already_committed ? '相同源文件已提交，未创建重复数据' : '旧谱文件已只读暂存并通过结构校验')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '暂存失败') }
    finally { setBusy(false) }
  }

  const commit = async () => {
    if (!activeRun || !window.confirm('确认把本次谱数据暂存原子提交到 SQLite？')) return
    setBusy(true); setError(null)
    try {
      const run = await api.commitSpectrumMigration(token, activeRun.id)
      setActiveRun(run); await load(); onToast(run.already_committed ? '迁移已提交，本次未生成重复记录' : '谱数据已完成原子提交')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '提交失败，目标数据已回滚') }
    finally { setBusy(false) }
  }

  const openRun = async (run: SpectrumMigrationRun) => {
    setBusy(true)
    try { setActiveRun(await api.spectrumMigrationRun(token, run.id)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取迁移报告') }
    finally { setBusy(false) }
  }

  const report = activeRun?.report
  const layout = activeRun?.staging?.layout
  const firstRecord = activeRun?.staging?.records[0]
  return <div className="page-content migration-page spectrum-migration-page" data-testid="spectrum-migration-page">
    <section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />S08 · SPECTRUM MIGRATION</span><h1>旧谱数据迁移</h1><p>只读解析 .cdt、.cmt、.edt、.wdt，校验布局、数组维度、端序和源文件指纹。</p></div><div className="hero-actions"><span className={`migration-reader-pill ${diagnostic?.available ? 'ready' : 'unavailable'}`}><span className={`status-dot ${diagnostic?.available ? 'online' : 'offline'}`} />{diagnostic?.available ? 'Jet 读取器就绪' : '读取器不可用'}</span><button className="secondary-button" onClick={load} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />重新检测</button></div></section>
    {error && <div className="auth-error migration-error"><AlertTriangle size={15} />{error}</div>}
    <div className="migration-top-grid">
      <form className="surface migration-source-surface" onSubmit={stage}>
        <div className="surface-heading"><div><span className="section-kicker">SOURCE FILE</span><h2>选择旧谱文件</h2></div><FolderOpen size={17} /></div>
        <p className="migration-note"><Info size={14} />服务会先复制到临时目录读取，并前后核对大小、修改时间和 SHA-256；原文件不会写入或修复。</p>
        <label className="field"><span>谱文件路径</span><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\\...\\sample.cmt" required disabled={!canWrite || busy} /></label>
        <div className="migration-form-footer"><span>支持 {diagnostic?.formats?.join(' / ').toUpperCase() ?? 'CDT / CMT / EDT / WDT'}</span><button className="primary-button" type="submit" disabled={!canWrite || busy || !diagnostic?.available}><Database size={15} />{busy ? '正在校验…' : '只读暂存并校验'}</button></div>
      </form>
      <section className="surface migration-reader-surface"><div className="surface-heading"><div><span className="section-kicker">READER DIAGNOSTIC</span><h2>旧版 Access 读取通道</h2></div><SquareTerminal size={17} /></div><div className={`reader-state ${diagnostic?.available ? 'ready' : 'unavailable'}`}>{diagnostic?.available ? <CheckCircle2 size={21} /> : <AlertTriangle size={21} />}<div><strong>{diagnostic?.message ?? '正在检测读取器…'}</strong><span>{diagnostic?.reader ?? '未选择读取后端'}</span></div></div><dl className="reader-facts"><div><dt>Provider</dt><dd>{diagnostic?.provider ?? 'Microsoft.Jet.OLEDB.4.0'}</dd></div><div><dt>解析器版本</dt><dd>{diagnostic?.parser_version ?? 's08-spectrum-1'}</dd></div><div><dt>模式</dt><dd>只读 / 临时副本</dd></div></dl></section>
    </div>
    {activeRun && <section className="surface migration-report-surface" data-testid="spectrum-migration-report"><div className="surface-heading"><div><span className="section-kicker">SPECTRUM REPORT</span><h2>迁移报告 <span className={`migration-status ${activeRun.status}`}>{activeRun.status === 'committed' ? '已提交' : activeRun.status === 'failed' ? '已回滚' : '待提交'}</span></h2></div><CopyableCode value={activeRun.fingerprint} visibleLength={16} /></div><div className="migration-count-grid spectrum-count-grid"><div><span>格式</span><strong>{activeRun.format.toUpperCase()}</strong><small>旧版 Access 数据文件</small></div><div><span>谱带记录</span><strong>{report?.record_count ?? 0}</strong><small>CCD_BAND 行数</small></div><div><span>帧布局</span><strong>{layout ? `${layout.frame_count} × ${layout.ccds_per_frame}` : '—'}</strong><small>帧数 × 每帧 CCD</small></div><div><span>CCD 点数</span><strong>{layout ? `${layout.ccd_count} × ${layout.points_per_ccd}` : '—'}</strong><small>有效 CCD × 每 CCD 点数</small></div></div><div className="migration-report-grid"><div><h3>一致性检查</h3><MigrationCheckList checks={report?.checks ?? {}} status={activeRun.status} /></div><div><h3>源文件指纹</h3><div className="spectrum-fingerprint"><strong title={activeRun.source_file.name}>{activeRun.source_file.name}</strong><code>{activeRun.source_file.sha256}</code><small>{(activeRun.source_file.size / 1024 / 1024).toFixed(2)} MB · {formatDateTime(activeRun.source_file.mtime_ns / 1e6)}</small></div>{layout && <div className="spectrum-layout-facts"><span>CCD 映射</span><code>{layout.ccd_indices.join(', ')}</code><span>端序</span><code>{layout.endianness}</code></div>}</div></div>{firstRecord && <div className="spectrum-record-summary"><h3>首条记录摘要</h3><div><span>谱带</span><strong>{String(firstRecord.band_name || firstRecord.long_name || '未命名')}</strong><span>样品</span><strong>{String(firstRecord.sample_name || '—')}</strong><span>坏帧</span><strong>{firstRecord.bad_frame_indices.length ? firstRecord.bad_frame_indices.map((item) => `${String(item.phase)}:${String(item.index)}`).join(', ') : '无'}</strong></div></div>}{(report?.issues.length ?? 0) > 0 && <div className="migration-issues"><h3>兼容性提示</h3>{report?.issues.map((issue) => <div key={issue.code}><AlertTriangle size={14} /><span><strong>{issue.message}</strong><code>{issue.code}</code></span></div>)}</div>}<div className="migration-commit-bar"><span>{activeRun.status === 'staged' ? '提交使用单个 SQLite 事务；任一记录失败都会完整回滚。' : activeRun.status === 'committed' ? '同一源文件 SHA-256 再次导入不会创建重复数据。' : '本次提交已回滚，可重新暂存后再试。'}</span>{activeRun.status === 'staged' && <button className="primary-button" onClick={commit} disabled={!canWrite || busy}><CheckCircle2 size={15} />原子提交</button>}</div></section>}
    <section className="surface migration-history-surface"><div className="surface-heading"><div><span className="section-kicker">HISTORY</span><h2>最近迁移</h2></div><Archive size={17} /></div>{runs.length === 0 ? <div className="method-empty compact"><Archive size={24} /><p>还没有旧谱迁移记录。</p></div> : <div className="migration-history-list">{runs.map((run) => <button key={run.id} onClick={() => openRun(run)} className={activeRun?.id === run.id ? 'active' : ''}><span className={`migration-status ${run.status}`}>{run.status === 'committed' ? '已提交' : run.status === 'failed' ? '已回滚' : '待提交'}</span><div><strong title={run.source_file.name}>{run.source_file.name}</strong><small>{formatDateTime(run.created_at)} · {run.report.record_count} 条谱带</small></div><code title={run.fingerprint}>{run.fingerprint.slice(0, 12)}</code><ChevronRight size={15} /></button>)}</div>}</section>
  </div>
}

function ResultMigrationPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [diagnostic, setDiagnostic] = useState<ResultMigrationDiagnostic | null>(null)
  const [runs, setRuns] = useState<ResultMigrationRun[]>([])
  const [activeRun, setActiveRun] = useState<ResultMigrationRun | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const canWrite = currentUser.permissions.includes('result-migration.write')

  const load = useCallback(async () => {
    try {
      const [nextDiagnostic, nextRuns] = await Promise.all([api.resultMigrationDiagnostics(token), api.resultMigrationRuns(token)])
      setDiagnostic(nextDiagnostic); setRuns(nextRuns.runs)
      setActiveRun((current) => current ? nextRuns.runs.find((item) => item.id === current.id) ?? current : nextRuns.runs[0] ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取结果迁移状态') }
  }, [token, onToast])
  useEffect(() => { void load() }, [load])

  const stage = async () => {
    if (!path.trim() || !canWrite) return
    setBusy(true)
    try { const next = await api.stageResultMigration(token, path.trim()); setActiveRun(next); setRuns((current) => [next, ...current.filter((item) => item.id !== next.id)]); onToast('结果文件已暂存') }
    catch (error) { onToast(error instanceof Error ? error.message : '结果文件暂存失败') }
    finally { setBusy(false) }
  }
  const commit = async () => {
    if (!activeRun || activeRun.status !== 'staged' || !canWrite) return
    setBusy(true)
    try { const next = await api.commitResultMigration(token, activeRun.id); setActiveRun(next); setRuns((current) => current.map((item) => item.id === next.id ? next : item)); onToast('结果矩阵已原子提交') }
    catch (error) { onToast(error instanceof Error ? error.message : '结果矩阵提交失败') }
    finally { setBusy(false) }
  }
  const record = activeRun?.staging?.records[0]
  return <div className="page-content migration-page result-migration-page" data-testid="result-migration-page">
    <div className="page-intro"><div><span className="section-kicker">S09 / RESULT MIGRATION</span><h1>谱图结果迁移</h1><p>读取旧版 .pdt/.dat 矩阵，保留方法引用、重复计数、谱线元数据、曝光段和原始矩阵。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} />刷新</button></div></div>
    <section className="surface migration-source-surface"><div className="surface-heading"><div><span className="section-kicker">READ-ONLY SOURCE</span><h2>选择结果文件</h2></div><Database size={17} /></div><div className="migration-path-form"><label className="field"><span>文件路径</span><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\\SpecDirect\\DATA\\result.pdt" /></label><button className="primary-button" onClick={() => void stage()} disabled={!canWrite || busy || !path.trim()}><Upload size={15} />暂存解析</button></div><div className="reader-status"><span className="status-dot online" /><div><strong>{diagnostic?.message ?? '正在检查解析器'}</strong><span>{diagnostic?.parser_version ?? 's09-result-1'} · {diagnostic?.formats?.join(' / ').toUpperCase() ?? 'DAT / PDT'} · 小端序</span></div></div></section>
    {activeRun && <section className="surface migration-report-surface" data-testid="result-migration-report"><div className="surface-heading"><div><span className="section-kicker">RESULT REPORT</span><h2>迁移报告 <span className={`migration-status ${activeRun.status}`}>{activeRun.status === 'committed' ? '已提交' : activeRun.status === 'failed' ? '已回滚' : '待提交'}</span></h2></div><CopyableCode value={activeRun.fingerprint} visibleLength={16} /></div><div className="migration-count-grid spectrum-count-grid"><div><span>格式</span><strong>{activeRun.format.toUpperCase()}</strong><small>严格旧版二进制布局</small></div><div><span>样品 / 谱线</span><strong>{activeRun.report.counts.samples} / {activeRun.report.counts.lines}</strong><small>原始行列维度</small></div><div><span>展开波段</span><strong>{activeRun.report.counts.bands}</strong><small>重复计数展开</small></div><div><span>矩阵值</span><strong>{activeRun.report.counts.matrix_values}</strong><small>原始值未重算</small></div></div><div className="migration-report-grid"><div><h3>一致性检查</h3><MigrationCheckList checks={activeRun.report.checks} status={activeRun.status} /></div><div><h3>源文件与方法</h3><div className="spectrum-fingerprint"><strong title={activeRun.source_file.name}>{activeRun.source_file.name}</strong><code>{activeRun.source_file.sha256}</code><small>{(activeRun.source_file.size / 1024).toFixed(1)} KB · {activeRun.parser.encoding} · {activeRun.parser.endianness}</small></div>{record && <div className="spectrum-layout-facts"><span>测量时间</span><code>{record.measure_time}</code><span>方法引用</span><code>{record.method_match_status}{record.method_legacy_id === null ? '' : ` · legacy ${record.method_legacy_id}`}</code></div>}</div></div>{record && <div className="spectrum-record-summary"><h3>矩阵摘要</h3><div><span>样品首项</span><strong>{record.sample_names[0] ?? '—'}</strong><span>样品末项</span><strong>{record.sample_names[record.sample_names.length - 1] ?? '—'}</strong><span>首个值</span><strong>{String(record.matrix_samples[0]?.value ?? record.matrix_samples[0]?.peak ?? '—')}</strong><span>末个值</span><strong>{String(record.matrix_samples[record.matrix_samples.length - 1]?.value ?? record.matrix_samples[record.matrix_samples.length - 1]?.peak ?? '—')}</strong></div></div>}{activeRun.report.issues.length > 0 && <div className="migration-issues">{activeRun.report.issues.map((issue) => <div key={issue.code}><AlertTriangle size={14} /><span><strong>{issue.message}</strong><code>{issue.code}</code></span></div>)}</div>}<div className="migration-commit-bar"><span>{activeRun.status === 'staged' ? '提交将把整份矩阵写入 SQLite 单事务。' : activeRun.status === 'committed' ? '相同源 SHA-256 再次导入不会产生重复矩阵。' : '提交已回滚，可重新暂存。'}</span>{activeRun.status === 'staged' && <button className="primary-button" onClick={() => void commit()} disabled={!canWrite || busy}><CheckCircle2 size={15} />原子提交</button>}</div></section>}
    <section className="surface migration-history-surface"><div className="surface-heading"><div><span className="section-kicker">HISTORY</span><h2>最近结果导入</h2></div><Archive size={17} /></div>{runs.length === 0 ? <div className="method-empty compact"><Archive size={24} /><p>还没有结果迁移记录。</p></div> : <div className="migration-history-list">{runs.map((run) => <button key={run.id} onClick={() => void api.resultMigrationRun(token, run.id).then(setActiveRun)} className={activeRun?.id === run.id ? 'active' : ''}><span className={`migration-status ${run.status}`}>{run.status === 'committed' ? '已提交' : run.status === 'failed' ? '已回滚' : '待提交'}</span><div><strong title={run.source_file.name}>{run.source_file.name}</strong><small>{formatDateTime(run.created_at)} · {run.format.toUpperCase()} · {run.report.counts.bands} 波段</small></div><code title={run.fingerprint}>{run.fingerprint.slice(0, 12)}</code></button>)}</div>}</section>
  </div>
}

function LegacySpectrumViewerPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [records, setRecords] = useState<SpectrumRecordSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SpectrumRecord | null>(null)
  const [ccd, setCcd] = useState(0)
  const [line, setLine] = useState(0)
  const [mode, setMode] = useState<'mean' | 'peak' | 'back' | 'value'>('mean')
  const [referenceShift, setReferenceShift] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState(0)
  const [crosshair, setCrosshair] = useState(true)
  const [locked, setLocked] = useState(false)
  const [cursor, setCursor] = useState<{ x: number; y: number; point: SpectrumPoint } | null>(null)
  const [framePhase, setFramePhase] = useState<'burn' | 'dark'>('burn')
  const [frameIndex, setFrameIndex] = useState(0)
  const [frameVisible, setFrameVisible] = useState(false)
  const [busy, setBusy] = useState(false)

  const loadRecords = useCallback(async () => {
    try {
      const next = await api.spectrumRecords(token)
      setRecords(next)
      setSelectedId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取谱图记录') }
  }, [token, onToast])

  const loadDetail = useCallback(async (id: string, nextCcd = ccd, nextLine = line) => {
    setBusy(true)
    try { setDetail(await api.spectrum(token, id, { ccd: nextCcd, line: nextLine, detail: 'summary' })); setFrameVisible(false); setCursor(null) }
    catch (error) { onToast(error instanceof Error ? error.message : '无法读取谱图数据') }
    finally { setBusy(false) }
  }, [token, onToast, ccd, line])

  useEffect(() => { void loadRecords() }, [loadRecords])
  useEffect(() => { if (selectedId) void loadDetail(selectedId) }, [selectedId])
  useEffect(() => { setZoom(1); setPan(0) }, [detail?.id, ccd, line, mode])

  const raw = detail?.kind === 'raw'
  const points = useMemo<SpectrumPoint[]>(() => raw ? (frameVisible ? detail?.frame_detail?.ccd.points ?? detail?.ccd?.points ?? [] : detail?.ccd?.points ?? []) : detail?.line?.points ?? [], [detail, raw, frameVisible])
  const plotted = useMemo(() => points.map((point, index) => {
    const rawX = point.wavelength_nm ?? point.step ?? point.x ?? index
    const y = mode === 'peak' ? point.peak : mode === 'back' ? point.back : point.value ?? point.peak ?? point.adc ?? 0
    return { point, x: rawX + (raw ? referenceShift : 0), y: Number(y ?? 0) }
  }).filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y)), [points, mode, referenceShift])
  const fullRange = useMemo(() => {
    if (!plotted.length) return { start: 0, end: 1, min: 0, max: 1 }
    const xs = plotted.map((item) => item.x); const ys = plotted.map((item) => item.y)
    return { start: Math.min(...xs), end: Math.max(...xs) || 1, min: Math.min(...ys), max: Math.max(...ys) }
  }, [plotted])
  const xSpan = Math.max((fullRange.end - fullRange.start) / zoom, 1e-9)
  const xStart = Math.max(fullRange.start, Math.min(fullRange.end - xSpan, fullRange.start + pan * xSpan * 0.45))
  const xEnd = xStart + xSpan
  const yPad = Math.max((fullRange.max - fullRange.min) * 0.08, 1)
  const yStart = fullRange.min - yPad
  const yEnd = fullRange.max + yPad
  const plotX = (x: number) => 54 + ((x - xStart) / (xEnd - xStart || 1)) * 872
  const plotY = (y: number) => 330 - ((y - yStart) / (yEnd - yStart || 1)) * 278
  const path = plotted.map((item, index) => `${index ? 'L' : 'M'} ${plotX(item.x).toFixed(2)} ${plotY(item.y).toFixed(2)}`).join(' ')
  const selected = records.find((item) => item.id === selectedId) ?? null

  const selectRecord = (record: SpectrumRecordSummary) => {
    setSelectedId(record.id); setCcd(0); setLine(0); setMode(record.kind === 'raw' ? 'mean' : record.matrix_kind === 'peak_back' ? 'peak' : 'value')
  }
  const move = (delta: number) => {
    if (!detail) return
    if (raw) { const count = Number(detail.layout?.ccd_count ?? 1); const next = Math.max(0, Math.min(count - 1, ccd + delta)); if (next !== ccd) { setCcd(next); void loadDetail(detail.id, next, line) } }
    else { const count = detail.line_count ?? 1; const next = Math.max(0, Math.min(count - 1, line + delta)); if (next !== line) { setLine(next); void loadDetail(detail.id, ccd, next) } }
  }
  const loadFrame = async () => {
    if (!detail || !raw) return
    setBusy(true)
    try { setDetail(await api.spectrum(token, detail.id, { ccd, line, detail: 'frame', phase: framePhase, frame: frameIndex })); setFrameVisible(true) }
    catch (error) { onToast(error instanceof Error ? error.message : '原始帧不可用') }
    finally { setBusy(false) }
  }
  const handlePlotMove = (event: MouseEvent<SVGSVGElement>) => {
    if (!crosshair || locked || !plotted.length) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = xStart + ((event.clientX - rect.left) / rect.width) * (xEnd - xStart)
    const nearest = plotted.reduce((best, current) => Math.abs(current.x - x) < Math.abs(best.x - x) ? current : best, plotted[0])
    setCursor({ x: plotX(nearest.x), y: plotY(nearest.y), point: nearest.point })
  }

  return <div className="page-content spectrum-viewer-page" data-testid="spectrum-viewer-page">
    <div className="page-intro"><div><span className="section-kicker">S10 / SPECTRUM VIEWER</span><h1>谱图查看</h1><p>对已发布的旧谱带和结果矩阵进行完整点位查看；原始帧按需读取。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => void loadRecords()} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />刷新</button><button className="secondary-button" onClick={() => window.print()} disabled={!detail} title="打印当前可见范围"><Printer size={15} />打印</button></div></div>
    <div className="spectrum-viewer-layout">
      <aside className="surface spectrum-records"><div className="surface-heading"><div><span className="section-kicker">PUBLISHED DATA</span><h2>谱图记录</h2></div><Database size={17} /></div>{records.length === 0 ? <div className="method-empty compact"><Database size={25} /><p>暂无已提交谱图</p></div> : <div className="spectrum-record-list">{records.map((record) => { const name = record.sample_name || record.band_name || record.id; const metadata = record.kind === 'raw' ? `${record.ccd_count} CCD · ${record.points_per_ccd} 点` : `${record.sample_count} 样品 · ${record.line_count} 谱线`; return <button key={record.id} className={record.id === selectedId ? 'active' : ''} onClick={() => selectRecord(record)}><span className={`spectrum-kind ${record.kind}`}>{record.kind === 'raw' ? 'RAW' : record.format.toUpperCase()}</span><div><strong title={name}>{name}</strong><small title={metadata}>{metadata}</small></div><ChevronRight size={14} /></button> })}</div>}</aside>
      <section className="surface spectrum-workbench">
        {!detail ? <div className="method-empty"><Activity size={30} /><h2>选择一条谱图记录</h2><p>左侧记录会显示 S08/S09 已提交的数据。</p></div> : <>
          <div className="spectrum-toolbar"><div className="spectrum-toolbar-group"><button className="icon-button" onClick={() => move(-1)} title={raw ? '上一个 CCD' : '上一条谱线'}><ChevronLeft size={16} /></button><span className="spectrum-position">{raw ? `CCD ${ccd + 1} / ${detail.layout?.ccd_count ?? 0}` : `谱线 ${line + 1} / ${detail.line_count ?? 0}`}</span><button className="icon-button" onClick={() => move(1)} title={raw ? '下一个 CCD' : '下一条谱线'}><ChevronRight size={16} /></button></div><div className="spectrum-toolbar-group"><button className="tool-button" onClick={() => { setZoom(1); setPan(0) }} title="适配全部数据"><Maximize2 size={14} />适配</button><button className={`tool-button ${zoom === 1 ? 'active' : ''}`} onClick={() => { setZoom(1); setPan(0) }}>100%</button><button className={`tool-button ${zoom === 4 ? 'active' : ''}`} onClick={() => setZoom(4)}>400%</button><button className="icon-button" onClick={() => { setZoom(1); setPan(0); setReferenceShift(0) }} title="还原视图"><RotateCcw size={15} /></button><button className="icon-button" onClick={() => setZoom((current) => Math.min(16, current * 2))} title="放大"><ZoomIn size={16} /></button><button className="icon-button" onClick={() => setZoom((current) => Math.max(1, current / 2))} title="缩小"><ZoomOut size={16} /></button></div><div className="spectrum-toolbar-group"><button className={`tool-button ${crosshair ? 'active' : ''}`} onClick={() => setCrosshair((value) => !value)} title="十字线"><Crosshair size={14} />十字线</button><button className={`tool-button ${locked ? 'active' : ''}`} onClick={() => setLocked((value) => !value)} title="锁定谱线">{locked ? <LockKeyhole size={14} /> : <UnlockKeyhole size={14} />}锁定</button></div></div>
          <div className="spectrum-controls"><div className="segmented-control">{(raw ? [['mean', '均值']] : detail.matrix_kind === 'peak_back' ? [['peak', '峰值'], ['back', '背景']] : [['value', '结果']]).map(([key, label]) => <button key={key} className={mode === key ? 'active' : ''} onClick={() => setMode(key as typeof mode)}>{label}</button>)}</div><label className="spectrum-reference"><span>参考线偏移</span><EmptyableNumberInput step="0.001" value={referenceShift} onValueChange={setReferenceShift} /><span>nm</span></label>{raw && <div className="spectrum-frame-actions"><select value={framePhase} onChange={(event) => setFramePhase(event.target.value as 'burn' | 'dark')}><option value="burn">burn</option><option value="dark">dark</option></select><EmptyableNumberInput min={0} value={frameIndex} onValueChange={(value) => setFrameIndex(Math.max(0, value))} /><button className="tool-button" onClick={() => void loadFrame()} disabled={busy}>原始帧</button></div>}</div>
          <div className="spectrum-plot-wrap"><svg className="spectrum-plot" viewBox="0 0 960 380" role="img" aria-label="谱图曲线" onMouseMove={handlePlotMove} onMouseLeave={() => !locked && setCursor(null)} onClick={() => cursor && setLocked(true)}><rect x="54" y="42" width="872" height="288" className="plot-background" /><line x1="54" y1="330" x2="926" y2="330" className="plot-axis" /><line x1="54" y1="42" x2="54" y2="330" className="plot-axis" />{[0, .25, .5, .75, 1].map((ratio) => <line key={ratio} x1="54" y1={42 + 288 * ratio} x2="926" y2={42 + 288 * ratio} className="plot-grid" />)}{path && <path d={path} className="spectrum-line" />}{cursor && crosshair && <><line x1={cursor.x} y1="42" x2={cursor.x} y2="330" className="plot-crosshair" /><line x1="54" y1={cursor.y} x2="926" y2={cursor.y} className="plot-crosshair" /><circle cx={cursor.x} cy={cursor.y} r="4" className="plot-cursor" /></>}<text x="58" y="24" className="plot-label">{detail.kind === 'raw' ? `${detail.sample_name || '谱带'} · ${detail.ccd?.index ?? 0}` : `${detail.line?.element || '谱线'} · ${detail.line?.wavelength_nm ?? ''}`}</text><text x="820" y="365" className="plot-label">{fullRange.end.toFixed(3)}</text><text x="55" y="365" className="plot-label">{fullRange.start.toFixed(3)}</text></svg>{cursor && <div className="spectrum-cursor-readout"><span>点 {cursor.point.point_index}</span><strong>{(cursor.point.wavelength_nm ?? cursor.point.x ?? cursor.point.step ?? cursor.point.point_index).toFixed?.(3) ?? cursor.point.point_index}</strong><span>{mode} {Number(cursor.point[mode === 'peak' ? 'peak' : mode === 'back' ? 'back' : mode === 'value' ? 'value' : 'value'] ?? cursor.point.adc ?? 0).toFixed(3)}</span></div>}</div>
          <div className="spectrum-pan"><button className="icon-button" onClick={() => setPan((value) => Math.max(-1, value - .25))} title="向左滚动"><ChevronLeft size={15} /></button><span>可见范围 {xStart.toFixed(3)} - {xEnd.toFixed(3)}</span><button className="icon-button" onClick={() => setPan((value) => Math.min(1, value + .25))} title="向右滚动"><ChevronRight size={15} /></button></div>
          <div className="spectrum-facts"><div><span>来源 SHA-256</span><CopyableCode value={detail.source_sha256} visibleLength={18} /></div><div><span>样品</span><ExpandableValue value={detail.sample_name || detail.sample_names?.join(' / ') || '—'} /></div><div><span>测量时间</span><strong>{detail.measure_time || '—'}</strong></div><div><span>点数</span><strong>{points.length}</strong></div>{raw && <div><span>当前帧</span><strong>{frameVisible && detail.frame_detail ? `${detail.frame_detail.phase} #${detail.frame_detail.index + 1}` : '均值'}</strong></div>}</div>
        </>}
      </section>
    </div>
  </div>
}

function SpectrumViewerPage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [records, setRecords] = useState<SpectrumRecordSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [overlayIds, setOverlayIds] = useState<string[]>([])
  const [details, setDetails] = useState<Record<string, SpectrumRecord>>({})
  const [priorityId, setPriorityId] = useState<string | null>(null)
  const [ccd, setCcd] = useState(0)
  const [line, setLine] = useState(0)
  const [mode, setMode] = useState<'mean' | 'peak' | 'back' | 'value'>('mean')
  const [angleFilter, setAngleFilter] = useState<string>('all')
  const [exposureEnabled, setExposureEnabled] = useState(false)
  const [exposureStart, setExposureStart] = useState(1)
  const [exposureEnd, setExposureEnd] = useState(1)
  const [referenceShift, setReferenceShift] = useState(0)
  const [zoomX, setZoomX] = useState(1)
  const [zoomY, setZoomY] = useState(1)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const [tool, setTool] = useState<'crosshair' | 'pan' | 'box'>('crosshair')
  const [cursor, setCursor] = useState<SpectrumPlotCursor | null>(null)
  const [locked, setLocked] = useState(false)
  const [locateValue, setLocateValue] = useState('')
  const [framePhase, setFramePhase] = useState<'burn' | 'dark'>('burn')
  const [frameIndex, setFrameIndex] = useState(0)
  const [frameVisible, setFrameVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const detailRequest = useRef(0)
  const palette = ['#1c68b2', '#c75b39', '#27805d', '#8b5bb5', '#d18b22', '#247c8b', '#b54769', '#58677a']

  const loadRecords = useCallback(async () => {
    setBusy(true)
    try {
      const next = await api.spectrumRecords(token)
      setRecords(next)
      setSelectedId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null)
      setPriorityId((current) => current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取谱图记录') }
    finally { setBusy(false) }
  }, [token, onToast])

  useEffect(() => { void loadRecords() }, [loadRecords])
  const selected = records.find((item) => item.id === selectedId) ?? null
  const raw = selected?.kind === 'raw'
  const displayIds = useMemo(() => {
    if (!selectedId) return []
    if (!raw) return [selectedId]
    return Array.from(new Set([selectedId, ...overlayIds])).slice(0, 8)
  }, [selectedId, overlayIds, raw])

  const loadDetails = useCallback(async () => {
    if (!displayIds.length) return
    const requestId = ++detailRequest.current
    setBusy(true)
    try {
      const loaded = await Promise.all(displayIds.map(async (id) => {
        const summary = records.find((item) => item.id === id)
        const nextCcd = Math.max(0, Math.min((summary?.ccd_count ?? 1) - 1, ccd))
        const params = {
          ccd: nextCcd,
          line,
          detail: 'summary' as const,
          exposureStart: raw && exposureEnabled ? exposureStart : undefined,
          exposureEnd: raw && exposureEnabled ? exposureEnd : undefined,
        }
        return [id, await api.spectrum(token, id, params)] as const
      }))
      if (requestId !== detailRequest.current) return
      setDetails(Object.fromEntries(loaded))
      setFrameVisible(false)
      setCursor(null)
      setLocked(false)
    } catch (error) { if (requestId === detailRequest.current) onToast(error instanceof Error ? error.message : '无法读取谱图数据') }
    finally { if (requestId === detailRequest.current) setBusy(false) }
  }, [token, onToast, displayIds, records, ccd, line, raw, exposureEnabled, exposureStart, exposureEnd])
  useEffect(() => { void loadDetails() }, [loadDetails])

  const active = selectedId ? details[selectedId] ?? null : null
  const visibleRecords = useMemo(() => angleFilter === 'all' ? records : records.filter((item) => item.angle_deg != null && String(item.angle_deg) === angleFilter), [records, angleFilter])
  const angles = useMemo(() => Array.from(new Set(records.flatMap((item) => item.angle_deg == null ? [] : [item.angle_deg]))).sort((a, b) => a - b), [records])
  useEffect(() => {
    if (!visibleRecords.length || (selectedId && visibleRecords.some((item) => item.id === selectedId))) return
    const first = visibleRecords[0]
    setSelectedId(first.id); setPriorityId(first.id); setOverlayIds(first.kind === 'raw' ? [first.id] : []); setCcd(0); setLine(0)
  }, [visibleRecords, selectedId])
  const maxExposure = Math.max(1, Number(active?.ignition?.burn_count ?? 1))

  const curves = useMemo<SpectrumPlotCurve[]>(() => displayIds.flatMap((id, index) => {
    const record = details[id]
    if (!record) return []
    const points = id === selectedId && frameVisible ? record.frame_detail?.ccd.points ?? record.ccd?.points ?? [] : record.kind === 'raw' ? record.ccd?.points ?? [] : record.line?.points ?? []
    const data = points.map((point, pointIndex) => {
      const x = Number(point.wavelength_nm ?? point.step ?? point.x ?? pointIndex) + (record.kind === 'raw' ? referenceShift : 0)
      const y = Number(mode === 'peak' ? point.peak : mode === 'back' ? point.back : point.value ?? point.peak ?? point.adc ?? 0)
      return { point, x, y }
    }).filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y))
    const summary = records.find((item) => item.id === id)
    return [{ id, label: summary?.sample_name || summary?.band_name || id, color: palette[index % palette.length], priority: (priorityId ?? selectedId) === id, data }]
  }), [displayIds, details, selectedId, frameVisible, referenceShift, mode, records, priorityId])

  const fullRange = useMemo(() => {
    const all = curves.flatMap((curve) => curve.data)
    if (!all.length) return { xMin: 0, xMax: 1, yMin: 0, yMax: 1 }
    const xs = all.map((item) => item.x); const ys = all.map((item) => item.y)
    const xMin = Math.min(...xs); const xMax = Math.max(...xs)
    const rawYMin = Math.min(...ys); const rawYMax = Math.max(...ys); const yPad = Math.max((rawYMax - rawYMin) * .08, 1)
    return { xMin, xMax: xMax === xMin ? xMin + 1 : xMax, yMin: rawYMin - yPad, yMax: rawYMax + yPad }
  }, [curves])
  const fullXSpan = fullRange.xMax - fullRange.xMin
  const fullYSpan = fullRange.yMax - fullRange.yMin
  const xSpan = fullXSpan / zoomX
  const ySpan = fullYSpan / zoomY
  const xStart = fullRange.xMin + ((panX + 1) / 2) * Math.max(0, fullXSpan - xSpan)
  const xEnd = xStart + xSpan
  const yStart = fullRange.yMin + ((panY + 1) / 2) * Math.max(0, fullYSpan - ySpan)
  const yEnd = yStart + ySpan

  const resetView = (resetCorrection = false) => {
    setZoomX(1); setZoomY(1); setPanX(0); setPanY(0); setCursor(null); setLocked(false)
    if (resetCorrection) setReferenceShift(0)
  }
  useEffect(() => { resetView() }, [selectedId, ccd, line, mode])

  const selectRecord = (record: SpectrumRecordSummary) => {
    setSelectedId(record.id); setPriorityId(record.id); setCcd(0); setLine(0); setFrameVisible(false)
    setMode(record.kind === 'raw' ? 'mean' : record.matrix_kind === 'peak_back' ? 'peak' : 'value')
    if (record.kind === 'raw') setOverlayIds((current) => Array.from(new Set([record.id, ...current])).slice(0, 8)); else setOverlayIds([])
  }
  const moveRecord = (delta: number) => {
    if (!selectedId || !visibleRecords.length) return
    const index = visibleRecords.findIndex((item) => item.id === selectedId)
    selectRecord(visibleRecords[Math.max(0, Math.min(visibleRecords.length - 1, index + delta))])
  }
  const moveBand = (delta: number) => {
    if (!active) return
    if (raw) setCcd((current) => Math.max(0, Math.min(Number(active.layout?.ccd_count ?? 1) - 1, current + delta)))
    else setLine((current) => Math.max(0, Math.min((active.line_count ?? 1) - 1, current + delta)))
  }
  const toggleOverlay = (id: string) => {
    setOverlayIds((current) => current.includes(id) ? (id === selectedId ? current : current.filter((item) => item !== id)) : current.length < 8 ? [...current, id] : current)
  }
  const loadFrame = async () => {
    if (!active || !raw || !selectedId) return
    setBusy(true)
    try {
      const next = await api.spectrum(token, active.id, { ccd, line, detail: 'frame', phase: framePhase, frame: frameIndex })
      setDetails((current) => ({ ...current, [selectedId]: next })); setFrameVisible(true); setMode('mean')
    } catch (error) { onToast(error instanceof Error ? error.message : '原始帧不可用') }
    finally { setBusy(false) }
  }
  const boxSelect = (range: { xMin: number; xMax: number; yMin: number; yMax: number }) => {
    const nextZoomX = Math.max(1, Math.min(32, fullXSpan / Math.max(range.xMax - range.xMin, 1e-9)))
    const nextZoomY = Math.max(1, Math.min(32, fullYSpan / Math.max(range.yMax - range.yMin, 1e-9)))
    const nextXSpan = fullXSpan / nextZoomX; const nextYSpan = fullYSpan / nextZoomY
    setZoomX(nextZoomX); setZoomY(nextZoomY)
    setPanX(fullXSpan === nextXSpan ? 0 : Math.max(-1, Math.min(1, 2 * ((range.xMin - fullRange.xMin) / (fullXSpan - nextXSpan)) - 1)))
    setPanY(fullYSpan === nextYSpan ? 0 : Math.max(-1, Math.min(1, 2 * ((range.yMin - fullRange.yMin) / (fullYSpan - nextYSpan)) - 1)))
    setTool('crosshair')
  }
  const locate = () => {
    const target = Number(locateValue)
    const curve = curves.find((item) => item.priority) ?? curves[0]
    if (!curve?.data.length || !Number.isFinite(target)) return
    const datum = curve.data.reduce((best, item) => Math.abs(item.x - target) < Math.abs(best.x - target) ? item : best)
    setCursor({ curveId: curve.id, curveLabel: curve.label, x: 54 + ((datum.x - xStart) / (xEnd - xStart || 1)) * 872, y: 330 - ((datum.y - yStart) / (yEnd - yStart || 1)) * 288, datum })
    setLocked(true)
  }
  const exportVisible = async () => {
    if (!active) return
    try {
      const result = await api.exportSpectrum(token, active.id, { ccd, line, detail: frameVisible ? 'frame' : 'summary', phase: framePhase, frame: frameIndex, exposureStart: raw && exposureEnabled ? exposureStart : undefined, exposureEnd: raw && exposureEnabled ? exposureEnd : undefined, xMin: xStart, xMax: xEnd, referenceShift })
      const url = URL.createObjectURL(result.blob); const anchor = document.createElement('a'); anchor.href = url
      anchor.download = result.filename.match(/filename="?([^";]+)/)?.[1] ?? `spectrum-${active.id.replace(':', '-')}.csv`; anchor.click(); URL.revokeObjectURL(url)
      onToast('当前可见范围已导出并写入审计')
    } catch (error) { onToast(error instanceof Error ? error.message : '导出失败') }
  }
  const printVisible = async () => {
    if (!active) return
    setBusy(true)
    try {
      const result = await api.printSpectrumPdf(token, active.id, { visible_x_min: xStart, visible_x_max: xEnd, visible_y_min: yStart, visible_y_max: yEnd, ccd, line, mode: frameVisible ? 'frame' : mode, reference_shift: referenceShift, selected_record_ids: displayIds, priority_record_id: priorityId ?? selectedId ?? undefined, frame_phase: framePhase, frame_index: frameIndex, exposure_start: raw && exposureEnabled ? exposureStart : undefined, exposure_end: raw && exposureEnabled ? exposureEnd : undefined })
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = result.filename.match(/filename="?([^";]+)/)?.[1] ?? `spectrum-${active.id.replace(':', '-')}.pdf`
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      onToast(`谱图打印 PDF 已生成：${result.curveCount} 条曲线，${result.pointCount} 个可见点`)
    } catch (error) { onToast(error instanceof Error ? error.message : '打印准备失败') }
    finally { setBusy(false) }
  }

  return <div className="page-content spectrum-viewer-page" data-testid="spectrum-viewer-page">
    <div className="page-intro"><div><span className="section-kicker">S10 / SPECTRUM VIEWER</span><h1>谱图查看</h1><p>完整点位、多样品叠加、转角/曝光区间、CCD/谱线导航和可见范围输出。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => void loadRecords()} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />刷新</button><button className="secondary-button" onClick={() => void exportVisible()} disabled={!active || busy}><Download size={15} />导出可见范围</button><button className="secondary-button" onClick={() => void printVisible()} disabled={!active || busy} title="生成当前可见范围的打印 PDF"><Printer size={15} />打印 PDF</button></div></div>
    <div className="spectrum-viewer-layout">
      <aside className="surface spectrum-records"><div className="surface-heading"><div><span className="section-kicker">PUBLISHED DATA</span><h2>谱图记录 <span className="count-badge">{visibleRecords.length}</span></h2></div><Database size={17} /></div><label className="spectrum-angle-filter"><span>转角</span><select value={angleFilter} onChange={(event) => setAngleFilter(event.target.value)}><option value="all">全部（含未记录）</option>{angles.map((angle) => <option value={String(angle)} key={angle}>{angle}°</option>)}</select></label><div className="spectrum-record-list">{visibleRecords.map((record) => { const name = record.sample_name || record.band_name || record.id; const metadata = record.kind === 'raw' ? `${record.ccd_count} CCD · ${record.points_per_ccd} 点 · ${record.angle_deg == null ? '转角未记录' : `${record.angle_deg}°`}` : `${record.sample_count} 样品 · ${record.line_count} 谱线`; return <div className={`spectrum-record-row ${record.id === selectedId ? 'active' : ''}`} key={record.id}><label className="spectrum-overlay-check" title="加入多样品叠加"><input type="checkbox" checked={displayIds.includes(record.id)} disabled={record.kind !== 'raw'} onChange={() => toggleOverlay(record.id)} /></label><button onClick={() => selectRecord(record)}><span className={`spectrum-kind ${record.kind}`}>{record.kind === 'raw' ? 'RAW' : record.format.toUpperCase()}</span><div><strong title={name}>{name}</strong><small title={metadata}>{metadata}</small></div><ChevronRight size={14} /></button></div> })}</div><small className="spectrum-overlay-note">可叠加 1–8 个原始样品；点击图例设置优先曲线。</small></aside>
      <section className="surface spectrum-workbench">{!active ? <div className="method-empty"><Activity size={30} /><h2>选择一条谱图记录</h2></div> : <>
        <div className="spectrum-toolbar"><div className="spectrum-toolbar-group"><button className="icon-button" onClick={() => moveRecord(-1)} title="上一条记录"><ChevronLeft size={16} /></button><span className="spectrum-position">记录 {Math.max(1, visibleRecords.findIndex((item) => item.id === selectedId) + 1)} / {visibleRecords.length}</span><button className="icon-button" onClick={() => moveRecord(1)} title="下一条记录"><ChevronRight size={16} /></button><span className="toolbar-rule" /><button className="icon-button" onClick={() => moveBand(-1)} title={raw ? '上一 CCD' : '上一谱线'}><ChevronLeft size={16} /></button><span className="spectrum-position">{raw ? `CCD ${ccd + 1} / ${active.layout?.ccd_count ?? 0}` : `谱线 ${line + 1} / ${active.line_count ?? 0}`}</span><button className="icon-button" onClick={() => moveBand(1)} title={raw ? '下一 CCD' : '下一谱线'}><ChevronRight size={16} /></button></div><div className="spectrum-toolbar-group"><button className="tool-button" onClick={() => resetView()}><Maximize2 size={14} />适配</button><button className="tool-button" onClick={() => { setZoomX(1); setPanX(0) }}>100%</button><button className="tool-button" onClick={() => setZoomX(4)}>400%</button><button className="icon-button" onClick={() => setZoomX((value) => Math.min(32, value * 2))} title="横向放大"><ZoomIn size={15} /></button><button className="icon-button" onClick={() => setZoomX((value) => Math.max(1, value / 2))} title="横向缩小"><ZoomOut size={15} /></button><button className="icon-button" onClick={() => setZoomY((value) => Math.min(32, value * 2))} title="纵向放大">Y+</button><button className="icon-button" onClick={() => setZoomY((value) => Math.max(1, value / 2))} title="纵向缩小">Y−</button><button className="icon-button" onClick={() => resetView(true)} title="还原视图与参考校正"><RotateCcw size={15} /></button></div></div>
        <div className="spectrum-controls"><div className="segmented-control">{(['crosshair', 'pan', 'box'] as const).map((value) => <button key={value} className={tool === value ? 'active' : ''} onClick={() => setTool(value)}>{value === 'crosshair' ? '十字线' : value === 'pan' ? '滚动' : '框选'}</button>)}</div><div className="segmented-control">{(raw ? [['mean', '强度']] : active.matrix_kind === 'peak_back' ? [['peak', '峰值'], ['back', '背景']] : [['value', '结果']]).map(([key, label]) => <button key={key} className={mode === key ? 'active' : ''} onClick={() => setMode(key as typeof mode)}>{label}</button>)}</div><label className="spectrum-reference"><span>参考校正</span><EmptyableNumberInput step="0.001" value={referenceShift} onValueChange={setReferenceShift} /><span>nm</span></label><label className="spectrum-reference spectrum-locate"><span>谱线定位</span><input value={locateValue} onChange={(event) => setLocateValue(event.target.value)} placeholder="波长/点" /><button className="tool-button" onClick={locate}>定位并锁定</button></label>{raw && <label className="spectrum-exposure"><input type="checkbox" checked={exposureEnabled} onChange={(event) => setExposureEnabled(event.target.checked)} /><span>曝光区间</span><EmptyableNumberInput min="1" max={maxExposure} value={exposureStart} onValueChange={(value) => setExposureStart(Math.max(1, Math.min(maxExposure, value)))} /><span>–</span><EmptyableNumberInput min={exposureStart} max={maxExposure} value={exposureEnd} onValueChange={(value) => setExposureEnd(Math.max(exposureStart, Math.min(maxExposure, value)))} /></label>}{raw && <div className="spectrum-frame-actions"><select value={framePhase} onChange={(event) => setFramePhase(event.target.value as 'burn' | 'dark')}><option value="burn">burn</option><option value="dark">dark</option></select><EmptyableNumberInput min="0" value={frameIndex} onValueChange={(value) => setFrameIndex(Math.max(0, value))} /><button className="tool-button" onClick={() => void loadFrame()} disabled={busy}>原始帧</button></div>}</div>
        <div className="spectrum-legend">{curves.map((curve) => <button key={curve.id} className={curve.priority ? 'priority' : ''} onClick={() => setPriorityId(curve.id)}><i style={{ background: curve.color }} />{curve.label}{curve.priority && <span>优先</span>}</button>)}</div>
        <div className="spectrum-plot-wrap"><SpectrumPlot curves={curves} xStart={xStart} xEnd={xEnd} yStart={yStart} yEnd={yEnd} tool={tool} cursor={cursor} locked={locked} xAxisLabel={curves.some((curve) => curve.data.some((item) => item.point.wavelength_nm != null)) ? '波长 (nm)' : raw ? 'CCD 点位' : '步长 / 点位'} yAxisLabel={mode === 'peak' ? '峰值' : mode === 'back' ? '背景' : mode === 'value' ? '结果值' : '强度 (ADC)'} onCursor={setCursor} onToggleLock={() => setLocked((value) => !value)} onPan={(dx, dy) => { setPanX((value) => Math.max(-1, Math.min(1, value - dx * 2))); setPanY((value) => Math.max(-1, Math.min(1, value + dy * 2))) }} onBoxSelect={boxSelect} />{cursor && <div className="spectrum-cursor-readout"><span>{cursor.curveLabel}</span><strong>{cursor.datum.x.toFixed(3)}</strong><span>点 {cursor.datum.point.point_index} · 强度 {cursor.datum.y.toFixed(3)}</span><span>{locked ? <LockKeyhole size={12} /> : <UnlockKeyhole size={12} />}</span></div>}</div>
        <div className="spectrum-pan"><button className="icon-button" onClick={() => setPanX((value) => Math.max(-1, value - .2))}><ChevronLeft size={15} /></button><button className="icon-button" onClick={() => setPanY((value) => Math.max(-1, value - .2))}>↑</button><span>可见范围 X {xStart.toFixed(3)}–{xEnd.toFixed(3)} · Y {yStart.toFixed(2)}–{yEnd.toFixed(2)}</span><button className="icon-button" onClick={() => setPanY((value) => Math.min(1, value + .2))}>↓</button><button className="icon-button" onClick={() => setPanX((value) => Math.min(1, value + .2))}><ChevronRight size={15} /></button></div>
        <div className="spectrum-facts"><div><span>来源 SHA-256</span><CopyableCode value={active.source_sha256} visibleLength={18} /></div><div><span>样品</span><ExpandableValue value={active.sample_name || active.sample_names?.join(' / ') || '—'} /></div><div><span>转角 / CCD</span><strong>{active.angle_deg == null ? '未记录' : `${active.angle_deg}°`} / {raw ? ccd + 1 : '—'}</strong></div><div><span>曝光</span><strong>{active.exposure_segment ? `${active.exposure_segment.start}–${active.exposure_segment.end}` : frameVisible ? `${framePhase} #${frameIndex + 1}` : '均值'}</strong></div><div><span>可见点 / 曲线</span><strong>{curves.reduce((sum, curve) => sum + curve.data.filter((item) => item.x >= xStart && item.x <= xEnd).length, 0)} / {curves.length}</strong></div></div>
      </>}</section>
    </div>
  </div>
}

function SampleQueuePage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [queues, setQueues] = useState<SampleQueue[]>([])
  const [selected, setSelected] = useState<SampleQueue | null>(null)
  const [name, setName] = useState('现场样品')
  const [entryName, setEntryName] = useState('')
  const [repeats, setRepeats] = useState(1)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await api.sampleQueues(token)
      setQueues(next)
      setSelected((current) => current ? next.find((item) => item.id === current.id) ?? next[0] ?? null : next[0] ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取样品队列') }
    finally { setLoading(false) }
  }, [token, onToast])
  useEffect(() => { void load() }, [load])

  const create = async () => {
    if (!entryName.trim()) return
    try {
      const next = await api.createSampleQueue(token, { name, items: [{ pre_name: entryName, repeats }] })
      setQueues((current) => [next, ...current])
      setSelected(next)
      setEntryName('')
      onToast('样品队列已创建')
    } catch (error) { onToast(error instanceof Error ? error.message : '创建失败') }
  }

  const importFile = async (file: File) => {
    try {
      const next = await api.importSampleQueue(token, file.name, await file.text())
      setQueues((current) => [next, ...current.filter((item) => item.id !== next.id)])
      setSelected(next)
      onToast(`已导入 ${next.record_count} 条样品记录`)
    } catch (error) { onToast(error instanceof Error ? error.message : 'SAM 导入失败') }
  }

  const exportQueue = async () => {
    if (!selected) return
    const result = await api.exportSampleQueue(token, selected.id)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `queue-${selected.id}.sam`
    anchor.click()
    URL.revokeObjectURL(url)
    onToast('SAM 文件已导出')
  }

  const addItem = async () => {
    if (!selected || !entryName.trim()) return
    try {
      const next = await api.updateSampleQueue(token, selected.id, [...selected.items.map((item) => ({ pre_name: item.pre_name, repeats: item.repeats })), { pre_name: entryName, repeats }])
      setSelected(next); setQueues((current) => current.map((item) => item.id === next.id ? next : item)); setEntryName('')
    } catch (error) { onToast(error instanceof Error ? error.message : '添加失败') }
  }

  const clearQueue = async () => {
    if (!selected || !window.confirm('清空当前队列？')) return
    try {
      const next = await api.clearSampleQueue(token, selected.id)
      setSelected(next); setQueues((current) => current.map((item) => item.id === next.id ? next : item)); onToast('队列已清空')
    } catch (error) { onToast(error instanceof Error ? error.message : '清空失败') }
  }

  const deleteItem = async (itemId: number) => {
    if (!selected) return
    try {
      const next = await api.deleteSampleItem(token, selected.id, itemId)
      setSelected(next); setQueues((current) => current.map((item) => item.id === next.id ? next : item))
    } catch (error) { onToast(error instanceof Error ? error.message : '删除失败') }
  }

  return <div className="page-content sample-queue-page">
    <div className="page-intro"><div><span className="section-kicker">S07 / SAMPLE QUEUE</span><h1>样品队列</h1><p>管理预录样号、重复次数和采集后命名。旧 `.sam` 文件只读导入，谱图数据不会在此步骤生成。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => setSelected(null)}><Plus size={15} />新建队列</button><label className="secondary-button"><Upload size={15} />导入 SAM<input type="file" accept=".sam,.txt" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file) }} /></label><button className="secondary-button" onClick={() => void exportQueue()} disabled={!selected}><Download size={15} />导出 SAM</button><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div></div>
    <div className="sample-queue-grid">
      <section className="surface sample-list"><div className="surface-heading"><div><span className="section-kicker">QUEUES</span><h2>队列</h2></div><span className="muted-label">{queues.length} 个</span></div>{loading ? <div className="empty-state">正在读取...</div> : queues.length === 0 ? <div className="empty-state">尚无队列</div> : <div className="queue-list">{queues.map((queue) => <button key={queue.id} className={selected?.id === queue.id ? 'queue-row active' : 'queue-row'} onClick={() => setSelected(queue)}><span><strong>{queue.name}</strong><small>{queue.record_count} 条记录 · {queue.expanded_bands} 个谱带</small></span><ChevronRight size={15} /></button>)}</div>}</section>
      <section className="surface sample-editor"><div className="surface-heading"><div><span className="section-kicker">QUEUE ENTRY</span><h2>{selected?.name ?? '新建队列'}</h2></div>{selected && <div className="page-intro-actions"><span className="status-chip">{selected.expanded_bands} 谱带</span><button className="icon-button compact danger" title="清空队列" onClick={() => void clearQueue()}><Trash2 size={14} /></button></div>}</div><div className="sample-entry-form"><label className="field"><span>队列名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><label className="field"><span>样品名</span><input value={entryName} onChange={(event) => setEntryName(event.target.value)} placeholder="例如 A001 / S10" /></label><label className="field small-field"><span>重复次数</span><EmptyableNumberInput min={0} max={10} value={repeats} onValueChange={setRepeats} /></label><button className="primary-button" onClick={() => void (selected ? addItem() : create())}><Plus size={15} />{selected ? '插入样品' : '创建队列'}</button></div>{selected && <div className="sample-table-wrap"><table className="data-table"><thead><tr><th>#</th><th>预录名称</th><th>重复</th><th>展开谱带</th><th>采集后名称</th><th /></tr></thead><tbody>{selected.items.map((item) => <tr key={item.id}><td>{item.position + 1}</td><td><strong>{item.pre_name || '空样'}</strong></td><td>{item.repeats || '空样'}</td><td>{item.expanded_bands}</td><td>{item.post_name ?? '待采集'}</td><td><button className="icon-button compact danger" title="删除样品" onClick={() => void deleteItem(item.id)}><Trash2 size={13} /></button></td></tr>)}</tbody></table></div>}</section>
    </div>
  </div>
}

function AboutPage({ about, diagnostics, capabilities, health, onRefresh }: { about: About | null; diagnostics: Diagnostics | null; capabilities: Capability[]; health: 'online' | 'offline'; onRefresh: () => void }) {
  return <div className="page-content about-page" data-testid="about-diagnostics"><section className="hero-row compact-hero"><div><span className="eyebrow"><span className="eyebrow-line" />SYSTEM INFORMATION</span><h1>关于与诊断</h1><p>验证模块注册、接口和本地运行时状态。</p></div><button className="secondary-button" onClick={onRefresh}><RefreshCw size={16} />重新诊断</button></section><div className="about-layout"><section className="surface about-intro"><div className="product-lockup"><div className="product-mark"><Sparkles size={26} /></div><div><h2>GeoSpectrum</h2><span>自动转角平面光栅光谱仪分析平台</span></div></div><p>{about?.description ?? '等待本地服务连接。'}</p><div className="version-line"><span>应用版本</span><strong>{about?.version ?? '—'}</strong><span>阶段</span><strong>{about?.stage ?? '—'}</strong></div><div className="diagnostic-result"><span className={`status-dot ${health}`} /><div><strong>{health === 'online' ? '本地服务运行正常' : '无法连接本地服务'}</strong><span>{about?.runtime ?? '启动 FastAPI 后刷新此页'}</span></div></div><div className="diagnostic-grid"><div><span>SQLite 完整性</span><strong>{diagnostics?.sqlite_integrity ?? '—'}</strong></div><div><span>日志事件</span><strong>{diagnostics?.event_count ?? '—'}</strong></div><div><span>日志模式</span><strong>{diagnostics?.journal_mode ?? '—'}</strong></div><div><span>外键约束</span><strong>{diagnostics?.foreign_keys === 1 ? '已启用' : '—'}</strong></div></div></section><section className="surface capability-surface"><div className="surface-heading"><div><span className="section-kicker">MODULE REGISTRY</span><h2>能力清单</h2></div><ClipboardCheck size={17} /></div><div className="capability-list">{capabilities.map((capability) => <div className="capability-row" key={capability.key}><span className="capability-icon"><CheckCircle2 size={16} /></span><div><strong>{capability.title}</strong><small>{capability.key} · {capability.version}</small></div><code>{capability.route}</code><span className="capability-enabled">已启用</span></div>)}</div><div className="api-note"><Info size={15} /><span>API 版本 {about?.api_version ?? 'v1'} · 能力由静态模块清单生成</span></div></section></div></div>
}

function DisabledPage({ item }: { item: { label: string; icon: typeof LayoutDashboard; hint: string } }) { const Icon = item.icon; return <div className="page-content disabled-page"><div className="disabled-illustration"><Icon size={34} /></div><span className="section-kicker">MODULE NOT ENABLED</span><h1>{item.label}</h1><p>{item.hint}。当前步骤只提供导航入口，业务数据和操作会在对应阶段交付。</p><div className="disabled-track"><span className="track-done" /><span /><span /><span /></div></div> }

function ErrorPage({ onRetry }: { onRetry: () => void }) { return <main className="error-page"><div className="error-panel"><div className="error-icon"><AlertTriangle size={25} /></div><span className="section-kicker">LOCAL SERVICE UNAVAILABLE</span><h1>无法连接本地服务</h1><p>GeoSpectrum 工作台需要本机 FastAPI 服务完成健康握手。请检查服务进程后重试。</p><button className="primary-button" onClick={onRetry}><RefreshCw size={16} />重新连接</button><div className="error-code"><span>诊断端点</span><code>http://127.0.0.1:&lt;random&gt;/health</code></div></div></main> }

export default App
