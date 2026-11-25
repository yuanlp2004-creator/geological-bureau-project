import { api, type AnalysisCurveSnapshot, type AnalysisRun } from '../../api'
import type { AnalysisCurveLine } from '../../api/analysis'
import { StandardCurveWorkspace, standardCurveLineLabel, type StandardCurveAdjustment } from './StandardCurveWorkspace'
import { findPreviousCurveSnapshot } from './standardCurveModel'

type PanelProps = {
  curveLine: AnalysisCurveLine
  canCurve: boolean
  curveAction: (lineId: string, payload: Record<string, unknown>, success: string, afterSuccess?: () => void) => void
  busy: boolean
  selected: AnalysisRun
  mutate: (operation: () => Promise<AnalysisRun>, success: string) => Promise<boolean>
  token: string
  shownSnapshot: AnalysisCurveSnapshot | undefined
  showPreview: (snapshot: AnalysisCurveSnapshot, mode: 'image' | 'text') => Promise<void>
  canPrint: boolean
  printCurve: (snapshot: AnalysisCurveSnapshot, mode: 'image' | 'text') => Promise<void>
  selectLine: (lineId: string) => void
  next: { label: string; disabled: boolean; action: () => void }
}

export function AnalysisCurves({
  curveLine, canCurve, curveAction, busy, selected, mutate, token, shownSnapshot, showPreview, canPrint, printCurve, selectLine, next,
}: PanelProps) {
  const { workspace, line_id: lineId } = curveLine
  const legacy = selected.calculation_profile === 'legacy_2_0_2'
  const currentFit = Boolean(shownSnapshot && shownSnapshot.qc_snapshot_id === selected.quality.latest_snapshot?.id
    && shownSnapshot.adjustment_set_id === workspace.adjustment_set_id
    && shownSnapshot.fit_mode === workspace.fit_mode && shownSnapshot.coordinate_type === workspace.coordinate_type)
  const canEdit = !busy && canCurve && selected.status === 'completed' && Boolean(selected.quality.latest_snapshot)
  const previousSnapshot = findPreviousCurveSnapshot(curveLine.snapshots, shownSnapshot)
  const samplePreview = shownSnapshot?.diagnostics?.sample_preview ?? selected.curves.results
    .filter((item) => !item.is_standard && item.curve_snapshot_id === shownSnapshot?.id)
  const canOutput = currentFit && !busy

  const fit = () => void mutate(() => api.fitAnalysisCurve(token, selected.id, lineId, {
    reason: '复核标准点后重新拟合'
  }), '新的标准曲线拟合已生成')
  const adjust = (payload: StandardCurveAdjustment, message: string, refit = false) =>
    curveAction(lineId, payload, message, legacy && refit ? fit : undefined)

  return <StandardCurveWorkspace key={`${selected.id}/${lineId}`} line={curveLine} workspace={workspace}
    profile={selected.calculation_profile} shownSnapshot={shownSnapshot} previousSnapshot={previousSnapshot} currentFit={currentFit}
    canEdit={canEdit} fit={fit} adjust={adjust} samplePreview={currentFit ? samplePreview : []}
    toolbar={<>
      <button type="button" disabled={next.disabled} onClick={next.action}>{next.label}</button>
      <select aria-label="分析谱线" value={lineId} disabled={busy} onChange={(event) => selectLine(event.target.value)}>
        {selected.curves.lines.map((line) => <option key={line.line_id} value={line.line_id}>{standardCurveLineLabel(line)}</option>)}
      </select>
      <button type="button" disabled={!shownSnapshot || !canOutput || !canPrint}
        onClick={() => shownSnapshot && void printCurve(shownSnapshot, 'text')}>打印标准</button>
      <button type="button" disabled={!shownSnapshot || !canOutput || !canPrint}
        onClick={() => shownSnapshot && void printCurve(shownSnapshot, 'image')}>打印曲线</button>
    </>}
    footer={shownSnapshot && <>
      <button type="button" disabled={!canOutput} onClick={() => void showPreview(shownSnapshot, 'text')}>文本预览</button>
      <button type="button" disabled={!canOutput} onClick={() => void showPreview(shownSnapshot, 'image')}>图像预览</button>
      <button type="button" className="primary-button" disabled={!canOutput || !canCurve || !shownSnapshot.publishable || shownSnapshot.id === curveLine.active_curve_snapshot_id}
        onClick={() => void mutate(() => api.publishAnalysisCurve(token, selected.id, lineId, shownSnapshot.id, '曲线复核通过并发布'), '曲线快照已发布')}>保存曲线</button>
    </>}
    status={currentFit ? (curveLine.active_curve_snapshot_id === shownSnapshot?.id ? '曲线已保存' : '待保存曲线') : undefined}
  />
}
