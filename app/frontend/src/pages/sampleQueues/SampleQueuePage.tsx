import { confirmAction } from '../../platform/dialogs'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Download, Plus, RefreshCw, Trash2, FolderOpen } from 'lucide-react'
import { api, saveFile, type SampleQueue } from '../../api'
import type { MethodConditions } from '../../api/methods'
import type { SamEncoding } from '../../api/sampleQueues'
import { NumericInput as EmptyableNumberInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { SampleNumberTable } from './SampleNumberTable'
import { useSamImport } from './useSamImport'
import { SectionHeading } from '../../components/SectionHeading'
import { nextSampleName } from '../../components/useSampleGrid'

export function SampleQueuePage({ token, onToast, entryRequest = 0, confirmation, onBusyChange, insertion }: {
  token: string
  onToast: (message: string) => void
  entryRequest?: number
  confirmation?: { target: HTMLElement | null; onConfirm: (queue: SampleQueue) => void }
  onBusyChange?: (busy: boolean) => void
  insertion?: { queueId: number; itemId: number }
}) {
  const confirmInDialog = Boolean(confirmation)
  const [selectedItemId,setSelectedItemId]=useState<number|null>(insertion?.itemId??null)
  const [queues, setQueues] = useState<SampleQueue[]>([])
  const [selected, setSelected] = useState<SampleQueue | null>()
  const [name, setName] = useState('现场样品')
  const [entryName, setEntryName] = useState('')
  const [nameLength, setNameLength] = useState<10 | 12 | 20>(12)
  const [manualRepeats, setManualRepeats] = useState<number | null>(null)
  const [methodDefaults, setMethodDefaults] = useState<MethodConditions | null>(null)
  const { importSam, samPreview } = useSamImport()
  const fileRef = useRef<HTMLInputElement>(null)
  const entryRef = useRef<HTMLInputElement>(null)
  const [entryBusy,setEntryBusy] = useState(false)
  const [editingItem, setEditingItem] = useState(false)
  const [loading, setLoading] = useState(true)
  const locked = entryBusy || editingItem || loading
  useLayoutEffect(() => { onBusyChange?.(locked); return () => onBusyChange?.(false) }, [locked, onBusyChange])
  useEffect(() => {
    let live = true
    void api.currentMethod(token).then((current) => { if (live) setMethodDefaults(current.referenced_version?.conditions ?? null) }).catch(() => { if (live) setMethodDefaults(null) })
    return () => { live = false }
  }, [token])
  const repeatsFor = (sampleName: string) => {
    if (manualRepeats !== null) return manualRepeats
    const prefix = sampleName.trim().charAt(0).toUpperCase()
    return (prefix === 'S' ? methodDefaults?.standard_repeats
      : prefix === 'D' ? methodDefaults?.control_repeats : methodDefaults?.sample_repeats) ?? 1
  }
  const repeats = repeatsFor(entryName)
  const handledEntry = useRef(0)
  useEffect(() => {
    if (!entryRequest || handledEntry.current === entryRequest || loading || locked) return
    handledEntry.current = entryRequest
    entryRef.current?.focus()
  }, [entryRequest, loading, locked])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [next, currentQueue] = await Promise.all([api.sampleQueues(token), api.currentSampleQueue(token)])
      setQueues(next)
      setSelected(current => {
        const id = confirmInDialog && current !== undefined ? current?.id : insertion?.queueId ?? currentQueue?.id ?? current?.id
        return next.find(item => item.id === id) ?? null
      })
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法读取样品队列')
    } finally {
      setLoading(false)
    }
  }, [token, onToast, insertion?.queueId, confirmInDialog])
  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    if (selected) setNameLength(selected.name_length)
  }, [selected?.id, selected?.name_length])

  const chooseQueue = async (queue: SampleQueue | null) => {
    if (locked) return
    if (confirmInDialog) {
      setSelected(queue)
      return
    }
    setEntryBusy(true)
    try { await api.selectSampleQueue(token, queue?.id ?? null); setSelected(queue) }
    catch (error) { onToast(error instanceof Error ? error.message : '选择样号表失败') }
    finally { setEntryBusy(false) }
  }

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
      if (!confirmInDialog) await api.selectSampleQueue(token, next.id)
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
      const workbook = /\.xlsx$/i.test(file.name)
      if (workbook && file.size > 5_000_000) throw new Error('Excel 文件超过 5 MB。')
      const bytes = new Uint8Array(await file.arrayBuffer())
      const read = (encoding?: SamEncoding) =>
        api.importSampleQueue(token, file.name, bytes, undefined, file.lastModified, encoding)
      const next = workbook ? await read() : await importSam(file.name, read)
      if (!next) return
      if (!confirmInDialog) await api.selectSampleQueue(token, next.id)
      setQueues((current) => [next, ...current.filter((item) => item.id !== next.id)])
      setSelected(next)
      onToast(`已导入 ${next.record_count} 条样品记录`)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '样号文件导入失败')
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

  const exportQueue = async (format: 'xlsx' | 'sam') => {
    if (!selected || locked) return
    setEntryBusy(true)
    try {
      const result = await api.exportSampleQueue(token, selected.id, format)
      const filename = format === 'xlsx' ? `样号表-${selected.id}.xlsx` : `queue-${selected.id}.sam`
      const path = await saveFile(result.blob, filename)
      onToast(path ? `样号文件已保存：${path}` : '已取消保存')
    } catch(error){onToast(error instanceof Error?error.message:'样号文件导出失败')}
    finally{setEntryBusy(false)}
  }

  const addItem = async (insert = false) => {
    if (!selected || entryBusy) return
    if (!reportInvalidNumericInput(document.querySelector('.sample-entry-form'))) return onToast('请先修正重复次数')
    setEntryBusy(true)
    try {
      const items: Array<{id?:number;pre_name:string;repeats:number}>=selected.items.map(item=>({id:item.id,pre_name:item.pre_name,repeats:item.repeats}))
      const anchor=insert?items.findIndex(item=>item.id===selectedItemId):-1
      items.splice(anchor<0?items.length:anchor,0,{pre_name:entryName.trim().startsWith(',')?'':entryName,repeats:entryName.trim().startsWith(',')?0:repeats})
      const next = await api.updateSampleQueue(token, selected.id, items)
      setSelected(next)
      setQueues((current) => current.map((item) => (item.id === next.id ? next : item)))
      advanceName()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '添加失败')
    } finally { setEntryBusy(false) }
  }

  const advanceName = () => {
    const next = nextSampleName(entryName.trim())
    setEntryName([...next].length <= nameLength ? next : '')
    requestAnimationFrame(() => { entryRef.current?.focus(); entryRef.current?.select() })
  }
  const entryCommand = async (insert = false) => {
    if (locked) return
    const value=entryName.trim()
    if (value.startsWith('.')) { setEntryName('');entryRef.current?.blur();onToast('样号录入已结束');return }
    if (value.startsWith('/')) {
      const item=selected?.items[selected.items.length-1]
      if (item) { setEntryBusy(true);try { await deleteItem(item.id);setEntryName('') } finally { setEntryBusy(false) } }
      return
    }
    if (selected) await addItem(insert || insertion?.queueId === selected.id)
    else await create()
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

  const pasteItems = async (changes: Array<{ position: number; name: string }>, action: 'paste' | 'fill') => {
    if (locked) throw new Error('队列正忙，请稍后粘贴。')
    if ((manualRepeats !== null || !methodDefaults) && !reportInvalidNumericInput(document.querySelector('.sample-entry-form'))) {
      throw new Error('请先修正重复次数。')
    }
    const items: Array<{ id?: number; pre_name: string; repeats: number }> = (selected?.items ?? [])
      .map(item => ({ id: item.id, pre_name: item.pre_name, repeats: item.repeats }))
    const lastPosition = Math.max(...changes.map(cell => cell.position))
    while (items.length <= lastPosition) items.push({ pre_name: '', repeats: 0 })
    for (const { position, name: text } of changes) {
      if (/[\x00-\x1f\x7f-\x9f\u2028\u2029]/.test(text)) throw new Error(`第 ${position + 1} 项含有换行、制表符或其他控制字符。`)
      const trimmed = text.trim()
      const preName = trimmed === ',' ? '' : trimmed
      const previous = selected?.items[position]
      if (previous?.pre_name === preName) continue
      if (previous?.spectrum_hash) throw new Error(`第 ${position + 1} 项已关联采集，整批样号未保存。`)
      items[position] = {
        id: previous?.id, pre_name: preName,
        repeats: preName ? previous?.pre_name ? previous.repeats : repeatsFor(preName) : 0,
      }
    }
    setEntryBusy(true)
    try {
      const next = selected ? await api.updateSampleQueue(token, selected.id, items)
        : await api.createSampleQueue(token, { name, name_length: nameLength === 10 ? undefined : nameLength, items })
      setSelected(next)
      setQueues(current => selected ? current.map(queue => queue.id === next.id ? next : queue) : [next, ...current])
      if (!selected && !confirmInDialog) {
        try { await api.selectSampleQueue(token, next.id) }
        catch {
          onToast('样号已保存到新队列，请重新选择该队列以将其设为当前队列。')
          return
        }
      }
      onToast(`已${action === 'fill' ? '填充' : '粘贴'} ${changes.length} 个样号位置`)
    } finally { setEntryBusy(false) }
  }

  const confirmQueue = async () => {
    if (!confirmation || !selected?.items.length || locked) return
    setEntryBusy(true)
    try {
      const queue = await api.selectSampleQueue(token, selected.id)
      if (queue) confirmation.onConfirm(queue)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '选择样号表失败')
    } finally { setEntryBusy(false) }
  }

  return (
    <div className="page-content sample-queue-page refined-page remaining-page">
      {confirmation?.target && createPortal(
        <button type="button" className="primary-button" disabled={!selected?.items.length || locked}
          onClick={() => void confirmQueue()}>确认</button>, confirmation.target
      )}
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
              onChange={(event) => void chooseQueue(queues.find((queue) => queue.id === Number(event.target.value)) ?? null)}
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
              accept=".xlsx,.sam,.txt"
              hidden
              disabled={locked}
              onChange={(event) => {
                const file = event.target.files?.[0]
                event.currentTarget.value = ''
                if (file) void importFile(file)
              }}
            />
          <button className="secondary-button" disabled={locked} onClick={() => void chooseQueue(null)}>
            <Plus size={15} />
            新建队列
          </button>
          <button className="secondary-button" onClick={() => void exportQueue('xlsx')} disabled={!selected?.items.length || locked}>
            <Download size={15} />导出 Excel
          </button>
          <button className="secondary-button" onClick={() => void exportQueue('sam')} disabled={!selected || locked}>
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
                  <Trash2 size={16} strokeWidth={1.75} aria-hidden="true" />
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
                <EmptyableNumberInput min={0} max={10} value={repeats} disabled={locked}
                  onValueChange={value => { if (value !== repeats) setManualRepeats(value) }} />
              </label>
            </div>
            {(!selected || !confirmInDialog) && <div className="sample-entry-actions">
              <button className="primary-button" disabled={locked} onClick={() => void entryCommand()}>
                <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
                {selected ? '添加样品' : '创建队列'}
              </button>
              {selected && <button className="secondary-button" disabled={locked} onClick={() => void entryCommand(true)}>插入样品</button>}
            </div>}
          </div>
          <SampleNumberTable initialSelectedId={selected?.id === insertion?.queueId ? insertion?.itemId : undefined}
            onSelectionChange={setSelectedItemId} key={selected?.id ?? 'new'} items={selected?.items ?? []}
            nameLength={selected?.name_length ?? nameLength} onDelete={deleteItem} onEdit={editItem}
            onPaste={pasteItems} onEditingChange={setEditingItem} busy={entryBusy || loading} />
        </section>
      </div>
      {samPreview}
    </div>
  )
}
