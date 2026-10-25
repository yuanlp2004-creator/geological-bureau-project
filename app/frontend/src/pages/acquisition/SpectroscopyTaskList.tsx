import { Activity } from 'lucide-react'

export function SpectroscopyTaskList({ title, tasks, busy, runningId, onChoose }: {
  title: string
  tasks: { id: number; name: string; status: string; details: string; completed: boolean }[]
  busy: boolean
  runningId?: number
  onChoose: (id: number) => void
}) {
  return <section className="surface spectroscopy-task-list" aria-label={`${title}任务列表`}>
    <div className="surface-heading"><h2>{title}任务 <span className="count-badge">{tasks.length}</span></h2><Activity size={17} /></div>
    {tasks.length ? <div className="sample-table-wrap"><table className="data-table">
      <thead><tr><th>任务名称</th><th>状态</th><th>任务信息</th><th>操作</th></tr></thead>
      <tbody>{tasks.map(task => <tr key={task.id} data-task-id={task.id}>
        <td>{task.name}</td><td>{task.status}</td><td>{task.details}</td>
        <td><button type="button" className="secondary-button" disabled={busy || (runningId !== undefined && runningId !== task.id)}
          onClick={() => onChoose(task.id)}>{task.completed ? '查看谱图' : '进入摄谱'}</button></td>
      </tr>)}</tbody>
    </table></div> : <div className="empty-state">暂无{title}任务，请点击右上角“新建任务”。</div>}
  </section>
}
