import { useEffect, useRef, useState } from 'react'
import { FolderOpen, X } from 'lucide-react'
import type { MethodRecord } from '../../api'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'

export function OpenMethodDialog({ token, methods, selectedId, busy, error, onOpen, onCancel, onImported, onBusyChange }: {
  token: string
  methods: MethodRecord[]
  selectedId: number | null
  busy: boolean
  error: string | null
  onOpen: (id: number) => void
  onCancel: () => void
  onImported: () => Promise<void>
  onBusyChange: (busy: boolean) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [choice, setChoice] = useState<number | null>(selectedId ?? methods[0]?.id ?? null)
  const selected = methods.find(method => method.id === choice)
  const available = selected?.published_version && selected.status !== 'deleted'
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
    onCancel={event => { event.preventDefault(); if (!busy) onCancel() }}>
    <header><h2 id="method-open-title">打开方法</h2><button type="button" className="icon-button" aria-label="取消打开方法" disabled={busy} onClick={onCancel}><X size={17} /></button></header>
    <form onSubmit={event => { event.preventDefault(); if (available && choice != null && !busy) onOpen(choice) }}>
      <label className="field"><span>选择要打开的方法</span>
        <select autoFocus aria-label="选择要打开的方法" value={choice ?? ''} disabled={busy || !methods.length} onChange={event => setChoice(Number(event.target.value))}>
          {!methods.length && <option value="">暂无方法，请先新建或打开方法文件</option>}
          {methods.map(method => <option key={method.id} value={method.id} disabled={!method.published_version || method.status === 'deleted'}>
            {method.name}{method.is_current ? ' · 当前运行' : ''}{!method.published_version ? ' · 尚未保存' : method.status === 'paused' ? ' · 打开时恢复使用' : ''}
          </option>)}
        </select>
      </label>
      <p>确认后载入已保存的参数和谱线，并设为当前运行方法。</p>
      {error && <p className="auth-error" role="alert">{error}</p>}
      <footer><button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>取消</button>
        <button type="submit" className="primary-button" disabled={busy || !available}><FolderOpen size={15} />{busy ? '正在打开…' : '打开所选方法'}</button></footer>
    </form>
    <div className="method-open-file"><OpenLegacyFile token={token} purpose="methods" label="打开方法文件" disabled={busy} onBusyChange={onBusyChange}
      onOpened={async result => { await onImported(); setChoice(result.method_ids[0] ?? choice) }} /></div>
  </dialog>
}
