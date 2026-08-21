import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  CheckSquare,
  Database,
  Download,
  FileCog,
  Layers3,
  RefreshCw,
  RotateCcw,
  Search,
} from 'lucide-react'
import {
  api,
  type PostProcessingInterval,
  type PostProcessingRecord,
  type PostProcessingRecalculationOptions,
  type PostProcessingRun,
} from './api'
import { NumericInput, reportInvalidNumericInput } from './NumericInput'
import './postprocessing.css'

type Props = {
  token: string
  initialView: 'interval' | 'recalculate-export'
  onViewChange: (view: 'interval' | 'recalculate-export') => void
  canWrite: boolean
  canExecute: boolean
  canExport: boolean
  onToast: (message: string) => void
}

const shortHash = (value: string | null | undefined, length = 12) => value ? `${value.slice(0, length)}…` : '无哈希'

const formatMeasureTime = (value: string | null | undefined) => {
  if (!value) return '时间未知'
  return value.replace('T', ' ').replace('Z', '').slice(0, 19)
}

const runStatusLabel: Record<string, string> = {
  completed: '已完成',
  blocked: '已阻断',
  failed: '失败',
  pending: '等待中',
  running: '执行中',
}

export function PostProcessingPage({ token, initialView, onViewChange, canWrite, canExecute, canExport, onToast }: Props) {
  const [view, setView] = useState<'interval' | 'recalculate-export'>(initialView)
  const [records, setRecords] = useState<PostProcessingRecord[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [recordQuery, setRecordQuery] = useState('')
  const [interval, setInterval] = useState<PostProcessingInterval | null>(null)
  const [ccd, setCcd] = useState(0)
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(1)
  const [layoutId, setLayoutId] = useState(1)
  const [methodVersionId, setMethodVersionId] = useState<number | undefined>()
  const [options, setOptions] = useState<PostProcessingRecalculationOptions>({ methods: [], sources: [], curve_snapshots: [] })
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [sourceQuery, setSourceQuery] = useState('')
  const [selectedCurves, setSelectedCurves] = useState<number[]>([])
  const [profile, setProfile] = useState<'legacy_2_0_2' | 'modern_v1'>('legacy_2_0_2')
  const [kind, setKind] = useState<'raw_intensity' | 'processed_intensity' | 'result_matrix'>('processed_intensity')
  const [format, setFormat] = useState<'txt' | 'csv' | 'excel'>('csv')
  const [directory, setDirectory] = useState('')
  const [filename, setFilename] = useState('s18-export')
  const [runs, setRuns] = useState<PostProcessingRun[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => setView(initialView), [initialView])

  const active = useMemo(() => records.filter((record) => selected.includes(record.id)), [records, selected])
  const edtSelectedCount = useMemo(() => active.filter((record) => record.format === 'edt').length, [active])
  const activeRecord = active[0]
  const filteredRecords = useMemo(() => {
    const query = recordQuery.trim().toLocaleLowerCase()
    if (!query) return records
    return records.filter((record) => [record.id, record.sample_name, record.band_name, record.format, record.source_sha256]
      .some((value) => value?.toLocaleLowerCase().includes(query)))
  }, [recordQuery, records])
  const filteredSources = useMemo(() => {
    const query = sourceQuery.trim().toLocaleLowerCase()
    if (!query) return options.sources
    return options.sources.filter((source) => [source.id, source.label, source.kind, source.source_sha256, source.measure_time]
      .some((value) => value?.toLocaleLowerCase().includes(query)))
  }, [options.sources, sourceQuery])
  const availableCurves = useMemo(
    () => options.curve_snapshots.filter((curve) => curve.method_version_id === methodVersionId && curve.calculation_profile === profile),
    [options.curve_snapshots, methodVersionId, profile],
  )
  const exportSelectionCount = kind === 'result_matrix' ? selectedSources.length : selected.length

  const load = async () => {
    try {
      const [nextRecords, nextRuns, nextRecalculations, nextOptions] = await Promise.all([
        api.postprocessingEdtRecords(token),
        api.postprocessingConversions(token),
        api.postprocessingRecalculations(token),
        api.postprocessingRecalculationOptions(token),
      ])
      setRecords(nextRecords.records)
      setRuns([...nextRuns.runs, ...nextRecalculations.runs])
      setOptions(nextOptions)
      setMethodVersionId((current) => current ?? nextOptions.methods[0]?.method_version_id)
      if (nextRecords.records[0]) setEnd(nextRecords.records[0].frame_count)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法加载 S18 数据')
    }
  }

  useEffect(() => { void load() }, [token])

  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  const toggleSource = (id: string) => setSelectedSources((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])
  const toggleCurve = (id: number) => setSelectedCurves((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])

  const selectVisibleRecords = () => {
    const visibleIds = filteredRecords.map((record) => record.id)
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.includes(id))
    setSelected((current) => allVisibleSelected
      ? current.filter((id) => !visibleIds.includes(id))
      : [...new Set([...current, ...visibleIds])])
  }
  const invertVisibleRecords = () => {
    const visibleIds = new Set(filteredRecords.map((record) => record.id))
    setSelected((current) => {
      const currentSet = new Set(current)
      filteredRecords.forEach((record) => currentSet.has(record.id) ? currentSet.delete(record.id) : currentSet.add(record.id))
      return [...currentSet].filter((id) => records.some((record) => record.id === id) || !visibleIds.has(id))
    })
  }
  const selectVisibleSources = () => {
    const visibleIds = filteredSources.map((source) => source.id)
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedSources.includes(id))
    setSelectedSources((current) => allVisibleSelected
      ? current.filter((id) => !visibleIds.includes(id))
      : [...new Set([...current, ...visibleIds])])
  }
  const invertVisibleSources = () => {
    const currentSet = new Set(selectedSources)
    filteredSources.forEach((source) => currentSet.has(source.id) ? currentSet.delete(source.id) : currentSet.add(source.id))
    setSelectedSources([...currentSet])
  }
  const selectAllCurves = () => setSelectedCurves(availableCurves.map((curve) => curve.id))
  const invertCurves = () => setSelectedCurves(availableCurves.filter((curve) => !selectedCurves.includes(curve.id)).map((curve) => curve.id))

  const viewInterval = async () => {
    if (!selected[0]) return onToast('请先选择 EDT 或 CMT 记录')
    if (!reportInvalidNumericInput(document.querySelector('.postprocessing-interval-grid'))) return onToast('请先修正区间参数')
    try {
      setInterval(await api.postprocessingInterval(token, selected[0], { ccd, startFrame: start, endFrame: end }))
    } catch (error) {
      onToast(error instanceof Error ? error.message : '区间读取失败')
    }
  }

  const convert = async () => {
    const edtSelected = selected.filter((id) => records.find((record) => record.id === id)?.format === 'edt')
    if (!canWrite || !edtSelected.length) return onToast('请选择可转换的 EDT 记录')
    if (!reportInvalidNumericInput(document.querySelector('.postprocessing-interval-grid'))) return onToast('请先修正转换参数')
    setBusy(true)
    try {
      await api.convertPostprocessingEdt(token, {
        record_ids: edtSelected,
        start_frame: start,
        end_frame: end,
        target_ccd_layout_id: layoutId,
        method_version_id: methodVersionId,
      })
      onToast('EDT 已转换为新版全时样品')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : 'EDT 转换失败')
    } finally {
      setBusy(false)
    }
  }

  const recalculate = async () => {
    if (!canExecute || !selectedSources.length || !methodVersionId || !selectedCurves.length) return onToast('请选择源记录、确切方法版本和曲线快照')
    setBusy(true)
    try {
      await api.recalculatePostprocessing(token, {
        source_record_ids: selectedSources,
        method_version_id: methodVersionId,
        calculation_profile: profile,
        curve_snapshot_ids: selectedCurves,
      })
      onToast('精确版本重算批次已保存')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '重算失败')
    } finally {
      setBusy(false)
    }
  }

  const exportMatrix = async () => {
    if (!canExport || !directory.trim()) return onToast('请输入输出目录')
    const recordIds = kind === 'result_matrix' ? selectedSources : selected
    if (!recordIds.length) return onToast('请选择要导出的记录')
    setBusy(true)
    try {
      await api.exportPostprocessing(token, {
        record_ids: recordIds,
        kind,
        format,
        output_directory: directory,
        filename,
        same_name_strategy: 'suffix',
      })
      onToast('矩阵已原子导出')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '导出失败')
    } finally {
      setBusy(false)
    }
  }

  return <div className="page-content postprocessing-page" data-testid="postprocessing-page" data-navigation-view={view}>
    <section className="hero-row compact-hero">
      <div>
        <span className="eyebrow"><span className="eyebrow-line" />S18 / POSTPROCESSING</span>
        <h1>全时处理与矩阵导出</h1>
        <p>在不修改旧文件的前提下完成区间查看、EDT 转换、精确重算与可追溯导出。</p>
      </div>
      <div className="hero-actions">
        <span className="postprocessing-count-pill"><Database size={14} />{records.length} 条源记录</span>
        <button className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={15} />刷新数据</button>
      </div>
    </section>

    <nav className="postprocessing-view-tabs" aria-label="后处理视图"><button className={view === 'interval' ? 'active' : ''} onClick={() => { setView('interval'); onViewChange('interval') }}>全时区间处理</button><button className={view === 'recalculate-export' ? 'active' : ''} onClick={() => { setView('recalculate-export'); onViewChange('recalculate-export') }}>重算与矩阵导出</button></nav>

    <div className="postprocessing-workbench">
      {view === 'interval' && <section className="surface postprocessing-surface postprocessing-source-surface">
        <div className="surface-heading">
          <div><span className="section-kicker">SOURCE RECORDS</span><h2>旧记录与曝光区间</h2></div>
          <Layers3 size={18} />
        </div>

        <div className="postprocessing-toolbar">
          <label className="postprocessing-search">
            <Search size={14} />
            <input value={recordQuery} onChange={(event) => setRecordQuery(event.target.value)} placeholder="搜索记录、样品或哈希" aria-label="搜索源记录" />
          </label>
          <span className="postprocessing-selection">已选 <strong>{selected.length}</strong> / {records.length}</span>
          <button type="button" className="postprocessing-text-button" onClick={selectVisibleRecords}>全选</button>
          <button type="button" className="postprocessing-text-button" onClick={invertVisibleRecords}>反选</button>
        </div>

        <div className="postprocessing-table-shell">
          <table className="postprocessing-table">
            <thead><tr><th className="check-column"><CheckSquare size={13} /></th><th>记录</th><th>格式</th><th>采集形状</th><th>源哈希</th></tr></thead>
            <tbody>
              {filteredRecords.length === 0 && <tr><td colSpan={5}><div className="postprocessing-empty">没有匹配的源记录</div></td></tr>}
              {filteredRecords.map((record) => <tr key={record.id} className={selected.includes(record.id) ? 'selected' : ''}>
                <td><input type="checkbox" checked={selected.includes(record.id)} onChange={() => toggle(record.id)} aria-label={`选择记录 ${record.id}`} /></td>
                <td className="record-cell"><strong title={record.id}>{record.id}</strong><small title={record.sample_name || record.band_name || ''}>{record.sample_name || record.band_name || '未命名'} · {formatMeasureTime(record.measure_time)}</small></td>
                <td><span className={`format-chip ${record.format}`}>{record.format.toUpperCase()}</span></td>
                <td className="shape-cell"><strong>{record.frame_count} 帧</strong><small>{record.ccd_count} CCD · {record.points_per_ccd} 点</small></td>
                <td><code className="hash-code" title={record.source_sha256}>{shortHash(record.source_sha256)}</code></td>
              </tr>)}
            </tbody>
          </table>
        </div>

        <div className="postprocessing-subsection">
          <div className="postprocessing-subsection-heading">
            <div><strong>曝光区间</strong><span>{activeRecord ? `当前：${activeRecord.id}` : '先从上方选择源记录'}</span></div>
            {active.length > 1 && <small>区间查看以第一条所选记录为准</small>}
          </div>
          <div className="postprocessing-interval-grid">
            <label className="field"><span>CCD 索引</span><NumericInput min={0} value={ccd} onValueChange={setCcd} /></label>
            <label className="field"><span>起始帧</span><NumericInput min={1} value={start} onValueChange={setStart} /></label>
            <label className="field"><span>结束帧</span><NumericInput min={1} value={end} onValueChange={setEnd} /></label>
            <label className="field"><span>目标 CCD 布局</span><NumericInput min={1} value={layoutId} onValueChange={setLayoutId} /></label>
          </div>
          <div className="postprocessing-action-row">
            <button className="secondary-button" disabled={!selected.length || busy} onClick={() => void viewInterval()}><FileCog size={15} />查看区间</button>
            <button className="primary-button" disabled={!canWrite || !edtSelectedCount || busy} onClick={() => void convert()}><RotateCcw size={15} />转换所选 EDT{edtSelectedCount > 0 ? `（${edtSelectedCount}）` : ''}</button>
          </div>
        </div>

        {interval && <div className="postprocessing-interval-result">
          <div><span>区间</span><strong>{interval.start_frame}–{interval.end_frame} 帧</strong><small>CCD {interval.ccd} · {interval.points_per_ccd} 点</small></div>
          <div><span>均值预览</span><strong>{interval.mean.values.slice(0, 4).map((value) => value.toFixed(2)).join(' · ')}</strong><small>显示前 4 个采样点</small></div>
          <div><span>源完整性</span><code title={interval.source_sha256}>{shortHash(interval.source_sha256, 16)}</code><small>{formatMeasureTime(interval.measure_time)}</small></div>
        </div>}
      </section>}

      {view === 'recalculate-export' && <section className="surface postprocessing-surface postprocessing-recalculation-surface">
        <div className="surface-heading">
          <div><span className="section-kicker">RECALCULATION</span><h2>确切版本重算</h2></div>
          <Activity size={18} />
        </div>

        <div className="postprocessing-version-grid">
          <label className="field"><span>方法版本</span><select value={methodVersionId ?? ''} onChange={(event) => { setMethodVersionId(event.target.value ? Number(event.target.value) : undefined); setSelectedCurves([]) }}><option value="">请选择</option>{options.methods.map((method) => <option key={method.method_version_id} value={method.method_version_id}>{method.name} · v{method.version}</option>)}</select></label>
          <label className="field"><span>算法档案</span><select value={profile} onChange={(event) => { setProfile(event.target.value as typeof profile); setSelectedCurves([]) }}><option value="legacy_2_0_2">legacy_2_0_2</option><option value="modern_v1">modern_v1</option></select></label>
        </div>

        <div className="postprocessing-list-section">
          <div className="postprocessing-list-heading">
            <div><strong>源记录</strong><span>{selectedSources.length} / {options.sources.length}</span></div>
            <div><button type="button" onClick={selectVisibleSources}>全选</button><button type="button" onClick={invertVisibleSources}>反选</button></div>
          </div>
          <label className="postprocessing-search compact">
            <Search size={13} />
            <input value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)} placeholder="筛选重算源记录" aria-label="筛选重算源记录" />
          </label>
          <div className="postprocessing-choice-list sources">
            {filteredSources.length === 0 && <div className="postprocessing-empty">没有可选的重算源记录</div>}
            {filteredSources.map((source) => <label className={`postprocessing-choice ${selectedSources.includes(source.id) ? 'selected' : ''}`} key={source.id}>
              <input type="checkbox" checked={selectedSources.includes(source.id)} onChange={() => toggleSource(source.id)} />
              <span><strong title={source.label}>{source.label}</strong><small title={source.id}>{source.kind === 'result' ? '结果' : '样品'} · {formatMeasureTime(source.measure_time)}</small></span>
              <code title={source.source_sha256 || source.id}>{shortHash(source.source_sha256, 9)}</code>
            </label>)}
          </div>
        </div>

        <div className="postprocessing-list-section">
          <div className="postprocessing-list-heading">
            <div><strong>曲线快照</strong><span>{selectedCurves.length} / {availableCurves.length}</span></div>
            <div><button type="button" onClick={selectAllCurves}>全选</button><button type="button" onClick={invertCurves}>反选</button></div>
          </div>
          <div className="postprocessing-choice-list curves">
            {availableCurves.length === 0 && <div className="postprocessing-empty">当前方法与算法档案没有可发布曲线</div>}
            {availableCurves.map((curve) => <label className={`postprocessing-choice ${selectedCurves.includes(curve.id) ? 'selected' : ''}`} key={curve.id}>
              <input type="checkbox" checked={selectedCurves.includes(curve.id)} onChange={() => toggleCurve(curve.id)} />
              <span><strong>{curve.line_id}</strong><small>{curve.fit_mode} · {curve.coordinate_type}</small></span>
              <code>#{curve.id}</code>
            </label>)}
          </div>
        </div>

        <button className="primary-button postprocessing-recalculate-button" disabled={!canExecute || !selectedSources.length || !selectedCurves.length || busy} onClick={() => void recalculate()}><RefreshCw size={15} />执行精确重算</button>

        <div className="postprocessing-run-section">
          <div className="postprocessing-list-heading"><div><strong>最近运行</strong><span>{runs.length} 个批次</span></div></div>
          <div className="postprocessing-run-list">
            {runs.length === 0 && <div className="postprocessing-empty compact">尚无转换或重算记录</div>}
            {runs.slice(0, 5).map((run) => <div className="postprocessing-run" key={run.id}>
              <span><strong title={run.id}>{run.id}</strong><small title={run.input_sha256}>{shortHash(run.input_sha256)}</small></span>
              <em className={`run-status ${run.status}`}>{runStatusLabel[run.status] || run.status}</em>
            </div>)}
          </div>
        </div>
      </section>}
    </div>

    {view === 'recalculate-export' && <section className="surface postprocessing-surface postprocessing-export-surface">
      <div className="surface-heading">
        <div><span className="section-kicker">MATRIX EXPORT</span><h2>原始、处理后强度与结果矩阵</h2></div>
        <Download size={18} />
      </div>
      <div className="postprocessing-export-grid">
        <label className="field"><span>矩阵类型</span><select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="raw_intensity">原始强度</option><option value="processed_intensity">处理后强度</option><option value="result_matrix">结果矩阵</option></select></label>
        <label className="field"><span>文件格式</span><select value={format} onChange={(event) => setFormat(event.target.value as typeof format)}><option value="txt">文本（TXT）</option><option value="csv">CSV</option><option value="excel">Excel（XLS）</option></select></label>
        <label className="field postprocessing-directory-field"><span>输出目录</span><input value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="例如 C:\\Exports" /></label>
        <label className="field"><span>文件名</span><input value={filename} onChange={(event) => setFilename(event.target.value)} /></label>
      </div>
      <div className="postprocessing-export-footer">
        <div><strong>{exportSelectionCount} 条记录待导出</strong><span>{kind === 'result_matrix' ? '使用右侧重算源记录选择' : '使用左侧旧记录选择'} · 同名文件自动追加后缀</span></div>
        <button className="primary-button" disabled={!canExport || !exportSelectionCount || busy} onClick={() => void exportMatrix()}><Download size={15} />原子导出</button>
      </div>
    </section>}
  </div>
}
