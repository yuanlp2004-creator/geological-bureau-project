import { confirmAction } from '../../platform/dialogs'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Download, Plus, RefreshCw, Trash2, FolderOpen } from 'lucide-react'
import { api, saveFile, type SampleQueue } from '../../api'
import type { MethodConditions } from '../../api/methods'
import { NumericInput as EmptyableNumberInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { SampleNumberTable } from './SampleNumberTable'
import { SectionHeading } from '../../components/SectionHeading'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'

export function SampleQueuePage({ token, onToast, entryRequest = 0, onUseQueue, onBusyChange }: { token: string; onToast: (message: string) => void; entryRequest?: number; onUseQueue?: (queue: SampleQueue) => void; onBusyChange?: (busy: boolean) => void }) {
  const [queues, setQueues] = useState<SampleQueue[]>([])
  const [selected, setSelected] = useState<SampleQueue | null>(null)
  const [name, setName] = useState('现场样品')
  const [entryName, setEntryName] = useState('')
  const [nameLength, setNameLength] = useState<10 | 12 | 20>(12)
  const [repeats, setRepeats] = useState(1)
  const [methodDefaults, setMethodDefaults] = useState<MethodConditions | null>(null)
  const [useMethodRepeats, setUseMethodRepeats] = useState(true)
  const [samEncoding,setSamEncoding] = useState<'gb18030'|'utf-8-sig'|''>('')
  const fileRef = useRef<HTMLInputElement>(null)
  const entryRef = useRef<HTMLInputElement>(null)
  const [entryBusy,setEntryBusy] = useState(false)
  const [editingItem, setEditingItem] = useState(false)
  const locked = entryBusy || editingItem
  useLayoutEffect(() => { onBusyChange?.(locked); return () => onBusyChange?.(false) }, [locked, onBusyChange])
  useEffect(() => {
    let live = true
    void api.currentMethod(token).then((current) => { if (live) setMethodDefaults(current.referenced_version?.conditions ?? null) }).catch(() => { if (live) setMethodDefaults(null) })
    return () => { live = false }
  }, [token])
  useEffect(() => {
    if (!useMethodRepeats || !methodDefaults) return
    const prefix = entryName.trim().toUpperCase()
    setRepeats(prefix.startsWith('S') ? methodDefaults.standard_repeats : prefix.startsWith('D') ? methodDefaults.control_repeats : methodDefaults.sample_repeats)
  }, [entryName, methodDefaults, useMethodRepeats])
  const [loading, setLoading] = useState(true)
  const handledEntry = useRef(0)
  useEffect(() => {
    if (!entryRequest || handledEntry.current === entryRequest || loading || locked) return
    handledEntry.current = entryRequest
    entryRef.current?.focus()
  }, [entryRequest, loading, locked])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await api.sampleQueues(token)
      setQueues(next)
      setSelected((current) =>
        current ? (next.find((item) => item.id === current.id) ?? next[0] ?? null) : (next[0] ?? null)
      )
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取样品队列')
    } finally {
      setLoading(false)
    }
  }, [token, onToast])
  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    if (selected) setNameLength(selected.name_length)
  }, [selected?.id, selected?.name_length])

  const changeNameLength = async (length: 10 | 12 | 20) => {
    if (locked) return
    if (!selected) return setNameLength(length)
    setEntryBusy(true)
    try {
      const next = await api.updateSampleQueue(token, selected.id,
        selected.items.map(item => ({ id: item.id, pre_name: item.pre_name, repeats: item.repeats })),
        length === 10 ? undefined : length)
      setSelected(next)
      setNameLength(next.name_length)
      setQueues(current => current.map(item => item.id === next.id ? next : item))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '样号长度切换失败')
    } finally { setEntryBusy(false) }
  }

  const create = async () => {
    if (entryBusy) return
    if (!reportInvalidNumericInput(document.querySelector('.sample-entry-form'))) return onToast('请先修正重复次数')
    setEntryBusy(true)
    try {
      const next = await api.createSampleQueue(token, { name, name_length: nameLength === 10 ? undefined : nameLength, items: [{ pre_name: entryName.trim().startsWith(',')?'':entryName, repeats:entryName.trim().startsWith(',')?0:repeats }] })
      setQueues((current) => [next, ...current])
      setSelected(next)
      advanceName()
      onToast('样品队列已创建')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '创建失败')
    } finally { setEntryBusy(false) }
  }

  const importFile = async (file: File) => {
    if (locked) return
    setEntryBusy(true)
    try {
      const next = await api.importSampleQueue(token, file.name, new Uint8Array(await file.arrayBuffer()),undefined,file.lastModified,samEncoding || undefined)
      setQueues((current) => [next, ...current.filter((item) => item.id !== next.id)])
      setSelected(next)
      onToast(`已导入 ${next.record_count} 条样品记录`)
    } catch (error) {
      onToast(error instanceof Error ? error.message : 'SAM 导入失败')
    } finally { setEntryBusy(false) }
  }

  const chooseFile = async () => {
    if (locked) return
    const invoke = window.__TAURI__?.core?.invoke
    if (!invoke) { fileRef.current?.click(); return }
    setEntryBusy(true)
    try {
      const selected = await invoke<{name: string; bytes: number[]; last_modified: number} | null>('select_sample_file')
      if (selected) await importFile(new File([new Uint8Array(selected.bytes)], selected.name, {lastModified: selected.last_modified}))
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)) }
    finally { setEntryBusy(false) }
  }

  const exportQueue = async () => {
    if (!selected) return
    const result = await api.exportSampleQueue(token, selected.id)
    const path = await saveFile(result.blob, `queue-${selected.id}.sam`)
    onToast(path ? `SAM 文件已保存：${path}` : '已取消保存')
  }

  const addItem = async () => {
    if (!selected || entryBusy) return
    if (!reportInvalidNumericInput(document.querySelector('.sample-entry-form'))) return onToast('请先修正重复次数')
    setEntryBusy(true)
    try {
      const next = await api.updateSampleQueue(token, selected.id, [
        ...selected.items.map((item) => ({ id: item.id, pre_name: item.pre_name, repeats: item.repeats })),
        { pre_name: entryName.trim().startsWith(',')?'':entryName, repeats:entryName.trim().startsWith(',')?0:repeats }
      ])
      setSelected(next)
      setQueues((current) => current.map((item) => (item.id === next.id ? next : item)))
      advanceName()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '添加失败')
    } finally { setEntryBusy(false) }
  }

  const advanceName = () => {
    const value = entryName.trim()
    setEntryName(/^\d+$/.test(value) ? (BigInt(value)+1n).toString() : '')
    entryRef.current?.focus()
  }
  const entryCommand = async () => {
    if (locked) return
    const value=entryName.trim()
    if (value.startsWith('.')) { setEntryName('');entryRef.current?.blur();onToast('样号录入已结束');return }
    if (value.startsWith('/')) {
      const item=selected?.items[selected.items.length-1]
      if (item) { setEntryBusy(true);try { await deleteItem(item.id);setEntryName('') } finally { setEntryBusy(false) } }
      return
    }
    if (selected) await addItem();else await create()
  }

  const clearQueue = async () => {
    if (!selected || locked) return
    setEntryBusy(true)
    try {
      if (!(await confirmAction('清空当前队列？'))) return
      const next = await api.clearSampleQueue(token, selected.id)
      setSelected(next)
      setQueues((current) => current.map((item) => (item.id === next.id ? next : item)))
      onToast('队列已清空')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '清空失败')
    } finally { setEntryBusy(false) }
  }

  const deleteItem = async (itemId: number) => {
    if (!selected || editingItem) return
    setEntryBusy(true)
    try {
      const next = await api.deleteSampleItem(token, selected.id, itemId)
      setSelected(next)
      setQueues((current) => current.map((item) => (item.id === next.id ? next : item)))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '删除失败')
    } finally { setEntryBusy(false) }
  }

  const editItem = async (itemId: number, preName: string) => {
    if (!selected || entryBusy) throw new Error('队列正忙，请稍后保存')
    setEntryBusy(true)
    try {
      const next = await api.updateSampleQueue(token, selected.id,
        selected.items.map(item => ({ id: item.id, pre_name: item.id === itemId ? preName : item.pre_name, repeats: item.repeats })))
      setSelected(next)
      setQueues(current => current.map(item => item.id === next.id ? next : item))
      onToast('样号已修改')
    } finally { setEntryBusy(false) }
  }

  return (
    <div className="page-content sample-queue-page refined-page remaining-page">
      
      {onUseQueue && <button type="button" className="primary-button" disabled={!selected?.items.length || locked} onClick={() => { if (selected) onUseQueue(selected) }}>使用此样号表</button>}
      <div className="sample-queue-grid">
        <section className="surface queue-context">
          <div className="surface-heading"><SectionHeading title="样品队列" /></div>
          <div className="queue-context-controls">
          <label className="field">
            <span>选择样品队列</span>
            <select
              value={selected?.id ?? ''}
              title={selected?.name}
              disabled={loading || locked}
              onChange={(event) => setSelected(queues.find((queue) => queue.id === Number(event.target.value)) ?? null)}
            >
              <option value="">{loading ? '正在读取…' : '新建队列'}</option>
              {queues.map((queue) => (
                <option key={queue.id} value={queue.id}>
                  {queue.name} · {queue.record_count} 条记录 · {queue.expanded_bands} 谱带
                </option>
              ))}
            </select>
          </label>
         <div className="page-intro-actions file-actions">
          <button type="button" className="secondary-button" disabled={locked} onClick={() => void chooseFile()}>
            <FolderOpen size={15} />打开样品号
          </button>
            <input ref={fileRef}
              type="file"
              accept=".sam,.txt"
              hidden
              disabled={locked}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.currentTarget.value = ''
                if (file) void importFile(file)
              }}
            />
          <button className="secondary-button" disabled={locked} onClick={() => setSelected(null)}>
            <Plus size={15} />
            新建队列
          </button>
          <button className="secondary-button" onClick={() => void exportQueue()} disabled={!selected || locked}>
            <Download size={15} />
            导出 SAM
          </button>
          <button className="secondary-button" disabled={locked} onClick={() => void load()}>
            <RefreshCw size={15} />
            刷新
          </button>
        </div></div></section>
        <section className="surface sample-editor">
          <div className="surface-heading">
            <div>
              <h2>{selected?.name ?? '新建队列'}</h2>
            </div>
            {selected && (
              <div className="page-intro-actions file-actions">
                <span className="status-chip">{selected.expanded_bands} 谱带</span>
                <button className="icon-button compact danger" title="清空队列" disabled={locked} onClick={() => void clearQueue()}>
                  <SpectroscopyIcon name="sample-list-clear" />
                </button>
              </div>
            )}
          </div>
          <div className={selected ? 'sample-entry-form sample-entry-existing' : 'sample-entry-form'}>
            <div className="sample-entry-fields">
              <label className="field small-field">
                <span>样号长度</span>
                <select value={nameLength} disabled={locked} onChange={event => void changeNameLength(Number(event.target.value) as 10 | 12 | 20)}>
                  <option value={10} disabled={selected?.name_length !== 10}>旧版 10 字节</option>
                  <option value={12}>12 位</option>
                  <option value={20}>20 位</option>
                </select>
              </label>
              {!selected && (
                <label className="field">
                  <span>队列名称</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} />
                </label>
              )}
              <label className="field">
                <span>样品名</span>
                <input
                  ref={entryRef}
                  value={entryName}
                  onChange={(event) => setEntryName(event.target.value)}
                  disabled={locked}
                  onKeyDown={event => { if (event.key==='Enter' && !event.nativeEvent.isComposing) { event.preventDefault();void entryCommand() } }}
                  placeholder="例如 A001 / S10"
                />
              </label>
              <label className="field small-field">
                <span>重复次数</span>
                <EmptyableNumberInput min={0} max={10} value={repeats} disabled={locked} onValueChange={(value) => { setUseMethodRepeats(false); setRepeats(value) }} />
              </label>
            </div>
            <div className="sample-entry-actions">
              {methodDefaults && (
                <label className="checkbox-row sample-repeat-default">
                  <input type="checkbox" checked={useMethodRepeats} disabled={locked} onChange={(event) => setUseMethodRepeats(event.target.checked)} />
                  <span>按当前方法默认次数</span>
                </label>
              )}
              <small>回车录入并递增数字样号；逗号插空，点号结束，斜杠删除末项。</small>
              <label className="field"><span>SAM 编码</span><select value={samEncoding} disabled={locked} onChange={e => setSamEncoding(e.target.value as typeof samEncoding)}>
                <option value="">旧版 GB18030（自动识别 UTF-8 BOM）</option><option value="utf-8-sig">UTF-8</option><option value="gb18030">GB18030</option></select></label>
              <button className="primary-button" disabled={locked} onClick={() => void entryCommand()}>
                <SpectroscopyIcon name={selected ? 'insert-sample' : 'sample-list-input'} />
                {selected ? '插入样品' : '创建队列'}
              </button>
            </div>
          </div>
          {selected && (
            <SampleNumberTable key={selected.id} items={selected.items} nameLength={selected.name_length}
              onDelete={deleteItem} onEdit={editItem} onEditingChange={setEditingItem} busy={entryBusy} />
          )}
        </section>
      </div>
    </div>
  )
}
