import { LegacySourcePicker } from '../../components/LegacySourcePicker'
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Archive, CheckCircle2, Database, RefreshCw, Upload } from 'lucide-react'
import { api, type AuthUser, type ResultMigrationDiagnostic, type ResultMigrationRun } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { MigrationCheckList } from './MigrationCheckList'
import { formatDateTime } from '../../components/dateFormat'

export function ResultMigrationPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [diagnostic, setDiagnostic] = useState<ResultMigrationDiagnostic | null>(null)
  const [runs, setRuns] = useState<ResultMigrationRun[]>([])
  const [activeRun, setActiveRun] = useState<ResultMigrationRun | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const canWrite = currentUser.permissions.includes('result-migration.write')

  const load = useCallback(async () => {
    try {
      const [nextDiagnostic, nextRuns] = await Promise.all([api.resultMigrationDiagnostics(token), api.resultMigrationRuns(token)])
      setDiagnostic(nextDiagnostic); setRuns(nextRuns.runs)
      setActiveRun((current) => current ? nextRuns.runs.find((item) => item.id === current.id) ?? current : nextRuns.runs[0] ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取结果迁移状态') }
  }, [token, onToast])
  useEffect(() => { void load() }, [load])

  const stage = async () => {
    if (!path.trim() || !canWrite) return
    setBusy(true)
    try { const next = await api.stageResultMigration(token, path.trim()); setActiveRun(next); setRuns((current) => [next, ...current.filter((item) => item.id !== next.id)]); onToast('结果文件已暂存') }
    catch (error) { onToast(error instanceof Error ? error.message : '结果文件暂存失败') }
    finally { setBusy(false) }
  }
  const commit = async () => {
    if (!activeRun || activeRun.status !== 'staged' || !canWrite) return
    setBusy(true)
    try { const next = await api.commitResultMigration(token, activeRun.id); setActiveRun(next); setRuns((current) => current.map((item) => item.id === next.id ? next : item)); onToast('结果矩阵已原子提交') }
    catch (error) { onToast(error instanceof Error ? error.message : '结果矩阵提交失败') }
    finally { setBusy(false) }
  }
  const record = activeRun?.staging?.records[0]
  return <div className="page-content migration-page result-migration-page refined-page remaining-page" data-testid="result-migration-page">
    <div className="page-intro"><div><h1>谱图结果迁移</h1><p>读取旧版 .pdt/.dat 矩阵，保留方法引用、重复计数、谱线元数据、曝光段和原始矩阵。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => void load()} disabled={busy}><RefreshCw size={15} />刷新</button></div></div>
    <section className="surface migration-source-surface"><div className="surface-heading"><div><h2>选择结果文件</h2></div><Database size={17} /></div><LegacySourcePicker token={token} kind="result-migration" disabled={!canWrite || busy} selectedPath={path} onSelect={(source) => setPath(source.path)} /><div className="migration-path-form"><label className="field"><span>文件路径</span><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\\SpecDirect\\DATA\\result.pdt" /></label><button className="primary-button" onClick={() => void stage()} disabled={!canWrite || busy || !path.trim()}><Upload size={15} />暂存解析</button></div><div className="reader-status"><span className="status-dot online" /><div><strong>{diagnostic?.message ?? '正在检查解析器'}</strong><span>{diagnostic?.parser_version ?? 's09-result-1'} · {diagnostic?.formats?.join(' / ').toUpperCase() ?? 'DAT / PDT'} · 小端序</span></div></div></section>
    {activeRun && <section className="surface migration-report-surface" data-testid="result-migration-report"><div className="surface-heading"><div><h2>迁移报告 <span className={`migration-status ${activeRun.status}`}>{activeRun.status === 'committed' ? '已提交' : activeRun.status === 'failed' ? '已回滚' : '待提交'}</span></h2></div><CopyableCode value={activeRun.fingerprint} visibleLength={16} /></div><div className="migration-count-grid spectrum-count-grid"><div><span>格式</span><strong>{activeRun.format.toUpperCase()}</strong><small>严格旧版二进制布局</small></div><div><span>样品 / 谱线</span><strong>{activeRun.report.counts.samples} / {activeRun.report.counts.lines}</strong><small>原始行列维度</small></div><div><span>展开波段</span><strong>{activeRun.report.counts.bands}</strong><small>重复计数展开</small></div><div><span>矩阵值</span><strong>{activeRun.report.counts.matrix_values}</strong><small>原始值未重算</small></div></div><div className="migration-report-grid"><div><h3>一致性检查</h3><MigrationCheckList checks={activeRun.report.checks} status={activeRun.status} /></div><div><h3>源文件与方法</h3><div className="spectrum-fingerprint"><strong title={activeRun.source_file.name}>{activeRun.source_file.name}</strong><code>{activeRun.source_file.sha256}</code><small>{(activeRun.source_file.size / 1024).toFixed(1)} KB · {activeRun.parser.encoding} · {activeRun.parser.endianness}</small></div>{record && <div className="spectrum-layout-facts"><span>测量时间</span><code>{record.measure_time}</code><span>方法引用</span><code>{record.method_match_status}{record.method_legacy_id === null ? '' : ` · legacy ${record.method_legacy_id}`}</code></div>}</div></div>{record && <div className="spectrum-record-summary"><h3>矩阵摘要</h3><div><span>样品首项</span><strong>{record.sample_names[0] ?? '—'}</strong><span>样品末项</span><strong>{record.sample_names[record.sample_names.length - 1] ?? '—'}</strong><span>首个值</span><strong>{String(record.matrix_samples[0]?.value ?? record.matrix_samples[0]?.peak ?? '—')}</strong><span>末个值</span><strong>{String(record.matrix_samples[record.matrix_samples.length - 1]?.value ?? record.matrix_samples[record.matrix_samples.length - 1]?.peak ?? '—')}</strong></div></div>}{activeRun.report.issues.length > 0 && <div className="migration-issues">{activeRun.report.issues.map((issue) => <div key={issue.code}><AlertTriangle size={14} /><span><strong>{issue.message}</strong><code>{issue.code}</code></span></div>)}</div>}<div className="migration-commit-bar"><span>{activeRun.status === 'staged' ? '提交将把整份矩阵写入 SQLite 单事务。' : activeRun.status === 'committed' ? '相同源 SHA-256 再次导入不会产生重复矩阵。' : '提交已回滚，可重新暂存。'}</span>{activeRun.status === 'staged' && <button className="primary-button" onClick={() => void commit()} disabled={!canWrite || busy}><CheckCircle2 size={15} />原子提交</button>}</div></section>}
    <section className="surface migration-history-surface"><div className="surface-heading"><div><h2>最近结果导入</h2></div><Archive size={17} /></div>{runs.length === 0 ? <div className="method-empty compact"><Archive size={24} /><p>还没有结果迁移记录。</p></div> : <div className="migration-history-list">{runs.map((run) => <button key={run.id} onClick={() => void api.resultMigrationRun(token, run.id).then(setActiveRun)} className={activeRun?.id === run.id ? 'active' : ''}><span className={`migration-status ${run.status}`}>{run.status === 'committed' ? '已提交' : run.status === 'failed' ? '已回滚' : '待提交'}</span><div><strong title={run.source_file.name}>{run.source_file.name}</strong><small>{formatDateTime(run.created_at)} · {run.format.toUpperCase()} · {run.report.counts.bands} 波段</small></div><code title={run.fingerprint}>{run.fingerprint.slice(0, 12)}</code></button>)}</div>}</section>
  </div>
}
