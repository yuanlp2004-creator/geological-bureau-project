import { useCallback, useEffect, useState } from 'react'
import type { Settings } from '../../api'
import { AcquisitionPage } from './AcquisitionPage'
import { MercuryCalibrationPage } from '../mercuryCalibration/MercuryCalibrationPage'
import { SoftwareParameters } from './SoftwareParameters'
import { DeviceParameters } from './DeviceParameters'
import './device-debug.css'

type Tab = 'software' | 'device' | 'alignment' | 'mercury'
type Props = {
  token: string
  permissions: string[]
  settings: Settings | null
  initialView: string | null
  onSettingsChange: (settings: Settings) => void
  onViewChange: (view: Tab) => void
  onToast: (message: string) => void
}

export function DeviceDebugPage({ token, permissions, settings, initialView, onSettingsChange, onViewChange, onToast }: Props) {
  const tabs: Array<{ id: Tab; label: string; allowed: boolean }> = [
    { id: 'software', label: '软件参数', allowed: permissions.includes('settings.read') },
    { id: 'device', label: '设备参数', allowed: permissions.includes('devices.read') },
    { id: 'alignment', label: '调试对中', allowed: permissions.includes('devices.read') },
    { id: 'mercury', label: '汞灯调试', allowed: permissions.includes('mercury-calibration.read') }
  ]
  const first = tabs.find(tab => tab.id === initialView && tab.allowed)?.id ?? tabs.find(tab => tab.allowed)?.id ?? 'software'
  const [tab, setTab] = useState<Tab>(first)
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set([first]))
  const [actionsTarget, setActionsTarget] = useState<HTMLDivElement | null>(null)
  const [revision, setRevision] = useState(0)
  const onDeviceSaved = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => {
    if (!tabs.some(item => item.id === initialView && item.allowed)) return
    const next = initialView as Tab
    setTab(next)
    setVisited(current => new Set([...current, next]))
  }, [initialView])
  const choose = (next: Tab) => {
    if (next === tab) return
    setTab(next)
    setVisited(current => new Set([...current, next]))
    onViewChange(next)
  }
  return <div className="page-content device-debug-page refined-page remaining-page" data-testid="device-debug-page">
    
    <div className="device-debug-toolbar"><nav className="device-debug-tabs" role="tablist" aria-label="设备调试功能">
      {tabs.filter(item => item.allowed).map(item => <button key={item.id} type="button" role="tab"
        id={`device-tab-${item.id}`} aria-controls={`device-panel-${item.id}`} aria-selected={tab === item.id}
        className={tab === item.id ? 'active' : ''} onClick={() => choose(item.id)}>{item.label}</button>)}
    </nav><div ref={setActionsTarget} className="device-debug-actions" /></div>
    {tabs.filter(item => item.allowed && visited.has(item.id)).map(item => <div className="device-debug-panel" key={item.id}
      id={`device-panel-${item.id}`} role="tabpanel" aria-labelledby={`device-tab-${item.id}`} hidden={tab !== item.id}>
      {item.id === 'software' && settings && <SoftwareParameters token={token} settings={settings} canWrite={permissions.includes('settings.write')}
        onSettingsChange={onSettingsChange} onToast={onToast} actionsTarget={actionsTarget} active={tab === item.id} />}
      {item.id === 'device' && <DeviceParameters token={token} canWrite={permissions.includes('devices.write')} onSaved={onDeviceSaved} onToast={onToast} actionsTarget={actionsTarget} active={tab === item.id} />}
      {item.id === 'alignment' && <AcquisitionPage embedded token={token} canWrite={permissions.includes('devices.write')}
        canExecute={permissions.includes('devices.execute')} revision={revision} actionsTarget={actionsTarget} active={tab === item.id} onToast={onToast} />}
      {item.id === 'mercury' && <MercuryCalibrationPage embedded token={token} canWrite={permissions.includes('mercury-calibration.write')}
        canExecute={permissions.includes('mercury-calibration.execute')} actionsTarget={actionsTarget} active={tab === item.id} onToast={onToast} />}
    </div>)}
  </div>
}
