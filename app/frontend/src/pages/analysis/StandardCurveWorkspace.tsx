import { ArrowDown, ArrowUp } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import type { AnalysisCurveSnapshot, AnalysisRun } from '../../api'
import type { AnalysisCurveLine } from '../../api/analysis'
import { calculationProfileLabel } from '../../components/calculationProfile'
import { nudgeStandardIntensity } from '../../components/legacyObservation'
import { ContextMenu, useContextMenu } from '../../components/ContextMenu'
import { CurveChart, curveChartLimits } from './CurveChart'
import './standard-curve.css'

const fitModes = {
  linear: '直线函数',
  quadratic: '二次曲线',
  cubic: '三次曲线',
  spline: '样条函数',
}

const displayNumber = (value: number | null | undefined, digits: number) => value == null ? '—' : value.toFixed(digits)
const pointNumber = (index: number) => index.toString(16).toUpperCase()
export const standardCurveLineLabel = (line: Pick<AnalysisCurveLine, 'element' | 'wavelength_nm'>) =>
  `${line.element}  ${line.wavelength_nm.toFixed(4)}`

export type StandardCurveAdjustment =
  | { action: 'set_fit'; fit_mode: AnalysisCurveSnapshot['fit_mode']; reason: string }
  | { action: 'set_coordinate'; coordinate_type: AnalysisCurveSnapshot['coordinate_type']; reason: string }
  | { action: 'set_active'; point_index: number; active: boolean; reason: string }
  | { action: 'adjust'; point_index: number; adjusted_intensity: number; reason: string }
  | { action: 'restore'; point_index: number; reason: string }
  | { action: 'restore_all'; restore_activation: false; reason: string }

export type CurveSamplePreview = {
  sample_name: string
  intensity: number | null
  calculated_value: number | null
  management_sample?: boolean
}

type WorkspaceProps = {
  line: Pick<AnalysisCurveLine, 'element' | 'wavelength_nm' | 'unit' | 'decimal_places'>
  workspace: Pick<AnalysisCurveLine['workspace'], 'points' | 'fit_mode' | 'coordinate_type'>
  profile: AnalysisRun['calculation_profile']
  shownSnapshot?: AnalysisCurveSnapshot
  currentFit: boolean
  canEdit: boolean
  fit: () => void
  adjust: (payload: StandardCurveAdjustment, message: string, refit?: boolean) => void
  samplePreview: CurveSamplePreview[]
  toolbar?: ReactNode
  footer?: ReactNode
  status?: string
}

