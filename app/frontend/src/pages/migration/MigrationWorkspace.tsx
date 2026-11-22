import { useState, type KeyboardEvent } from 'react'
import type { AuthUser } from '../../api'
import { LegacyMigrationPage } from './LegacyMigrationPage'
import { SpectrumMigrationPage } from './SpectrumMigrationPage'
import { ResultMigrationPage } from './ResultMigrationPage'
import './migration.css'

const migrationTabs = [
  { id: 'methods', label: '方法与配置', permission: 'migration.read', Panel: LegacyMigrationPage },
  { id: 'spectra', label: '谱图数据', permission: 'spectrum-migration.read', Panel: SpectrumMigrationPage },
  { id: 'results', label: '分析结果', permission: 'result-migration.read', Panel: ResultMigrationPage }
] as const

type MigrationTab = typeof migrationTabs[number]['id']
type Props = { token: string; currentUser: AuthUser; onToast: (message: string) => void }

export function MigrationWorkspace(props: Props) {
  const tabs = migrationTabs.filter(({ permission }) => props.currentUser.permissions.includes(permission))
  const [selected, setSelected] = useState<MigrationTab | undefined>(tabs[0]?.id)
  const [visited, setVisited] = useState<MigrationTab[]>(() => tabs.length ? [tabs[0].id] : [])
  const active = tabs.find(({ id }) => id === selected)?.id ?? tabs[0]?.id

  const select = (id: MigrationTab) => {
    setSelected(id)
    setVisited(current => current.includes(id) ? current : [...current, id])
  }

  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number
    switch (event.key) {
      case 'ArrowLeft': next = (index + tabs.length - 1) % tabs.length; break
      case 'ArrowRight': next = (index + 1) % tabs.length; break
      case 'Home': next = 0; break
      case 'End': next = tabs.length - 1; break
      default: return
    }
    event.preventDefault()
    select(tabs[next].id)
    event.currentTarget.parentElement?.querySelectorAll('button')[next]?.focus()
  }

  return <div className="page-content migration-workspace refined-page remaining-page" data-testid="migration-workspace">
    <div className="migration-workspace-tabs" role="tablist" aria-label="旧数据类型">
      {tabs.map(({ id, label }, index) => <button key={id} id={`migration-tab-${id}`} type="button" role="tab"
        aria-controls={`migration-panel-${id}`} aria-selected={active === id} tabIndex={active === id ? 0 : -1}
        onClick={() => select(id)} onKeyDown={event => handleTabKey(event, index)}>{label}</button>)}
    </div>
    {tabs.map(({ id, Panel }) => <div key={id} id={`migration-panel-${id}`} role="tabpanel"
      aria-labelledby={`migration-tab-${id}`} hidden={active !== id}>
      {(active === id || visited.includes(id)) && <Panel {...props} />}
    </div>)}
  </div>
}
