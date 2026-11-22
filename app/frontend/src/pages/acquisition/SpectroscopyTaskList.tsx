import { Activity, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { SpectroscopyTaskDialog } from './SpectroscopyTaskDialog'

type TaskBadge = { label: string; tone: 'neutral' | 'running' | 'warning' | 'danger' | 'success' }
type TaskRow = { id: number; name: string; status: string; badge?: TaskBadge; details: string; completed: boolean }

const captureBadges = new Map<string, TaskBadge>(Object.entries({
  draft: { label: '草稿', tone: 'neutral' },
  countdown: { label: '运行中', tone: 'running' },
  pre_excitation: { label: '运行中', tone: 'running' },
  burn: { label: '运行中', tone: 'running' },
  dark: { label: '运行中', tone: 'running' },
  between_repeats: { label: '运行中', tone: 'running' },
  stopping: { label: '停止中', tone: 'warning' },
  failed: { label: '已失败', tone: 'danger' },
  paused: { label: '已暂停', tone: 'warning' },
  stopped: { label: '已停止', tone: 'neutral' },
  completed: { label: '已完成', tone: 'success' },
}))

export function captureTaskPresentation(
  task: { status: string; capture_turns?: { status: string; angle_deg: number }[] },
  labels: Record<string, string>,
  details: string,
) {
  const { status, capture_turns: turns } = task
  const badgeFor = (value: string): TaskBadge => {
    if (value === 'draft') return { label: labels.draft, tone: 'neutral' }
    return captureBadges.get(value) ?? { label: value, tone: 'neutral' }
  }
  if (!turns?.length) {
    const badge = badgeFor(status)
    const phase = labels[status]
    return { status, badge, details: phase && badge.tone === 'running' ? `${details} · ${phase}` : details }
  }

  const statuses = turns.map(turn => turn.status)
  const completedCount = statuses.filter(value => value === 'completed').length
  const priority = statuses.find(value => captureBadges.get(value)?.tone === 'running')
    ?? ['stopping', 'failed', 'paused', 'stopped'].find(value => statuses.includes(value))
    ?? statuses.find(value => !captureBadges.has(value))
  const badge: TaskBadge = priority !== undefined ? badgeFor(priority)
    : completedCount === turns.length ? badgeFor('completed')
    : completedCount > 0 ? { label: '待续采', tone: 'neutral' }
    : badgeFor('draft')
  return { status, badge, details: `${turns.map(turn => `${turn.angle_deg}°`).join(' / ')} · ${completedCount}/${turns.length} 转角完成` }
}

export function SpectroscopyTaskList({ title, tasks, busy, runningId, onChoose, onView, onDelete }: {
  title: string
  tasks: TaskRow[]
  busy: boolean
  runningId?: number
  onChoose: (id: number) => void
  onView?: (id: number) => void
  onDelete?: (id: number) => Promise<void>
}) {
  const [deleteTarget, setDeleteTarget] = useState<TaskRow | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const pending = useRef(false)
  const confirmDelete = async () => {
    if (!deleteTarget || !onDelete || busy || runningId !== undefined || pending.current) return
    pending.current = true
    setDeleting(true)
    setDeleteError(null)
    try {
      await onDelete(deleteTarget.id)
      setDeleteTarget(null)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : '删除摄谱任务失败')
    } finally {
      pending.current = false
      setDeleting(false)
    }
  }
  return <section className="surface spectroscopy-task-list" aria-label={`${title}任务列表`}>
    <div className="surface-heading"><h2>{title}任务 <span className="count-badge">{tasks.length}</span></h2><Activity size={17} /></div>
    {tasks.length ? <div className="spectroscopy-task-table-wrap"><table className={`data-table spectroscopy-task-table${onDelete ? ' has-delete' : ''}`}>
      <colgroup><col className="task-name-column" /><col className="task-status-column" /><col /><col className="task-action-column" /></colgroup>
      <thead><tr><th scope="col">任务名称</th><th scope="col">状态</th><th scope="col">任务信息</th>
        <th scope="col"><span className="spectroscopy-task-actions"><span>操作</span></span></th></tr></thead>
      <tbody>{tasks.map(task => <tr key={task.id} data-task-id={task.id}>
        <td>{task.name}</td><td>{task.badge
          ? <span className={`task-status-badge ${task.badge.tone}`}>{task.badge.label}</span>
          : task.status}</td><td>{task.details}</td>
        <td><div className="spectroscopy-task-actions">
          <button type="button" className={`secondary-button task-open${task.completed ? ' task-view' : ''}`} disabled={busy || (runningId !== undefined && runningId !== task.id)}
            onClick={() => (task.completed && onView ? onView : onChoose)(task.id)}>{task.completed ? '查看谱图' : '进入摄谱'}</button>
          {onDelete && <button type="button" className="icon-button task-delete"
            aria-label={`删除任务：${task.name}`} title="删除任务" disabled={busy || runningId !== undefined}
            onClick={() => { setDeleteError(null); setDeleteTarget(task) }}><Trash2 size={16} /></button>}
        </div></td>
      </tr>)}</tbody>
    </table></div> : <div className="empty-state">暂无{title}任务，请点击右上角“新建任务”。</div>}
    {onDelete && <SpectroscopyTaskDialog open={deleteTarget !== null} title={`删除${title}任务`} busy={deleting}
      error={deleteError} onCancel={() => setDeleteTarget(null)} actions={
        <button type="button" className="primary-button" disabled={busy || deleting || runningId !== undefined}
          onClick={() => void confirmDelete()}>确认删除</button>
      }>
      <p>确定删除任务「{deleteTarget?.name}」吗？已保存的原始采集帧将保留供审计。</p>
    </SpectroscopyTaskDialog>}
  </section>
}