export function StandardCurveWorkspace({
  line, workspace, profile, shownSnapshot, currentFit, canEdit, fit, adjust, samplePreview, toolbar, footer, status,
}: WorkspaceProps) {
  const { points, coordinate_type: coordinate } = workspace
  const [selection, setSelectedPoint] = useState<number | undefined>()
  const menu = useContextMenu<number>()
  const [ruler, setRuler] = useState<1 | 5>(5)
  const [tab, setTab] = useState<'standards' | 'samples'>('standards')
  const chartHost = useRef<HTMLDivElement>(null)
  const point = points.find((item) => item.point_index === selection) ?? points[0]
  const selectedPoint = point?.point_index ?? 0
  const legacy = profile === 'legacy_2_0_2'
  const logarithmic = coordinate === 'logarithmic'
  const fitForChart = shownSnapshot?.coordinate_type === coordinate ? shownSnapshot : undefined
  const activeCount = points.filter((item) => item.active && item.adjusted_intensity != null).length
  const canTogglePoint = (item: typeof point) => canEdit && item?.adjusted_intensity != null && !(legacy && item.active && activeCount <= 4)
  const canRestorePoint = (item: typeof point) => canEdit && Boolean(item && item.adjusted_intensity !== item.original_intensity)
  const canRestoreAll = canEdit && points.some(canRestorePoint)
  const togglePoint = (index: number, value: boolean) => adjust({ action: 'set_active', point_index: index, active: value,
    reason: '修改参与拟合状态' }, '参与拟合状态已保存', true)
  const restorePoint = (index: number) => adjust({ action: 'restore', point_index: index, reason: '还原当前标准点测量强度' }, '当前标准点强度已还原')
  const restoreAll = () => adjust({ action: 'restore_all', restore_activation: false, reason: '恢复全部原始标准强度' }, '全部标准点强度已还原')
  const menuPoint = points.find(item => item.point_index === menu.target?.data)
  const canNudge = canEdit && point?.adjusted_intensity != null
  const diagnostics = currentFit ? shownSnapshot?.diagnostics : undefined
  const label = standardCurveLineLabel(line)

  const nudge = (direction: -1 | 1) => {
    if (!canNudge || point?.adjusted_intensity == null) return
    const { intensityMin, intensityMax } = curveChartLimits(fitForChart, points, logarithmic, legacy)
    const height = chartHost.current?.querySelector('svg')?.getBoundingClientRect().height ?? 280
    const value = nudgeStandardIntensity(point.adjusted_intensity, [intensityMin, intensityMax], logarithmic, height, ruler, direction)
    if (value === point.adjusted_intensity || (legacy && value <= 1e-5)) return
    adjust({ action: 'adjust', point_index: selectedPoint, adjusted_intensity: value,
      reason: `按标尺 ${ruler} 微调标准点 ${point.name}` }, '标准点已微调，请重新拟合')
  }

  return (
    <div className="standard-curve-window" aria-label="标准点标尺操作" tabIndex={0} onKeyDown={(event) => {
      if (event.altKey || event.metaKey || event.shiftKey || event.target instanceof HTMLInputElement) return
      if (event.key === 'Insert') {
        event.preventDefault()
        setRuler((value) => value === 1 ? 5 : 1)
      } else if (event.ctrlKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
        event.preventDefault()
        nudge(event.key === 'ArrowUp' ? 1 : -1)
      } else if (event.ctrlKey && points.length && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
        event.preventDefault()
        const index = Math.max(0, points.findIndex((item) => item.point_index === selectedPoint))
        setSelectedPoint(points[(index + (event.key === 'ArrowLeft' ? -1 : 1) + points.length) % points.length].point_index)
      }
    }}>
      {menu.target && menuPoint && <ContextMenu target={menu.target} close={menu.close} label="标准点菜单" groups={[
        [{ label: '参与拟合', checked: menuPoint.active, disabled: !canTogglePoint(menuPoint), run: () => togglePoint(menuPoint.point_index, !menuPoint.active) }],
        [{ label: '强度还原', disabled: !canRestorePoint(menuPoint), run: () => restorePoint(menuPoint.point_index) },
          { label: '全部还原', disabled: !canRestoreAll, run: restoreAll }]
      ]} />}
      <div className="standard-curve-toolbar" role="group" aria-label="标准曲线工具">
        <label>标准 <select aria-label="曲线标准点" value={selectedPoint} onChange={(event) => setSelectedPoint(Number(event.target.value))}>
          {!points.length && <option value={selectedPoint}>—</option>}
          {points.map((item) => <option key={item.point_index} value={item.point_index}>{pointNumber(item.point_index)} · {item.name}</option>)}
        </select></label>
        <label>标尺 <select aria-label="标准点标尺" value={ruler} onChange={(event) => setRuler(Number(event.target.value) as 1 | 5)}>
          <option value={1}>1</option><option value={5}>5</option>
        </select></label>
        <label title={legacy && point?.active && activeCount <= 4 ? '旧版拟合至少需要四个有效标准点' : undefined}>
          <input type="checkbox" checked={point?.active ?? false} disabled={!canTogglePoint(point)} onChange={event => togglePoint(selectedPoint, event.target.checked)} />
          参与拟合
        </label>
        <button type="button" disabled={!canRestorePoint(point)} onClick={() => restorePoint(selectedPoint)}>强度还原</button>
        <button type="button" disabled={!canRestoreAll} onClick={restoreAll}>全部还原</button>
        <button type="button" disabled={!canEdit} onClick={fit}>重新拟合</button>
        <select aria-label="拟合方式" value={workspace.fit_mode} disabled={!canEdit} onChange={(event) =>
          adjust({ action: 'set_fit', fit_mode: event.target.value as AnalysisCurveSnapshot['fit_mode'], reason: '切换拟合方式' }, '拟合方式已保存', true)}>
          {Object.entries(fitModes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        {toolbar}
      </div>

      <div className="standard-curve-panes">
        <section className="standard-curve-list" aria-label="标准曲线数据">
          <div className="standard-curve-tabs" role="tablist" aria-label="标准曲线数据视图">
            <button type="button" role="tab" aria-selected={tab === 'standards'} onClick={() => setTab('standards')}>标准列表</button>
            <button type="button" role="tab" aria-selected={tab === 'samples'} onClick={() => setTab('samples')}>数据预览</button>
          </div>
          <div className="standard-curve-table" role="tabpanel" aria-label={tab === 'standards' ? '标准列表' : '数据预览'}>
            {tab === 'standards' ? <>
              <p>分析谱线：{label}　拟合方式：{fitModes[workspace.fit_mode]}{logarithmic && '　对数坐标'}</p>
              <table><thead><tr>{['序号', '测量强度', '修正强度', '标准含量', '校正含量', '相对误差%', '拟合'].map((label) => <th key={label}>{label}</th>)}</tr></thead>
                <tbody>{points.map((item) => {
                  const row = diagnostics?.points.find((entry) => entry.point_index === item.point_index)
                  const digits = item.standard_value < 1 ? 6 : 3
                  return <tr key={item.point_index} className={selectedPoint === item.point_index ? 'selected' : undefined}
                    onClick={() => setSelectedPoint(item.point_index)}>
                    <td><button type="button" aria-label={`选择标准点 ${item.name}`}>{pointNumber(item.point_index)}</button></td>
                    <td>{displayNumber(item.original_intensity, 3)}</td><td>{displayNumber(item.adjusted_intensity, 3)}</td>
                    <td>{displayNumber(item.standard_value, digits)}</td><td>{displayNumber(row?.calculated_value, digits)}</td>
                    <td>{displayNumber(row?.relative_error_percent, 2)}</td><td>{item.active ? '是' : '否'}</td>
                  </tr>
                })}</tbody>
              </table>
              <p>相关系数 = {displayNumber(diagnostics?.correlation, 6)}</p>
              <p>标准样品分析结果</p>
              {samplePreview.filter((item) => item.management_sample).map((item, index) =>
                <p key={index}>{item.sample_name}　{displayNumber(item.calculated_value, 6)}</p>)}
            </> : <>
              <table><thead><tr><th>样品号</th><th>分析值 ({line.unit})</th><th>强度值</th></tr></thead>
                <tbody>{samplePreview.map((item, index) => <tr key={index}>
                  <td>{item.sample_name}</td><td>{displayNumber(item.calculated_value, line.decimal_places ?? 3)}</td>
                  <td>{displayNumber(item.intensity, 3)}</td></tr>)}</tbody>
              </table>
              {!samplePreview.length && <p>{currentFit ? '当前快照没有试样预览数据' : '拟合后显示试样分析值'}</p>}
            </>}
          </div>
        </section>

        <div className="standard-curve-plot" ref={chartHost}>
          <output className="standard-curve-reading">
            <span>序号：{point ? pointNumber(point.point_index) : '—'}</span>
            <span>标准含量：{displayNumber(point?.standard_value, 5)}</span>
            <span>测量强度：{displayNumber(point?.original_intensity, 3)}</span>
            <span>修正强度：{displayNumber(point?.adjusted_intensity, 3)}</span>
          </output>
          <CurveChart snapshot={fitForChart} lineLabel={label} unit={line.unit} points={points}
            logarithmic={logarithmic} legacy={legacy} selectedPoint={selectedPoint} onSelectPoint={setSelectedPoint}
            onPointContext={(event, index) => { setSelectedPoint(index); menu.open(event, index) }} />
        </div>
      </div>

      <div className="standard-curve-footer">
        <label><input type="checkbox" checked={logarithmic} disabled={!canEdit} onChange={(event) =>
          adjust({ action: 'set_coordinate', coordinate_type: event.target.checked ? 'logarithmic' : 'normal', reason: '切换坐标方式' }, '坐标方式已保存')} />对数坐标</label>
        <button type="button" disabled={!canNudge} aria-label="上移标准点" title="Ctrl＋↑" onClick={() => nudge(1)}><ArrowUp size={14} /></button>
        <button type="button" disabled={!canNudge} aria-label="下移标准点" title="Ctrl＋↓" onClick={() => nudge(-1)}><ArrowDown size={14} /></button>
        {footer}
        <span className="standard-curve-status" role="status">{!currentFit ? (shownSnapshot ? '标准点或条件已改变，请重新拟合' : '待拟合') : status}</span>
        <span>{calculationProfileLabel(profile)}</span>
      </div>
    </div>
  )
}

