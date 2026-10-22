import type { CurrentMethodState } from '../api'
import { navigationAvailability, type NavigationEntry } from '../navigation'
import type { MethodShortcutAction } from '../pages/methods/methodShortcuts'
import { FunctionIcon, type FunctionIconName } from '../components/FunctionIcon'

type Shortcut = {
  name: string
  hint: string
  icon: FunctionIconName
  page: NavigationEntry['page']
  view?: string
  action?: MethodShortcutAction
}

// Image indices and meanings come from FmMain.dfm / AcmMain.ActionBars.
const groups: { name: string; items: Shortcut[] }[] = [
  { name: '方法操作', items: [
    { name: '新建方法', hint: '填写名称，建立新方法', icon: 'new-method', page: 'methods', action: 'create' },
    { name: '打开方法', hint: '选择并载入方法，设为当前运行方法', icon: 'open-method', page: 'methods', action: 'open' },
    { name: '方法另存为', hint: '将选中的方法保存为副本', icon: 'save-as', page: 'methods', action: 'copy' }
  ] },
  { name: '参数设置', items: [
    { name: '方法参数', hint: '查看与编辑方法条件', icon: 'conditions', page: 'methods', view: 'conditions' },
    { name: '分析谱线', hint: '设置谱线、内标、峰值与标准点', icon: 'lines', page: 'methods', view: 'lines' }
  ] },
  { name: '样品流程', items: [
    { name: '预录样号', hint: '准备样品队列与重复次数', icon: 'samples', page: 'samples' },
    { name: '样品摄谱', hint: '进入摄谱工作区，核对条件后开始采集', icon: 'acquisition', page: 'sample-acquisition' },
    { name: '样品分析', hint: '打开分析批次、曲线与样品结果', icon: 'analysis', page: 'analysis' }
  ] }
]

export function QuickAccessBar({ entries, permissions, currentMethod, activeEntry, onNavigate, onMethodShortcut }: {
  entries: NavigationEntry[]
  permissions: string[]
  currentMethod: CurrentMethodState | null
  activeEntry?: NavigationEntry
  onNavigate: (entry: NavigationEntry) => void
  onMethodShortcut: (action: MethodShortcutAction) => void
}) {
  const visibleGroups = groups.map(group => ({ ...group, items: group.items.flatMap(shortcut => {
    const entry = entries.find(item => item.page === shortcut.page &&
      (shortcut.page !== 'methods' || item.view === (shortcut.view ?? 'conditions')))
    if (!entry || (shortcut.action && !permissions.includes('methods.write'))) return []
    return [{ shortcut, entry }]
  }) })).filter(group => group.items.length > 0)
  if (visibleGroups.length === 0) return null
  return (
    <nav className="quick-access-bar" aria-label="常用快捷方式">
      {visibleGroups.map(group => (
          <div className="quick-access-group" role="group" aria-label={group.name} key={group.name}>
            {group.items.map(({ shortcut, entry }) => {
              const availability = navigationAvailability(entry, currentMethod)
              return (
                <span key={shortcut.name} title={`${shortcut.name} · ${availability.reason ?? shortcut.hint}`}>
                  <button type="button" className="quick-access-button" aria-label={shortcut.name}
                    disabled={availability.disabled}
                    aria-current={!shortcut.action && activeEntry?.key === entry.key ? 'page' : undefined}
                    onClick={() => shortcut.action ? onMethodShortcut(shortcut.action) : onNavigate(entry)}>
                    <FunctionIcon name={shortcut.icon} size={20} />
                  </button>
                </span>
              )
            })}
          </div>
        ))}
    </nav>
  )
}
