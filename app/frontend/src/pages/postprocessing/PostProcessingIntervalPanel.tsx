import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { CheckSquare, FileCog, Layers3, RotateCcw, Search } from 'lucide-react'
import { api, type PostProcessingInterval, type PostProcessingRecord } from '../../api'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { shortHash, formatMeasureTime } from './formatting'

export type IntervalConversion = {
  record_ids: string[]
  start_frame: number
  end_frame: number
  target_ccd_layout_id: number
  storage_mode: 'averaged' | 'full_interval'
}

type Props = {
  hidden: boolean
  showTools: boolean
  token: string
  records: PostProcessingRecord[]
  selected: string[]
  setSelected: Dispatch<SetStateAction<string[]>>
  canWrite: boolean
  busy: boolean
  onToast: (message: string) => void
  onConvert: (input: IntervalConversion) => Promise<void>
}

// 搜索、区间参数与查看结果归面板；勾选结果由父页面共享给矩阵导出。
export function PostProcessingIntervalPanel({
  hidden,
  showTools,
  token,
  records,
  selected,
  setSelected,
  canWrite,
  busy,
  onToast,
  onConvert
}: Props) {
  const [recordQuery, setRecordQuery] = useState('')
  const [interval, setInterval] = useState<PostProcessingInterval | null>(null)
  const [ccd, setCcd] = useState(0)
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(1)
  const [layoutId, setLayoutId] = useState(1)
  const [storageMode, setStorageMode] = useState<'averaged' | 'full_interval'>('full_interval')
  const intervalFields = useRef<HTMLDivElement>(null)
  const initializedInterval = useRef(false)
  const intervalRequest = useRef(0)
  useEffect(() => {
    intervalRequest.current++
    setInterval(null)
    return () => { intervalRequest.current++ }
  }, [token, selected[0], ccd, start, end])

  // 初次加载默认完整时段；刷新和切换页签均保留用户正在查看的区间。
  useEffect(() => {
    if (!initializedInterval.current && records[0]) {
      initializedInterval.current = true
      setEnd(records[0].frame_count)
    }
  }, [records])

  const active = useMemo(() => records.filter((record) => selected.includes(record.id)), [records, selected])
  const edtSelectedCount = useMemo(() => active.filter((record) => record.format === 'edt').length, [active])
  const activeRecord = active[0]
  const filteredRecords = useMemo(() => {
    const query = recordQuery.trim().toLocaleLowerCase()
    if (!query) return records
    return records.filter((record) =>
      [record.id, record.sample_name, record.band_name, record.format, record.source_sha256].some((value) =>
        value?.toLocaleLowerCase().includes(query)
      )
    )
  }, [recordQuery, records])
  const toggle = (id: string) =>
    setSelected((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]))

  const selectVisibleRecords = () => {
    const visibleIds = filteredRecords.map((record) => record.id)
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.includes(id))
    setSelected((current) =>
      allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : [...new Set([...current, ...visibleIds])]
    )
  }
  const invertVisibleRecords = () => {
    const visibleIds = new Set(filteredRecords.map((record) => record.id))
    setSelected((current) => {
      const currentSet = new Set(current)
      filteredRecords.forEach((record) =>
        currentSet.has(record.id) ? currentSet.delete(record.id) : currentSet.add(record.id)
      )
      return [...currentSet].filter((id) => records.some((record) => record.id === id) || !visibleIds.has(id))
    })
  }
  const viewInterval = async () => {
    if (!selected[0]) return onToast('请先选择 EDT 或 CMT 记录')
    if (!reportInvalidNumericInput(intervalFields.current)) return onToast('请先修正区间参数')
    const request = ++intervalRequest.current
    setInterval(null)
    try {
      const next = await api.postprocessingInterval(token, selected[0], { ccd, startFrame: start, endFrame: end })
      if (request === intervalRequest.current) setInterval(next)
    } catch (error) {
      if (request === intervalRequest.current) onToast(error instanceof Error ? error.message : '区间读取失败')
    }
  }

  const convert = () => {
    const edtSelected = selected.filter((id) => records.find((record) => record.id === id)?.format === 'edt')
    if (!canWrite || !edtSelected.length) return onToast('请选择可转换的 EDT 记录')
    if (!reportInvalidNumericInput(intervalFields.current)) return onToast('请先修正转换参数')
    return onConvert({ record_ids: edtSelected, start_frame: start, end_frame: end, target_ccd_layout_id: layoutId, storage_mode: storageMode })
  }

  return (
    <section
      style={hidden ? { display: 'none' } : undefined}
      className="surface postprocessing-surface postprocessing-source-surface"
    >
      <div className="surface-heading">
        <div>
          <h2>全时源记录</h2>
        </div>
        <Layers3 size={18} />
      </div>

      <div className="postprocessing-toolbar">
        <label className="postprocessing-search">
          <Search size={14} />
          <input
            value={recordQuery}
            onChange={(event) => setRecordQuery(event.target.value)}
            placeholder="搜索记录、样品或哈希"
            aria-label="搜索源记录"
          />
        </label>
        <span className="postprocessing-selection">
          已选 <strong>{selected.length}</strong> / {records.length}
        </span>
        <button type="button" className="postprocessing-text-button" onClick={selectVisibleRecords}>
          全选
        </button>
        <button type="button" className="postprocessing-text-button" onClick={invertVisibleRecords}>
          反选
        </button>
      </div>

      <div className="postprocessing-table-shell">
        <table className="postprocessing-table">
          <thead>
            <tr>
              <th className="check-column">
                <CheckSquare size={13} />
              </th>
              <th>记录</th>
              <th>格式</th>
              <th>采集形状</th>
              <th>源哈希</th>
            </tr>
          </thead>
          <tbody>
            {filteredRecords.length === 0 && (
              <tr>
                <td colSpan={5}>
                  <div className="postprocessing-empty">没有匹配的源记录</div>
                </td>
              </tr>
            )}
            {filteredRecords.map((record) => (
              <tr key={record.id} className={selected.includes(record.id) ? 'selected' : ''}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.includes(record.id)}
                    onChange={() => toggle(record.id)}
                    aria-label={`选择记录 ${record.id}`}
                  />
                </td>
                <td className="record-cell">
                  <strong title={record.id}>{record.id}</strong>
                  <small title={record.sample_name || record.band_name || ''}>
                    {record.sample_name || record.band_name || '未命名'} · {formatMeasureTime(record.measure_time)}
                  </small>
                </td>
                <td>
                  <span className={`format-chip ${record.format}`}>{record.format.toUpperCase()}</span>
                </td>
                <td className="shape-cell">
                  <strong>{record.frame_count} 帧</strong>
                  <small>
                    {record.ccd_count} CCD · {record.points_per_ccd} 点
                  </small>
                </td>
                <td>
                  <code className="hash-code" title={record.source_sha256}>
                    {shortHash(record.source_sha256)}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="postprocessing-subsection" style={showTools ? undefined : { display: 'none' }}>
        <summary>区间查看与旧 EDT 转换</summary>
        <p>仅用于临时查看或转换，不修改分析谱线已设置的曝光区间。</p>
        <div className="postprocessing-subsection-heading">
          <div>
            <strong>曝光区间</strong>
            <span>{activeRecord ? `当前：${activeRecord.id}` : '先从上方选择源记录'}</span>
          </div>
          {active.length > 1 && <small>区间查看以第一条所选记录为准</small>}
        </div>
        <div className="postprocessing-interval-grid" ref={intervalFields}>
          <label className="field"><span>转换存储模式</span>
            <select value={storageMode} onChange={(event) => setStorageMode(event.target.value as typeof storageMode)}>
              <option value="full_interval">分时帧（保留燃烧与暗帧）</option><option value="averaged">平均值</option>
            </select>
          </label>
          <label className="field">
            <span>CCD 索引</span>
            <NumericInput min={0} value={ccd} onValueChange={setCcd} />
          </label>
          <label className="field">
            <span>起始帧</span>
            <NumericInput min={1} value={start} onValueChange={setStart} />
          </label>
          <label className="field">
            <span>结束帧</span>
            <NumericInput min={1} value={end} onValueChange={setEnd} />
          </label>
          <label className="field">
            <span>目标 CCD 布局</span>
            <NumericInput min={1} value={layoutId} onValueChange={setLayoutId} />
          </label>
        </div>
        <div className="postprocessing-action-row">
          <button className="secondary-button" disabled={!selected.length || busy} onClick={() => void viewInterval()}>
            <FileCog size={15} />
            查看区间
          </button>
          <button
            className="primary-button"
            disabled={!canWrite || !edtSelectedCount || busy}
            onClick={() => void convert()}
          >
            <RotateCcw size={15} />
            转换所选 EDT{edtSelectedCount > 0 ? `（${edtSelectedCount}）` : ''}
          </button>
        </div>
      </details>

      {showTools && interval && (
        <div className="postprocessing-interval-result">
          <div>
            <span>区间</span>
            <strong>
              {interval.start_frame}–{interval.end_frame} 帧
            </strong>
            <small>
              CCD {interval.ccd} · {interval.points_per_ccd} 点
            </small>
          </div>
          <div>
            <span>均值预览</span>
            <strong>
              {interval.mean.values
                .slice(0, 4)
                .map((value) => value.toFixed(2))
                .join(' · ')}
            </strong>
            <small>显示前 4 个采样点</small>
          </div>
          <div>
            <span>源完整性</span>
            <code title={interval.source_sha256}>{shortHash(interval.source_sha256, 16)}</code>
            <small>{formatMeasureTime(interval.measure_time)}</small>
          </div>
        </div>
      )}
    </section>
  )
}
