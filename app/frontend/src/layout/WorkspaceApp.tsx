import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, CircleX, X } from 'lucide-react'
import {
  api,
  type About,
  type AuthUser,
  type Capability,
  type CurrentMethodState,
  type Settings
} from '../api'
import type { AnalysisRun } from '../api'
import type { ReportSource } from '../pages/reports/ReportBuilder'
import { DeviceDebugPage } from '../pages/devices/DeviceDebugPage'
import { SpectroscopyWorkbench } from '../pages/acquisition/SpectroscopyWorkbench'
import { EvaporationCurvesPage } from '../pages/acquisition/EvaporationCurvesPage'
import { isSpectroscopyMode } from '../pages/acquisition/spectroscopySession'
import { AnalysisPage } from '../pages/analysis/AnalysisPage'
import { DataProcessingPage } from '../pages/postprocessing/DataProcessingPage'
import { PreparedImportPage } from '../pages/postprocessing/PreparedImportPage'
import { MaintenancePage } from '../pages/maintenance/MaintenancePage'
import { HelpPage } from '../pages/help/HelpPage'
import { entryForPage, navigationAvailability, navigationEntries, type NavigationEntry, type Page } from '../navigation'
import { type ToastNotice, feedbackToneFor } from './feedback'
import { ErrorPage } from './StatusPages'
import { PageHeading } from '../components/PageHeading'
import { MessagePanel } from '../components/MessagePanel'
import { RenderProfilerProbe } from '../components/RenderProfiler'
import { runtimeEventsStore } from '../stores/runtimeEventsStore'
import { deviceStatusStore } from '../stores/deviceStatusStore'
import { shellLayoutStore, useShellLayout } from '../stores/shellLayoutStore'
import { themeStore, useTheme } from '../stores/themeStore'
import type { CSSProperties } from 'react'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { Workspace } from '../pages/workspace/WorkspacePage'
import { MethodsPage } from '../pages/methods/MethodsPage'
import { WorkspaceOpenMethodDialog } from '../pages/methods/OpenMethodDialog'
import type { MethodShortcutAction, MethodShortcutRequest } from '../pages/methods/methodShortcuts'
import { MigrationWorkspace } from '../pages/migration/MigrationWorkspace'
import { SpectrumViewerPage } from '../pages/spectra/SpectrumViewerPage'
import { hashPermissions } from '../stores/workbenchStore'
import { SampleQueuePage } from '../pages/sampleQueues/SampleQueuePage'
import { AboutPage } from '../pages/about/AboutPage'
import { UsersPage } from '../pages/auth/UsersPage'
import { AuditPage } from '../pages/auth/AuditPage'
import { ExtensionPage } from '../pages/extensions/ExtensionPage'

