import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, CircleX, X } from 'lucide-react'
import { api, type About, type AuthUser, type Capability, type CurrentMethodState, type Diagnostics, type RuntimeEvent, type Settings } from '../api'
import { AcquisitionPage } from '../pages/devices/AcquisitionPage'
import { DispersionPage } from '../pages/dispersion/DispersionPage'
import { SampleAcquisitionPage } from '../pages/acquisition/SampleAcquisitionPage'
import { HardwareAcquisitionPage } from '../pages/hardwareAcquisition/HardwareAcquisitionPage'
import { MercuryCalibrationPage } from '../pages/mercuryCalibration/MercuryCalibrationPage'
import { AnalysisPage } from '../pages/analysis/AnalysisPage'
import { PostProcessingPage } from '../pages/postprocessing/PostProcessingPage'
import { ReportsPage } from '../pages/reports/ReportsPage'
import { MaintenancePage } from '../pages/maintenance/MaintenancePage'
import { HelpPage } from '../pages/help/HelpPage'
import { entryForPage, navigationAvailability, navigationEntries, type NavigationEntry, type Page } from '../navigation'
import { type ToastNotice, feedbackToneFor } from './feedback'
import { ErrorPage } from './StatusPages'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { Workspace } from '../pages/workspace/WorkspacePage'
import { MethodsPage } from '../pages/methods/MethodsPage'
import { LegacyMigrationPage } from '../pages/migration/LegacyMigrationPage'
import { SpectrumMigrationPage } from '../pages/migration/SpectrumMigrationPage'
import { ResultMigrationPage } from '../pages/migration/ResultMigrationPage'
import { SpectrumViewerPage } from '../pages/spectra/SpectrumViewerPage'
import { SampleQueuePage } from '../pages/sampleQueues/SampleQueuePage'
import { SettingsPage } from '../pages/settings/SettingsPage'
import { AboutPage } from '../pages/about/AboutPage'
import { UsersPage } from '../pages/auth/UsersPage'
import { AuditPage } from '../pages/auth/AuditPage'
import { ExtensionPage } from '../pages/extensions/ExtensionPage'

