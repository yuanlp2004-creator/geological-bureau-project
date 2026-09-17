import { LegacySourcePicker } from '../../components/LegacySourcePicker'
import { FormDisclosure } from '../../layout/TaskLayout'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { AlertTriangle, Archive, CheckCircle2, ChevronRight, Database, FolderOpen, Info, RefreshCw, SquareTerminal } from 'lucide-react'
import { api, type AuthUser, type SpectrumMigrationDiagnostic, type SpectrumMigrationRun } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { MigrationCheckList } from './MigrationCheckList'
import { formatDateTime } from '../../components/dateFormat'

export function SpectrumMigrationPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [diagnostic, setDiagnostic] = useState<SpectrumMigrationDiagnostic | null>(null)
  const [runs, setRuns] = useState<SpectrumMigrationRun[]>([])
  const [activeRun, setActiveRun] = useState<SpectrumMigrationRun | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canWrite = currentUser.permissions.includes('spectrum-migration.write')

  const load = useCallback(async () => {
    try {
      const [nextDiagnostic, history] = await Promise.all([api.spectrumMigrationDiagnostics(token), api.spectrumMigrationRuns(token)])
      setDiagnostic(nextDiagnostic)
      setRuns(history.runs)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取旧谱迁移状态') }
  }, [token])

  useEffect(() => { void load() }, [load])

  const stage = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      const run = await api.stageSpectrumMigration(token, path)
      setActiveRun(run); await load(); onToast(run.already_committed ? '相同源文件已提交，未创建重复数据' : '旧谱文件已只读暂存并通过结构校验')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '暂存失败') }
    finally { setBusy(false) }
  }

  const commit = async () => {
    if (!activeRun || !window.confirm('确认把本次谱数据暂存原子提交到 SQLite？')) return
    setBusy(true); setError(null)
    try {
      const run = await api.commitSpectrumMigration(token, activeRun.id)
      setActiveRun(run); await load(); onToast(run.already_committed ? '迁移已提交，本次未生成重复记录' : '谱数据已完成原子提交')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '提交失败，目标数据已回滚') }
    finally { setBusy(false) }
  }

  const openRun = async (run: SpectrumMigrationRun) => {
    setBusy(true)
    try { setActiveRun(await api.spectrumMigrationRun(token, run.id)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取迁移报告') }
    finally { setBusy(false) }
  }

  const report = activeRun?.report
  const layout = activeRun?.staging?.layout
  const firstRecord = activeRun?.staging?.records[0]
  return <div className="page-content migration-page spectrum-migration-page refined-page remaining-page" data-testid="spectrum-migration-page">
    <section className="hero-row compact-hero"><div><h1>旧谱数据迁移</h1><p>只读解析 .cdt、.cmt、.edt、.wdt，校验布局、数组维度、端序和源文件指纹。</p></div><div className="hero-actions"><span className={`migration-reader-pill ${diagnostic?.available ? 'ready' : 'unavailable'}`}><span className={`status-dot ${diagnostic?.available ? 'online' : 'offline'}`} />{diagnostic?.available ? 'Jet 读取器就绪' : '读取器不可用'}</span><button className="secondary-button" onClick={load} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />重新检测</button></div></section>
    {error && <div className="auth-error migration-error"><AlertTriangle size={15} />{error}</div>}
    <div className="migration-top-grid">
      <form className="surface migration-source-surface" onSubmit={stage}>
        <div className="surface-heading"><div><h2>选择旧谱文件</h2></div><FolderOpen size={17} /></div>
        <p className="migration-note"><Info size={14} />服务会先复制到临时目录读取，并前后核对大小、修改时间和 SHA-256；原文件不会写入或修复。</p>
        <LegacySourcePicker token={token} kind="spectrum-migration" disabled={!canWrite || busy} selectedPath={path} onSelect={(source) => setPath(source.path)} />
        <label className="field"><span>谱文件路径</span><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="C:\\...\\sample.cmt" required disabled={!canWrite || busy} /></label>
        <div className="migration-form-footer"><span>支持 {diagnostic?.formats?.join(' / ').toUpperCase() ?? 'CDT / CMT / EDT / WDT'}</span><button className="primary-button" type="submit" disabled={!canWrite || busy || !diagnostic?.available}><Database size={15} />{busy ? '正在校验…' : '只读暂存并校验'}</button></div>
      </form>
      <section className="surface migration-reader-surface"><div className="surface-heading"><div><h2>旧版 Access 读取通道</h2></div><SquareTerminal size={17} /></div><div className={`reader-state ${diagnostic?.available ? 'ready' : 'unavailable'}`}>{diagnostic?.available ? <CheckCircle2 size={21} /> : <AlertTriangle size={21} />}<div><strong>{diagnostic?.message ?? '正在检测读取器…'}</strong><span>{diagnostic?.reader ?? '未选择读取后端'}</span></div></div><FormDisclosure title="读取通道技术详情"><dl className="reader-facts"><div><dt>Provider</dt><dd>{diagnostic?.provider ?? 'Microsoft.Jet.OLEDB.4.0'}</dd></div><div><dt>解析器版本</dt><dd>{diagnostic?.parser_version ?? 's08-spectrum-1'}</dd></div><div><dt>模式</dt><dd>只读 / 临时副本</dd></div></dl></FormDisclosure></section>
    </div>
    {activeRun && <section className="surface migration-report-surface" data-testid="spectrum-migration-report"><div className="surface-heading"><div><h2>迁移报告 <span className={`migration-status ${activeRun.status}`}>{activeRun.status === 'committed' ? '已提交' : activeRun.status === 'failed' ? '已回滚' : '待提交'}</span></h2></div><CopyableCode value={activeRun.fingerprint} visibleLength={16} /></div><div className="migration-count-grid spectrum-count-grid"><div><span>格式</span><strong>{activeRun.format.toUpperCase()}</strong><small>旧版 Access 数据文件</small></div><div><span>谱带记录</span><strong>{report?.record_count ?? 0}</strong><small>CCD_BAND 行数</small></div><div><span>帧布局</span><strong>{layout ? `${layout.frame_count} × ${layout.ccds_per_frame}` : '—'}</strong><small>帧数 × 每帧 CCD</small></div><div><span>CCD 点数</span><strong>{layout ? `${layout.ccd_count} × ${layout.points_per_ccd}` : '—'}</strong><small>有效 CCD × 每 CCD 点数</small></div></div><div className="migration-report-grid"><div><h3>一致性检查</h3><MigrationCheckList checks={report?.checks ?? {}} status={activeRun.status} /></div><div><h3>源文件指纹</h3><div className="spectrum-fingerprint"><strong title={activeRun.source_file.name}>{activeRun.source_file.name}</strong><code>{activeRun.source_file.sha256}</code><small>{(activeRun.source_file.size / 1024 / 1024).toFixed(2)} MB · {formatDateTime(activeRun.source_file.mtime_ns / 1e6)}</small></div>{layout && <div className="spectrum-layout-facts"><span>CCD 映射</span><code>{layout.ccd_indices.join(', ')}</code><span>端序</span><code>{layout.endianness}</code></div>}</div></div>{firstRecord && <div className="spectrum-record-summary"><h3>首条记录摘要</h3><div><span>谱带</span><strong>{String(firstRecord.band_name || firstRecord.long_name || '未命名')}</strong><span>样品</span><strong>{String(firstRecord.sample_name || '—')}</strong><span>坏帧</span><strong>{firstRecord.bad_frame_indices.length ? firstRecord.bad_frame_indices.map((item) => `${String(item.phase)}:${String(item.index)}`).join(', ') : '无'}</strong></div></div>}{(report?.issues.length ?? 0) > 0 && <div className="migration-issues"><h3>兼容性提示</h3>{report?.issues.map((issue) => <div key={issue.code}><AlertTriangle size={14} /><span><strong>{issue.message}</strong><code>{issue.code}</code></span></div>)}</div>}<div className="migration-commit-bar"><span>{activeRun.status === 'staged' ? '提交使用单个 SQLite 事务；任一记录失败都会完整回滚。' : activeRun.status === 'committed' ? '同一源文件 SHA-256 再次导入不会创建重复数据。' : '本次提交已回滚，可重新暂存后再试。'}</span>{activeRun.status === 'staged' && <button className="primary-button" onClick={commit} disabled={!canWrite || busy}><CheckCircle2 size={15} />原子提交</button>}</div></section>}
    <section className="surface migration-history-surface"><div className="surface-heading"><div><h2>最近迁移</h2></div><Archive size={17} /></div>{runs.length === 0 ? <div className="method-empty compact"><Archive size={24} /><p>还没有旧谱迁移记录。</p></div> : <div className="migration-history-list">{runs.map((run) => <button key={run.id} onClick={() => openRun(run)} className={activeRun?.id === run.id ? 'active' : ''}><span className={`migration-status ${run.status}`}>{run.status === 'committed' ? '已提交' : run.status === 'failed' ? '已回滚' : '待提交'}</span><div><strong title={run.source_file.name}>{run.source_file.name}</strong><small>{formatDateTime(run.created_at)} · {run.report.record_count} 条谱带</small></div><code title={run.fingerprint}>{run.fingerprint.slice(0, 12)}</code><ChevronRight size={15} /></button>)}</div>}</section>
  </div>
}
