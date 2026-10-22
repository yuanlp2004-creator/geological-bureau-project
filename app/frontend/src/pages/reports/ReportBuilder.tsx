import { SectionHeading } from '../../components/SectionHeading'
import { useEffect, useState } from 'react'
import { FileBarChart } from 'lucide-react'
import { type ReportTemplate } from '../../api'

export type ReportDraft = {
  analysis_run_ids: number[]
  legacy_result_ids?: number[]
  template_key: string
  report_number?: string
  arrangement: 'standard' | 'exchange'
  table_layout?: 'legacy_matrix'|'detail'
  filters: { sample_name: string; element: string }
}

export type ReportSource = { kind: 'dat'; id: number; name: string; sampleCount: number }
  | { kind: 'analysis'; id: number; name: string; sampleCount: number; status: string }

type Props = {
  source: ReportSource | null
  templates: ReportTemplate[]
  canWrite: boolean
  busy: boolean
  onCreate: (input: ReportDraft) => Promise<void>
  onToast: (message: string) => void
}

export function ReportBuilder({ source, templates, canWrite, busy, onCreate, onToast }: Props) {
  const [arrangement, setArrangement] = useState<'standard' | 'exchange'>('standard')
  const [tableLayout,setTableLayout]=useState<'legacy_matrix'|'detail'>('legacy_matrix')
  const [sampleFilter, setSampleFilter] = useState('')
  const [elementFilter, setElementFilter] = useState('')
  const [templateKey, setTemplateKey] = useState('analysis-standard')
  const [reportNumber, setReportNumber] = useState('')
  useEffect(() => {
    if (templates[0]) setTemplateKey(templates[0].key)
  }, [templates])
  const create = () => {
    if (!source) return onToast('请先打开要建立报告的数据')
    if (!canWrite || busy) return
    if (source.kind === 'analysis' && source.status !== 'completed') return onToast('请先完成当前批次的分析')
    return onCreate({
      analysis_run_ids: source.kind === 'analysis' ? [source.id] : [],
      ...(source.kind === 'dat' ? { legacy_result_ids: [source.id] } : {}),
      template_key: templateKey,
      report_number: reportNumber.trim() || undefined,
      arrangement,
      table_layout:tableLayout,
      filters: { sample_name: sampleFilter, element: elementFilter }
    })
  }
  return (
    <section className="surface report-builder">
      <div className="surface-heading"><SectionHeading title="建立报告" /></div>
      {source ? <div className="report-current-source" data-testid="report-current-source">
        <strong title={source.name}>{source.name}</strong>
        <span>{source.kind === 'dat' ? 'DAT 结果' : '分析批次'} · {source.sampleCount} 个样品</span>
        {source.kind === 'analysis' && source.status !== 'completed' && <span>当前批次尚未完成分析</span>}
      </div> : <div className="empty-state">请打开 DAT 报告文件，或在“样品分析”中打开要输出的批次。</div>}
        <div className="report-form">
          <div className="report-format-fields">
            <label className="field">
              <span>报告编号（可选）</span>
              <input
                value={reportNumber}
                onChange={(event) => setReportNumber(event.target.value)}
                placeholder="自动生成"
              />
            </label>
            <label className="field">
              <span>报告模板</span>
              <select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>
                {templates.map((template) => (
                  <option key={template.key} value={template.key}>
                    {template.name} v{template.version}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>表格形式</span>
              <select value={tableLayout} onChange={e => setTableLayout(e.target.value as typeof tableLayout)}>
                <option value="legacy_matrix">旧版样品×元素矩阵</option>
                <option value="detail">完整明细长表</option>
              </select>
            </label>
          </div>
          <div className="report-filter-fields">
            <div className="field">
              <span>排列</span>
              <div className="segmented" role="group" aria-label="排列">
                <button aria-pressed={arrangement === 'standard'} className={arrangement === 'standard' ? 'active' : ''} onClick={() => setArrangement('standard')}>
                  常规排列
                </button>
                <button aria-pressed={arrangement === 'exchange'} className={arrangement === 'exchange' ? 'active' : ''} onClick={() => setArrangement('exchange')}>
                  交换排列
                </button>
              </div>
            </div>
            <label className="field">
              <span>样品筛选</span>
              <input
                value={sampleFilter}
                onChange={(event) => setSampleFilter(event.target.value)}
                placeholder="全部样品"
              />
            </label>
            <label className="field">
              <span>元素筛选</span>
              <input
                value={elementFilter}
                onChange={(event) => setElementFilter(event.target.value)}
                placeholder="全部元素"
              />
            </label>
            <button className="primary-button report-create-button" disabled={!canWrite || busy || !source || (source.kind === 'analysis' && source.status !== 'completed')} onClick={() => void create()}>
              <FileBarChart size={16} />
              建立报告版本
            </button>
          </div>
        </div>
      </section>
  )
}
