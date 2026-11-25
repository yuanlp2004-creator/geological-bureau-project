import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronUp, CircleAlert } from 'lucide-react'
import type { RuntimeEvent } from '../api'
import { useDeviceStatus } from '../stores/deviceStatusStore'
import { runtimeEventsStore, useRuntimeEvents } from '../stores/runtimeEventsStore'
import { shellLayoutStore, useLastSeenEventId } from '../stores/shellLayoutStore'
import { unreadAlerts } from '../stores/shellLayoutStoreCore'
import { RenderProfiler } from './RenderProfiler'
import { formatTime } from './dateFormat'
import { categoryLabel, severityLabel } from './eventLabels'
import './message-panel.css'

type Channel = 'general' | 'communication'
type Level = 'detailed' | 'default' | 'brief'
const channelOf = (event: RuntimeEvent): Channel => event.details?.channel === 'communication' ? 'communication' : 'general'
const limitHeight = (height: number) => Math.round(Math.max(120, Math.min(height, 360, window.innerHeight / 2)))
const sourceLabel: Record<string, string> = {
  devices: '设备调试', acquisition: '样品采集', analysis: '样品分析', dispersion: '色散采集',
  hardware: '转角采集', mercury: '汞灯校正'
}
const levelHint = '精简：完成、警告和错误；默认：普通运行信息；详细：全部记录及来源、任务等细节。仅影响显示。'

function eventContext(event: RuntimeEvent) {
  const details = event.details ?? {}
  const parts = [categoryLabel[event.category] ?? event.category, severityLabel[event.severity]]
  if (typeof details.source === 'string') parts.push(sourceLabel[details.source] ?? details.source)
  if (typeof details.task_id === 'number') parts.push(`任务 ${details.task_id}`)
  if (typeof details.code === 'string' && details.code) parts.push(details.code)
  if (typeof details.state === 'string' && details.state) parts.push(`状态 ${details.state}`)
  if (typeof details.port === 'number') parts.push(`COM${details.port}`)
  if (typeof details.repeat_index === 'number') parts.push(`第 ${details.repeat_index + 1} 轮重复`)
  if (typeof details.frame_index === 'number' && details.event_type !== 'ccd_transfer') parts.push(`帧 ${details.frame_index}`)
  return parts.join(' · ')
}

function preferences(key: string) {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? '{}')
    return {
      legacyCollapsed: value.layoutVersion !== 2 || value.collapsed !== false,
      height: limitHeight(Number.isFinite(value.height) ? value.height : 184),
      level: (['detailed', 'default', 'brief'].includes(value.level) ? value.level : 'default') as Level
    }
  } catch { return { legacyCollapsed: true, height: 184, level: 'default' as Level } }
}

function RuntimeDeviceStatus() {
  const device = useDeviceStatus()
  const name = device.transport === 'simulator' ? '模拟设备' : device.port === null ? '' : `COM${device.port}`
  const label = name ? `${name} · ${device.stateLabel}` : device.stateLabel
  return <span className="runtime-device-status" title={label}>{label}</span>
}

