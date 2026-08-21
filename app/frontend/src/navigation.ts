import type { Capability, CurrentMethodState } from './api'

export type Page =
  | 'workspace' | 'methods' | 'migration' | 'spectrum-migration' | 'result-migration'
  | 'spectra' | 'postprocessing' | 'samples' | 'acquisition' | 'dispersion'
  | 'sample-acquisition' | 'hardware-acquisition' | 'mercury-calibration' | 'analysis'
  | 'reports' | 'maintenance' | 'help' | 'settings' | 'about' | 'users' | 'audit'
  | 'extension'

export type NavigationGroupId = 'workspace' | 'methods' | 'conditions' | 'analysis-tests' | 'data' | 'tools' | 'system' | 'help'
export type NavigationContext = 'none' | 'current_method' | 'current_method_exp_seg' | 'page_scoped'
export type NavigationStatus = 'normal' | 'deferred_external' | 'test_only'

export type NavigationEntry = {
  key: string
  group: NavigationGroupId
  section_label: string
  label: string
  description: string
  page: Page
  view: string | null
  required_any: string[]
  order: number
  status: NavigationStatus
  required_context: NavigationContext
  extension?: Capability
}

export type NavigationGroup = {
  id: NavigationGroupId
  label: string
  order: number
  description: string
}

export type NavigationAvailability = {
  disabled: boolean
  reason: string | null
}

export const navigationGroups: NavigationGroup[] = [
  { id: 'workspace', label: '工作台', order: 10, description: '运行状态与常用操作' },
  { id: 'methods', label: '光谱方法', order: 20, description: '方法文件与输出设置' },
  { id: 'conditions', label: '分析条件', order: 30, description: '当前方法的测量与计算条件' },
  { id: 'analysis-tests', label: '分析测试', order: 40, description: '准备、摄谱、查看、分析与质控' },
  { id: 'data', label: '数据处理', order: 50, description: '全时、重算、矩阵与报告' },
  { id: 'tools', label: '工具', order: 60, description: '设备校准与旧版迁移' },
  { id: 'system', label: '系统管理', order: 70, description: '设置、维护、身份与审计' },
  { id: 'help', label: '帮助', order: 80, description: '离线帮助与诊断信息' },
]

const validGroups = new Set(navigationGroups.map((group) => group.id))

export function navigationEntries(capabilities: Capability[], permissions: string[]): NavigationEntry[] {
  const keys = new Set<string>()
  const entries: NavigationEntry[] = []
  for (const capability of capabilities) {
    for (const raw of capability.navigation_entries ?? []) {
      if (!validGroups.has(raw.group) || keys.has(raw.key)) continue
      if (!raw.required_any.some((permission) => permissions.includes(permission))) continue
      keys.add(raw.key)
      entries.push({ ...raw, page: raw.page as Page })
    }
    if (capability.key.startsWith('s21-') && capability.permissions.every((permission) => permissions.includes(permission))) {
      const key = `system.extension.${capability.key}`
      keys.add(key)
      entries.push({
        key,
        group: 'system',
        section_label: '扩展',
        label: capability.title,
        description: '仅测试构建启用的模块清单扩展',
        page: 'extension',
        view: null,
        required_any: capability.permissions,
        order: 90,
        status: 'test_only',
        required_context: 'none',
        extension: capability,
      })
    }
  }
  return entries.sort((left, right) => left.order - right.order || left.key.localeCompare(right.key))
}

function currentMethodUsesFullInterval(currentMethod: CurrentMethodState | null): boolean {
  const conditions = currentMethod?.referenced_version?.conditions
  return conditions?.angle_exposures?.some((exposure) => exposure.storage_mode === 'full_interval') === true
}

function currentMethodUnavailableReason(currentMethod: CurrentMethodState | null): string | null {
  if (currentMethod?.method_id == null) return '请先选择已发布的当前方法'
  if (currentMethod.status !== 'active' || currentMethod.action_state !== 'idle') {
    return '当前方法已暂停，请先恢复或选择其他已发布方法'
  }
  return null
}

export function navigationAvailability(entry: NavigationEntry, currentMethod: CurrentMethodState | null): NavigationAvailability {
  if (entry.required_context === 'current_method') {
    const reason = currentMethodUnavailableReason(currentMethod)
    if (reason) return { disabled: true, reason }
  }
  if (entry.required_context === 'current_method_exp_seg') {
    const reason = currentMethodUnavailableReason(currentMethod)
    if (reason) return { disabled: true, reason }
    if (!currentMethodUsesFullInterval(currentMethod)) return { disabled: true, reason: '当前方法未启用全时保存模式' }
  }
  return { disabled: false, reason: null }
}

export function entryForPage(entries: NavigationEntry[], page: Page, preferredView?: string | null): NavigationEntry | undefined {
  return entries.find((entry) => entry.page === page && (preferredView == null || entry.view === preferredView))
    ?? entries.find((entry) => entry.page === page)
}

export function groupedNavigation(entries: NavigationEntry[]): Array<NavigationGroup & { entries: NavigationEntry[] }> {
  return navigationGroups
    .map((group) => ({ ...group, entries: entries.filter((entry) => entry.group === group.id) }))
    .filter((group) => group.entries.length > 0)
}
