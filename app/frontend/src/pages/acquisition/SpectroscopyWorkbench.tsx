import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChartSpline, FlaskConical, LockKeyhole } from 'lucide-react'
import type { CurrentMethodState } from '../../api'
import { navigationAvailability, type NavigationEntry } from '../../navigation'
import { DispersionPage } from '../dispersion/DispersionPage'
import { AcquisitionWorkspace } from './AcquisitionWorkspace'
import { SpectroscopySession, spectroscopyModes, type SpectroscopyMode } from './spectroscopySession'

type Props = {
  mode: SpectroscopyMode
  view?: 'capture' | 'curve'
  token: string
  permissions: string[]
  entries: NavigationEntry[]
  currentMethod: CurrentMethodState | null
  onNavigate: (entry: NavigationEntry) => void
  onViewSpectra: (group: string, recordId?: string) => void
  onLockChange: (reason: string | null) => void
  onToast: (message: string) => void
}

export function SpectroscopyWorkbench({ mode, view = 'capture', token, permissions, entries, currentMethod, onNavigate, onViewSpectra, onLockChange, onToast }: Props) {
  const [actionsTarget, setActionsTarget] = useState<HTMLDivElement | null>(null)
  const [visited, setVisited] = useState<SpectroscopyMode[]>([mode])
  const [locks, setLocks] = useState<Partial<Record<SpectroscopyMode, string | null>>>({})
  const [captureScreens, setCaptureScreens] = useState<Partial<Record<SpectroscopyMode, boolean>>>({})
  const reportScreen = useCallback((page: SpectroscopyMode, capture: boolean) => {
    setCaptureScreens(current => current[page] === capture ? current : { ...current, [page]: capture })
  }, [])
  const report = useCallback((page: SpectroscopyMode, reason: string | null) => {
    setLocks((current) => current[page] === reason ? current : { ...current, [page]: reason })
  }, [])
  const reason = Object.values(locks).find(Boolean) ?? null
  useEffect(() => { setVisited((current) => current.includes(mode) ? current : [...current, mode]) }, [mode])
  useLayoutEffect(() => {
    onLockChange(reason)
    return () => onLockChange(null)
  }, [reason, onLockChange])
  const selected = spectroscopyModes.find((item) => item.page === mode)!
  const headerRef = useRef<HTMLElement>(null)
  const lockRef = useRef<HTMLParagraphElement>(null)
  const HeadingIcon = view === 'curve' ? ChartSpline : FlaskConical
  const capturing = view === 'capture' && Boolean(captureScreens[mode])
  useLayoutEffect(() => {
    const header = headerRef.current
    const workbench = header?.parentElement
    if (!capturing || !header || !workbench) return
    const lock = lockRef.current
    const measure = () => {
      const height = header.getBoundingClientRect().height + (lock?.getBoundingClientRect().height ?? 0)
      workbench.style.setProperty('--capture-heading-height', height + 'px')
    }
    const observer = new ResizeObserver(measure)
    observer.observe(header)
    if (lock) observer.observe(lock)
    measure()
    return () => {
      observer.disconnect()
      workbench.style.removeProperty('--capture-heading-height')
    }
  }, [capturing, reason])
  const viewSpectra = (group: string, recordId?: string) => {
    if (reason) onToast(reason)
    else onViewSpectra(group, recordId)
  }
  return (
    <div className={`page-content spectroscopy-workbench refined-page remaining-page ${view === 'curve' ? 'spectroscopy-curve-workbench' : ''}`} data-testid="spectroscopy-workbench" data-mode={mode} data-view={view} data-stage={capturing ? 'capture' : 'tasks'}>
      <section ref={headerRef} className="spectroscopy-header">
        <div className="spectroscopy-heading">
          <span className="spectroscopy-icon"><HeadingIcon className="page-title-glyph" size={22} strokeWidth={1.75} aria-hidden="true" /></span>
          <div><h1>{view === 'curve' ? '色散曲线' : capturing ? selected.label : '建立摄谱'}</h1></div>
        </div>
        {view === 'capture' && !capturing && <nav className="spectroscopy-modes" aria-label="摄谱方式">
          {spectroscopyModes.map((item) => {
            const entry = entries.find((entry) => entry.page === item.page && entry.view !== 'curve')
            if (!entry) return null
            const availability = navigationAvailability(entry, currentMethod)
            const disabledReason = item.page === mode ? null : reason || availability.reason
            return <button key={item.page} type="button" aria-current={item.page === mode ? 'page' : undefined}
              disabled={Boolean(disabledReason)} title={disabledReason ?? item.description}
              onClick={() => { if (item.page !== mode) onNavigate(entry) }}>{item.label}</button>
          })}
        </nav>}
        <div className="spectroscopy-page-actions"><div ref={setActionsTarget} className="page-file-actions-slot"/>{view === 'curve' && <button className="secondary-button" disabled={Boolean(reason)} onClick={() => {
          const entry = entries.find((entry) => entry.page === 'dispersion' && entry.view !== 'curve')
          if (entry) onNavigate(entry)
        }}>返回色散摄谱</button>}</div>
      </section>
      {reason && <p ref={lockRef} className="spectroscopy-lock" role="status"><LockKeyhole size={14} />{reason}</p>}
      <SpectroscopySession.Provider value={report}>
        {spectroscopyModes.filter((item) => item.page === mode || visited.includes(item.page)).map((item) => (
          <div key={item.page} className="spectroscopy-mode-panel" hidden={item.page !== mode}>
            {item.page === 'dispersion' ? (
              <DispersionPage token={token} actionsTarget={item.page === mode ? actionsTarget : undefined} onCaptureChange={reportScreen} view={view} canWrite={permissions.includes('dispersion.write')} canExport={permissions.includes('spectra.export')}
                onViewSpectra={viewSpectra}
                onCloseCurve={()=>{const entry=entries.find(entry=>entry.page==='dispersion'&&entry.view!=='curve');if(entry&&!reason)onNavigate(entry)}}
                canReadMethods={permissions.includes('methods.read')} canExecute={permissions.includes('dispersion.execute')} onToast={onToast} />
            ) : (
              <AcquisitionWorkspace token={token} actionsTarget={item.page === mode ? actionsTarget : undefined} onCaptureChange={reportScreen} taskKind={item.page === 'sample-acquisition' ? 'sample' : 'evaporation'}
                currentMethodKey={currentMethod?.method_id && currentMethod.version ? `${currentMethod.method_id}:${currentMethod.version}` : undefined}
                canWrite={permissions.includes('acquisition.write')} canExecute={permissions.includes('acquisition.execute')}
                canExport={permissions.includes('spectra.read') && permissions.includes('spectra.export')}
                canReadSpectra={permissions.includes('spectra.read')}
                canReadMethods={permissions.includes('methods.read')}
                canWriteSamples={permissions.includes('samples.write')}
                onViewSpectra={viewSpectra}
                onOpenSamples={permissions.includes('samples.read') ? () => {
                  const entry = entries.find(entry => entry.key === 'analysis-tests.samples')
                  if (entry && !reason) onNavigate(entry)
                } : undefined} onToast={onToast} />
            )}
          </div>
        ))}
      </SpectroscopySession.Provider>
    </div>
  )
}
