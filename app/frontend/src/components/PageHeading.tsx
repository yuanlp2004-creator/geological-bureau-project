import type { NavigationEntry } from '../navigation'
import { FunctionIcon, iconForEntry } from './FunctionIcon'
import './page-heading.css'

export function PageHeading({ entry, actionsRef }: { entry: NavigationEntry; actionsRef?: (node: HTMLDivElement | null) => void }) {
  return <header className="app-page-heading" data-testid="page-heading">
    <div className="app-page-heading-inner">
      <div className="app-page-heading-title">
        <span className="app-page-heading-icon" aria-hidden="true"><FunctionIcon name={iconForEntry(entry)} size={26} /></span>
        <div className="app-page-heading-copy"><h1>{entry.label}</h1><p>{entry.description}</p></div>
      </div>
      <div ref={actionsRef} className="app-page-heading-actions" />
    </div>
  </header>
}
