import type { NavigationEntry } from '../navigation'

const iconUrls = {
  'new-method': new URL('../assets/toolbar/new-method.png', import.meta.url).href,
  'open-method': new URL('../assets/toolbar/open-method.png', import.meta.url).href,
  'save-as': new URL('../assets/toolbar/save-as.png', import.meta.url).href,
  conditions: new URL('../assets/toolbar/conditions.png', import.meta.url).href,
  lines: new URL('../assets/toolbar/lines.png', import.meta.url).href,
  samples: new URL('../assets/toolbar/samples.png', import.meta.url).href,
  acquisition: new URL('../assets/toolbar/acquisition.png', import.meta.url).href,
  analysis: new URL('../assets/toolbar/analysis.png', import.meta.url).href,
  print: new URL('../assets/menu/print.png', import.meta.url).href,
  'dispersion-acquisition': new URL('../assets/menu/dispersion-acquisition.png', import.meta.url).href,
  'evaporation-acquisition': new URL('../assets/menu/evaporation-acquisition.png', import.meta.url).href,
  'dispersion-curve': new URL('../assets/menu/dispersion-curve.png', import.meta.url).href,
  'evaporation-curve': new URL('../assets/menu/evaporation-curve.png', import.meta.url).href,
  spectra: new URL('../assets/menu/spectra.png', import.meta.url).href,
  workspace: new URL('../assets/menu/workspace.png', import.meta.url).href,
  settings: new URL('../assets/menu/settings.png', import.meta.url).href,
  users: new URL('../assets/menu/users.png', import.meta.url).href,
  audit: new URL('../assets/menu/audit.png', import.meta.url).href,
  'import-methods': new URL('../assets/menu/import-methods.png', import.meta.url).href,
  'import-spectra': new URL('../assets/menu/import-spectra.png', import.meta.url).href,
  'import-results': new URL('../assets/menu/import-results.png', import.meta.url).href,
  devices: new URL('../assets/menu/devices.png', import.meta.url).href,
  rotation: new URL('../assets/menu/rotation.png', import.meta.url).href,
  mercury: new URL('../assets/menu/mercury.png', import.meta.url).href,
  recalculate: new URL('../assets/menu/recalculate.png', import.meta.url).href,
  maintenance: new URL('../assets/menu/maintenance.png', import.meta.url).href,
  help: new URL('../assets/menu/help.png', import.meta.url).href,
  tools: new URL('../assets/menu/tools.png', import.meta.url).href,
  about: new URL('../assets/brand/geospectrum.png', import.meta.url).href
}

export type FunctionIconName = keyof typeof iconUrls

// One presentation mapping keeps menu, toolbar and home shortcuts consistent.
export const navigationEntryIcons: Readonly<Record<string, FunctionIconName>> = {
  'workspace.overview': 'workspace',
  'methods.lifecycle': 'conditions',
  'methods.lines': 'lines',
  'methods.print-preview': 'print',
  'analysis-tests.samples': 'samples',
  'analysis-tests.dispersion': 'dispersion-acquisition',
  'analysis-tests.dispersion-curves': 'dispersion-curve',
  'analysis-tests.evaporation': 'evaporation-acquisition',
  'analysis-tests.acquisition': 'acquisition',
  'analysis-tests.evaporation-curves': 'evaporation-curve',
  'analysis-tests.spectra': 'spectra',
  'analysis-tests.hardware': 'rotation',
  'analysis-tests.raw': 'analysis',
  'data.recalculate': 'recalculate',
  'data.reports': 'print',
  'tools.devices': 'devices',
  'tools.mercury': 'mercury',
  'tools.legacy-methods': 'import-methods',
  'tools.legacy-spectra': 'import-spectra',
  'tools.legacy-results': 'import-results',
  'system.settings': 'settings',
  'system.maintenance': 'maintenance',
  'system.users': 'users',
  'system.audit': 'audit',
  'help.offline': 'help',
  'help.about': 'about'
}

export function iconForEntry(entry: NavigationEntry): FunctionIconName {
  return navigationEntryIcons[entry.key] ?? 'tools'
}

export function FunctionIcon({ name, size = 24, className = '' }: {
  name: FunctionIconName
  size?: number
  className?: string
}) {
  return <img className={`function-icon ${className}`} data-icon={name} src={iconUrls[name]} width={size} height={size}
    alt="" aria-hidden="true" draggable={false} />
}
