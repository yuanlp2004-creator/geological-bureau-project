import { SectionHeading } from '../../components/SectionHeading'
import { PageFileActions } from '../../components/PageFileActions'
import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { useEffect, useRef, useState } from 'react'
import { Eye, RefreshCw } from 'lucide-react'
import { api, type AnalysisRun } from '../../api'
import { request } from '../../api/client'
import { IntensityExportPanel } from './IntensityExportPanel'
import { ReportPreview, type ReportPreviewState } from '../reports/ReportOutput'

type Table = Array<Array<string | number | null>>
const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)

export function AnalysisIntensityOutput({ actionsTarget, token, hidden, canPrint, onToast }: {
  actionsTarget?: HTMLElement | null; token: string; hidden: boolean; canPrint: boolean; onToast: (message: string) => void
}) {
  const [legacyIds, setLegacyIds] = useState<number[]>([])
  const [runs, setRuns] = useState<AnalysisRun[]>([])
  const [runId, setRunId] = useState<number | undefined>()
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [table, setTable] = useState<Table | null>(null)
  const [previewState, setPreviewState] = useState<ReportPreviewState | null>(null)
  const [error, setError] = useState('')
  const [tableError, setTableError] = useState('')
  const loaded = useRef(false)
  const generation = useRef(0)
  const previewGeneration = useRef(0)
  useEffect(() => { loaded.current = false; generation.current++; return () => { generation.current++ } }, [token])
  const load = async () => {
    const current = ++generation.current
    try {
      const next = await api.analysisRuns(token)
      if (current !== generation.current) return
      const completed = next.filter(item => item.status === 'completed')
      setRuns(completed)
      setRunId(value => completed.some(item => item.id === value) ? value : undefined)
      setError('')
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : '无法读取分析批次')
    }
  }
  useEffect(() => {
    if (hidden || loaded.current) return
    loaded.current = true
    void load()
  }, [hidden, token])
  useEffect(() => {
    const current = ++previewGeneration.current
    setTable(null)
    setTableError('')
    setPreviewState(null)
    setLoading(Boolean(runId || legacyIds.length))
    if (runId || legacyIds.length) void request<{ table: Table }>(legacyIds.length ? '/api/v1/postprocessing/legacy-intensity-output' : `/api/v1/analyses/runs/${runId}/intensity-output`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(legacyIds.length ? {record_ids: legacyIds} : { save_intensity: false, print_intensity: false, print_to_text: false, save_positions: false })
    }).then(result => {
      if (current === previewGeneration.current) setTable(result.table)
    }).catch(failure => {
      if (current === previewGeneration.current) setTableError(failure instanceof Error ? failure.message : '无法读取强度表')
    }).finally(() => { if (current === previewGeneration.current) setLoading(false) })
    return () => { previewGeneration.current++ }
  }, [token, runId, legacyIds])
  const active = runs.find(item => item.id === runId)
  const title = legacyIds.length ? '旧 PDT 强度表' : active ? `${active.name || `分析 ${active.id}`} · 强度表` : '强度表'
  const preview = () => {
    if (!table) return
    const markup = table.map((row, index) => `<tr>${row.map(value => `<${index ? 'td' : 'th'}>${escapeHtml(value)}</${index ? 'td' : 'th'}>`).join('')}</tr>`).join('')
    setPreviewState({ title: `${title}预览`, html: `<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>${escapeHtml(title)}</title><style>body{font-family:"Microsoft YaHei",sans-serif;color:#243b53;padding:24px;background:white}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #cbd5e1;padding:8px;text-align:right;white-space:nowrap}th{background:#eef2f6}th:first-child,td:first-child{text-align:left}p{font-size:12px;color:#52677c}</style><h2>${escapeHtml(title)}</h2><p>${escapeHtml(active?.method_name)} v${escapeHtml(active?.method_version)} · ${table.length - 1} 行强度数据</p><table>${markup}</table></html>` })
  }
  return <div className="page-content reports-page intensity-report-page refined-page remaining-page" style={hidden ? { display: 'none' } : undefined} data-testid="analysis-intensity-output">
    <PageFileActions target={actionsTarget} hidden={hidden}><OpenLegacyFile onBusyChange={setBusy} token={token} purpose="intensity" label="打开强度文件" disabled={busy || loading} onOpened={result => {setRunId(undefined);setLegacyIds(result.record_ids)}}/><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}><RefreshCw size={16}/>刷新批次</button></PageFileActions>
    <div className="reports-grid">
      <section className="surface report-builder">
        <div className="surface-heading"><SectionHeading title={<>数据来源</>} /><span className="state-chip">已完成分析</span></div>
        <label className="field intensity-run-selector"><span>分析批次</span><select aria-label="分析批次" value={runId ?? ''} disabled={busy}
          onChange={event => {setLegacyIds([]);setRunId(Number(event.target.value) || undefined)}}>
          <option value="">请选择已完成分析</option>{runs.map(item => <option key={item.id} value={item.id}>{item.name || `分析 ${item.id}`} · {item.method_name} v{item.method_version}</option>)}
        </select></label>
        {legacyIds.length ? <div className="report-summary"><strong>旧 PDT 强度数据</strong><span>已保存到新版数据库，可直接预览、打印和导出。</span></div> : active ? <div className="report-summary"><strong>{active.name || `分析 ${active.id}`}</strong><span>{active.method_name} · 方法 v{active.method_version}</span><span>按样品和重复次数展示各谱线峰值及背景强度。</span></div>
          : <div className="empty-state">选择分析批次后查看、打印或导出强度数据</div>}
        {error && <p role="alert">{error}</p>}
      </section>
      <section className="surface report-output intensity-preview">
        <div className="surface-heading"><h2>强度表预览</h2>{table && <span className="state-chip">{table.length - 1} 行</span>}</div>
        {table ? <>
          <div className="intensity-table-scroll"><table><thead><tr>{table[0].map((value, index) => <th key={index}>{value}</th>)}</tr></thead>
            <tbody>{table.slice(1, 6).map((row, index) => <tr key={index}>{row.map((value, column) => <td key={column}>{value}</td>)}</tr>)}</tbody></table></div>
          <div className="report-format-actions"><button className="secondary-button" onClick={preview}><Eye size={16}/>预览</button><span className="intensity-output-note">此处展示前 5 行，预览和输出包含全部数据。</span></div>
        </> : <div className="empty-state">{loading ? '正在读取强度表…' : tableError ? '强度表读取失败，请重新选择批次重试' : '选择分析批次后将在此显示强度表'}</div>}
        {tableError && <p role="alert">{tableError}</p>}
      </section>
    </div>
    <IntensityExportPanel token={token} runId={runId} legacyIds={legacyIds} disabled={!table || loading} canPrint={canPrint} onBusyChange={setBusy} onToast={onToast}/>
    <ReportPreview previewLoading={null} previewState={hidden ? null : previewState} closePreview={() => setPreviewState(null)}/>
  </div>
}
