import { Plus, Search } from 'lucide-react'
import { useLayoutEffect, useRef } from 'react'
import {
  type CcdLayoutOption,
  type MethodLineCollection,
  type SpectralLine
} from '../../api'
import { lineTypeLabel } from './spectralLineDraft'
import {
  buildBatchPreviewSummary, ccdLabel, defaultSpectralLineFilters, lineDetectionReason, type SpectralLineFilters
} from './spectralLineFilters'

type LineLocation = { id: string; focus: boolean }

function wavelengthText(range: [number, number] | null) {
  if (!range) return '—'
  const [start, end] = range
  return start === end ? `${start.toFixed(4)} nm` : `${start.toFixed(4)}–${end.toFixed(4)} nm`
}

function BatchPreview({ summary, onClear }: { summary: ReturnType<typeof buildBatchPreviewSummary>; onClear: () => void }) {
  return (
    <section className="spectral-batch-preview" data-testid="spectral-batch-preview" aria-label="批量预览">
      <div className="spectral-preview-heading">
        <strong>已勾选 {summary.totalCount} 条</strong>
        <button type="button" onClick={onClear}>清空勾选</button>
      </div>
      <p>只读预览（不执行批量修改）</p>
      <p>列表外 {summary.offListCount} 条 · 理论波长 {wavelengthText(summary.wavelengthRange)}</p>
      <p>基线 {summary.byType.baseline} · 分析 {summary.byType.analysis} · 内标 {summary.byType.internal_standard} · 定位 {summary.byType.positioning}</p>
      <p>启用 {summary.enabledCount} · 停用 {summary.disabledCount} · 可检出 {summary.detectableCount} · 未检出 {summary.undetectableCount}</p>
      {summary.offListCount > 0 && <p>列表外元素 {summary.offListElements.join('、')} · {wavelengthText(summary.offListWavelengthRange)}</p>}
    </section>
  )
}

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  listCollapsed: boolean
  collection: MethodLineCollection | null
  canWrite: boolean
  beginCreate: () => void
  busy: boolean
  sortBy: (key: "element" | "wavelength_nm") => void
  movable: SpectralLine[]
  selectedId: string | null
  creating: boolean
  edit: (line: SpectralLine) => void
  visibleLines: SpectralLine[]
  filters: SpectralLineFilters
  setFilters: (filters: SpectralLineFilters) => void
  ccdLayout?: CcdLayoutOption
  batchSelectedIds: ReadonlySet<string>
  toggleBatchSelection: (id: string) => void
  clearBatchSelection: () => void
  location: LineLocation | null
  onLocate: (id: string) => void
}

