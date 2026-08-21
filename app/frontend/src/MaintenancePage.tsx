import { useEffect, useState } from 'react'
import { CheckCircle2, DatabaseBackup, RefreshCw, ShieldCheck, Wrench } from 'lucide-react'
import { api, type MaintenanceStatus } from './api'
import { NumericInput, reportInvalidNumericInput } from './NumericInput'

const operationLabels: Record<string, string> = {
  backup: '在线备份',
  restore_rehearsal: '恢复演练',
  checkpoint: 'WAL checkpoint',
  optimize: '数据库优化',
  reclaim: '受控回收',
  retention: '过期备份清理',
  logs: '过期日志清理',
  temp: '临时文件清理',
}

export function MaintenancePage({ token, canWrite, onToast }: { token: string; canWrite: boolean; onToast: (message: string) => void }) {
  const [status, setStatus] = useState<MaintenanceStatus | null>(null)
  const [directory, setDirectory] = useState('backups')
  const [retentionDays, setRetentionDays] = useState(30)
  const [busy, setBusy] = useState(false)
  const load = async () => {
    try { setStatus(await api.maintenanceStatus(token)) } catch (error) { onToast(error instanceof Error ? error.message : '无法读取维护状态') }
  }
  useEffect(() => { void load() }, [])
  const run = async (action: () => Promise<unknown>, message: string) => {
    if (!reportInvalidNumericInput(document.querySelector('.maintenance-page'))) return onToast('请先修正维护参数')
    setBusy(true)
    try { await action(); onToast(message); await load() } catch (error) { onToast(error instanceof Error ? error.message : '维护操作失败') } finally { setBusy(false) }
  }
  return <div className="page-content maintenance-page" data-testid="maintenance-page">
    <div className="page-intro maintenance-intro">
      <div><span className="section-kicker">S20 / MAINTENANCE</span><h1>备份与维护</h1><p>在线备份、隔离恢复演练和受控空间维护。每次操作都会写入维护记录。</p></div>
      <div className="page-intro-actions"><span className={`maintenance-health ${status?.integrity === 'ok' ? 'ok' : status ? 'error' : 'pending'}`}><span className="maintenance-health-dot" />{status?.integrity === 'ok' ? '数据库正常' : status ? '需要检查' : '读取中'}</span><button className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={15} className={busy ? 'spin' : ''} />刷新</button></div>
    </div>
    <div className="maintenance-grid">
      <section className="surface maintenance-primary">
        <div className="surface-heading"><div><span className="section-kicker">ONLINE BACKUP</span><h2>SQLite 在线备份</h2></div><DatabaseBackup size={18} /></div>
        <label className="field"><span>备份目录</span><input value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="例如 C:\GeoSpectrum\backups" /></label>
        <div className="maintenance-action-row">
          <button className="primary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.createBackup(token, { output_directory: directory, retention_days: retentionDays }), '在线备份已完成')}><DatabaseBackup size={15} />创建备份</button>
          <button className="secondary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.maintenanceAction(token, 'retention'), '备份保留策略已执行')}><Wrench size={15} />清理过期备份</button>
        </div>
        <div className="maintenance-note"><ShieldCheck size={15} /><span>副本会执行完整性、外键、实体计数和 BLOB 抽样哈希校验；恢复演练只在隔离副本中执行，不会切换当前数据库。</span></div>
      </section>
      <section className="surface maintenance-status">
        <div className="surface-heading"><div><span className="section-kicker">HEALTH</span><h2>数据库状态</h2></div><span className={`state-chip ${status?.integrity === 'ok' ? 'completed' : 'failed'}`}>{status?.integrity ?? '读取中'}</span></div>
        <div className="diagnostic-grid"><div><span>数据库</span><strong>{status ? `${(status.database_bytes / 1024).toFixed(1)} KB` : '—'}</strong></div><div><span>WAL</span><strong>{status ? `${(status.wal_bytes / 1024).toFixed(1)} KB` : '—'}</strong></div><div><span>外键错误</span><strong>{status?.foreign_key_errors ?? '—'}</strong></div><div><span>备份数</span><strong>{status?.backups.length ?? '—'}</strong></div></div>
        <div className="maintenance-action-group"><span className="maintenance-group-label">数据库整理</span><div className="maintenance-action-row">
          <button className="secondary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.maintenanceAction(token, 'checkpoint', { mode: 'TRUNCATE' }), 'WAL checkpoint 已完成')}><CheckCircle2 size={15} />WAL checkpoint</button>
          <button className="secondary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.maintenanceAction(token, 'optimize'), '数据库优化已完成')}>优化</button>
          <button className="secondary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.maintenanceAction(token, 'reclaim'), '空间回收已完成')}>受控回收</button>
        </div></div>
        <div className="maintenance-action-group"><div className="maintenance-retention-heading"><span className="maintenance-group-label">文件清理</span><label className="maintenance-retention-field"><span>保留天数</span><NumericInput min={1} max={3650} value={retentionDays} onValueChange={setRetentionDays} /></label></div><div className="maintenance-action-row">
          <button className="secondary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.maintenanceAction(token, 'logs/cleanup', { retention_days: retentionDays }), '过期轮转日志已清理')}>清理过期日志</button>
          <button className="secondary-button" disabled={!canWrite || busy} onClick={() => void run(() => api.maintenanceAction(token, 'temp/cleanup', { retention_days: retentionDays }), '过期临时文件已清理')}>清理临时文件</button>
        </div></div>
      </section>
    </div>
    <section className="surface maintenance-table">
      <div className="surface-heading"><div><span className="section-kicker">VERIFIED ARTIFACTS</span><h2>备份记录</h2></div><span className="muted-label">{status?.backups.length ?? 0} 条</span></div>
      {!status?.backups.length ? <div className="maintenance-empty"><DatabaseBackup size={22} /><strong>尚无备份记录</strong><span>创建在线备份后，路径、哈希和恢复演练入口会显示在这里。</span></div> : <div className="maintenance-list">{status.backups.map((backup) => <div className="maintenance-row" key={backup.id}><div><strong title={backup.backup_path}>{backup.backup_path}</strong><small>{backup.created_at} · {(backup.byte_length / 1024).toFixed(1)} KB · SHA-256 {backup.backup_sha256.slice(0, 16)}...</small></div><span className="state-chip completed">{backup.status}</span><div className="maintenance-row-actions"><button className="secondary-button compact-button" disabled={!canWrite || busy} onClick={() => void run(() => api.verifyBackup(token, backup.id), '备份校验通过')}>校验</button><button className="secondary-button compact-button" disabled={!canWrite || busy} onClick={() => void run(() => api.restoreRehearsal(token, backup.id), '恢复演练通过')}>恢复演练</button></div></div>)}</div>}
    </section>
    <section className="surface maintenance-history">
      <div className="surface-heading"><div><span className="section-kicker">OPERATION LOG</span><h2>最近维护记录</h2></div><span className="muted-label">{status?.operations.length ?? 0} 条</span></div>
      {!status?.operations.length ? <div className="maintenance-empty compact"><Wrench size={20} /><strong>尚无维护操作</strong></div> : <div className="maintenance-operation-list">{status.operations.map((operation) => <div className="maintenance-operation-row" key={operation.id}><span className="maintenance-operation-icon"><Wrench size={14} /></span><div><strong>{operationLabels[operation.operation] ?? operation.operation}</strong><small>{operation.created_at}</small></div><span className={`state-chip ${operation.status === 'completed' ? 'completed' : 'failed'}`}>{operation.status}</span></div>)}</div>}
    </section>
  </div>
}
