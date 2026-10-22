import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, FolderOpen, X } from 'lucide-react'
import { request } from '../api/client'
import './open-legacy-file.css'

export type LegacyOpened = {
  format: string; run_id: string; reused: boolean; source_sha256: string
  method_ids: number[]; record_ids: number[]; task_ids?: number[]
  records?: Array<{id: number; sample_name: string; sample_no: number; layout_json: string; ignition_json: string}>
}
export type OpenPurpose = 'methods' | 'spectra' | 'analysis' | 'dispersion' | 'evaporation' | 'recalculate' | 'reports' | 'intensity' | 'edt-conversion' | 'batch-methods' | 'batch-spectra' | 'batch-results'

export function OpenLegacyFile({ token, purpose, label = '打开文件', disabled = false, multiple = false, onOpened, onBusyChange }: {
  token: string; purpose: OpenPurpose; label?: string; disabled?: boolean; multiple?: boolean
  onOpened: (result: LegacyOpened, path: string) => void | Promise<void>; onBusyChange?: (busy: boolean) => void
}) {
  const [extensions, setExtensions] = useState<string[] | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const pending = useRef(false)
  const generation = useRef(0)
  useEffect(() => {
    const current = ++generation.current
    pending.current = false
    setBusy(false); setExtensions(null); setError(''); setStatus(''); setPath(''); setExpanded(false)
    void request<Record<string, {extensions: string[]}>>('/api/v1/legacy-migration/open-options', {
      headers: {Authorization: `Bearer ${token}`}
    }).then(result => { if (current === generation.current) setExtensions(result[purpose]?.extensions ?? null) })
      .catch(() => {})
    return () => { generation.current++ }
  }, [token, purpose])
  const openPaths = async (paths: string[]) => {
    if (pending.current || disabled || !paths.length) return
    pending.current = true; setBusy(true); onBusyChange?.(true); setError(''); setStatus('')
    const current = generation.current
    let completed = 0
    let saved = 0
    try {
      for (const selected of paths) {
        if (current !== generation.current) return
        const result = await request<LegacyOpened>('/api/v1/legacy-migration/open-file', {
          method: 'POST', timeoutMs: 300000, headers: {Authorization: `Bearer ${token}`},
          body: JSON.stringify({path: selected, purpose})
        })
        try {
          const end = Math.max(selected.lastIndexOf('/'), selected.lastIndexOf('\\'))
          if (end >= 0) localStorage.setItem('geospectrum.last-open-directory', selected.slice(0, end + 1))
        } catch { /* optional browser preference */ }
        if (current !== generation.current) return
        saved++
        await onOpened(result, selected)
        completed++
        if (current === generation.current) setStatus(`${completed} 个文件已打开并保存${result.reused ? '（复用已有记录）' : ''}`)
      }
      if (current === generation.current) { setExpanded(false); setPath('') }
    } catch (failure) {
      if (current === generation.current) setError(`${saved ? `已保存 ${saved} 个文件；后续处理未完成：` : ''}${failure instanceof Error ? failure.message : '打开失败'}`)
    } finally {
      if (current === generation.current) { pending.current = false; setBusy(false); onBusyChange?.(false) }
    }
  }
  const choose = async () => {
    const invoke = window.__TAURI__?.core?.invoke
    if (!invoke) {
      try { if (!path) setPath(localStorage.getItem('geospectrum.last-open-directory') ?? '') } catch { /* optional browser preference */ }
      setExpanded(true); return
    }
    if (pending.current || disabled) return
    const current = generation.current
    pending.current = true; setBusy(true); onBusyChange?.(true)
    try {
      const paths = await invoke<string[]>('select_legacy_files', {extensions, multiple})
      if (current !== generation.current) return
      pending.current = false; setBusy(false); onBusyChange?.(false)
      await openPaths(paths)
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : String(failure))
    } finally { if (current === generation.current) { pending.current = false; setBusy(false); onBusyChange?.(false) } }
  }
  if (!extensions) return null
  return <div className="open-legacy-file" data-purpose={purpose}>
    <button type="button" className="secondary-button" aria-expanded={expanded} disabled={disabled || busy} onClick={() => void choose()}><FolderOpen size={15}/>{busy ? '正在打开…' : label}</button>
    {(expanded || error) && <div className="legacy-open-panel">
      <div className="legacy-open-heading"><strong>{label}</strong><button type="button" className="icon-button" aria-label="关闭文件打开面板" onClick={() => {setExpanded(false);setError('')}}><X size={14}/></button></div>
    {expanded && <div className="legacy-open-path">
      <label className="field"><span>{multiple ? '文件路径（每行一个）' : '文件路径'} · {extensions.map(ext => `.${ext}`).join(' / ')}</span>
        <textarea aria-label={`${label}路径`} rows={multiple ? 3 : 1} value={path} disabled={busy} onChange={event => setPath(event.target.value)}/></label>
      <button type="button" className="primary-button" disabled={disabled || busy || !path.trim()}
        onClick={() => void openPaths(multiple ? path.split(/\r?\n/).map(value => value.trim()).filter(Boolean) : [path.trim()])}>打开并保存</button>
    </div>}
    {error && <p className="auth-error" role="alert">{error}</p>}
    </div>}
    {status && <small role="status" className="file-open-status" title={status}><CheckCircle2 size={14}/><span>{status}</span></small>}
  </div>
}
