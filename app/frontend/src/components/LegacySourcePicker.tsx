import { useCallback, useEffect, useRef, useState } from 'react'
import { FolderOpen, RefreshCw } from 'lucide-react'
import { api, selectLegacyDirectory, type LegacySource, type LegacySourceKind, type LegacySourceScan } from '../api'


export function LegacySourcePicker({ token, kind, disabled, selectedPath, onSelect }: {
  token: string; kind: LegacySourceKind; disabled: boolean; selectedPath: string; onSelect: (source: LegacySource) => void
}) {
  const [root, setRoot] = useState(() => sessionStorage.getItem('geospectrum.legacy-directory') ?? '')
  const [scan, setScan] = useState<LegacySourceScan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const requestId = useRef(0)
  const detect = useCallback(async (directory?: string) => {
    const id = ++requestId.current
    setBusy(true); setError(''); setScan(null)
    try {
      const result = await api.discoverLegacySources(token, kind, directory)
      if (id === requestId.current) setScan(result)
    } catch (cause) {
      if (id === requestId.current) setError(cause instanceof Error ? cause.message : '检测失败')
    } finally { if (id === requestId.current) setBusy(false) }
  }, [token, kind])
  useEffect(() => {
    void detect(sessionStorage.getItem('geospectrum.legacy-directory') || undefined)
    return () => { requestId.current += 1 }
  }, [detect])
  const choose = async () => {
    setError('')
    try {
      const directory = await selectLegacyDirectory()
      if (directory) {
        setRoot(directory); sessionStorage.setItem('geospectrum.legacy-directory', directory)
        void detect(directory)
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法选择目录') }
  }
  const candidates = scan?.candidates.filter((item) => item.path.toLocaleLowerCase().includes(filter.toLocaleLowerCase())) ?? []
  return <section className="legacy-source-picker" aria-label="自动检测旧版文件">
    <div className="legacy-source-actions">
      <button type="button" className="secondary-button" disabled={busy || disabled} onClick={() => { setRoot(''); sessionStorage.removeItem('geospectrum.legacy-directory'); void detect() }}><RefreshCw size={14} className={busy ? 'spin' : ''} />自动检测</button>
      <button type="button" className="secondary-button" disabled={busy || disabled} onClick={() => void choose()}><FolderOpen size={14} />选择旧版目录</button>
      <span>选择文件后自动填入下方路径</span>
    </div>
    <details className="legacy-source-custom"><summary>指定其他目录</summary><div className="legacy-source-actions"><input aria-label="旧版目录" value={root} onChange={(event) => setRoot(event.target.value)} placeholder="旧版程序或数据文件夹" disabled={busy || disabled} /><button type="button" className="secondary-button" disabled={busy || disabled || !root.trim()} onClick={() => { sessionStorage.setItem('geospectrum.legacy-directory', root.trim()); void detect(root.trim()) }}>检测目录</button></div></details>
    {error && <p className="auth-error" role="alert">{error}</p>}
    {busy && <p role="status">正在查找旧版文件…</p>}
    {scan && <>
      <div className="legacy-source-summary"><span>找到 {scan.candidates.length} 项 · 仅检测文件，内容将在暂存时校验</span>{scan.candidates.length > 5 && <input aria-label="筛选旧版文件" placeholder="按文件名或目录筛选" value={filter} onChange={(event) => setFilter(event.target.value)} />}</div>
      {candidates.length === 0 && <p className="migration-note">{scan.candidates.length ? '没有匹配项，请修改筛选条件。' : '未找到对应文件，请选择旧版程序或数据所在目录。'}</p>}
      <div className="legacy-source-list">{candidates.map((item) => <button type="button" key={item.path} className={selectedPath === item.path ? 'selected' : ''} disabled={disabled || item.missing.length > 0} onClick={() => onSelect(item)}><strong>{item.name}<small>{(item.size / 1024 / 1024).toFixed(2)} MB{selectedPath === item.path ? ' · 已选择' : ''}</small></strong><span>{item.directory}</span>{item.missing.length > 0 && <em>缺少 {item.missing.join('、')}，请选择包含完整三文件的目录</em>}</button>)}</div>
      <details className="legacy-source-custom"><summary>已检测目录（{scan.roots.length}）</summary>{scan.roots.map((path) => <p key={path}>{path}</p>)}</details>
      {scan.warnings.map((warning, index) => <p className="migration-note" key={index}>{warning}</p>)}
    </>}
  </section>
}
