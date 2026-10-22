import { SectionHeading } from '../../components/SectionHeading'
import { PageFileActions } from '../../components/PageFileActions'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { calculationProfileLabel } from '../../components/calculationProfile'
import { useEffect, useMemo, useState } from 'react'
import { Activity, Database, Download, RefreshCw, Search } from 'lucide-react'
import {
  api,
  type PostProcessingRecord,
  type PostProcessingRecalculationOptions,
  type PostProcessingRun
} from '../../api'
import { PostProcessingIntervalPanel, type IntervalConversion } from './PostProcessingIntervalPanel'
import { shortHash, formatMeasureTime } from './formatting'

type Props = {
  actionsTarget?: HTMLElement | null
  active?: boolean
  embedded?: boolean
  token: string
  view: 'recalculate' | 'reports' | 'intensity'
  canWrite: boolean
  canExecute: boolean
  canExport: boolean
  onToast: (message: string) => void
}

const runStatusLabel: Record<string, string> = {
  completed: '已完成',
  blocked: '已阻断',
  failed: '失败',
  pending: '等待中',
  running: '执行中'
}

export function PostProcessingPage({
  actionsTarget,
  active = true,
  embedded = false,
  token,
  view,
  canWrite,
  canExecute,
  canExport,
  onToast
}: Props) {
  const [records, setRecords] = useState<PostProcessingRecord[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [methodVersionId, setMethodVersionId] = useState<number | undefined>()
  const [options, setOptions] = useState<PostProcessingRecalculationOptions>({
    methods: [],
    sources: [],
    curve_snapshots: []
  })
  const [exportBatch, setExportBatch] = useState('')
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [sourceQuery, setSourceQuery] = useState('')
  const [selectedCurves, setSelectedCurves] = useState<number[]>([])
  const [profile, setProfile] = useState<'legacy_2_0_2' | 'modern_v1'>('legacy_2_0_2')
  const [allowOlderMethod, setAllowOlderMethod] = useState(false)
  const [format, setFormat] = useState<'txt' | 'csv' | 'excel'>('csv')
  const [directory, setDirectory] = useState('')
  const [filename, setFilename] = useState('s18-export')
  const [runs, setRuns] = useState<PostProcessingRun[]>([])
  const [busy, setBusy] = useState(false)


  const filteredSources = useMemo(() => {
    const query = sourceQuery.trim().toLocaleLowerCase()
    if (!query) return options.sources
    return options.sources.filter((source) =>
      [source.id, source.label, source.kind, source.source_sha256, source.measure_time].some((value) =>
        value?.toLocaleLowerCase().includes(query)
      )
    )
  }, [options.sources, sourceQuery])
  const availableCurves = useMemo(
    () =>
      options.curve_snapshots.filter(
        (curve) => curve.method_version_id === methodVersionId && curve.calculation_profile === profile
      ),
    [options.curve_snapshots, methodVersionId, profile]
  )
  const exportSelectionCount = exportBatch ? 1 : selectedSources.length

  const load = async () => {
    try {
      const [nextRecords, nextRuns, nextRecalculations, nextOptions] = await Promise.all([
        api.postprocessingEdtRecords(token),
        api.postprocessingConversions(token),
        api.postprocessingRecalculations(token),
        api.postprocessingRecalculationOptions(token)
      ])
      setRecords(nextRecords.records)
      setRuns([...nextRuns.runs, ...nextRecalculations.runs])
      setOptions(nextOptions)
      setMethodVersionId((current) => current ?? nextOptions.methods[0]?.method_version_id)
    } catch (error) {
      onToast(error instanceof Error ? error.message : '无法加载 S18 数据')
    }
  }

  useEffect(() => {
    void load()
  }, [token])

  const toggleSource = (id: string) =>
    setSelectedSources((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]))
  const toggleCurve = (id: number) =>
    setSelectedCurves((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]))

  const selectVisibleSources = () => {
    const visibleIds = filteredSources.map((source) => source.id)
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedSources.includes(id))
    setSelectedSources((current) =>
      allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : [...new Set([...current, ...visibleIds])]
    )
  }
  const invertVisibleSources = () => {
    const currentSet = new Set(selectedSources)
    filteredSources.forEach((source) =>
      currentSet.has(source.id) ? currentSet.delete(source.id) : currentSet.add(source.id)
    )
    setSelectedSources([...currentSet])
  }
  const selectAllCurves = () => setSelectedCurves(availableCurves.map((curve) => curve.id))
  const invertCurves = () =>
    setSelectedCurves(availableCurves.filter((curve) => !selectedCurves.includes(curve.id)).map((curve) => curve.id))

  const convert = async (input: IntervalConversion) => {
    setBusy(true)
    try {
      await api.convertPostprocessingEdt(token, { ...input, method_version_id: methodVersionId })
      onToast('EDT 已按所选存储模式转换为新版样品')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : 'EDT 转换失败')
    } finally {
      setBusy(false)
    }
  }

  const recalculate = async () => {
    if (!canExecute || !selectedSources.length || !methodVersionId || !selectedCurves.length)
      return onToast('请选择源记录、确切方法版本和曲线快照')
    setBusy(true)
    try {
      const batch = await api.recalculatePostprocessing(token, {
        ...(allowOlderMethod ? { allow_older_method: true } : {}),
        source_record_ids: selectedSources,
        method_version_id: methodVersionId,
        calculation_profile: profile,
        curve_snapshot_ids: selectedCurves
      })
      if (batch.status === 'completed') {
        setExportBatch(`recalc:${batch.id}`)
      }
      onToast(batch.status === 'completed' ? '重算已完成，导出来源已选中本批次' : '重算已阻断，请查看批次诊断')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '重算失败')
    } finally {
      setBusy(false)
    }
  }

  const exportMatrix = async () => {
    if (!canExport || !directory.trim()) return onToast('请输入输出目录')
    const recordIds = exportBatch ? [exportBatch] : selectedSources
    if (!recordIds.length) return onToast('请选择要导出的记录')
    setBusy(true)
    try {
      await api.exportPostprocessing(token, {
        record_ids: recordIds,
        kind: 'result_matrix',
        format,
        output_directory: directory,
        filename,
        same_name_strategy: 'suffix'
      })
      onToast('矩阵已原子导出')
      await load()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '导出失败')
    } finally {
      setBusy(false)
    }
  }

  const [recalculateActionsTarget, setRecalculateActionsTarget] = useState<HTMLDivElement | null>(null)
  const refreshActions = <PageFileActions target={view === 'recalculate' ? recalculateActionsTarget : actionsTarget} hidden={!active}>
    <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="recalculate" label="打开强度文件" disabled={busy} onOpened={async result => {
      await load(); setSelectedSources(result.record_ids.map(id => `result:${id}`)); setSourceQuery(''); setProfile('legacy_2_0_2')
    }}/>

    <span className="postprocessing-count-pill"><Database size={14}/>{records.length} 条源记录</span>
    <button className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={15}/>刷新数据</button>
  </PageFileActions>
  return (
    <div
      className="page-content postprocessing-page refined-page remaining-page"
      data-testid="postprocessing-page"
      data-navigation-view={view}
    >
      {!embedded && view !== 'recalculate' && <section className="page-action-toolbar">
        
        {refreshActions}
      </section>}

      {(embedded || view === 'recalculate') && refreshActions}
      <div className="postprocessing-workbench">
        <details className="surface postprocessing-legacy-tools" style={view === 'recalculate' ? undefined : { display: 'none' }}>
          <summary>旧记录区间查看与 EDT 转换</summary>

        <div className="surface-heading"><h2>EDT 转换</h2><PageFileActions><OpenLegacyFile onBusyChange={setBusy} token={token} purpose="edt-conversion" label="打开蒸发摄谱文件" disabled={busy} onOpened={async result => {
          await load(); setSelected(result.record_ids.map(id => `raw:${id}`))
        }}/></PageFileActions></div>
        <PostProcessingIntervalPanel
          hidden={view !== 'recalculate'}
          showTools
          token={token}
          records={records}
          selected={selected}
          setSelected={setSelected}
          canWrite={canWrite}
          busy={busy}
          onToast={onToast}
          onConvert={convert}
        />
        </details>

        <section style={view === 'recalculate' || view === 'intensity' ? undefined : { display: 'none' }} className="surface postprocessing-surface postprocessing-recalculation-surface">
            <div className="surface-heading">
              <SectionHeading title={<>{view === 'recalculate' ? '确切版本重算' : '结果来源'}</>} />
              <div ref={setRecalculateActionsTarget} className="page-file-actions-slot" />
            </div>

            <div className="postprocessing-version-grid" style={view === 'recalculate' ? undefined : { display: 'none' }}>
              <label className="field">
                <span>方法版本</span>
                <select
                  value={methodVersionId ?? ''}
                  onChange={(event) => {
                    setMethodVersionId(event.target.value ? Number(event.target.value) : undefined)
                    setSelectedCurves([])
                  }}
                >
                  <option value="">请选择</option>
                  {options.methods.map((method) => (
                    <option key={method.method_version_id} value={method.method_version_id}>
                      {method.name} · v{method.version}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>计算模式</span>
                <select
                  value={profile}
                  onChange={(event) => {
                    setProfile(event.target.value as typeof profile)
                    setSelectedCurves([])
                  }}
                >
                  <option value="legacy_2_0_2">{calculationProfileLabel('legacy_2_0_2')}</option>
                  <option value="modern_v1">{calculationProfileLabel('modern_v1')}</option>
                </select>
              </label>
            </div>

            <div className="postprocessing-list-section">
              <div className="postprocessing-list-heading">
                <div>
                  <strong>源记录</strong>
                  <span>
                    {selectedSources.length} / {options.sources.length}
                  </span>
                </div>
                <div>
                  <button type="button" onClick={selectVisibleSources}>
                    全选
                  </button>
                  <button type="button" onClick={invertVisibleSources}>
                    反选
                  </button>
                </div>
              </div>
              <label className="postprocessing-search compact">
                <Search size={13} />
                <input
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="筛选重算源记录"
                  aria-label="筛选重算源记录"
                />
              </label>
              <div className="postprocessing-choice-list sources">
                {filteredSources.length === 0 && <div className="postprocessing-empty">没有可选的重算源记录</div>}
                {filteredSources.map((source) => (
                  <label
                    className={`postprocessing-choice ${selectedSources.includes(source.id) ? 'selected' : ''}`}
                    key={source.id}
                  >
                    <input
                      type="checkbox"
                      checked={selectedSources.includes(source.id)}
                      onChange={() => toggleSource(source.id)}
                    />
                    <span>
                      <strong title={source.label}>{source.label}</strong>
                      <small title={source.id}>
                        {source.kind === 'result' ? '结果' : '样品'} · {formatMeasureTime(source.measure_time)}
                      </small>
                    </span>
                    <code title={source.source_sha256 || source.id}>{shortHash(source.source_sha256, 9)}</code>
                  </label>
                ))}
              </div>
            </div>

            <div style={view === 'recalculate' ? undefined : { display: 'none' }}>
            <div className="postprocessing-list-section">
              <div className="postprocessing-list-heading">
                <div>
                  <strong>曲线快照</strong>
                  <span>
                    {selectedCurves.length} / {availableCurves.length}
                  </span>
                </div>
                <div>
                  <button type="button" onClick={selectAllCurves}>
                    全选
                  </button>
                  <button type="button" onClick={invertCurves}>
                    反选
                  </button>
                </div>
              </div>
              <div className="postprocessing-choice-list curves">
                {availableCurves.length === 0 && (
                  <div className="postprocessing-empty">当前方法与计算模式没有可发布曲线</div>
                )}
                {availableCurves.map((curve) => (
                  <label
                    className={`postprocessing-choice ${selectedCurves.includes(curve.id) ? 'selected' : ''}`}
                    key={curve.id}
                  >
                    <input
                      type="checkbox"
                      checked={selectedCurves.includes(curve.id)}
                      onChange={() => toggleCurve(curve.id)}
                    />
                    <span>
                      <strong>{curve.line_id}</strong>
                      <small>
                        {curve.fit_mode} · {curve.coordinate_type}
                      </small>
                    </span>
                    <code>#{curve.id}</code>
                  </label>
                ))}
              </div>
            </div>

            <label className="checkbox-row"><input type="checkbox" checked={allowOlderMethod} onChange={(event) => setAllowOlderMethod(event.target.checked)}/>
              已核对方法修改，允许重算较旧 PDT（记录此确认）</label>
            <button
              className="primary-button postprocessing-recalculate-button"
              disabled={!canExecute || !selectedSources.length || !selectedCurves.length || busy}
              onClick={() => void recalculate()}
            >
              <RefreshCw size={15} />
              执行精确重算
            </button>

            </div>
            <div className="postprocessing-run-section">
              <div className="postprocessing-list-heading">
                <div>
                  <strong>最近运行</strong>
                  <span>{runs.length} 个批次</span>
                </div>
              </div>
              <div className="postprocessing-run-list">
                {runs.length === 0 && <div className="postprocessing-empty compact">尚无转换或重算记录</div>}
                {runs.slice(0, 5).map((run) => (
                  <div className="postprocessing-run" key={run.id}>
                    <span>
                      <strong title={run.id}>{run.id}</strong>
                      <small title={run.input_sha256}>{shortHash(run.input_sha256)}</small>
                    </span>
                    <em className={`run-status ${run.status}`}>{runStatusLabel[run.status] || run.status}</em>
                  </div>
                ))}
              </div>
            </div>
          </section>
      </div>

      <section style={view === 'intensity' ? undefined : { display: 'none' }} className="surface postprocessing-surface postprocessing-export-surface">
          <div className="surface-heading">
            <div>
              <h2>重算结果与已导入结果导出</h2>
            </div>
            <Download size={18} />
          </div>
          <div className="postprocessing-export-grid">
            <label className="field">
              <span>文件格式</span>
              <select value={format} onChange={(event) => setFormat(event.target.value as typeof format)}>
                <option value="txt">文本（TXT）</option>
                <option value="csv">CSV</option>
                <option value="excel">Excel（XLS）</option>
              </select>
            </label>
            <label className="field postprocessing-directory-field">
              <span>输出目录</span>
              <input
                value={directory}
                onChange={(event) => setDirectory(event.target.value)}
                placeholder="例如 C:\\Exports"
              />
            </label>
            <label className="field">
              <span>文件名</span>
              <input value={filename} onChange={(event) => setFilename(event.target.value)} />
            </label>
          </div>
          <div className="postprocessing-export-footer">
              <label className="field">
                <span>矩阵输出来源</span>
                <select value={exportBatch} onChange={(event) => setExportBatch(event.target.value)}>
                  <option value="">所选原始结果（DAT 数值 / PDT 峰值与背景）</option>
                  {runs
                    .filter((run) => run.status === 'completed' && run.result)
                    .map((run) => (
                      <option key={run.id} value={`recalc:${run.id}`}>
                        重算批次 {run.id}
                      </option>
                    ))}
                </select>
              </label>
            <div>
              <strong>{exportSelectionCount} 条记录待导出</strong>
              <span>
                {exportBatch ? '使用所选重算批次数值' : '使用所选原始结果'}{' '}
                · 同名文件自动追加后缀
              </span>
            </div>
            <button
              className="primary-button"
              disabled={!canExport || !exportSelectionCount || busy}
              onClick={() => void exportMatrix()}
            >
              <Download size={15} />
              导出数据
            </button>
          </div>
        </section>
    </div>
  )
}
