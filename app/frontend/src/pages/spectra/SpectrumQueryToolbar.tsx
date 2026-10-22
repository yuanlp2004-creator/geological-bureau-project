import { type SpectrumRecordSummary } from '../../api'
import { SectionHeading } from '../../components/SectionHeading'

// State and request ownership remain in the page.
type PanelProps = {
  actions?: React.ReactNode
  sourceKind: string
  setSourceKind: React.Dispatch<React.SetStateAction<string>>
  setOffset: React.Dispatch<React.SetStateAction<number>>
  search: string
  setSearch: React.Dispatch<React.SetStateAction<string>>
  angleFilter: string
  setAngleFilter: React.Dispatch<React.SetStateAction<string>>
  offset: number
  busy: boolean
  pageRecords: SpectrumRecordSummary[]
}

export function SpectrumQueryToolbar({
  actions,
  sourceKind,
  setSourceKind,
  setOffset,
  search,
  setSearch,
  angleFilter,
  setAngleFilter,
  offset,
  busy,
  pageRecords,
}: PanelProps) {
  return (
    <section className="surface spectrum-query-panel">
      <div className="surface-heading"><SectionHeading title="谱图查看" description="选择谱图，定位并比较信号。" />{actions}</div>
      <div className="spectrum-query-toolbar">
      <label className="field">
        来源{' '}
        <select
          aria-label="谱图来源"
          value={sourceKind}
          onChange={(event) => {
            setSourceKind(event.target.value)
            setOffset(0)
          }}
        >
          <option value="all">全部</option>
          <option value="raw">旧谱图</option>
          <option value="result">旧结果</option>
          <option value="sample">新采集样品</option>
        </select>
      </label>
      <label className="field">
        检索{' '}
        <input
          aria-label="检索谱图"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setOffset(0)
          }}
        />
      </label>
      <label className="field">
        转角{' '}
        <input
          aria-label="检索转角"
          value={angleFilter === 'all' ? '' : angleFilter}
          onChange={(event) => {
            setAngleFilter(event.target.value || 'all')
            setOffset(0)
          }}
        />
      </label>
      <nav className="spectrum-pagination" aria-label="谱图分页">
        <button
          className="secondary-button"
          disabled={offset === 0 || busy}
          onClick={() => setOffset((value) => Math.max(0, value - 100))}
        >
          上一页
        </button>
        <span aria-live="polite">第 {offset / 100 + 1} 页</span>
        <button
          className="secondary-button"
          disabled={pageRecords.length < 100 || busy}
          onClick={() => setOffset((value) => value + 100)}
        >
          下一页
        </button>
      </nav>
      </div>
    </section>
  )
}
