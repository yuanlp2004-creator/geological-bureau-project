import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, type Diagnostics, type ModuleDiagnostic } from '../../api'
import { FormDisclosure } from '../../layout/TaskLayout'
import { formatTime } from '../../components/dateFormat'

const moduleStatus: Record<ModuleDiagnostic['status'], string> = {
  active: '软件可用', disabled: '未启用', error: '异常', restricted: '无检测权限', unchecked: '未检测'
}

export function SystemDiagnostics({ token }: { token: string }) {
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setBusy(true)
    setDiagnostics(null)
    setError('')
    try {
      setDiagnostics(await api.diagnostics(token))
    } catch (error) {
      setDiagnostics(null)
      setError(error instanceof Error ? error.message : '无法读取系统诊断')
    } finally {
      setBusy(false)
    }
  }, [token])
  useEffect(() => { void load() }, [load])
  return (
    <section className="surface system-diagnostics" data-testid="system-diagnostics" aria-busy={busy}>
      <div className="surface-heading">
        <h2>系统诊断</h2>
        <button className="secondary-button" disabled={busy} onClick={() => void load()}>
          <RefreshCw size={15} />刷新诊断
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="diagnostic-grid">
        <div><span>本地服务</span><strong>{diagnostics?.service === 'ok' ? '运行正常' : '—'}</strong></div>
        <div><span>SQLite 完整性</span><strong>{diagnostics?.sqlite_integrity ?? '—'}</strong></div>
        <div><span>数据库版本</span><strong>{diagnostics?.schema_version ?? '—'}</strong></div>
        <div><span>日志模式</span><strong>{diagnostics?.journal_mode ?? '—'}</strong></div>
        <div><span>外键约束</span><strong>{diagnostics ? (diagnostics.foreign_keys === 1 ? '已启用' : '未启用') : '—'}</strong></div>
        <div><span>日志事件</span><strong>{diagnostics?.event_count ?? '—'}</strong></div>
        <div><span>清单结构校验</span><strong>{diagnostics ? (diagnostics.manifest_valid ? '通过' : '未通过') : '—'}</strong></div>
      </div>
      <dl className="system-diagnostic-paths">
        <div><dt>数据库路径</dt><dd>{diagnostics?.database_path ?? '—'}</dd></div>
        <div><dt>运行日志路径</dt><dd>{diagnostics?.runtime_log_path ?? '—'}</dd></div>
      </dl>
      <FormDisclosure title="查看模块清单">
        <p>检测当前软件的数据结构、依赖和查询接口，不启动采集或执行分析。</p>
        {diagnostics?.checked_at && <p>检测时间：{formatTime(diagnostics.checked_at)} · {(diagnostics.modules ?? []).filter(module => module.status === 'active').length}/{diagnostics.modules?.length ?? 0} 个模块软件可用</p>}
        {diagnostics?.manifest_error && <p role="alert">清单结构异常：{diagnostics.manifest_error}</p>}
        {!diagnostics && <p>{busy ? '正在检测模块…' : '尚未获得检测结果'}</p>}
        <div className="capability-list">
          {(diagnostics?.modules ?? []).map(module => (
            <div className="capability-row" key={module.key} data-module-key={module.key} data-module-status={module.status}>
              <div><strong>{module.title}</strong><small>{module.key} · {module.version}</small><p>{module.message}</p>{module.note && <small>{module.note}</small>}</div>
              <code>{module.probe_path ?? module.route}</code>
              <span className={`state-chip ${module.status === 'active' ? 'completed' : module.status === 'error' ? 'failed' : 'pending'}`}>{moduleStatus[module.status]}</span>
            </div>
          ))}
        </div>
      </FormDisclosure>
    </section>
  )
}
