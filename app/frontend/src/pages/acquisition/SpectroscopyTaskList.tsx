import { Activity, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { SpectroscopyTaskDialog } from './SpectroscopyTaskDialog'
import type { SpectroscopyStatus } from './spectroscopyStatus'

export { captureTaskPresentation } from './spectroscopyStatus'

type TaskRow = { id: number; name: string; status: string; badge?: SpectroscopyStatus; details: string; completed: boolean }

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
          ? <span className={`task-status-badge ${task.badge.tone}`} title={task.badge.detail}>{task.badge.label}</span>
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
