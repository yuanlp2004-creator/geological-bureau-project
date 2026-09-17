import { Check, Clock3, X } from 'lucide-react'

export function MigrationCheckList({ checks, status }: { checks: Record<string, boolean | null>; status?: string }) {
  return <div className="migration-check-list">{Object.entries(checks).map(([key, passed]) => {
    const pending = passed === null || (key === 'atomic_commit' && passed === false && status === 'staged')
    return <div key={key}><span className={pending ? 'pending' : passed ? 'pass' : 'fail'}>{pending ? <Clock3 size={13} /> : passed ? <Check size={13} /> : <X size={13} />}</span><code>{key}</code><strong>{pending ? '待提交' : passed ? '通过' : '失败'}</strong></div>
  })}</div>
}