export function WorkspaceApp({ token, user, onLogout }: { token: string; user: AuthUser; onLogout: () => void }) {
  const theme = useTheme()
  const [target, setTarget] = useState<{ page: Page; key: string; view: string | null; spectrumFileGroup?: string; spectrumRecordId?: string }>({
    page: 'workspace',
    key: 'workspace.overview',
    view: null
  })
  const [dockHeight, setDockHeight] = useState(28)
  const { sidebarCollapsed, informationExpanded, focusMode } = useShellLayout(user.id)
  const canReadEvents = user.permissions.includes('runtime-events.read')
  const canReadDevices = user.permissions.includes('devices.read')
  const canWriteMethods = user.permissions.includes('methods.write')
  const [settings, setSettings] = useState<Settings | null>(null)
  const [pageActionsTarget, setPageActionsTarget] = useState<HTMLDivElement | null>(null)
  const [about, setAbout] = useState<About | null>(null)
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [health, setHealth] = useState<'online' | 'offline'>('offline')
  const [currentMethod, setCurrentMethod] = useState<CurrentMethodState | null>(null)
  const currentMethodRevision = useRef(0)
  const [methodDialogToken, setMethodDialogToken] = useState<string | null>(null)
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
  const permissionsKey = useMemo(() => hashPermissions(user.permissions), [user.permissions])
  const activeEntry =
    entries.find((entry) => entry.key === target.key) ?? entryForPage(entries, target.page, target.view)
  const page = target.page
  const spectroscopyLock = useRef<string | null>(null)
  const updateSpectroscopyLock = useCallback((reason: string | null) => { spectroscopyLock.current = reason }, [])
  const switchBlockedReason = useCallback(() => spectroscopyLock.current, [])
  const updateCurrentMethod = useCallback((method: CurrentMethodState) => {
    currentMethodRevision.current++
    setCurrentMethod(method)
  }, [])

  const loadData = useCallback(async (refreshDevices = false) => {
    const methodRevision = currentMethodRevision.current
    setLoading(true)
    if (canReadEvents) void runtimeEventsStore.refresh()
    if (refreshDevices && canReadDevices) void deviceStatusStore.refresh()
    try {
      const currentPromise = user.permissions.includes('methods.read')
        ? api.currentMethod(token)
        : Promise.resolve(null)
      const aboutPromise = user.permissions.includes('about.read') ? api.about(token) : Promise.resolve(null)
      const [nextHealth, nextSettings, nextAbout, nextCapabilities, nextCurrentMethod] =
        await Promise.all([
          api.health(),
          user.permissions.includes('settings.read') ? api.settings(token) : Promise.resolve(null),
          aboutPromise,
          api.capabilities(),
          currentPromise
        ])
      setHealth(nextHealth.status === 'ok' ? 'online' : 'offline')
      setSettings(nextSettings)
      setAbout(nextAbout)
      setCapabilities(nextCapabilities.capabilities)
      if (methodRevision === currentMethodRevision.current) setCurrentMethod(nextCurrentMethod)
    } catch {
      setHealth('offline')
    } finally {
      setLoading(false)
    }
  }, [token, user.permissions, canReadEvents, canReadDevices])

  useLayoutEffect(() => {
    void deviceStatusStore.startSession({ token, userId: user.id, canRead: canReadDevices })
    return () => deviceStatusStore.stopSession()
  }, [token, user.id, canReadDevices])
  useLayoutEffect(() => {
    runtimeEventsStore.startSession({ token, userId: user.id, canRead: canReadEvents })
    return () => runtimeEventsStore.stopSession()
  }, [token, user.id, canReadEvents])
  useLayoutEffect(() => {
    shellLayoutStore.startSession(user.id)
    return () => shellLayoutStore.stopSession()
  }, [user.id])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.altKey || event.metaKey) return
      if (event.shiftKey && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        if (!event.repeat) shellLayoutStore.toggleFocusMode()
      } else if (canReadEvents && !event.shiftKey && event.key === '`') {
        event.preventDefault()
        if (!event.repeat) shellLayoutStore.setInformationExpanded(!shellLayoutStore.getSnapshot().view.informationExpanded)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [canReadEvents])
  useEffect(() => {
    void loadData()
  }, [loadData, user.id])
  useEffect(() => {
    setMethodDialogToken(null)
  }, [token, canWriteMethods])
  useEffect(() => {
    const root = document.documentElement
    themeStore.setSettingsTheme(settings?.display.theme ?? null)
    root.dataset.density = settings?.display.density === 'compact' ? 'compact' : 'comfortable'
    root.dataset.timezone = settings?.time.timezone || 'Asia/Shanghai'
  }, [settings])
  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const handleNavigation = (entry: NavigationEntry, spectrumFileGroup?: string, spectrumRecordId?: string) => {
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
    setTarget({ page: entry.page, key: entry.key, view: entry.view, spectrumFileGroup, spectrumRecordId })
    return true
  }
  const handleMethodShortcut = (action: MethodShortcutAction) => {
    if (!user.permissions.includes('methods.write')) return
    const entry = entryForPage(entries, 'methods', 'conditions')
    if (entry && handleNavigation(entry)) setMethodShortcut({ id: ++shortcutId.current, action })
  }
  const handleSwitchMethod = () => {
    if (!canWriteMethods) return
    const blocked = switchBlockedReason()
    if (blocked) { showToast(blocked); return }
    if (page === 'methods') setMethodShortcut({ id: ++shortcutId.current, action: 'open' })
    else setMethodDialogToken(token)
  }
  const handleQuickNavigation = (entry: NavigationEntry) => {
    if (handleNavigation(entry) && entry.page === 'samples') setSampleEntryRequest(request => request + 1)
  }
  const handlePage = (nextPage: Page) => {
    const entry = entryForPage(entries, nextPage, nextPage === 'methods' ? 'lifecycle' : undefined)
    if (entry) handleNavigation(entry)
  }
  const viewSpectrumFile = (group: string, recordId?: string) => {
    const entry = entryForPage(entries, 'spectra')
    if (entry) handleNavigation(entry, group, recordId)
    else showToast('当前账号没有谱图查看权限')
  }
  const handleInternalView = (nextPage: Page, view: string) => {
    const entry = entryForPage(entries, nextPage, nextPage === 'analysis' ? undefined : view)
    if (entry) setTarget({ page: entry.page, key: entry.key, view })
  }

  return (
    <div
      className={`app-shell${canReadEvents ? ' with-runtime-messages' : ''}`}
      style={{ '--runtime-dock-height': `${canReadEvents ? dockHeight : 0}px` } as CSSProperties}
      data-testid="app-shell"
      data-theme={theme}
      data-density={settings?.display.density ?? 'comfortable'}
      data-focus-mode={focusMode}
    >
      <RenderProfilerProbe id="WorkspaceApp" />
      {health === 'offline' && !loading && !about && !capabilities.length ? (
        <ErrorPage onRetry={() => void loadData(true)} />
      ) : (
        <>
          <Sidebar
            activeEntry={activeEntry}
            entries={entries}
            onNavigate={handleNavigation}
            currentMethod={currentMethod}
            health={health}
            showStatusBar={settings?.display.show_status_bar !== false}
            collapsed={sidebarCollapsed}
            focusMode={focusMode}
            onToggleCollapsed={shellLayoutStore.toggleSidebar}
            onToast={showToast}
          />
          <main className="main-area">
            <Header
              activeEntry={activeEntry}
              extensionTitle={activeExtension?.title}
              onRefresh={() => void loadData(true)}
              loading={loading}
              onNavigate={handlePage}
              entries={entries}
              onNavigateEntry={handleQuickNavigation}
              onMethodShortcut={handleMethodShortcut}
              onSwitchMethod={handleSwitchMethod}
              user={user}
              currentMethod={currentMethod}
              theme={theme}
              onToggleTheme={themeStore.toggleTheme}
              focusMode={focusMode}
              onToggleFocusMode={shellLayoutStore.toggleFocusMode}
              onLogout={onLogout}
            />
            {canWriteMethods && methodDialogToken === token && (
              <WorkspaceOpenMethodDialog token={token} selectedId={currentMethod?.method_id ?? null}
                switchBlockedReason={switchBlockedReason} onCancel={() => setMethodDialogToken(null)}
                onOpened={method => {
                  updateCurrentMethod(method)
                  setMethodDialogToken(null)
                  showToast('当前方法已打开')
                }} />
            )}
            <div className="page-scroll-region">
            {activeEntry && !isSpectroscopyMode(page) && page !== 'analysis' && page !== 'extension' && <PageHeading entry={activeEntry} actionsRef={setPageActionsTarget} />}
            {page === 'workspace' && (
              <Workspace
                token={token}
                health={health}
                canClearEvents={user.permissions.includes('runtime-events.write')}
                canReadDevices={canReadDevices}
                currentMethod={currentMethod}
                capabilities={capabilities}
                entries={entries}
                onNavigate={handlePage}
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
                onCurrentMethodChange={updateCurrentMethod}
                switchBlockedReason={switchBlockedReason}
                onToast={showToast}
              />
            )}
            {page === 'migration' && <MigrationWorkspace token={token} currentUser={user} onToast={showToast} />}
            {page === 'spectra' && <SpectrumViewerPage userId={user.id} permissionsKey={permissionsKey}
              token={token} initialFileGroup={target.spectrumFileGroup} initialRecordId={target.spectrumRecordId}
              currentMethodVersionId={currentMethod?.referenced_version?.id}
              actionsTarget={pageActionsTarget} canExport={user.permissions.includes('spectra.export')} onToast={showToast} onClose={()=>handlePage('workspace')} />}
            {page === 'prepared-import' && <PreparedImportPage token={token} currentMethod={currentMethod}
              canWrite={user.permissions.includes('postprocessing.write')} onToast={showToast}
              onViewSpectra={viewSpectrumFile} />}
            {(page === 'postprocessing' || page === 'reports') && (
              <DataProcessingPage token={token} page={page} initialView={target.view}
                reportSource={reportSource} onReportSourceChange={setReportSource}
                permissions={user.permissions} onViewChange={(view) => handleInternalView('reports', view)} onToast={showToast} />
            )}
            {page === 'samples' && <SampleQueuePage token={token} onToast={showToast} entryRequest={sampleEntryRequest} />}
            {(page === 'acquisition' || page === 'mercury-calibration') && (
              <DeviceDebugPage token={token} permissions={user.permissions} settings={settings}
                initialView={page === 'mercury-calibration' ? 'alignment' : target.view}
                onSettingsChange={setSettings} onViewChange={view => handleInternalView('acquisition', view)} onToast={showToast} />
            )}
            {isSpectroscopyMode(page) && (
              <SpectroscopyWorkbench mode={page} view={page === 'dispersion' && target.view === 'curve' ? 'curve' : 'capture'} token={token} permissions={user.permissions} entries={entries}
                currentMethod={currentMethod} onNavigate={handleNavigation} onViewSpectra={viewSpectrumFile} onLockChange={updateSpectroscopyLock} onToast={showToast} />
            )}
            {page === 'evaporation-curves' && <EvaporationCurvesPage token={token} userId={user.id} permissionsKey={permissionsKey}
              currentMethodVersionId={currentMethod?.referenced_version?.id} actionsTarget={pageActionsTarget}
              canExport={user.permissions.includes('spectra.export')} onToast={showToast} onClose={()=>handlePage('workspace')} />}
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
                information={canReadEvents ? { expanded: informationExpanded, setExpanded: shellLayoutStore.setInformationExpanded } : undefined}
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
            {page === 'about' && (
              <AboutPage about={about} token={token} permissions={user.permissions} />
            )}
            {page === 'users' && <UsersPage token={token} currentUser={user} onToast={showToast} />}
            {page === 'audit' && <AuditPage token={token} />}
            {page === 'extension' && activeExtension && (
              <ExtensionPage token={token} extension={activeExtension} onToast={showToast} />
            )}
            </div>
            {canReadEvents && <MessagePanel key={user.id} userId={user.id} onHeightChange={setDockHeight}
              health={health} canReadDevices={canReadDevices} expanded={informationExpanded}
              onExpandedChange={shellLayoutStore.setInformationExpanded} />}
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
