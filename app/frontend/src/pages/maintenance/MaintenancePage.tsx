import { useEffect, useRef, useState } from 'react'
import { DatabaseBackup, RefreshCw } from 'lucide-react'
import { api, type MaintenanceStatus } from '../../api'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { formatTime } from '../../components/dateFormat'
import { SystemDiagnostics } from './SystemDiagnostics'

export function MaintenancePage({ token, canWrite, onToast }: {
  token: string
  canWrite: boolean
  onToast: (message: string) => void
}) {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null)
  const [directory, setDirectory] = useState('backups')
  const [retentionDays, setRetentionDays] = useState(30)
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(true)
  const [showDiagnostics, setShowDiagnostics] = useState(false)
  const running = useRef(false)
  const load = async () => {
    setRefreshing(true)
    try {
      setStatus(await api.maintenanceStatus(token))
    } catch (error) {
      setStatus(null)
      onToast(error instanceof Error ? error.message : '无法读取维护状态')
    } finally {
      setRefreshing(false)
    }
  }
  useEffect(() => {
    void load()
    void api.settings(token)
      .then(settings => setDirectory(settings.directories.backups))
      .catch(error => onToast(error instanceof Error ? error.message : '无法读取备份目录设置'))
  }, [token])
  const run = async (action: () => Promise<unknown>, message: string) => {
    if (!canWrite || running.current) return
    running.current = true
    setBusy(true)
    try {
      await action()
      onToast(message)
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '维护操作失败')
    } finally {
      running.current = false
      setBusy(false)
    }
  }
  const healthy = status?.integrity === 'ok' && status.foreign_key_errors === 0
  return (
    <div className="page-content maintenance-page maintenance-simple refined-page remaining-page" data-testid="maintenance-page">
      <section className="surface maintenance-basic">
        <div className="surface-heading">
          <h2>数据库维护</h2>
          <div className="maintenance-summary">
            <span className={`maintenance-health ${healthy ? 'ok' : status ? 'error' : 'pending'}`}>
              <span className="maintenance-health-dot" />
              {healthy ? '数据库正常' : status ? '需要检查' : refreshing ? '读取中' : '状态未知'}
            </span>
            <button className="secondary-button" disabled={busy || refreshing} onClick={() => void load()}>
              <RefreshCw size={15} />刷新
            </button>
          </div>
        </div>
        <div className="maintenance-task">
          <div className="maintenance-task-content">
            <h3>备份数据库</h3>
            <p>保存当前数据库的完整副本，完成后自动校验。</p>
            <label className="field maintenance-backup-directory">
              <span>备份目录</span>
              <input value={directory} disabled={!canWrite || busy} onChange={event => setDirectory(event.target.value)} placeholder="例如 C:\GeoSpectrum\backups" />
            </label>
          </div>
          <button className="primary-button" disabled={!canWrite || busy || refreshing}
            onClick={() => void run(() => api.createBackup(token, { output_directory: directory, retention_days: 30 }), '数据库备份及校验已完成')}>
            <DatabaseBackup size={15} />创建备份
          </button>
        </div>
        <div className="maintenance-task">
          <div className="maintenance-task-content">
            <h3>整理数据库</h3>
            <p>回收删除数据留下的空闲空间；整理前请先创建备份。</p>
          </div>
          <button className="secondary-button" disabled={!canWrite || busy || refreshing}
            onClick={() => void run(() => api.maintenanceAction(token, 'reclaim'), '数据库整理已完成')}>
            整理数据库
          </button>
        </div>
        <div className="maintenance-task">
          <div className="maintenance-task-content">
            <h3>清理记录文件</h3>
            <p>只清理过期历史日志，保留当前日志和审计记录。</p>
            <label className="field maintenance-log-settings">
              <span>保留天数</span>
              <NumericInput min={1} max={3650} value={retentionDays} disabled={!canWrite || busy} onValueChange={setRetentionDays} />
            </label>
          </div>
          <button className="secondary-button" disabled={!canWrite || busy || refreshing} onClick={() => {
            if (!reportInvalidNumericInput(document.querySelector('.maintenance-log-settings'))) return onToast('请先修正保留天数')
            void run(() => api.maintenanceAction(token, 'logs/cleanup', { retention_days: retentionDays }), '过期历史日志已清理')
          }}>清理记录文件</button>
        </div>
      </section>
      <section className="surface maintenance-table">
        <div className="surface-heading"><h2>备份记录</h2><span className="muted-label">{status?.backups.length ?? 0} 条</span></div>
        {!status?.backups.length ? (
          <div className="maintenance-empty compact"><DatabaseBackup size={22} /><strong>尚无备份记录</strong></div>
        ) : (
          <div className="maintenance-list">
            {status.backups.map(backup => (
              <div className="maintenance-row" key={backup.id}>
                <div><strong title={backup.backup_path}>{backup.backup_path}</strong><small>{formatTime(backup.created_at)} · {(backup.byte_length / 1024).toFixed(1)} KB</small></div>
                <span className="state-chip completed">{backup.status === 'completed' ? '已备份' : backup.status}</span>
                <button className="secondary-button compact-button" disabled={!canWrite || busy || refreshing}
                  onClick={() => void run(() => api.verifyBackup(token, backup.id), '备份校验通过')}>校验</button>
              </div>
            ))}
          </div>
        )}
      </section>
      {canWrite && (
        <details className="surface maintenance-diagnostics" onToggle={event => setShowDiagnostics(event.currentTarget.open)}>
          <summary>系统诊断</summary>
          {showDiagnostics && <SystemDiagnostics token={token} />}
        </details>
      )}
    </div>
  )
}
