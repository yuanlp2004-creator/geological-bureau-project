import { useMemo, useState } from 'react'
import {
  Activity,
  Archive,
  Check,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Clock3,
  Database,
  Gauge,
  Info,
  MessageSquareText,
  ShieldCheck,
  SlidersHorizontal,
  SquareTerminal,
} from 'lucide-react'
import { api, saveFile, type Capability, type CurrentMethodState, type RuntimeEvent } from '../../api'
import { type NavigationEntry, type Page } from '../../navigation'
import { formatTime } from '../../components/dateFormat'
import { categoryLabel } from '../../components/eventLabels'
import { WorkspaceMessages } from '../../components/WorkspaceMessages'
import { FunctionIcon, type FunctionIconName } from '../../components/FunctionIcon'

export function Workspace({
  token,
  health,
  canClearEvents,
  events,
  currentMethod,
  capabilities,
  entries,
  onNavigate,
  onEventsChange,
  onToast
}: {
  token: string
  health: 'online' | 'offline'
  canClearEvents: boolean
  events: RuntimeEvent[]
  currentMethod: CurrentMethodState | null
  capabilities: Capability[]
  entries: NavigationEntry[]
  onNavigate: (page: Page) => void
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
  const hasPage = (page: Page) => entries.some((entry) => entry.page === page)
  const hasQuickAccess = hasPage('methods') || hasPage('settings') || hasPage('about')
  const isDesktop = '__TAURI__' in window

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
                {hasCurrentMethod ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}
                {hasCurrentMethod ? `版本 ${currentMethod?.version}` : '等待选择'}
              </span>
            </div>
            <div className="readiness-grid">
              <ReadinessItem
                icon={Database}
                title="数据存储"
                detail={health === 'online' ? '本地数据库已连接' : '等待本地服务连接'}
                done={health === 'online'}
              />
              <ReadinessItem
                icon={SquareTerminal}
                title="API 服务"
                detail={health === 'online' ? 'FastAPI /api/v1 · 在线' : 'FastAPI /api/v1 · 离线'}
                done={health === 'online'}
              />
              <ReadinessItem
                icon={Archive}
                title="模块清单"
                detail={`${capabilities.length} 个模块已注册`}
                done={capabilities.length > 0}
              />
              <ReadinessItem
                icon={SlidersHorizontal}
                title="运行方法"
                detail={hasCurrentMethod ? `${currentMethod?.work_type} · 已发布` : '打开已发布方法后就绪'}
                done={hasCurrentMethod}
              />
            </div>
            <div className="surface-note">
              <Info size={16} />
              <span>当前运行使用已发布版本。修改条件时保存草稿，验证并发布后再切换。</span>
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
        <aside className="secondary-column">
          {hasQuickAccess && (
            <section className="surface quick-surface">
              <div className="surface-heading">
                <div>
                  <h2>常用入口</h2>
                </div>
                <Clipboard size={16} />
              </div>
              {hasPage('methods') && (
                <QuickAction
                  icon="conditions"
                  label="方法管理"
                  detail="版本、条件与当前方法"
                  onClick={() => onNavigate('methods')}
                />
              )}
              {hasPage('settings') && (
                <QuickAction
                  icon="settings"
                  label="软件设置"
                  detail="目录、显示、日志与打印"
                  onClick={() => onNavigate('settings')}
                />
              )}
              {hasPage('about') && (
                <QuickAction
                  icon="about"
                  label="关于软件"
                  detail="软件名称、版本和版权"
                  onClick={() => onNavigate('about')}
                />
              )}
            </section>
          )}
          <section className="stat-grid workspace-diagnostics" aria-label="运行概况">
            <StatCard
              icon={Database}
              label="数据存储"
              value={health === 'online' ? '已连接' : '未连接'}
              note="本地数据库"
              tone={health === 'online' ? 'blue' : 'amber'}
            />
            <StatCard
              icon={ShieldCheck}
              label="注册模块"
              value={String(capabilities.length)}
              note={capabilities.length ? '应用功能已载入' : '等待功能载入'}
              tone={capabilities.length ? 'green' : 'amber'}
            />
            <StatCard
              icon={MessageSquareText}
              label="运行消息"
              value={String(events.length)}
              note="最近 500 条以内"
              tone="amber"
            />
            <StatCard
              icon={Gauge}
              label="本地服务"
              value={health === 'online' ? '在线' : '离线'}
              note="随机端口握手"
              tone="violet"
            />
          </section>
          <section className="surface protocol-surface">
            <div className="surface-heading">
              <div>
                <h2>服务通道</h2>
              </div>
              <Activity size={16} />
            </div>
            <div className="protocol-row">
              <span>REST API</span>
              <code>127.0.0.1</code>
              <span className={health === 'online' ? 'protocol-ok' : 'protocol-error'}>
                {health === 'online' ? '在线' : '离线'}
              </span>
            </div>
            <div className="protocol-row">
              <span>运行消息</span>
              <code>1.5 秒刷新</code>
              <span className={health === 'online' ? 'protocol-ok' : 'protocol-error'}>
                {health === 'online' ? '在线' : '离线'}
              </span>
            </div>
            <div className="protocol-row">
              <span>运行环境</span>
              <code>{isDesktop ? 'Tauri 2' : '浏览器'}</code>
              <span className="protocol-ok">{isDesktop ? '桌面程序' : '浏览器预览'}</span>
            </div>
          </section>
        </aside>
      </section>
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  note,
  tone
}: {
  icon: typeof Database
  label: string
  value: string
  note: string
  tone: string
}) {
  return (
    <div className={`stat-card ${tone}`}>
      <div className="stat-icon">
        <Icon size={17} />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{note}</small>
      </div>
    </div>
  )
}

function ReadinessItem({
  icon: Icon,
  title,
  detail,
  done = false
}: {
  icon: typeof Database
  title: string
  detail: string
  done?: boolean
}) {
  return (
    <div className="readiness-item">
      <div className={`readiness-icon ${done ? 'done' : 'pending'}`}>
        <Icon size={16} />
      </div>
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      {done ? <Check size={15} className="check" /> : <Clock3 size={15} className="pending-icon" />}
    </div>
  )
}

function QuickAction({
  icon,
  label,
  detail,
  onClick
}: {
  icon: FunctionIconName
  label: string
  detail: string
  onClick: () => void
}) {
  return (
    <button className="quick-action" onClick={onClick}>
      <span className="quick-icon">
        <FunctionIcon name={icon} />
      </span>
      <span>
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
      <ChevronRight size={15} />
    </button>
  )
}
