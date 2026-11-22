import type { NavigationEntry } from '../navigation'
import {
  Activity, BarChart3, ChartSpline, CircleHelp, ClipboardList, DatabaseBackup, Droplets, FileInput,
  FilePlus, FlaskConical, FolderOpen, History, Info, LayoutDashboard, Lightbulb, ListTree, Printer, RotateCw,
  Save, Sigma, SlidersHorizontal, Usb, Users, Waves, Wrench, type LucideIcon
} from 'lucide-react'
import { iconForEntry, type FunctionIconName } from './FunctionIcon'
import './page-heading.css'

const headingIcons: Record<FunctionIconName, LucideIcon> = {
  'new-method': FilePlus,
  'open-method': FolderOpen,
  'save-as': Save,
  conditions: SlidersHorizontal,
  lines: ListTree,
  samples: ClipboardList,
  acquisition: FlaskConical,
  analysis: BarChart3,
  print: Printer,
  'dispersion-acquisition': FlaskConical,
  'evaporation-acquisition': Droplets,
  'dispersion-curve': ChartSpline,
  'evaporation-curve': Waves,
  spectra: Activity,
  workspace: LayoutDashboard,
  users: Users,
  audit: History,
  'import-methods': FileInput,
  'import-spectra': FileInput,
  'import-results': FileInput,
  devices: Usb,
  rotation: RotateCw,
  mercury: Lightbulb,
  recalculate: Sigma,
  maintenance: DatabaseBackup,
  help: CircleHelp,
  tools: Wrench,
  about: Info
}

export function PageHeading({ entry, actionsRef }: { entry: NavigationEntry; actionsRef?: (node: HTMLDivElement | null) => void }) {
  const Icon = headingIcons[iconForEntry(entry)]
  return <header className="app-page-heading" data-testid="page-heading">
    <div className="app-page-heading-inner">
      <div className="app-page-heading-title">
        <span className="app-page-heading-icon" aria-hidden="true"><Icon className="page-title-glyph" size={22} strokeWidth={1.75} aria-hidden="true" /></span>
        <div className="app-page-heading-copy"><h1>{entry.label}</h1></div>
      </div>
      <div ref={actionsRef} className="app-page-heading-actions" />
    </div>
  </header>
}