export function MessagePanel({ userId, health, canReadDevices, onHeightChange, expanded, onExpandedChange }: {
  userId: number
  health: 'online' | 'offline'
  canReadDevices: boolean
  onHeightChange: (height: number) => void
  expanded: boolean
  onExpandedChange: (value: boolean) => void
}) {
  const events = useRuntimeEvents()
  const lastSeenEventId = useLastSeenEventId(userId)
  const { count: unreadCount, severity: unreadSeverity, maxEventId } = useMemo(
    () => unreadAlerts(events, lastSeenEventId), [events, lastSeenEventId]
  )
  const storageKey = `geospectrum:information-panel:${userId}`
  const [initial] = useState(() => preferences(storageKey))
  const [channel, setChannel] = useState<Channel>('general')
  const [level, setLevel] = useState<Level>(initial.level)
  const [filter, setFilter] = useState('')
  const collapsed = !expanded
  const [height, setHeight] = useState(initial.height)
  const [snapshot, setSnapshot] = useState<RuntimeEvent[] | null>(null)
  const [cleared, setCleared] = useState<Record<Channel, number>>({ general: 0, communication: 0 })
  const panel = useRef<HTMLElement>(null)
  const toggleButton = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const drag = useRef<{ y: number; height: number } | null>(null)
  const source = snapshot ?? events
  const paused = snapshot !== null
  const available = useMemo(() => source.filter(event => event.id > cleared[channelOf(event)]), [source, cleared])
  const latest = collapsed ? available.reduce<RuntimeEvent | undefined>((newest, event) =>
    !newest || event.id > newest.id ? event : newest, undefined) : undefined
  const matching = useMemo(() => available.filter(event => {
    if (level === 'default' && event.severity === 'debug') return false
    if (level === 'brief' && !['success', 'warning', 'error'].includes(event.severity)) return false
    const context = level === 'detailed' ? eventContext(event) : ''
    return `${formatTime(event.created_at)} ${event.message} ${context}`.toLocaleLowerCase().includes(filter.trim().toLocaleLowerCase())
  }), [available, level, filter])
  const counts = useMemo(() => ({
    general: matching.filter(event => channelOf(event) === 'general').length,
    communication: matching.filter(event => channelOf(event) === 'communication').length
  }), [matching])
  const rows = useMemo(() => matching.filter(event => channelOf(event) === channel).sort((a, b) => a.id - b.id), [matching, channel])

  useEffect(() => {
    // Preserve the old expansion preference for accounts still reading it on startup.
    try { localStorage.setItem(storageKey, JSON.stringify({ layoutVersion: 2, collapsed: initial.legacyCollapsed, height, level })) } catch { /* Storage may be unavailable. */ }
  }, [storageKey, initial.legacyCollapsed, height, level])
  useEffect(() => {
    if (expanded && events === runtimeEventsStore.getSnapshot()) shellLayoutStore.markEventsSeen(userId, maxEventId)
  }, [expanded, events, maxEventId, userId])
  useLayoutEffect(() => {
    const element = panel.current
    if (!element) return
    const measure = () => onHeightChange(Math.ceil(element.getBoundingClientRect().height))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [onHeightChange])
  useEffect(() => {
    const resize = () => setHeight(value => limitHeight(value))
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  useLayoutEffect(() => {
    if (!paused && !collapsed && follow.current && list.current) list.current.scrollTop = list.current.scrollHeight
  }, [rows, paused, collapsed])

  const chooseChannel = (next: Channel) => { follow.current = true; setChannel(next) }
  const clearScreen = () => {
    const latest = source.filter(event => channelOf(event) === channel).reduce((id, event) => Math.max(id, event.id), 0)
    setCleared(previous => ({ ...previous, [channel]: Math.max(previous[channel], latest) }))
  }
  const toggleLabel = collapsed ? '展开信息记录' : '收起信息记录'
  const unreadLabel = `查看 ${unreadCount} 条未读告警或错误`
  const content = (
    <section ref={panel} className={`runtime-message-panel${collapsed ? ' is-collapsed' : ''}`} data-testid="runtime-messages"
      aria-label="信息记录" style={collapsed ? undefined : { height }}>
      {!collapsed && <div className="runtime-message-resizer" role="separator" aria-label="调整信息记录高度"
        aria-orientation="horizontal" aria-valuemin={120} aria-valuemax={Math.min(360, Math.floor(window.innerHeight / 2))}
        aria-valuenow={height} tabIndex={0}
        onKeyDown={event => {
          if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
            event.preventDefault(); setHeight(value => limitHeight(value + (event.key === 'ArrowUp' ? 16 : -16)))
          }
        }}
        onPointerDown={event => { drag.current = { y: event.clientY, height }; event.currentTarget.setPointerCapture(event.pointerId) }}
        onPointerMove={event => { if (drag.current) setHeight(limitHeight(drag.current.height + drag.current.y - event.clientY)) }}
        onPointerUp={event => { drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId) }}
        onPointerCancel={() => { drag.current = null }} />}
      <div className="runtime-message-toolbar">
        {collapsed ? <>
          <div className="runtime-message-status">
            <span className="runtime-service-status">
              <span className={`status-dot ${health}`} aria-hidden="true" />
              {health === 'online' ? '服务已连接' : '服务未连接'}
            </span>
            {canReadDevices && <RuntimeDeviceStatus />}
          </div>
          <span className="runtime-message-summary" title={latest?.message}>{latest?.message ?? '暂无信息记录'}</span>
          {unreadCount > 0 && <button type="button" className="runtime-unread-badge"
            data-testid="runtime-unread-badge" data-severity={unreadSeverity} aria-label={unreadLabel} title={unreadLabel}
            onClick={() => { onExpandedChange(true); toggleButton.current?.focus() }}>
            {unreadSeverity === 'error' ? <CircleAlert size={12} aria-hidden="true" /> : <AlertTriangle size={12} aria-hidden="true" />}
            {unreadCount}
          </button>}
        </> : <>
          <div className="runtime-message-tabs" role="tablist" aria-label="信息记录分类">
            {(['general', 'communication'] as const).map(item => <button key={item} type="button" role="tab"
              id={`runtime-${item}-tab`} aria-selected={channel === item} aria-controls="runtime-message-content"
              onClick={() => chooseChannel(item)}>
              {item === 'general' ? '常规信息' : '通信命令'} <span title="当前日志级别和文字过滤后的条数">{counts[item]}</span>
            </button>)}
          </div>
          <label className="runtime-message-level">日志级别
            <select aria-label="信息记录日志级别" title={levelHint} value={level} onChange={event => { follow.current = true; setLevel(event.target.value as Level) }}>
              <option value="detailed">详细</option><option value="default">默认</option><option value="brief">精简</option>
            </select>
          </label>
          <input className="runtime-message-filter" aria-label="过滤信息记录" type="search" placeholder="过滤…" value={filter}
            onChange={event => { follow.current = true; setFilter(event.target.value) }} />
        </>}
        <div className="runtime-message-actions">
          {!collapsed && <>
            <button type="button" aria-pressed={paused} title="暂停刷新，采集和分析继续运行"
              onClick={() => { follow.current = true; setSnapshot(paused ? null : [...events]) }}>{paused ? '继续' : '暂停'}</button>
            <button type="button" title="只清除当前分类的显示" onClick={clearScreen}>清屏</button>
          </>}
          <button ref={toggleButton} type="button" className="runtime-message-collapse" aria-label={toggleLabel}
            title={toggleLabel + ' (Ctrl+`)'} aria-keyshortcuts="Control+`" aria-expanded={expanded}
            aria-controls="runtime-message-content" onClick={() => onExpandedChange(collapsed)}>
            {collapsed ? <ChevronUp size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
          </button>
        </div>
      </div>
      <div ref={list} className="runtime-message-list" id="runtime-message-content" role="tabpanel"
        aria-labelledby={`runtime-${channel}-tab`} hidden={collapsed}
        onScroll={event => { const element = event.currentTarget; follow.current = element.scrollHeight - element.clientHeight - element.scrollTop < 16 }}>
        {rows.length ? rows.map(event => <div className={`runtime-message-row ${event.severity}`} key={event.id}>
          <time dateTime={event.created_at}>{formatTime(event.created_at)}</time><span>{event.message}
            {level === 'detailed' && <small className="runtime-message-context">{eventContext(event)}</small>}
          </span>
        </div>) : <div className="runtime-message-empty">{filter.trim() ? '没有匹配的记录' : '暂无记录'}</div>}
      </div>
    </section>
  )
  return <RenderProfiler id="MessagePanel">{content}</RenderProfiler>
}
