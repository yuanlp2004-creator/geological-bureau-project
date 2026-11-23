import { useMemo, useState } from 'react'
import {
  Activity,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock3,
  Database,
  FlaskConical,
  Info,
  Layers3,
  Printer,
  Server,
  SlidersHorizontal,
} from 'lucide-react'
import { api, saveFile, type CurrentMethodState, type Health, type RuntimeEvent } from '../../api'
import { navigationAvailability, type NavigationEntry } from '../../navigation'
import { formatTime } from '../../components/dateFormat'
import { categoryLabel } from '../../components/eventLabels'
import { WorkspaceMessages } from '../../components/WorkspaceMessages'

const quickActions = [
  { key: 'methods.lifecycle', icon: SlidersHorizontal, label: '方法管理', detail: '版本、条件与当前方法' },
  { key: 'analysis-tests.samples', icon: ClipboardList, label: '预录样号', detail: '录入样号与重复次数', permission: 'samples.write' },
  { key: 'analysis-tests.acquisition', icon: FlaskConical, label: '样品摄谱', detail: '建立任务与采集谱带' },
  { key: 'analysis-tests.raw', icon: BarChart3, label: '样品分析', detail: '测量与结果计算' },
  { key: 'analysis-tests.spectra', icon: Activity, label: '谱图查看', detail: '查看已保存的谱带' },
  { key: 'data.reports', icon: Printer, label: '分析报告', detail: '建立、预览与导出', permission: 'reports.read' },
]

