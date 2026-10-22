import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, CircleX, X } from 'lucide-react'
import {
  api,
  type About,
  type AuthUser,
  type Capability,
  type CurrentMethodState,
  type RuntimeEvent,
  type Settings
} from '../api'
import type { AnalysisRun } from '../api'
import type { ReportSource } from '../pages/reports/ReportBuilder'
import { DeviceDebugPage } from '../pages/devices/DeviceDebugPage'
import { SpectroscopyWorkbench } from '../pages/acquisition/SpectroscopyWorkbench'
import { EvaporationCurvesPage } from '../pages/acquisition/EvaporationCurvesPage'
import { isSpectroscopyMode } from '../pages/acquisition/spectroscopySession'
import { HardwareAcquisitionPage } from '../pages/hardwareAcquisition/HardwareAcquisitionPage'
import { AnalysisPage } from '../pages/analysis/AnalysisPage'
import { DataProcessingPage } from '../pages/postprocessing/DataProcessingPage'
import { MaintenancePage } from '../pages/maintenance/MaintenancePage'
import { HelpPage } from '../pages/help/HelpPage'
import { entryForPage, navigationAvailability, navigationEntries, type NavigationEntry, type Page } from '../navigation'
import { type ToastNotice, feedbackToneFor } from './feedback'
import { ErrorPage } from './StatusPages'
import { PageHeading } from '../components/PageHeading'
import { MessagePanel } from '../components/MessagePanel'
import type { CSSProperties } from 'react'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { Workspace } from '../pages/workspace/WorkspacePage'
import { MethodsPage } from '../pages/methods/MethodsPage'
import type { MethodShortcutAction, MethodShortcutRequest } from '../pages/methods/methodShortcuts'
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
  const [target, setTarget] = useState<{ page: Page; key: string; view: string | null }>({
    page: 'workspace',
    key: 'workspace.overview',
    view: null
  })
  const [events, setEvents] = useState<RuntimeEvent[]>([])
  const [dockHeight, setDockHeight] = useState(184)
  const canReadEvents = user.permissions.includes('runtime-events.read')
  const [settings, setSettings] = useState<Settings | null>(null)
  const [pageActionsTarget, setPageActionsTarget] = useState<HTMLDivElement | null>(null)
  const [about, setAbout] = useState<About | null>(null)
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [health, setHealth] = useState<'online' | 'offline'>('offline')
  const [currentMethod, setCurrentMethod] = useState<CurrentMethodState | null>(null)
  const [reportSource, setReportSource] = useState<ReportSource | null>(null)
  const [methodShortcut, setMethodShortcut] = useState<MethodShortcutRequest | null>(null)
  const shortcutId = useRef(0)
  const [sampleEntryRequest, setSampleEntryRequest] = useState(0)
  const rememberAnalysis = useCallback((run: AnalysisRun) => setReportSource({
    kind: 'analysis', id: run.id, name: run.name, sampleCount: run.samples.length, status: run.status
  }), [])
  const [toast, setToast] = useState<ToastNotice | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeExtension, setActiveExtension] = useState<Capability | null>(null)
  const showToast = useCallback((message: string) => setToast({ message, tone: feedbackToneFor(message) }), [])
  const entries = useMemo(() => navigationEntries(capabilities, user.permissions), [capabilities, user.permissions])
  const activeEntry =
    entries.find((entry) => entry.key === target.key) ?? entryForPage(entries, target.page, target.view)
  const page = target.page
  const spectroscopyLock = useRef<string | null>(null)
  const updateSpectroscopyLock = useCallback((reason: string | null) => { spectroscopyLock.current = reason }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const currentPromise = user.permissions.includes('methods.read')
        ? api.currentMethod(token)
        : Promise.resolve(null)
      const aboutPromise = user.permissions.includes('about.read') ? api.about(token) : Promise.resolve(null)
      const [nextHealth, nextEvents, nextSettings, nextAbout, nextCapabilities, nextCurrentMethod] =
        await Promise.all([
          api.health(),
          canReadEvents ? api.logs(token, '?limit=500') : Promise.resolve([]),
          user.permissions.includes('settings.read') ? api.settings(token) : Promise.resolve(null),
          aboutPromise,
          api.capabilities(),
          currentPromise
        ])
      setHealth(nextHealth.status === 'ok' ? 'online' : 'offline')
      setEvents(nextEvents)
      setSettings(nextSettings)
      setAbout(nextAbout)
      setCapabilities(nextCapabilities.capabilities)
      setCurrentMethod(nextCurrentMethod)
    } catch {
      setHealth('offline')
    } finally {
      setLoading(false)
    }
  }, [token, user.permissions, canReadEvents])

  useEffect(() => {
    void loadData()
  }, [loadData])
  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = settings?.display.theme === 'dark' ? 'dark' : 'light'
    root.dataset.density = settings?.display.density === 'compact' ? 'compact' : 'comfortable'
    root.dataset.timezone = settings?.time.timezone || 'Asia/Shanghai'
  }, [settings])
  useEffect(() => {
    if (page !== 'settings') return
    void api
      .settings(token)
      .then(setSettings)
      .catch((error) => showToast(error instanceof Error ? error.message : '无法刷新软件设置'))
  }, [page, showToast, token])
  useEffect(() => {
    if (!canReadEvents) return
    const interval = window.setInterval(() => {
      void api
        .logs(token, '?limit=500')
        .then(setEvents)
        .catch(() => undefined)
    }, 1500)
    return () => window.clearInterval(interval)
  }, [token, canReadEvents])
  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const handleNavigation = (entry: NavigationEntry) => {
    if ((entry.page !== page || entry.view !== target.view) && isSpectroscopyMode(page)
      && (isSpectroscopyMode(entry.page) || entry.page === 'evaporation-curves') && spectroscopyLock.current) {
      showToast(spectroscopyLock.current)
      return false
    }
    const availability = navigationAvailability(entry, currentMethod)
    if (availability.disabled) {
      showToast(availability.reason ?? '当前入口不可用')
      return false
    }
    if (entry.extension) setActiveExtension(entry.extension)
    setTarget({ page: entry.page, key: entry.key, view: entry.view })
    return true
  }
  const handleMethodShortcut = (action: MethodShortcutAction) => {
    if (!user.permissions.includes('methods.write')) return
    const entry = entryForPage(entries, 'methods', 'conditions')
    if (entry && handleNavigation(entry)) setMethodShortcut({ id: ++shortcutId.current, action })
  }
  const handleQuickNavigation = (entry: NavigationEntry) => {
    if (handleNavigation(entry) && entry.page === 'samples') setSampleEntryRequest(request => request + 1)
  }
  const handlePage = (nextPage: Page) => {
    const entry = entryForPage(entries, nextPage, nextPage === 'methods' ? 'lifecycle' : undefined)
    if (entry) handleNavigation(entry)
  }
  const handleInternalView = (nextPage: Page, view: string) => {
    const entry = entryForPage(entries, nextPage, nextPage === 'analysis' ? undefined : view)
    if (entry) setTarget({ page: entry.page, key: entry.key, view })
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
    <div
      className={`app-shell${canReadEvents ? ' with-runtime-messages' : ''}`}
      style={{ '--runtime-dock-height': `${canReadEvents ? dockHeight : 0}px` } as CSSProperties}
      data-testid="app-shell"
      data-theme={settings?.display.theme ?? 'light'}
      data-density={settings?.display.density ?? 'comfortable'}
    >
      {health === 'offline' && !loading && !about ? (
        <ErrorPage onRetry={loadData} />
      ) : (
        <>
          <Sidebar
            activeEntry={activeEntry}
            entries={entries}
            onNavigate={handleNavigation}
            currentMethod={currentMethod}
            health={health}
            showStatusBar={settings?.display.show_status_bar !== false}
            onToast={showToast}
          />
          <main className="main-area">
            <Header
              activeEntry={activeEntry}
              extensionTitle={activeExtension?.title}
              onRefresh={loadData}
              loading={loading}
              onNavigate={handlePage}
              entries={entries}
              onNavigateEntry={handleQuickNavigation}
              onMethodShortcut={handleMethodShortcut}
              user={user}
              currentMethod={currentMethod}
              onLogout={onLogout}
            />
            <div className="page-scroll-region">
            {activeEntry && !isSpectroscopyMode(page) && page !== 'analysis' && page !== 'extension' && <PageHeading entry={activeEntry} actionsRef={setPageActionsTarget} />}
            {page === 'workspace' && (
              <Workspace
                token={token}
                health={health}
                canClearEvents={user.permissions.includes('runtime-events.write')}
                events={events}
                currentMethod={currentMethod}
                capabilities={capabilities}
                entries={entries}
                onNavigate={handlePage}
                onEventsChange={setEvents}
                onToast={showToast}
              />
            )}
            {page === 'methods' && (
              <MethodsPage
                token={token}
                currentUser={user}
                currentMethod={currentMethod}
                initialSection={target.view}
                shortcut={methodShortcut}
                onShortcutHandled={() => setMethodShortcut(null)}
                onViewChange={(view) => handleInternalView('methods', view)}
                onCurrentMethodChange={setCurrentMethod}
                onToast={showToast}
              />
            )}
            {page === 'migration' && <LegacyMigrationPage token={token} currentUser={user} onToast={showToast} />}
            {page === 'spectrum-migration' && (
              <SpectrumMigrationPage token={token} currentUser={user} onToast={showToast} />
            )}
            {page === 'result-migration' && (
              <ResultMigrationPage token={token} currentUser={user} onToast={showToast} />
            )}
            {page === 'spectra' && <SpectrumViewerPage token={token} onToast={showToast} />}
            {(page === 'postprocessing' || page === 'reports') && (
              <DataProcessingPage token={token} page={page} initialView={target.view}
                reportSource={reportSource} onReportSourceChange={setReportSource}
                permissions={user.permissions} onViewChange={(view) => handleInternalView('reports', view)} onToast={showToast} />
            )}
            {page === 'samples' && <SampleQueuePage token={token} onToast={showToast} entryRequest={sampleEntryRequest} />}
            {(page === 'acquisition' || page === 'mercury-calibration') && (
              <DeviceDebugPage token={token} permissions={user.permissions} settings={settings}
                initialView={page === 'mercury-calibration' ? 'mercury' : target.view}
                onSettingsChange={setSettings} onViewChange={view => handleInternalView('acquisition', view)} onToast={showToast} />
            )}
            {isSpectroscopyMode(page) && (
              <SpectroscopyWorkbench mode={page} view={page === 'dispersion' && target.view === 'curve' ? 'curve' : 'capture'} token={token} permissions={user.permissions} entries={entries}
                currentMethod={currentMethod} onNavigate={handleNavigation} onLockChange={updateSpectroscopyLock} onToast={showToast} />
            )}
            {page === 'evaporation-curves' && <EvaporationCurvesPage token={token} onToast={showToast} />}
            {page === 'hardware-acquisition' && (
              <HardwareAcquisitionPage
                canSaveSample={user.permissions.includes('hardware-acquisition.execute') && user.permissions.includes('acquisition.write')}
                token={token}
                canWrite={user.permissions.includes('hardware-acquisition.write')}
                canExecute={user.permissions.includes('hardware-acquisition.execute')}
                onToast={showToast}
              />
            )}
            {page === 'analysis' && (
              <AnalysisPage
                token={token}
                initialView={target.view === 'quality' || target.view === 'curve' || target.view === 'standards' || target.view === 'samples' ? target.view : 'raw'}
                onViewChange={(view) => handleInternalView('analysis', view)}
                canExecute={user.permissions.includes('analysis.execute')}
                canIntervene={user.permissions.includes('analysis.intervene')}
                canQuality={user.permissions.includes('analysis.quality')}
                canCurve={user.permissions.includes('analysis.curve')}
                canPrint={user.permissions.includes('analysis.print')}
                canSaveMethod={user.permissions.includes('methods.write')}
                onCurrentRunChange={rememberAnalysis}
                onToast={showToast}
              />
            )}
            {page === 'maintenance' && (
              <MaintenancePage
                token={token}
                canWrite={user.permissions.includes('maintenance.write')}
                onToast={showToast}
              />
            )}
            {page === 'help' && <HelpPage token={token} onToast={showToast} />}
            {page === 'settings' && settings && (
              <SettingsPage settings={settings} onSave={saveSettings} onReset={resetSettings} onToast={showToast} actionsTarget={pageActionsTarget} />
            )}
            {page === 'about' && (
              <AboutPage about={about} />
            )}
            {page === 'users' && <UsersPage token={token} currentUser={user} onToast={showToast} />}
            {page === 'audit' && <AuditPage token={token} />}
            {page === 'extension' && activeExtension && (
              <ExtensionPage token={token} extension={activeExtension} onToast={showToast} />
            )}
            </div>
            {canReadEvents && <MessagePanel key={user.id} events={events} userId={user.id} onHeightChange={setDockHeight} />}
          </main>
        </>
      )}
      {toast && (
        <div
          className={`toast ${toast.tone}`}
          role={toast.tone === 'error' ? 'alert' : 'status'}
          aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}
        >
          {toast.tone === 'success' ? (
            <CheckCircle2 size={17} />
          ) : toast.tone === 'error' ? (
            <CircleX size={17} />
          ) : toast.tone === 'warning' ? (
            <AlertTriangle size={17} />
          ) : (
            <Info size={17} />
          )}
          <span>{toast.message}</span>
          <button title="关闭" onClick={() => setToast(null)}>
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
