import { useCallback, useEffect, useState } from 'react'
import { Download, Plus, RefreshCw, Trash2, Upload } from 'lucide-react'
import { api, saveFile, type SampleQueue } from '../../api'
import { NumericInput as EmptyableNumberInput, reportInvalidNumericInput } from '../../components/NumericInput'

export function SampleQueuePage({ token, onToast }: { token: string; onToast: (message: string) => void }) {
  const [queues, setQueues] = useState<SampleQueue[]>([])
  const [selected, setSelected] = useState<SampleQueue | null>(null)
  const [name, setName] = useState('现场样品')
  const [entryName, setEntryName] = useState('')
  const [repeats, setRepeats] = useState(1)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const next = await api.sampleQueues(token)
      setQueues(next)
      setSelected((current) => current ? next.find((item) => item.id === current.id) ?? next[0] ?? null : next[0] ?? null)
    } catch (error) { onToast(error instanceof Error ? error.message : '无法读取样品队列') }
    finally { setLoading(false) }
  }, [token, onToast])
  useEffect(() => { void load() }, [load])

  const create = async () => {
    if (!entryName.trim()) return
    if (!reportInvalidNumericInput(document.querySelector('.sample-entry-form'))) return onToast('请先修正重复次数')
    try {
      const next = await api.createSampleQueue(token, { name, items: [{ pre_name: entryName, repeats }] })
      setQueues((current) => [next, ...current])
      setSelected(next)
      setEntryName('')
      onToast('样品队列已创建')
    } catch (error) { onToast(error instanceof Error ? error.message : '创建失败') }
  }

  const importFile = async (file: File) => {
    try {
      const next = await api.importSampleQueue(token, file.name, await file.text())
      setQueues((current) => [next, ...current.filter((item) => item.id !== next.id)])
      setSelected(next)
      onToast(`已导入 ${next.record_count} 条样品记录`)
    } catch (error) { onToast(error instanceof Error ? error.message : 'SAM 导入失败') }
  }

  const exportQueue = async () => {
    if (!selected) return
    const result = await api.exportSampleQueue(token, selected.id)
    const path = await saveFile(result.blob, `queue-${selected.id}.sam`)
    onToast(path ? `SAM 文件已保存：${path}` : '已取消保存')
  }

  const addItem = async () => {
    if (!selected || !entryName.trim()) return
    if (!reportInvalidNumericInput(document.querySelector('.sample-entry-form'))) return onToast('请先修正重复次数')
    try {
      const next = await api.updateSampleQueue(token, selected.id, [...selected.items.map((item) => ({ pre_name: item.pre_name, repeats: item.repeats })), { pre_name: entryName, repeats }])
      setSelected(next); setQueues((current) => current.map((item) => item.id === next.id ? next : item)); setEntryName('')
    } catch (error) { onToast(error instanceof Error ? error.message : '添加失败') }
  }

  const clearQueue = async () => {
    if (!selected || !window.confirm('清空当前队列？')) return
    try {
      const next = await api.clearSampleQueue(token, selected.id)
      setSelected(next); setQueues((current) => current.map((item) => item.id === next.id ? next : item)); onToast('队列已清空')
    } catch (error) { onToast(error instanceof Error ? error.message : '清空失败') }
  }

  const deleteItem = async (itemId: number) => {
    if (!selected) return
    try {
      const next = await api.deleteSampleItem(token, selected.id, itemId)
      setSelected(next); setQueues((current) => current.map((item) => item.id === next.id ? next : item))
    } catch (error) { onToast(error instanceof Error ? error.message : '删除失败') }
  }

  return <div className="page-content sample-queue-page refined-page remaining-page">
    <div className="page-intro"><div><h1>样品队列</h1><p>管理预录样号、重复次数和采集后命名。旧 `.sam` 文件只读导入，谱图数据不会在此步骤生成。</p></div><div className="page-intro-actions"><button className="secondary-button" onClick={() => setSelected(null)}><Plus size={15} />新建队列</button><label className="secondary-button"><Upload size={15} />导入 SAM<input type="file" accept=".sam,.txt" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file) }} /></label><button className="secondary-button" onClick={() => void exportQueue()} disabled={!selected}><Download size={15} />导出 SAM</button><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div></div>
    <div className="sample-queue-grid">
      <section className="surface queue-context"><label className="field"><span>选择样品队列</span><select value={selected?.id ?? ''} title={selected?.name} disabled={loading} onChange={(event) => setSelected(queues.find((queue) => queue.id === Number(event.target.value)) ?? null)}><option value="">{loading ? '正在读取…' : '新建队列'}</option>{queues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name} · {queue.record_count} 条记录 · {queue.expanded_bands} 谱带</option>)}</select></label></section>
      <section className="surface sample-editor"><div className="surface-heading"><div><h2>{selected?.name ?? '新建队列'}</h2></div>{selected && <div className="page-intro-actions"><span className="status-chip">{selected.expanded_bands} 谱带</span><button className="icon-button compact danger" title="清空队列" onClick={() => void clearQueue()}><Trash2 size={14} /></button></div>}</div><div className="sample-entry-form">{!selected && <label className="field"><span>队列名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>}<label className="field"><span>样品名</span><input value={entryName} onChange={(event) => setEntryName(event.target.value)} placeholder="例如 A001 / S10" /></label><label className="field small-field"><span>重复次数</span><EmptyableNumberInput min={0} max={10} value={repeats} onValueChange={setRepeats} /></label><button className="primary-button" onClick={() => void (selected ? addItem() : create())}><Plus size={15} />{selected ? '插入样品' : '创建队列'}</button></div>{selected && <div className="sample-table-wrap"><table className="data-table"><thead><tr><th>#</th><th>预录名称</th><th>重复</th><th>展开谱带</th><th>采集后名称</th><th /></tr></thead><tbody>{selected.items.map((item) => <tr key={item.id}><td>{item.position + 1}</td><td><strong>{item.pre_name || '空样'}</strong></td><td>{item.repeats || '空样'}</td><td>{item.expanded_bands}</td><td>{item.post_name ?? '待采集'}</td><td><button className="icon-button compact danger" title="删除样品" onClick={() => void deleteItem(item.id)}><Trash2 size={13} /></button></td></tr>)}</tbody></table></div>}</section>
    </div>
  </div>
}