export function SpectralLineList({
  listCollapsed,
  collection,
  canWrite,
  beginCreate,
  busy,
  sortBy,
  movable,
  selectedId,
  creating,
  edit,
  visibleLines,
  filters,
  setFilters,
  ccdLayout,
  batchSelectedIds,
  toggleBatchSelection,
  clearBatchSelection,
  location,
  onLocate,
}: PanelProps) {
  const list = useRef<HTMLDivElement>(null)
  const handledLocation = useRef<LineLocation | null>(null)
  const lines = collection?.lines ?? []
  const ccdIndices = new Set(lines.flatMap(line => line.detectability?.ccd_index ?? []))
  const angles = new Set(lines.flatMap(line => line.detectability?.angle_deg ?? []))
  if (filters.ccdFilter !== 'all' && filters.ccdFilter !== 'unassigned') ccdIndices.add(Number(filters.ccdFilter))
  if (filters.angleFilter !== 'all' && filters.angleFilter !== 'undetermined') angles.add(Number(filters.angleFilter))
  const batch = buildBatchPreviewSummary(lines, visibleLines, batchSelectedIds)
  const setFilter = <K extends keyof SpectralLineFilters,>(key: K, value: SpectralLineFilters[K]) =>
    setFilters({ ...filters, [key]: value })

  useLayoutEffect(() => {
    const container = list.current
    if (listCollapsed || !container) return
    const request = location !== handledLocation.current ? location : null
    handledLocation.current = location
    const id = request?.id ?? selectedId
    const card = Array.from(container.querySelectorAll<HTMLButtonElement>('.spectral-line-card'))
      .find(button => button.dataset.lineId === id)
    if (!card) return
    if (request?.focus) {
      card.focus({ preventScroll: true })
      card.scrollIntoView({ block: 'nearest', inline: 'nearest' })
      return
    }
    const row = card.getBoundingClientRect()
    const viewport = container.getBoundingClientRect()
    if (row.top < viewport.top) container.scrollTop += row.top - viewport.top
    else if (row.bottom > viewport.bottom) container.scrollTop += row.bottom - viewport.bottom
  }, [listCollapsed, location, selectedId, visibleLines])

  return (
    <section className="surface spectral-list-surface" id="method-spectral-list" hidden={listCollapsed}>
      <div className="surface-heading spectral-heading">
        <div>
          <h2>
            谱线清单 <span className="count-badge">{collection?.lines.length ?? 0}/300</span>
          </h2>
        </div>
        {canWrite && (
          <button className="secondary-button" onClick={beginCreate} disabled={busy}>
            <Plus size={15} />
            添加谱线
          </button>
        )}
      </div>
      <div className="spectral-search-filters">
        <label className="spectral-search-field">
          <Search size={15} aria-hidden="true" />
          <input type="search" aria-label="搜索谱线" placeholder="元素、波长或 ID" value={filters.query}
            onChange={event => setFilter('query', event.target.value)} />
        </label>
        <div className="spectral-filter-grid">
          <label>谱线类型
            <select aria-label="按谱线类型筛选" value={filters.lineType}
              onChange={event => setFilter('lineType', event.target.value as SpectralLineFilters['lineType'])}>
              <option value="all">全部</option>
              {Object.entries(lineTypeLabel).map(([type, label]) => <option value={type} key={type}>{label}</option>)}
            </select>
          </label>
          <label>CCD
            <select aria-label="按 CCD 筛选" value={filters.ccdFilter}
              onChange={event => setFilter('ccdFilter', event.target.value as SpectralLineFilters['ccdFilter'])}>
              <option value="all">全部</option>
              <option value="unassigned">未分配</option>
              {[...ccdIndices].sort((a, b) => a - b).map(index => <option value={index} key={index}>{ccdLabel(ccdLayout, index)}</option>)}
            </select>
          </label>
          <label>角位
            <select aria-label="按角位筛选" value={filters.angleFilter}
              onChange={event => setFilter('angleFilter', event.target.value as SpectralLineFilters['angleFilter'])}>
              <option value="all">全部</option>
              <option value="undetermined">未确定</option>
              {[...angles].sort((a, b) => a - b).map(angle => <option value={angle} key={angle}>{angle}°</option>)}
            </select>
          </label>
          <label>检出状态
            <select aria-label="按检出状态筛选" value={filters.statusFilter}
              onChange={event => setFilter('statusFilter', event.target.value as SpectralLineFilters['statusFilter'])}>
              <option value="all">全部</option>
              <option value="undetectable">未检出</option>
              <option value="disabled">停用</option>
              <option value="attention">未检出或停用</option>
            </select>
          </label>
        </div>
        <div className="spectral-filter-actions">
          <span role="status">显示 {visibleLines.length} / {lines.length} 条</span>
          <button type="button" onClick={() => setFilters(defaultSpectralLineFilters)}>重置筛选</button>
        </div>
        {selectedId != null && !visibleLines.some(line => line.id === selectedId) && (
          <div className="spectral-filter-actions spectral-selected-hidden">
            <span>当前编辑项在筛选结果外</span>
            <button type="button" onClick={() => onLocate(selectedId)}>定位</button>
          </div>
        )}
      </div>
      <div className="spectral-sortbar">
        <span>排序</span>
        <button onClick={() => sortBy('element')} disabled={!canWrite || busy || movable.length < 2}>
          按元素
        </button>
        <button onClick={() => sortBy('wavelength_nm')} disabled={!canWrite || busy || movable.length < 2}>
          按波长
        </button>
      </div>
      {batch.totalCount > 0 && <BatchPreview summary={batch} onClear={clearBatchSelection} />}
      <div className="spectral-line-list" ref={list}>
        {collection && !visibleLines.length && <p className="spectral-list-empty">没有符合条件的谱线</p>}
        {visibleLines.map(line => {
          const active = line.id === selectedId && !creating
          const title = `${line.element} ${line.wavelength_nm.toFixed(4)} nm`
          const detail = line.detectability?.detectable
            ? [line.detectability.ccd_label, line.detectability.angle_slot == null ? null : `角度位 ${line.detectability.angle_slot}`].filter(Boolean).join(' / ')
            : lineDetectionReason(line) || '暂无检出结果'
          return (
            <div className="spectral-line-item-row" key={line.id}>
              <input type="checkbox" aria-label={`勾选 ${title}`} checked={batchSelectedIds.has(line.id)}
                onChange={() => toggleBatchSelection(line.id)} />
              <button type="button" className={`spectral-line-card ${active ? 'active' : ''} ${line.enabled ? '' : 'disabled'}`}
                data-line-id={line.id} aria-current={active || undefined} disabled={busy} onClick={() => edit(line)}>
                <span className={`line-type-mark ${line.line_type}`} />
                <span className="line-main">
                  <strong title={title}>{line.element} <b>{line.wavelength_nm.toFixed(4)}</b> nm</strong>
                  <small title={`${lineTypeLabel[line.line_type]} · ${detail}`}>{lineTypeLabel[line.line_type]} · {detail}</small>
                </span>
                <span className="line-badges">
                  {line.reference_baseline && <i>基线</i>}
                  {line.critical_band && <i className="critical">关键</i>}
                  {!line.enabled && <i className="off">停用</i>}
                </span>
              </button>
            </div>
          )
        })}
      </div>
    </section>
  )
}