export function Workspace({
  token,
  health,
  canReadEvents,
  canClearEvents,
  events,
  currentMethod,
  moduleCount,
  entries,
  permissions,
  onNavigate,
  onEventsChange,
  onToast
}: {
  token: string
  health: Health | null
  canReadEvents: boolean
  canClearEvents: boolean
  events: RuntimeEvent[]
  currentMethod: CurrentMethodState | null
  moduleCount: number
  entries: NavigationEntry[]
  permissions: string[]
  onNavigate: (entry: NavigationEntry) => void
  onEventsChange: (events: RuntimeEvent[]) => void
  onToast: (message: string) => void
}) {
  const [eventFilter, setEventFilter] = useState('all')
  const [selected, setSelected] = useState<number[]>([])
  const filteredEvents = useMemo(
    () => (eventFilter === 'all' ? events : events.filter((event) => event.severity === eventFilter)),
    [eventFilter, events]
  )
  const selectAll = selected.length === filteredEvents.length && filteredEvents.length > 0
  const hasCurrentMethod = currentMethod?.method_id != null
  const databaseReady = health?.database === 'ok'
  const apiOnline = health !== null
  const isDesktop = '__TAURI__' in window
  const readiness = [
    {
      label: '数据存储', icon: Database, tone: 'green', ready: databaseReady,
      detail: health ? `SQLite schema v${health.schema_version}` : '等待数据库连接',
    },
    {
      label: 'API 服务', icon: Server, tone: 'blue', ready: apiOnline,
      detail: `FastAPI /api/v1 · ${apiOnline ? '在线' : '离线'}`,
    },
    {
      label: '模块清单', icon: Layers3, tone: 'violet', ready: moduleCount > 0,
      detail: `${moduleCount} 个模块已注册`,
    },
    {
      label: '运行方法', icon: SlidersHorizontal, tone: 'amber', ready: hasCurrentMethod,
      detail: hasCurrentMethod ? `${currentMethod.work_type} · 已发布` : '等待选择已发布方法',
    },
  ]
  const visibleActions = quickActions.flatMap((action) => {
    const entry = entries.find((item) => item.key === action.key)
    if (!entry || (action.permission && !permissions.includes(action.permission))) return []
    return [{ ...action, entry }]
  })

  const clearEvents = async () => {
    if (!canClearEvents) {
      onToast('当前账号只有运行消息读取权限')
      return
    }
    try {
      await api.clearLogs(token)
      onEventsChange([])
      setSelected([])
      onToast('运行消息已清空')
    } catch {
      onToast('清空消息失败')
    }
  }
  const copyEvents = async () => {
    const selectedEvents = filteredEvents.filter((event) => selected.includes(event.id))
    const content = (selectedEvents.length ? selectedEvents : filteredEvents)
      .map((event) => `[${formatTime(event.created_at)}] ${event.message}`)
      .join('\n')
    try {
      await navigator.clipboard.writeText(content)
      onToast('消息已复制到剪贴板')
    } catch {
      onToast('当前环境不支持剪贴板')
    }
  }
  const saveEvents = async () => {
    const content = filteredEvents
      .map((event) => `${event.created_at}\t${categoryLabel[event.category] ?? event.category}\t${event.message}`)
      .join('\n')
    try {
      const path = await saveFile(
        new Blob([content], { type: 'text/plain;charset=utf-8' }),
        `geospectrum-events-${new Date().toISOString().slice(0, 10)}.log`
      )
      onToast(path ? `消息日志已保存：${path}` : '已取消保存')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '消息日志保存失败')
    }
  }
  return (
    <div className="page-content workspace-page refined-page" data-testid="workspace">
      <section className="workspace-grid">
        <div className="primary-column">
          <section className="surface status-surface">
            <div className="surface-heading">
              <div>
                <span className="current-method-label">当前运行方法</span>
                <h2>{currentMethod?.title || '尚未选择运行方法'}</h2>
              </div>
              <span className={`ready-badge ${hasCurrentMethod ? '' : 'pending'}`}>
                {hasCurrentMethod ? <CheckCircle2 size={14} aria-hidden="true" /> : <Clock3 size={14} aria-hidden="true" />}
                {hasCurrentMethod ? `版本 ${currentMethod?.version}` : '等待选择'}
              </span>
            </div>
            <div className="readiness-grid">
              {readiness.map(({ label, icon: Icon, tone, detail, ready }) => {
                const StatusIcon = ready ? CheckCircle2 : Clock3
                return (
                  <div className="readiness-item" key={label}>
                    <div className="readiness-icon" data-tone={tone}><Icon size={16} aria-hidden="true" /></div>
                    <div><strong>{label}</strong><span>{detail}</span></div>
                    <StatusIcon className={ready ? 'check' : 'pending-icon'} size={15} aria-hidden="true" />
                  </div>
                )
              })}
            </div>
            <div className="surface-note">
              <Info size={15} aria-hidden="true" />
              <span>{hasCurrentMethod ? '样品摄谱与分析沿用当前运行方法。' : '请在方法管理中选择已发布的方法，再进入样品摄谱或分析。'}</span>
            </div>
          </section>
          <WorkspaceMessages
            events={events}
            filteredEvents={filteredEvents}
            selected={selected}
            setSelected={setSelected}
            selectAll={selectAll}
            setSelectAll={() => setSelected(selectAll ? [] : filteredEvents.map((event) => event.id))}
            filter={eventFilter}
            setFilter={setEventFilter}
            onClear={clearEvents}
            onCopy={copyEvents}
            onSave={saveEvents}
          />
        </div>
        <div className="secondary-column">
          {visibleActions.length > 0 && <section className="surface quick-surface">
            <div className="surface-heading"><h2>常用入口</h2></div>
            <div className="workspace-quick-grid">
              {visibleActions.map(({ key, icon: Icon, label, detail, entry }) => {
                const { disabled, reason } = navigationAvailability(entry, currentMethod)
                return <button key={key} type="button" className="quick-action" disabled={disabled} title={reason ?? undefined}
                  onClick={() => onNavigate(key === 'data.reports' ? { ...entry, view: 'reports' } : entry)}>
                  <span className="quick-icon"><Icon size={17} aria-hidden="true" /></span>
                  <span><strong>{label}</strong><small>{detail}</small></span>
                  <ChevronRight size={15} aria-hidden="true" />
                </button>
              })}
            </div>
          </section>}
          <section className="workspace-diagnostics" aria-label="运行概况">
            <div className="surface workspace-metric">
              <span>运行消息</span>
              <strong className="scientific-number">{canReadEvents ? events.length : '—'}</strong>
            </div>
            <div className="surface workspace-metric">
              <span>本地服务</span>
              <strong className={apiOnline ? 'check' : 'service-offline'}>{apiOnline ? '在线' : '离线'}</strong>
            </div>
          </section>
          <section className="surface protocol-surface" aria-label="服务通道">
            <div className="surface-heading"><h2>服务通道</h2></div>
            <div className="protocol-row">
              <strong>REST API</strong><code>127.0.0.1</code>
              <span className={apiOnline ? 'protocol-ok' : 'protocol-error'}>{apiOnline ? '在线' : '离线'}</span>
            </div>
            {canReadEvents && <div className="protocol-row">
              <strong>运行消息</strong><span className="scientific-number">1.5 秒刷新</span>
              <span className={apiOnline ? 'protocol-ok' : 'protocol-pending'}>{apiOnline ? '自动刷新' : '等待连接'}</span>
            </div>}
            <div className="protocol-row">
              <strong>运行环境</strong><span>{isDesktop ? 'Tauri 2' : '浏览器'}</span>
              <span className="protocol-environment">{isDesktop ? '桌面程序' : '浏览器预览'}</span>
            </div>
          </section>
        </div>
      </section>
    </div>
  )
}
