import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { FolderOpen, X } from 'lucide-react'
import { api, type CurrentMethodState, type MethodRecord } from '../../api'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'

function isPublished(method: MethodRecord) {
  return Boolean(method.published_version && method.status !== 'deleted')
}

export async function openPublishedMethod(token: string, id: number): Promise<CurrentMethodState> {
  const method = await api.openMethod(token, id, true)
  const active = method.status === 'active'
  // The open receipt contains the published version selected by the server.
  return {
    method_id: method.id,
    version: method.current_version,
    title: method.name,
    work_type: method.work_type,
    status: method.status,
    action_state: 'idle',
    actions: { can_acquire: active, can_analyze: active, can_pause: active, can_resume: !active, can_delete: true },
    method,
    referenced_version: method.published_version
  }
}

export function OpenMethodDialog({ token, methods, selectedId, busy, loading = false, error, onOpen, onCancel, onImported, onBusyChange }: {
  token: string
  methods: MethodRecord[]
  selectedId: number | null
  busy: boolean
  loading?: boolean
  error: string | null
  onOpen: (id: number) => void
  onCancel: () => void
  onImported: () => Promise<void>
  onBusyChange: (busy: boolean) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [choice, setChoice] = useState<number | null>(selectedId)
  const selected = methods.find(method => method.id === choice)
    ?? methods.find(method => method.id === selectedId)
    ?? methods.find(isPublished)
  const available = selected && isPublished(selected)
  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement
    element?.showModal()
    element?.querySelector('select')?.focus()
    return () => {
      element?.close()
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
    }
  }, [])
  return <dialog ref={dialog} className="method-open-dialog" aria-labelledby="method-open-title"
    onKeyDown={event => { if (event.key === 'Escape') event.stopPropagation() }}
    onCancel={event => { event.preventDefault(); if (!busy) onCancel() }}>
    <header><h2 id="method-open-title">打开方法</h2><button type="button" className="icon-button" aria-label="取消打开方法" disabled={busy} onClick={onCancel}><X size={17} /></button></header>
    <form onSubmit={event => { event.preventDefault(); if (available && !busy && !loading) onOpen(selected.id) }}>
      <label className="field"><span>选择要打开的方法</span>
        <select autoFocus aria-label="选择要打开的方法" value={selected?.id ?? ''} disabled={busy || loading || !methods.length} onChange={event => setChoice(Number(event.target.value))}>
          {!selected && <option value="">{loading ? '正在读取方法列表…' : '暂无已发布方法'}</option>}
          {methods.map(method => <option key={method.id} value={method.id} disabled={!isPublished(method)}>
            {method.name}{method.is_current ? ' · 当前运行' : ''}{!method.published_version ? ' · 尚未保存' : method.status === 'paused' ? ' · 打开时恢复使用' : ''}
          </option>)}
        </select>
      </label>
      <p>确认后载入已保存的参数和谱线，并设为当前运行方法。</p>
      {error && <p className="auth-error" role="alert">{error}</p>}
      <footer><button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>取消</button>
        <button type="submit" className="primary-button" disabled={busy || loading || !available}><FolderOpen size={15} />{busy ? '正在打开…' : '打开所选方法'}</button></footer>
    </form>
    <div className="method-open-file"><OpenLegacyFile token={token} purpose="methods" label="打开方法文件" disabled={busy || loading} onBusyChange={onBusyChange}
      onOpened={async result => { await onImported(); if (result.method_ids.length) setChoice(result.method_ids[0]) }} /></div>
  </dialog>
}

export function WorkspaceOpenMethodDialog({ token, selectedId, switchBlockedReason, beforeOpen, onOpened, onCancel }: {
  token: string
  selectedId: number | null
  switchBlockedReason: () => string | null
  beforeOpen: () => Promise<boolean>
  onOpened: (method: CurrentMethodState) => void
  onCancel: () => void
}) {
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pending = useRef(false)
  const mounted = useRef(false)
  useLayoutEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  useEffect(() => {
    let cancelled = false
    void api.methods(token).then(next => {
      if (!cancelled) setMethods(next)
    }).catch(cause => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : '无法读取方法列表')
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [token])

  const updateBusy = (next: boolean) => {
    pending.current = next
    setBusy(next)
  }
  const open = async (id: number) => {
    if (pending.current) return
    const blocked = switchBlockedReason()
    if (blocked) { setError(blocked); return }
    updateBusy(true)
    setError(null)
    try {
      if (!await beforeOpen() || !mounted.current) return
      const currentBlock = switchBlockedReason()
      if (currentBlock) { setError(currentBlock); return }
      const current = await openPublishedMethod(token, id)
      if (mounted.current) onOpened(current)
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : '打开方法失败，请重试')
    } finally {
      if (mounted.current) updateBusy(false)
    }
  }
  const reloadAfterImport = async () => {
    const next = await api.methods(token)
    if (mounted.current) {
      setMethods(next)
      setError(null)
    }
  }
  return <OpenMethodDialog token={token} methods={methods} selectedId={selectedId} loading={loading}
    busy={busy} error={error} onOpen={id => void open(id)} onCancel={onCancel}
    onImported={reloadAfterImport} onBusyChange={updateBusy} />
}
