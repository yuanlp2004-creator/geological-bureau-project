import { useCallback, useEffect, useState } from 'react'
import type { Settings, DeviceProfile } from '../../api'
import { AcquisitionPage } from './AcquisitionPage'
import { SoftwareParameters } from './SoftwareParameters'
import { DeviceParameters } from './DeviceParameters'
import { DeviceConnection } from './DeviceConnection'
import { hardwareLockStore } from '../../stores/hardwareLockStore'
import './device-debug.css'

type Tab = 'software' | 'device' | 'alignment' | 'connection'
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
    { id: 'connection', label: '设备连接', allowed: permissions.includes('devices.read') },
    { id: 'alignment', label: '调试对中', allowed: permissions.includes('devices.read') }
  ]
  const requestedView = initialView === 'mercury' ? 'alignment' : initialView ?? tabs.find(item => item.allowed)?.id
  const first = tabs.find(tab => tab.id === requestedView && tab.allowed)?.id ?? tabs.find(tab => tab.allowed)?.id ?? 'software'
  const [tab, setTab] = useState<Tab>(first)
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set([first]))
  const [actionsTarget, setActionsTarget] = useState<HTMLDivElement | null>(null)
  const [revision, setRevision] = useState(0)
  const [profile, setProfile] = useState<DeviceProfile | null>(null)
  const onDeviceSaved = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => {
    if (!tabs.some(item => item.id === requestedView && item.allowed)) return
    const next = requestedView as Tab
    setTab(next)
    setVisited(current => new Set([...current, next]))
  }, [requestedView])
  const choose = (next: Tab) => {
    if (next === tab) return
    const blocked = hardwareLockStore.blockedReason()
    if (blocked) { onToast(blocked); return }
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
      {item.id === 'device' && <DeviceParameters token={token} canWrite={permissions.includes('devices.write')} canExecute={permissions.includes('devices.execute')}
        handoffPurpose={permissions.includes('acquisition.execute') ? 'acquisition'
          : permissions.includes('dispersion.execute') ? 'dispersion'
          : permissions.includes('hardware-acquisition.execute') ? 'hardware-acquisition' : undefined}
        canWriteScreen={permissions.includes('settings.write')} canReadLayouts={permissions.includes('methods.read')}
        settings={settings} onSettingsChange={onSettingsChange} revision={revision} onSaved={onDeviceSaved} onProfileChange={setProfile} onToast={onToast} actionsTarget={actionsTarget} active={tab === item.id} />}
      {item.id === 'connection' && <DeviceConnection token={token} canWrite={permissions.includes('devices.write')} canExecute={permissions.includes('devices.execute')}
        active={tab === item.id} revision={revision} onSaved={onDeviceSaved} onProfileChange={setProfile} onConfigure={() => choose('device')} onToast={onToast} />}
      {item.id === 'alignment' && <AcquisitionPage token={token}
        canExecute={permissions.includes('devices.execute')} preferredProfileId={profile?.id} revision={revision} actionsTarget={actionsTarget}
        active={tab === item.id} onToast={onToast} />}
    </div>)}
  </div>
}
