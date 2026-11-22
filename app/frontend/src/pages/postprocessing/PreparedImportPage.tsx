import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, RefreshCw } from 'lucide-react'
import { api, type CurrentMethodState, type PreparedImportOptions, type PreparedImportInput } from '../../api'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { ViewerDialog } from '../spectra/ViewerDialog'
import { formatMeasureTime } from './formatting'
import './prepared-import.css'

type Props = { token: string; currentMethod: CurrentMethodState | null; canWrite: boolean
  onToast: (message: string) => void; onViewSpectra: (group: string) => void }

export function PreparedImportPage({ token, currentMethod, canWrite, onToast, onViewSpectra }: Props) {
  const [options, setOptions] = useState<PreparedImportOptions | null>(null)
  const [source, setSource] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [interval, setInterval] = useState('')
  const [targetName, setTargetName] = useState('')
  const [storage, setStorage] = useState<'averaged' | 'full_interval'>('averaged')
  const [useMethod, setUseMethod] = useState(true)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [status, setStatus] = useState('')
  const generation = useRef(0)
  const pending = useRef(false)
  const request = useRef<{ key: string; id: string } | null>(null)
  const records = options?.records ?? []
  const target = options?.targets.find(item => item.name.toLocaleLowerCase() === targetName.trim().toLocaleLowerCase())
  const methodId = options?.method.version_id

  async function load(sha = source, reset = false) {
    const current = ++generation.current
    setLoading(true); setError('')
    try {
      const result = await api.preparedImportOptions(token, sha)
      if (current !== generation.current) return
      setOptions(result)
      if (reset) {
        setSelected([])
        const end = Math.min(...result.records.map(record => record.ignition.burn_count))
        setInterval(result.records.length ? `1-${end}` : '')
        setStatus('')
      }
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : '读取导入数据失败')
    } finally { if (current === generation.current) setLoading(false) }
  }

  useEffect(() => {
    void load(source)
    return () => { generation.current++ }
  }, [token, currentMethod?.method_id, currentMethod?.version])

  const selectSource = async (sha: string) => {
    setSource(sha); setOptions(current => current ? { ...current, records: [], saved_dispersion: null } : current)
    setSelected([]); setInterval(''); setConflict(false); request.current = null
    await load(sha, true)
  }
  const toggle = (id: string) => setSelected(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id])

  const prepare = (): Omit<PreparedImportInput, 'request_id' | 'same_name_strategy'> | null => {
    const parts = /^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$/.exec(interval)
    const start = parts ? Number(parts[1]) : 0, end = parts ? Number(parts[2] ?? parts[1]) : 0
    if (!source) { setError('请先打开蒸发摄谱文件'); return null }
    if (!selected.length) { setError('请选择要导入的记录'); return null }
    if (!targetName.trim()) { setError('请填写输出样品集名称'); return null }
    if (!methodId) { setError('请先打开当前方法'); return null }
    if (!start || start > end || selected.some(id => end > (records.find(item => item.id === id)?.ignition.burn_count ?? 0))) {
      setError('请填写有效的帧区间，例如 1-20，且不超出所选记录'); return null
    }
    return { source_sha256: source, record_ids: selected, target_name: targetName.trim(), storage_mode: storage,
      start_frame: start, end_frame: end, use_method_id: useMethod, expected_method_version_id: methodId,
      ...(target ? { expected_target_revision: target.revision } : {}) }
  }

  const runImport = async (strategy: PreparedImportInput['same_name_strategy'] = 'error') => {
    if (pending.current || !canWrite || loading) return
    const input = prepare()
    if (!input) return
    if (target && strategy === 'error') { setConflict(true); return }
    const payload = { ...input, same_name_strategy: strategy }
    const key = JSON.stringify(payload)
    if (request.current?.key !== key) request.current = { key, id: crypto.randomUUID() }
    pending.current = true; setBusy(true); setError(''); setConflict(false)
    try {
      const result = await api.importPreparedRecords(token, { ...payload, request_id: request.current.id })
      setOptions(current => current ? { ...current, targets: [...current.targets.filter(item => item.id !== result.target.id), result.target] } : current)
      request.current = null
      setStatus(`已导入 ${selected.length} 条记录，输出样品集共 ${result.target.records.length} 条`)
      onToast('预备摄谱记录已导入，可在“查看谱图”中查看')
    } catch (failure) { setError(failure instanceof Error ? failure.message : '导入失败，请重试') }
    finally { pending.current = false; setBusy(false) }
  }

  const saveDispersion = async () => {
    if (pending.current || !canWrite || !source || !methodId) return
    pending.current = true; setBusy(true); setError('')
    try {
      const result = await api.savePreparedDispersion(token, source, methodId)
      setStatus(result.message); await load(source)
    } catch (failure) { setError(failure instanceof Error ? failure.message : '保存色散失败') }
    finally { pending.current = false; setBusy(false) }
  }

  const disabled = busy || loading
  return <div className="page-content prepared-import-page refined-page" data-testid="prepared-import-page" aria-busy={disabled}>
    <section className="surface prepared-import-workspace">
      <div className="prepared-file-row">
        <label className="prepared-source-field field"><span>导入蒸发文件</span>
          <select aria-label="导入蒸发文件" value={source} disabled={disabled} onChange={event => void selectSource(event.target.value)}>
            <option value="">请选择已打开的 EDT 文件</option>
            {options?.sources.map(item => <option key={item.sha256} value={item.sha256}>{item.name} · {item.record_count} 条</option>)}
          </select>
        </label>
        <OpenLegacyFile token={token} purpose="edt-conversion" label="打开蒸发文件" disabled={disabled || !canWrite}
          onBusyChange={setBusy} onOpened={async result => { await selectSource(result.source_sha256) }} />
        <label className="prepared-interval field"><span>导入区间</span><input aria-label="导入区间" value={interval} disabled={disabled}
          placeholder="例如 1-20" onChange={event => setInterval(event.target.value)} /></label>
      </div>
      <div className="prepared-file-row prepared-output-row">
        <label className="prepared-output-field field"><span>输出样品集</span><input aria-label="输出样品集" maxLength={120}
          value={targetName} disabled={disabled} placeholder="填写新名称，或选择已有样品集"
          onChange={event => setTargetName(event.target.value)} /></label>
        <label className="prepared-existing-field field"><select aria-label="选择已有输出" value={target?.id ?? ''} disabled={disabled} onChange={event => {
          const item = options?.targets.find(value => value.id === event.target.value)
          if (item) { setTargetName(item.name); setStorage(item.storage_mode) }
        }}><option value="">已有样品集…</option>{options?.targets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="prepared-format field"><span>导出格式</span><select aria-label="导出格式" value={storage} disabled={disabled}
          onChange={event => { setStorage(event.target.value as typeof storage); setTargetName(''); setConflict(false) }}>
          <option value="averaged">均值样品</option><option value="full_interval">全时样品</option></select></label>
      </div>
      <div className="prepared-context"><span>当前方法：{options?.method.title ?? '未打开方法'}</span>
        <button className="prepared-refresh" disabled={disabled} onClick={()=>void load()}><RefreshCw size={14}/>刷新</button></div>
      {error && <p className="auth-error prepared-feedback" role="alert">{error}</p>}
      {status && <p className="prepared-feedback" role="status">{status}</p>}
      <div className="prepared-columns">
        <section className="prepared-record-panel" aria-label="源记录">
          <div className="prepared-selection-bar"><button className="secondary-button" disabled={disabled || !records.length}
            onClick={()=>setSelected(records.map(item=>item.id))}>全部选择</button>
            <button className="secondary-button" disabled={disabled || !records.length}
              onClick={()=>setSelected(records.filter(item=>!selected.includes(item.id)).map(item=>item.id))}>反向选择</button>
            <label><input type="checkbox" checked={useMethod} disabled={disabled} onChange={event=>setUseMethod(event.target.checked)}/>使用方法 ID</label>
          </div>
          <div className="prepared-record-scroll"><table><thead><tr><th aria-label="选择"/><th>谱带名称</th><th>测量时间</th></tr></thead>
            <tbody>{records.map(item=><tr key={item.id} aria-selected={selected.includes(item.id)}>
              <td><input type="checkbox" aria-label={`选择 ${item.band_name || item.sample_name || item.id}`} checked={selected.includes(item.id)}
                disabled={disabled} onChange={()=>toggle(item.id)}/></td>
              <td title={item.band_name || item.sample_name || ''}>{item.band_name || item.sample_name || item.id}</td>
              <td>{formatMeasureTime(item.measure_time)}</td></tr>)}
              {!records.length && <tr><td colSpan={3} className="prepared-empty">{loading ? '正在读取…' : '请打开或选择蒸发摄谱文件'}</td></tr>}
            </tbody></table></div>
          <footer>已选 {selected.length} / {records.length} 条记录</footer>
        </section>
        <div className="prepared-operation-bar">
          <button className="primary-button" disabled={disabled || !canWrite || !selected.length} onClick={()=>void runImport()}>导入记录<ArrowRight size={16}/></button>
          <button className="secondary-button" disabled={disabled || !canWrite || !source || !methodId} title="将当前方法色散保存到源文件的新版工作副本"
            onClick={()=>void saveDispersion()}><ArrowLeft size={16}/>保存色散</button>
        </div>
        <section className="prepared-record-panel prepared-output-panel" aria-label="输出记录">
          <div className="prepared-selection-bar"><strong>{target?.name || '输出记录'}</strong>
            <button className="secondary-button" disabled={!target?.records.length || disabled} onClick={()=>target && onViewSpectra('prepared:' + target.id)}>查看谱图</button></div>
          <div className="prepared-record-scroll"><table><thead><tr><th>记录号</th><th>样品名称</th><th>测量时间</th></tr></thead>
            <tbody>{target?.records.map(item=><tr key={item.id}><td>{item.id}</td><td title={item.name}>{item.name}</td><td>{formatMeasureTime(item.measure_time)}</td></tr>)}
              {!target?.records.length && <tr><td colSpan={3} className="prepared-empty">导入后在这里显示输出记录</td></tr>}
            </tbody></table></div><footer>{target?.records.length ?? 0} 条输出记录</footer>
        </section>
      </div>
      <p className="prepared-storage-note">区间按帧编号，两端计入。输出保存在新版样品集中；保存色散更新新版工作副本，旧文件原件保持不变。</p>
    </section>
    {conflict && <ViewerDialog title="输出样品集已存在" onClose={()=>setConflict(false)}>
      <p>“{targetName.trim()}”已有 {target?.records.length ?? 0} 条记录，请选择本次导入方式。</p>
      <p>替换更新样品集中的记录，已有样品和分析历史仍会保留。</p>
      <div className="prepared-conflict-actions"><button className="secondary-button" onClick={()=>setConflict(false)}>取消</button>
        <button className="secondary-button" onClick={()=>void runImport('append')}>追加记录</button>
        <button className="primary-button" onClick={()=>void runImport('replace')}>替换样品集</button></div>
    </ViewerDialog>}
  </div>
}