export function WorkspaceApp({ token, user, onLogout }: { token: string; user: AuthUser; onLogout: () => void }) {
  const [target, setTarget] = useState<{ page: Page; key: string; view: string | null }>({ page: 'workspace', key: 'workspace.overview', view: null })
  const [events, setEvents] = useState<RuntimeEvent[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [about, setAbout] = useState<About | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null)
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [health, setHealth] = useState<'online' | 'offline'>('offline')
  const [currentMethod, setCurrentMethod] = useState<CurrentMethodState | null>(null)
  const [toast, setToast] = useState<ToastNotice | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeExtension, setActiveExtension] = useState<Capability | null>(null)
  const showToast = useCallback((message: string) => setToast({ message, tone: feedbackToneFor(message) }), [])
  const entries = useMemo(() => navigationEntries(capabilities, user.permissions), [capabilities, user.permissions])
  const activeEntry = entries.find((entry) => entry.key === target.key) ?? entryForPage(entries, target.page, target.view)
  const page = target.page

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const currentPromise = user.permissions.includes('methods.read') ? api.currentMethod(token) : Promise.resolve(null)
      const aboutPromise = user.permissions.includes('about.read') ? api.about(token) : Promise.resolve(null)
      const diagnosticsPromise = user.permissions.includes('about.read') ? api.diagnostics(token) : Promise.resolve(null)
      const [nextHealth, nextEvents, nextSettings, nextAbout, nextCapabilities, nextDiagnostics, nextCurrentMethod] = await Promise.all([
        api.health(), api.logs(token), api.settings(token), aboutPromise, api.capabilities(), diagnosticsPromise,
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

  const handleNavigation = (entry: NavigationEntry) => {
    const availability = navigationAvailability(entry, currentMethod)
    if (availability.disabled) {
      showToast(availability.reason ?? '当前入口不可用')
      return
    }
    if (entry.extension) setActiveExtension(entry.extension)
    setTarget({ page: entry.page, key: entry.key, view: entry.view })
  }
  const handlePage = (nextPage: Page) => {
    const entry = entryForPage(entries, nextPage, nextPage === 'methods' ? 'lifecycle' : undefined)
    if (entry) handleNavigation(entry)
  }
  const handleInternalView = (nextPage: Page, view: string) => {
    const normalizedView = nextPage === 'analysis' && !['raw', 'quality'].includes(view) ? 'curve' : view
    const entry = entryForPage(entries, nextPage, normalizedView)
    if (entry) setTarget({ page: entry.page, key: entry.key, view: entry.view })
  }

  const saveSettings = async (nextSettings: Settings) => {
    const invalid = document.querySelector<HTMLInputElement>('.settings-page [data-numeric-input]:invalid')
    if (invalid) {
      invalid.reportValidity()
      showToast('请先修正设置中的无效数值')
      return
    }
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
      {health === 'offline' && !loading && !about ? <ErrorPage onRetry={loadData} /> : <><Sidebar activeEntry={activeEntry} entries={entries} onNavigate={handleNavigation} currentMethod={currentMethod} health={health} showStatusBar={settings?.display.show_status_bar !== false} onToast={showToast} />
        <main className="main-area">
          <Header activeEntry={activeEntry} extensionTitle={activeExtension?.title} onRefresh={loadData} loading={loading} onNavigate={handlePage} user={user} currentMethod={currentMethod} onLogout={onLogout} />
          {page === 'workspace' && <Workspace token={token} health={health} canClearEvents={user.permissions.includes('runtime-events.write')} events={events} currentMethod={currentMethod} diagnostics={diagnostics} capabilities={capabilities} entries={entries} onNavigate={handlePage} onEventsChange={setEvents} onToast={showToast} />}
          {page === 'methods' && <MethodsPage token={token} currentUser={user} currentMethod={currentMethod} initialSection={target.view} onViewChange={(view) => handleInternalView('methods', view)} onCurrentMethodChange={setCurrentMethod} onToast={showToast} />}
          {page === 'migration' && <LegacyMigrationPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'spectrum-migration' && <SpectrumMigrationPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'result-migration' && <ResultMigrationPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'spectra' && <SpectrumViewerPage token={token} onToast={showToast} />}
          {page === 'postprocessing' && <PostProcessingPage token={token} initialView={target.view === 'recalculate-export' ? 'recalculate-export' : 'interval'} onViewChange={(view) => handleInternalView('postprocessing', view)} canWrite={user.permissions.includes('postprocessing.write')} canExecute={user.permissions.includes('postprocessing.execute')} canExport={user.permissions.includes('postprocessing.export')} onToast={showToast} />}
          {page === 'samples' && <SampleQueuePage token={token} onToast={showToast} />}
          {page === 'acquisition' && <AcquisitionPage token={token} canWrite={user.permissions.includes('devices.write')} canExecute={user.permissions.includes('devices.execute')} onToast={showToast} />}
          {page === 'dispersion' && <DispersionPage token={token} canWrite={user.permissions.includes('dispersion.write')} canExecute={user.permissions.includes('dispersion.execute')} onToast={showToast} />}
          {page === 'sample-acquisition' && <SampleAcquisitionPage token={token} canWrite={user.permissions.includes('acquisition.write')} canExecute={user.permissions.includes('acquisition.execute')} onToast={showToast} />}
          {page === 'hardware-acquisition' && <HardwareAcquisitionPage token={token} canWrite={user.permissions.includes('hardware-acquisition.write')} canExecute={user.permissions.includes('hardware-acquisition.execute')} onToast={showToast} />}
          {page === 'mercury-calibration' && <MercuryCalibrationPage token={token} canWrite={user.permissions.includes('mercury-calibration.write')} canExecute={user.permissions.includes('mercury-calibration.execute')} onToast={showToast} />}
          {page === 'analysis' && <AnalysisPage token={token} initialView={target.view === 'quality' || target.view === 'curve' ? target.view : 'raw'} onViewChange={(view) => handleInternalView('analysis', view)} canExecute={user.permissions.includes('analysis.execute')} canIntervene={user.permissions.includes('analysis.intervene')} canQuality={user.permissions.includes('analysis.quality')} canCurve={user.permissions.includes('analysis.curve')} canPrint={user.permissions.includes('analysis.print')} onToast={showToast} />}
          {page === 'reports' && <ReportsPage token={token} canWrite={user.permissions.includes('reports.write')} canExport={user.permissions.includes('reports.export')} onToast={showToast} />}
          {page === 'maintenance' && <MaintenancePage token={token} canWrite={user.permissions.includes('maintenance.write')} onToast={showToast} />}
          {page === 'help' && <HelpPage token={token} onToast={showToast} />}
          {page === 'settings' && settings && <SettingsPage settings={settings} onSave={saveSettings} onReset={resetSettings} />}
          {page === 'about' && <AboutPage about={about} diagnostics={diagnostics} capabilities={capabilities} health={health} onRefresh={loadData} />}
          {page === 'users' && <UsersPage token={token} currentUser={user} onToast={showToast} />}
          {page === 'audit' && <AuditPage token={token} />}
          {page === 'extension' && activeExtension && <ExtensionPage token={token} extension={activeExtension} onToast={showToast} />}
        </main></>}
      {toast && <div className={`toast ${toast.tone}`} role={toast.tone === 'error' ? 'alert' : 'status'} aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}>
        {toast.tone === 'success' ? <CheckCircle2 size={17} /> : toast.tone === 'error' ? <CircleX size={17} /> : toast.tone === 'warning' ? <AlertTriangle size={17} /> : <Info size={17} />}
        <span>{toast.message}</span><button title="关闭" onClick={() => setToast(null)}><X size={14} /></button>
      </div>}
    </div>
  )
}
