import {
  FileText,
  Image,
  Printer,
  RefreshCw,
  RotateCcw,
  Save,
  ArrowUp,
  ArrowDown,
  Info
} from 'lucide-react'
import { api, type AnalysisCurveSnapshot, type AnalysisRun } from '../../api'
import type { AnalysisCurveLine } from '../../api/analysis'
import { CurveChart } from './CurveChart'
import { useEffect, useRef, useState } from 'react'
import { nudgeStandardIntensity } from '../../components/legacyObservation'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  curveLine: AnalysisCurveLine
  canCurve: boolean
  curveAction: (lineId: string, payload: Record<string, unknown>, success: string, afterSuccess?: () => void) => void
  busy: boolean
  selected: AnalysisRun
  mutate: (operation: () => Promise<AnalysisRun>, success: string, continuous?: boolean) => Promise<boolean>
  token: string
  shownSnapshot: AnalysisCurveSnapshot | undefined
  showPreview: (snapshot: AnalysisCurveSnapshot, mode: "image" | "text") => Promise<void>
  canPrint: boolean
  printCurve: (snapshot: AnalysisCurveSnapshot, mode: "image" | "text") => Promise<void>
}

export function AnalysisCurves({
  curveLine,
  canCurve,
  curveAction,
  busy,
  selected,
  mutate,
  token,
  shownSnapshot,
  showPreview,
  canPrint,
  printCurve,
}: PanelProps) {
  const [selectedPoint, setSelectedPoint] = useState(0)
  const [ruler, setRuler] = useState<1 | 5>(5)
  const chartHost = useRef<HTMLDivElement>(null)
  useEffect(() => { setSelectedPoint(curveLine.workspace.points[0]?.point_index ?? 0); setRuler(5) },
    [selected.id, curveLine.line_id, shownSnapshot?.id])
  const point = curveLine.workspace.points.find((item) => item.point_index === selectedPoint)
  const currentFit = Boolean(shownSnapshot && shownSnapshot.adjustment_set_id === curveLine.workspace.adjustment_set_id
    && shownSnapshot.fit_mode === curveLine.workspace.fit_mode && shownSnapshot.coordinate_type === curveLine.workspace.coordinate_type)
  const selectNext = (direction: number) => {
    const points = curveLine.workspace.points
    if (!points.length) return
    const index = Math.max(0, points.findIndex((item) => item.point_index === selectedPoint))
    setSelectedPoint(points[(index + direction + points.length) % points.length].point_index)
  }
  const nudge = (direction: -1 | 1) => {
    if (!canCurve || busy || point?.adjusted_intensity == null) return
    const intensities = [...curveLine.workspace.points.map((item) => item.adjusted_intensity),
      ...(shownSnapshot?.chart.map((item) => item.intensity) ?? [])].filter((value): value is number => value != null)
    const height = Math.max(1, (chartHost.current?.querySelector('svg')?.getBoundingClientRect().height ?? 280) - 20)
    const next = nudgeStandardIntensity(point.adjusted_intensity, intensities,
      curveLine.workspace.coordinate_type === 'logarithmic', height, ruler, direction)
    if (next === point.adjusted_intensity) return
    curveAction(curveLine.line_id, { action: 'adjust', point_index: point.point_index, adjusted_intensity: next,
      reason: `按旧版标尺 ${ruler} ${direction > 0 ? '上移' : '下移'}标准点 ${point.name}` }, '标准点已微调，请重新拟合')
  }
  return (
    <div className="analysis-workspace curve-panel">
      <div className="curve-panel-heading"><h3>{curveLine.element} <span>{curveLine.wavelength_nm.toFixed(3)} nm</span></h3><span>标准曲线</span></div>
      <div className="curve-command-row">
        <label className="field">
          <span>拟合方式</span>
          <select
            value={curveLine.workspace.fit_mode}
            disabled={busy || !canCurve}
            onChange={(event) =>
              curveAction(
                curveLine.line_id,
                { action: 'set_fit', fit_mode: event.target.value, reason: '切换拟合方式' },
                '拟合方式已保存到新的修正集'
              )
            }
          >
            <option value="linear">直线函数</option>
            <option value="quadratic">二次曲线</option>
            <option value="cubic">三次曲线</option>
            <option value="spline">样条函数</option>
          </select>
        </label>
        <label className="analysis-switch">
          <input type="checkbox" checked={curveLine.workspace.coordinate_type === 'logarithmic'}
            disabled={busy || !canCurve}
            onChange={(event) => curveAction(curveLine.line_id,
              { action: 'set_coordinate', coordinate_type: event.target.checked ? 'logarithmic' : 'normal', reason: '切换坐标方式' },
              '坐标方式已保存到新的修正集')} />
          <span>对数坐标</span>
        </label>
        <div className="curve-fit-actions"><button
          className="secondary-button"
          disabled={busy || !canCurve || !selected.quality.latest_snapshot}
          onClick={() =>
            void mutate(
              () =>
                api.fitAnalysisCurve(token, selected.id, curveLine.line_id, {
                  reason: '复核修正集后重新拟合'
                }),
              '新的不可变曲线快照已生成'
            )
          }
        >
          <RefreshCw size={14} />
          重新拟合
        </button>
        <button
          className="secondary-button curve-reset"
          disabled={busy || !canCurve}
          onClick={() =>
            curveAction(
              curveLine.line_id,
              { action: 'restore_all', reason: '恢复全部原始标准强度和启用状态' },
              '全部标准点已恢复到原始状态'
            )
          }
        >
          <RotateCcw size={14} />
          全部还原
        </button>
        {shownSnapshot && (
          <button
            className="primary-button"
            disabled={
              busy ||
              !currentFit ||
              !canCurve ||
              !shownSnapshot.publishable ||
              shownSnapshot.id === curveLine.active_curve_snapshot_id
            }
            onClick={() =>
              void mutate(
                () =>
                  api.publishAnalysisCurve(
                    token,
                    selected.id,
                    curveLine.line_id,
                    shownSnapshot.id,
                    '曲线复核通过并发布'
                  ),
                '曲线快照已发布，样品结果永久引用该版本'
              )
            }
          >
            <Save size={14} />
            保存曲线
          </button>
        )}
        </div>
      </div>
      <div className="curve-summary">
        <div>
          <span>当前修正集</span>
          <strong>#{curveLine.workspace.sequence || '基础'}</strong>
        </div>
        <div>
          <span>最新拟合快照</span>
          <strong>{shownSnapshot ? `#${shownSnapshot.id}` : '—'}</strong>
        </div>
        <div>
          <span>已发布快照</span>
          <strong>
            {curveLine.active_curve_snapshot_id ? `#${curveLine.active_curve_snapshot_id}` : '—'}
          </strong>
        </div>
        <div>
          <span>相关系数 / RMSE</span>
          <strong>
            {shownSnapshot
              ? `${shownSnapshot.diagnostics.correlation?.toFixed(6) ?? '—'} / ${shownSnapshot.diagnostics.rmse.toFixed(5)}`
              : '—'}
          </strong>
        </div>
      </div>
      <div className="analysis-curve-operator" tabIndex={0} aria-label="标准点标尺操作" ref={chartHost}
        onKeyDown={(event) => {
          if (event.altKey || event.metaKey || event.shiftKey || event.target instanceof HTMLInputElement) return
          if (event.key === 'Insert') { event.preventDefault(); setRuler((value) => value === 1 ? 5 : 1) }
          if (event.ctrlKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
            event.preventDefault()
            if (event.key === 'ArrowLeft') selectNext(-1)
            else if (event.key === 'ArrowRight') selectNext(1)
            else nudge(event.key === 'ArrowUp' ? 1 : -1)
          }
        }}>
        <div className="analysis-actions">
          <label>标准点 <select aria-label="曲线标准点" value={selectedPoint} onChange={(event) => setSelectedPoint(Number(event.target.value))}>
            {curveLine.workspace.points.map((item) => <option key={item.point_index} value={item.point_index}>{item.point_index.toString(16).toUpperCase()} · {item.name}</option>)}
          </select></label>
          <label>标尺 <select aria-label="标准点标尺" value={ruler} onChange={(event) => setRuler(Number(event.target.value) as 1 | 5)}>
            <option value={1}>1</option><option value={5}>5</option></select></label>
          <button className="secondary-button curve-nudge" aria-label="上移标准点" title="上移标准点（Ctrl＋↑）" disabled={!canCurve || busy || point?.adjusted_intensity == null} onClick={() => nudge(1)}><ArrowUp size={15} /></button>
          <button className="secondary-button curve-nudge" aria-label="下移标准点" title="下移标准点（Ctrl＋↓）" disabled={!canCurve || busy || point?.adjusted_intensity == null} onClick={() => nudge(-1)}><ArrowDown size={15} /></button>
          <output>修正强度 {point?.adjusted_intensity?.toPrecision(9) ?? '未测量'}</output>
          <span className="curve-keyboard-help" tabIndex={0} aria-label="曲线快捷键说明" title="图上选点；Ctrl＋左右切换标准点，Ctrl＋上下微调，Insert 切换标尺。"><Info size={15} /></span>
        </div>
        {!currentFit && <p className="curve-stale-note">标准点或条件已改变，请重新拟合后打印、保存。</p>}
        <CurveChart snapshot={shownSnapshot} unit={curveLine.unit} points={curveLine.workspace.points}
          selectedPoint={selectedPoint} onSelectPoint={setSelectedPoint} />
      </div>
      <div className="curve-footer-actions">
        {shownSnapshot && (
          <>
            <button className="secondary-button" disabled={!currentFit || busy} onClick={() => void showPreview(shownSnapshot, 'image')}>
              <Image size={14} />
              图像预览
            </button>
            <button className="secondary-button" disabled={!currentFit || busy} onClick={() => void showPreview(shownSnapshot, 'text')}>
              <FileText size={14} />
              文本预览
            </button>
            <button
              className="secondary-button"
              disabled={!canPrint || !currentFit || busy}
              onClick={() => void printCurve(shownSnapshot, 'image')}
            >
              <Printer size={14} />
              图像打印 PDF
            </button>
            <button
              className="secondary-button"
              disabled={!canPrint || !currentFit || busy}
              onClick={() => void printCurve(shownSnapshot, 'text')}
            >
              <Printer size={14} />
              文本打印 PDF
            </button>
          </>
        )}
        <span>
          {curveLine.snapshots.length} 个曲线版本 ·{' '}
          {selected.curves.print_jobs.filter((job) => job.curve_snapshot_id === shownSnapshot?.id).length}{' '}
          条打印记录
        </span>
      </div>
    </div>
  )
}
