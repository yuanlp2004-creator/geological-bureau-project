import { LegacySourcePicker } from '../../components/LegacySourcePicker'
import { FormDisclosure } from '../../layout/TaskLayout'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { AlertTriangle, Archive, CheckCircle2, ChevronRight, Database, FolderOpen, Info, RefreshCw, SquareTerminal } from 'lucide-react'
import { api, type AuthUser, type LegacyMigrationDiagnostic, type LegacyMigrationRun } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { MigrationCheckList } from './MigrationCheckList'
import { formatDateTime } from '../../components/dateFormat'

export function LegacyMigrationPage({ token, currentUser, onToast }: { token: string; currentUser: AuthUser; onToast: (message: string) => void }) {
  const [diagnostic, setDiagnostic] = useState<LegacyMigrationDiagnostic | null>(null)
  const [runs, setRuns] = useState<LegacyMigrationRun[]>([])
  const [activeRun, setActiveRun] = useState<LegacyMigrationRun | null>(null)
  const [paths, setPaths] = useState({ mtd_path: '', cfg_path: '', opt_path: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canWrite = currentUser.permissions.includes('migration.write')

  const load = useCallback(async () => {
    try {
      const [nextDiagnostic, history] = await Promise.all([
        api.legacyMigrationDiagnostics(token),
        api.legacyMigrationRuns(token),
      ])
      setDiagnostic(nextDiagnostic)
      setRuns(history.runs)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取迁移状态')
    }
  }, [token])

  useEffect(() => { void load() }, [load])

  const stage = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const run = await api.stageLegacyMigration(token, paths)
      setActiveRun(run)
      await load()
      onToast(run.already_committed ? '相同源文件已经提交，没有创建重复数据' : '旧版文件已只读暂存并通过结构校验')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂存失败')
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    if (!activeRun || !window.confirm('确认把本次暂存的方法、谱线、色散和配置快照原子写入当前项目？')) return
    setBusy(true)
    setError(null)
    try {
      const run = await api.commitLegacyMigration(token, activeRun.id)
      setActiveRun(run)
      await load()
      onToast(run.already_committed ? '迁移已提交；本次未生成重复记录' : '旧版方法与配置已完成原子迁移')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '提交失败，目标写入已回滚')
    } finally {
      setBusy(false)
    }
  }

  const openRun = async (run: LegacyMigrationRun) => {
    setBusy(true)
    try {
      setActiveRun(await api.legacyMigrationRun(token, run.id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取迁移报告')
    } finally {
      setBusy(false)
    }
  }

  const counts = activeRun?.report.counts
  const issues = activeRun?.report.issues ?? []
  const sourceEntries = Object.entries(activeRun?.source_files ?? {})
  return <div className="page-content migration-page refined-page remaining-page" data-testid="legacy-migration-page">
    <section className="hero-row compact-hero"><div><h1>旧版方法迁移</h1><p>用 32 位 Jet 读取系统临时副本，校验后一次性提交方法、谱线、色散与配置快照。</p></div><div className="hero-actions"><span className={`migration-reader-pill ${diagnostic?.available ? 'ready' : 'unavailable'}`}><span className={`status-dot ${diagnostic?.available ? 'online' : 'offline'}`} />{diagnostic?.available ? 'Jet 读取器就绪' : '读取器不可用'}</span><button className="secondary-button" onClick={load} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />重新检测</button></div></section>
    {error && <div className="auth-error migration-error"><AlertTriangle size={15} />{error}</div>}
    <div className="migration-top-grid">
      <form className="surface migration-source-surface" onSubmit={stage}>
        <div className="surface-heading"><div><h2>选择旧版源文件</h2></div><FolderOpen size={17} /></div>
        <p className="migration-note"><Info size={14} />源文件不会由 Jet 直接打开；服务先复制到操作系统临时目录，并在前后核对 SHA-256、大小和修改时间。</p>
        <LegacySourcePicker token={token} kind="legacy-migration" disabled={!canWrite || busy} selectedPath={paths.mtd_path} onSelect={(source) => setPaths({ mtd_path: source.paths.mtd_path ?? '', cfg_path: source.paths.cfg_path ?? '', opt_path: source.paths.opt_path ?? '' })} />
        <div className="migration-paths">
          <label className="field"><span>方法库 · DIRECT.MTD</span><input value={paths.mtd_path} onChange={(event) => setPaths({ ...paths, mtd_path: event.target.value })} placeholder="C:\\...\\DIRECT.MTD" required disabled={!canWrite || busy} /></label>
          <label className="field"><span>设备配置 · DIRECT.CFG</span><input value={paths.cfg_path} onChange={(event) => setPaths({ ...paths, cfg_path: event.target.value })} placeholder="C:\\...\\DIRECT.CFG" required disabled={!canWrite || busy} /></label>
          <label className="field"><span>软件选项 · DIRECT.OPT</span><input value={paths.opt_path} onChange={(event) => setPaths({ ...paths, opt_path: event.target.value })} placeholder="C:\\...\\DIRECT.OPT" required disabled={!canWrite || busy} /></label>
        </div>
        <div className="migration-form-footer"><span>暂存阶段不会写入正式方法表。</span><button className="primary-button" type="submit" disabled={!canWrite || busy || !diagnostic?.available}><Database size={15} />{busy ? '正在校验…' : '只读暂存并校验'}</button></div>
      </form>
      <section className="surface migration-reader-surface">
        <div className="surface-heading"><div><h2>32 位读取通道</h2></div><SquareTerminal size={17} /></div>
        <div className={`reader-state ${diagnostic?.available ? 'ready' : 'unavailable'}`}>{diagnostic?.available ? <CheckCircle2 size={21} /> : <AlertTriangle size={21} />}<div><strong>{diagnostic?.message ?? '正在检测读取器…'}</strong><span>{diagnostic?.reader ?? '未选择读取后端'}</span></div></div>
        <FormDisclosure title="读取通道技术详情"><dl className="reader-facts"><div><dt>Provider</dt><dd>{diagnostic?.provider ?? 'Microsoft.Jet.OLEDB.4.0'}</dd></div><div><dt>进程位数</dt><dd>{diagnostic?.process_bits ? `${diagnostic.process_bits}-bit` : '—'}</dd></div><div><dt>缺失时影响</dt><dd>仅禁用旧版迁移</dd></div><div><dt>读取模式</dt><dd>临时副本 · Read</dd></div></dl></FormDisclosure>
      </section>
    </div>

    {activeRun && <section className="surface migration-report-surface" data-testid="migration-report">
      <div className="surface-heading"><div><h2>迁移报告 <span className={`migration-status ${activeRun.status}`}>{activeRun.status === 'committed' ? '已提交' : activeRun.status === 'failed' ? '已回滚' : '待提交'}</span></h2></div><CopyableCode value={activeRun.fingerprint} visibleLength={16} /></div>
      <div className="migration-count-grid"><div><span>方法</span><strong>{counts?.methods ?? 0}</strong><small>已配对 MTD_PRIM / BURN / WSTC</small></div><div><span>旧谱线</span><strong>{counts?.spectral_lines ?? 0}</strong><small>不含每方法自动生成的参考基线</small></div><div><span>色散曲线</span><strong>{counts?.dispersion_curves ?? 0}</strong><small>系数与 CCD BLOB 已校验</small></div><div><span>配置文件</span><strong>2</strong><small>CFG / OPT 保存为非激活快照</small></div></div>
      <div className="migration-report-grid">
        <div><h3>一致性检查</h3><MigrationCheckList checks={activeRun.report.checks} status={activeRun.status} /></div>
        <div><h3>源文件指纹</h3><div className="migration-source-list">{sourceEntries.map(([kind, source]) => <div key={kind}><span>{kind.toUpperCase()}</span><div><strong title={source.path}>{source.name}</strong><code title={source.sha256}>{source.sha256.slice(0, 18)}…</code></div><small>{(source.size / 1024).toFixed(1)} KB</small></div>)}</div></div>
      </div>
      {issues.length > 0 && <div className="migration-issues"><h3>兼容性说明</h3>{issues.map((issue) => <div key={`${issue.code}-${issue.field ?? ''}`}><AlertTriangle size={14} /><span><strong>{issue.message}</strong><code>{issue.code}{issue.field ? ` · ${issue.field}` : ''}</code></span></div>)}</div>}
      {activeRun.error && <div className="migration-failure"><AlertTriangle size={15} /><span><strong>{activeRun.error.message}</strong><code>{activeRun.error.code}</code></span></div>}
      <div className="migration-commit-bar"><span>{activeRun.status === 'staged' ? '提交使用单个 SQLite 事务；任一目标记录失败都会完整回滚。' : activeRun.status === 'committed' ? `提交时间 ${activeRun.committed_at ? formatDateTime(activeRun.committed_at) : '—'}；相同源指纹再次导入不会创建重复数据。` : '上次提交已回滚，可重新暂存后再试。'}</span>{activeRun.status === 'staged' && <button className="primary-button" onClick={commit} disabled={!canWrite || busy}><CheckCircle2 size={15} />原子提交</button>}</div>
    </section>}

    <section className="surface migration-history-surface"><div className="surface-heading"><div><h2>最近迁移</h2></div><Archive size={17} /></div>{runs.length === 0 ? <div className="method-empty compact"><Archive size={24} /><p>还没有旧版迁移记录。</p></div> : <div className="migration-history-list">{runs.map((run) => { const sourceName = run.source_files.mtd?.name ?? 'DIRECT.MTD'; return <button key={run.id} onClick={() => openRun(run)} className={activeRun?.id === run.id ? 'active' : ''}><span className={`migration-status ${run.status}`}>{run.status === 'committed' ? '已提交' : run.status === 'failed' ? '已回滚' : '待提交'}</span><div><strong title={sourceName}>{sourceName}</strong><small>{formatDateTime(run.created_at)} · {run.report.counts.methods} 方法 / {run.report.counts.spectral_lines} 谱线</small></div><code title={run.fingerprint}>{run.fingerprint.slice(0, 12)}</code><ChevronRight size={15} /></button> })}</div>}</section>
  </div>
}
