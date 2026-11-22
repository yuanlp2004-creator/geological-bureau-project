import { useCallback, useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { request, requestRaw } from '../../api/client'
import { NumericInput } from '../../components/NumericInput'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { saveFile } from '../../platform/files'

type FullTimeSource = { id: string; name: string; kind: 'cmt' | 'sample'; record_count: number; burn_count: number }
type FullTimeOptions = {
  current_method: { id: number; name: string; version: number } | null
  sources: FullTimeSource[]
}
const endpoint = '/api/v1/postprocessing/full-time'

export function FullTimeExportPanel({ token, canExport, onToast }: {
  token: string; canExport: boolean; onToast: (message: string) => void
}) {
  const [options, setOptions] = useState<FullTimeOptions | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(1)
  const [busy, setBusy] = useState(false)
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const saving = useRef(false)
  const source = options?.sources.find(item => item.id === sourceId)
  const maxFrame = source?.burn_count ?? 0
  const method = options?.current_method

  const refresh = useCallback(async (preferred?: string) => {
    const current = ++generation.current
    setError('')
    try {
      const result = await request<FullTimeOptions>(endpoint, { headers: { Authorization: `Bearer ${token}` } })
      if (current !== generation.current) return
      setOptions(result)
      setSourceId(prior => [preferred, prior].find(id => result.sources.some(item => item.id === id)) ?? result.sources[0]?.id ?? '')
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : '无法读取全时数据来源')
    }
  }, [token])

  useEffect(() => {
    void refresh()
    return () => { generation.current++ }
  }, [refresh])
  useEffect(() => {
    setStart(1)
    setEnd(Math.max(1, maxFrame))
  }, [sourceId, maxFrame])

  const validInterval = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && start <= end && end <= maxFrame
  const canSave = canExport && source && validInterval && (source.kind !== 'cmt' || method)
  const exportBatch = async () => {
    if (saving.current || !canSave || opening) return
    saving.current = true
    setBusy(true)
    setError('')
    try {
      const response = await requestRaw(`${endpoint}/export`, {
        method: 'POST',
        timeoutMs: 300000,
        headers: { Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          source_id: sourceId, start_frame: start, end_frame: end,
          method_version_id: source.kind === 'cmt' ? method?.id : undefined
        })
      })
      const name = source.name.replace(/\.cmt$/i, '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 100)
      const path = await saveFile(await response.blob(), `${name || '批次'}-全时数据.xlsx`)
      onToast(path ? `已导出 ${source.record_count} 条记录的全时数据` : '已取消保存')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '全时数据导出失败')
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  return <section className="surface report-export">
    <div className="surface-heading">
      <h2>全时数据</h2>
      <OpenLegacyFile token={token} purpose="full-time" label="打开 CMT" disabled={busy}
        onBusyChange={setOpening} onOpened={result => refresh(`raw:${result.source_sha256}`)} />
    </div>
    <div className="report-export-form">
      <label className="field"><span>全时批次</span>
        <select aria-label="全时批次" value={sourceId} disabled={busy || opening || !options?.sources.length}
          onChange={event => setSourceId(event.target.value)}>
          {!options?.sources.length && <option value="">{options ? '暂无全时批次' : '正在读取批次…'}</option>}
          {options?.sources.map(item => <option key={item.id} value={item.id}>
            {item.name}（{item.kind === 'cmt' ? 'CMT' : '样品摄谱'}，{item.record_count} 条）
          </option>)}
        </select>
      </label>
      <label className="field"><span>起始帧</span><NumericInput aria-label="全时起始帧" min={1} max={maxFrame || 1} step={1}
        value={start} disabled={!maxFrame || busy || opening} onValueChange={setStart} /></label>
      <label className="field"><span>结束帧</span><NumericInput aria-label="全时结束帧" min={1} max={maxFrame || 1} step={1}
        value={end} disabled={!maxFrame || busy || opening} onValueChange={setEnd} /></label>
    </div>
    {source?.kind === 'cmt' && <p>{method ? `当前方法 ${method.name}（版本 ${method.version}）` : '请先打开用于解析 CMT 谱线的光谱方法。'}</p>}
    {source?.kind === 'sample' && <p>使用采集时绑定的方法版本。</p>}
    {source && !validInterval && <p role="status">{maxFrame ? `请输入 1 至 ${maxFrame} 之间的有效曝光区间。` : '此批次缺少完整燃烧帧。'}</p>}
    {error && <p className="auth-error" role="alert">{error}</p>}
    <div className="report-format-actions">
      <button type="button" className="primary-button" disabled={!canSave || busy || opening} onClick={() => void exportBatch()}>
        <Download size={15}/>{busy ? '正在生成 Excel…' : '导出 Excel'}
      </button>
      <button type="button" className="secondary-button" disabled={busy || opening} onClick={() => void refresh()}>刷新批次</button>
    </div>
  </section>
}
