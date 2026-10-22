import { AdvancedSettings } from '../../components/AdvancedSettings'
import { CheckCircle2, CircleX, Clock3, Info, Plus, Save, SlidersHorizontal, Trash2 } from 'lucide-react'
import {
  type LineDetectability,
  type SpectralLine,
  type SpectralLineInput,
  type SpectralLineOptions
} from '../../api'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'
import { NumberField } from './NumberField'
import { AnalysisUnitSelect } from '../../components/AnalysisUnitSelect'
import { convertLineUnit, decimalLimit, unitScale } from '../../components/analysisUnits'
import { lineTypeLabel } from './spectralLineDraft'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  exposureEnabled: boolean
  frameCount: number
  listCollapsed: boolean
  setListCollapsed: React.Dispatch<React.SetStateAction<boolean>>
  creating: boolean
  selected: SpectralLine | null
  isBaseline: boolean
  canWrite: boolean
  move: (line: SpectralLine, offset: number) => void
  busy: boolean
  movable: SpectralLine[]
  toggle: (line: SpectralLine) => void
  remove: (line: SpectralLine) => void
  draft: SpectralLineInput
  setLineType: (lineType: SpectralLineInput["line_type"]) => void
  updateDraft: <K extends keyof SpectralLineInput>(key: K, value: SpectralLineInput[K]) => void
  options: SpectralLineOptions | null
  setDraft: React.Dispatch<React.SetStateAction<SpectralLineInput>>
  detectability: LineDetectability | null
  backgroundLines: SpectralLine[]
  alignmentLines: SpectralLine[]
  internalLines: SpectralLine[]
  save: () => Promise<void>
}

export function SpectralLineEditor({
  exposureEnabled,
  frameCount,
  listCollapsed,
  setListCollapsed,
  creating,
  selected,
  isBaseline,
  canWrite,
  move,
  busy,
  movable,
  toggle,
  remove,
  draft,
  setLineType,
  updateDraft,
  options,
  setDraft,
  detectability,
  backgroundLines,
  alignmentLines,
  internalLines,
  save,
}: PanelProps) {
  return (
    <section className="surface spectral-editor-surface">
      <div className="surface-heading">
        <button
          className="secondary-button spectral-list-toggle"
          aria-controls="method-spectral-list"
          aria-expanded={!listCollapsed}
          onClick={() => setListCollapsed(!listCollapsed)}
        >
          <SlidersHorizontal size={14} />
          {listCollapsed ? '展开谱线清单' : '收起清单'}
        </button>
        <div>
          <h2>
            {creating
              ? '添加谱线'
              : selected
                ? `${selected.element} ${selected.wavelength_nm.toFixed(4)} nm`
                : '选择谱线'}
          </h2>
        </div>
        {selected && !isBaseline && canWrite && (
          <div className="line-toolbar">
            <button
              className="icon-button compact"
              title="上移"
              onClick={() => move(selected, -1)}
              disabled={busy || movable[0]?.id === selected.id}
            >
              ↑
            </button>
            <button
              className="icon-button compact"
              title="下移"
              onClick={() => move(selected, 1)}
              disabled={busy || movable[movable.length - 1]?.id === selected.id}
            >
              ↓
            </button>
            <button
              className="icon-button compact"
              title={selected.enabled ? '停用' : '启用'}
              onClick={() => toggle(selected)}
              disabled={busy}
            >
              {selected.enabled ? '●' : '○'}
            </button>
            <button
              className="icon-button compact danger"
              title="删除"
              onClick={() => remove(selected)}
              disabled={busy}
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>
      {!selected && !creating ? (
        <div className="method-empty compact">
          <SlidersHorizontal size={25} />
          <p>选择一条谱线查看完整参数。</p>
        </div>
      ) : (
        <>
          {isBaseline && (
            <div className="baseline-notice">
              <Info size={16} />
              <span>参考基线全方法唯一，波长、实际波长、线宽和单位由“方法条件”维护。</span>
            </div>
          )}
          <div className="spectral-form-grid">
            {!isBaseline && <section className="spectral-exposure-block" aria-label="谱线曝光区间">
              <h3>谱线曝光区间</h3>
              <p className="method-exposure-help">{exposureEnabled
                ? `当前为区间曝光：分别设置每条谱线使用的帧，范围为1–${frameCount}，至少连续两帧。未单独指定时使用完整采集区间。`
                : '当前为简单均值：逐线曝光区间不参与计算。请先在方法参数中开启“区间曝光”并保存方法。'}</p>
              <label className="field"><span>曝光起始帧</span>
                <EmptyableNumberInput min="1" max={frameCount} value={draft.exposure_start_frame ?? 1}
                  disabled={!canWrite || busy || !exposureEnabled} onValueChange={(value) => setDraft((previous) => ({
                    ...previous, exposure_start_frame: value, exposure_end_frame: previous.exposure_end_frame ?? frameCount
                  }))} />
              </label>
              <label className="field"><span>曝光结束帧</span>
                <EmptyableNumberInput min="1" max={frameCount} value={draft.exposure_end_frame ?? frameCount}
                  disabled={!canWrite || busy || !exposureEnabled} onValueChange={(value) => setDraft((previous) => ({
                    ...previous, exposure_start_frame: previous.exposure_start_frame ?? 1, exposure_end_frame: value
                  }))} />
              </label>
            </section>}
            <label className="field">
              <span>谱线类型</span>
              <select
                value={draft.line_type}
                onChange={(event) => setLineType(event.target.value as SpectralLineInput['line_type'])}
                disabled={!canWrite || isBaseline}
              >
                <option value="analysis">分析线</option>
                <option value="internal_standard">内标线</option>
                <option value="positioning">定位线</option>
                {isBaseline && <option value="baseline">参考基线</option>}
              </select>
            </label>
            <label className="field">
              <span>元素</span>
              <select
                value={draft.element}
                onChange={(event) => updateDraft('element', event.target.value)}
                disabled={!canWrite || isBaseline}
              >
                {options?.element_symbols.map((element) => (
                  <option key={element}>{element}</option>
                ))}
              </select>
            </label>
            <NumberField
              label="理论波长 (nm)"
              value={draft.wavelength_nm}
              min={160}
              max={800}
              step={0.0001}
              disabled={!canWrite || isBaseline}
              onChange={(value) =>
                setDraft((previous) => ({
                  ...previous,
                  wavelength_nm: value,
                  actual_wavelength_nm:
                    previous.actual_wavelength_nm === previous.wavelength_nm ? value : previous.actual_wavelength_nm
                }))
              }
            />
            <NumberField
              label="实际波长 (nm)"
              value={draft.actual_wavelength_nm ?? draft.wavelength_nm}
              min={160}
              max={800}
              step={0.0001}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('actual_wavelength_nm', value)}
            />
          </div>
          <div
            className={`detectability-card ${detectability == null ? 'checking' : detectability.detectable ? 'detectable' : 'undetectable'}`}
          >
            <span className="detect-icon">
              {detectability?.detectable ? (
                <CheckCircle2 size={18} />
              ) : detectability ? (
                <CircleX size={18} />
              ) : (
                <Clock3 size={18} />
              )}
            </span>
            <div>
              <strong>
                {detectability?.detectable
                  ? '当前条件可检测'
                  : detectability
                    ? '当前条件不可检测'
                    : '正在检查检测条件'}
              </strong>
              <span>
                {detectability?.detectable
                  ? `${detectability.ccd_label} · 点位 ${detectability.point_index} · 角度位 ${detectability.angle_slot}${detectability.angle_deg == null ? '' : ` (${detectability.angle_deg}°)`}`
                  : (detectability?.message ?? '正在计算 CCD 落点…')}
              </span>
            </div>
            <code>{detectability?.reason_code ?? 'checking'}</code>
          </div>
          <div className="spectral-toggle-grid">
            <label>
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) => updateDraft('enabled', event.target.checked)}
                disabled={!canWrite || isBaseline}
              />
              <span>
                <strong>启用谱线</strong>
                <small>停用后不参与后续分析</small>
              </span>
            </label>
            <label>
              <input
                type="checkbox"
                checked={draft.critical_band}
                onChange={(event) => updateDraft('critical_band', event.target.checked)}
                disabled={!canWrite || isBaseline}
              />
              <span>
                <strong>关键波段</strong>
                <small>随方法版本固化</small>
              </span>
            </label>
          </div>

          <div className="spectral-section-title">
            <strong>内标与定位</strong>
          </div>
          <div className="spectral-form-grid">
            <label className="field">
              <span>定位谱线</span>
              <select
                value={draft.alignment_line_id ?? ''}
                onChange={(event) => updateDraft('alignment_line_id', event.target.value || null)}
                disabled={!canWrite || isBaseline}
              >
                <option value="">参考线定位</option>
                {alignmentLines.map((line) => (
                  <option key={line.id} value={line.id}>
                    {lineTypeLabel[line.line_type]} · {line.element} {line.wavelength_nm.toFixed(4)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>内标谱线</span>
              <select
                value={draft.internal_standard_mode === 'line' ? `line:${draft.internal_standard_line_id ?? ''}` : draft.internal_standard_mode}
                onChange={(event) => {
                  const value = event.target.value
                  setDraft((previous) => ({
                    ...previous,
                    internal_standard_mode: value.startsWith('line:') ? 'line' : value as 'none' | 'background',
                    internal_standard_line_id: value.startsWith('line:') ? value.slice(5) || null : null,
                    background_line_id: value === 'background'
                      ? previous.background_line_id ?? backgroundLines[0]?.id ?? null
                      : previous.background_line_id
                  }))
                }}
                disabled={!canWrite || isBaseline || draft.line_type !== 'analysis'}
              >
                <option value="none">无内标</option>
                <option value="background">背景做内标</option>
                {draft.internal_standard_mode === 'line' && !internalLines.some((line) => line.id === draft.internal_standard_line_id) &&
                  <option value={`line:${draft.internal_standard_line_id ?? ''}`} disabled>原内标谱线（当前不可用）</option>}
                {internalLines.map((line) => <option key={line.id} value={`line:${line.id}`}>
                  {line.element} {line.wavelength_nm.toFixed(4)}
                </option>)}
              </select>
            </label>
          </div>

          <div className="spectral-section-title">
            <strong>峰值、拟合与结果规则</strong>
          </div>
          <div className="spectral-form-grid dense">
            <NumberField
              label="扫描点数"
              value={draft.scan_width_points}
              min={5}
              max={31}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('scan_width_points', value)}
            />
            <NumberField
              label="背景位置"
              value={draft.background_offset_points}
              min={-100}
              max={100}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('background_offset_points', value)}
            />
            <label className="field">
              <span>峰值方式</span>
              <select
                value={draft.peak_mode}
                onChange={(event) =>
                  setDraft((previous) => ({
                    ...previous,
                    peak_mode: event.target.value as SpectralLineInput['peak_mode'],
                    peak_width_points:
                      event.target.value === 'max_single_point' ? 1 : Math.max(3, previous.peak_width_points | 1)
                  }))
                }
                disabled={!canWrite || isBaseline}
              >
                <option value="max_single_point">最大值</option>
                <option value="gaussian">高斯曲线</option>
              </select>
            </label>
            <NumberField
              label="计算点数"
              value={draft.peak_width_points}
              min={1}
              max={9}
              step={draft.peak_mode === 'gaussian' ? 2 : 1}
              disabled={!canWrite || isBaseline || draft.peak_mode === 'max_single_point'}
              onChange={(value) => updateDraft('peak_width_points', value)}
            />
            <label className="field">
              <span>拟合方式</span>
              <select
                value={draft.fit_mode}
                onChange={(event) => updateDraft('fit_mode', event.target.value as SpectralLineInput['fit_mode'])}
                disabled={!canWrite || isBaseline}
              >
                <option value="linear">直线函数</option>
                <option value="quadratic">二次曲线</option>
                <option value="cubic">三次曲线</option>
                <option value="spline">样条函数</option>
              </select>
            </label>
            <label className="toggle-row compact-toggle">
              <input type="checkbox" checked={draft.coordinate_type === 'logarithmic'}
                onChange={(event) => updateDraft('coordinate_type', event.target.checked ? 'logarithmic' : 'normal')}
                disabled={!canWrite || isBaseline} />
              <strong>对数坐标</strong>
            </label>
            <AnalysisUnitSelect label="单位" value={draft.unit} disabled={!canWrite || isBaseline}
              onChange={(unit) => setDraft((previous) => convertLineUnit(previous, unit))} />
            <NumberField
              label="小数位数"
              value={draft.decimal_places}
              min={0}
              max={decimalLimit(draft.unit)}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('decimal_places', value)}
            />
            <NumberField
              label="最低峰值"
              value={draft.lower_peak}
              min={100}
              max={600}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('lower_peak', value)}
            />
            <NumberField
              label="最小倍数"
              value={draft.minimum_peak_ratio}
              min={1.1}
              max={2.5}
              step={0.1}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('minimum_peak_ratio', value)}
            />
          </div>

          <AdvancedSettings title="高级谱线参数">
            <div className="advanced-field-grid">
              <NumberField
              label="优先级"
              value={draft.priority}
              min={0}
              max={100}
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('priority', value)}
            />
              <NumberField
              label="有效下限"
              value={draft.valid_range_min}
              min={0}
              max={9999999}
              step="any"
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('valid_range_min', value)}
            />
              <NumberField
              label="有效上限"
              value={draft.valid_range_max}
              min={0}
              max={9999999}
              step="any"
              disabled={!canWrite || isBaseline}
              onChange={(value) => updateDraft('valid_range_max', value)}
            />
            </div>
          </AdvancedSettings>

          {draft.line_type === 'analysis' && (
            <>
              <div className="spectral-section-title">
                <strong>
                  标准点 <i>{draft.standard_points.length}/50</i>
                </strong>
                {canWrite && (
                  <button
                    className="secondary-button compact"
                    onClick={() =>
                      updateDraft('standard_points', [
                        ...draft.standard_points,
                        {
                          name: `S${draft.standard_points.length + 1}`,
                          value: draft.standard_points.length + 1,
                          active: true
                        }
                      ])
                    }
                    disabled={isBaseline || draft.standard_points.length >= 50}
                  >
                    <Plus size={14} />
                    添加
                  </button>
                )}
              </div>
              <div className="standard-points-wrap">
                <table className="standard-points-table">
                  <thead>
                    <tr>
                      <th>启用</th>
                      <th>名称</th>
                      <th>含量 / 浓度 ({draft.unit})</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.standard_points.map((point, index) => (
                      <tr key={index}>
                        <td>
                          <input
                            type="checkbox"
                            checked={point.active}
                            onChange={(event) =>
                              updateDraft(
                                'standard_points',
                                draft.standard_points.map((item, itemIndex) =>
                                  itemIndex === index ? { ...item, active: event.target.checked } : item
                                )
                              )
                            }
                            disabled={!canWrite || isBaseline}
                          />
                        </td>
                        <td>
                          <input
                            value={point.name}
                            maxLength={50}
                            onChange={(event) =>
                              updateDraft(
                                'standard_points',
                                draft.standard_points.map((item, itemIndex) =>
                                  itemIndex === index ? { ...item, name: event.target.value } : item
                                )
                              )
                            }
                            disabled={!canWrite || isBaseline}
                          />
                        </td>
                        <td>
                          <EmptyableNumberInput
                            min={9.9e-7 / unitScale(draft.unit)}
                            max="9999999"
                            step="any"
                            value={point.value}
                            onValueChange={(value) =>
                              updateDraft(
                                'standard_points',
                                draft.standard_points.map((item, itemIndex) =>
                                  itemIndex === index ? { ...item, value } : item
                                )
                              )
                            }
                            disabled={!canWrite || isBaseline}
                          />
                        </td>
                        <td>
                          <button
                            className="icon-button compact danger"
                            title="删除标准点"
                            onClick={() =>
                              updateDraft(
                                'standard_points',
                                draft.standard_points.filter((_, itemIndex) => itemIndex !== index)
                              )
                            }
                            disabled={!canWrite || isBaseline || draft.standard_points.length <= 4}
                          >
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {canWrite && !isBaseline && (
            <div className="spectral-savebar">
              <span>确认谱线后，点击顶部“保存”使方法修改生效。</span>
              <button className="primary-button" onClick={save} disabled={busy || !detectability?.detectable}>
                <Save size={15} />
                {creating ? '添加谱线' : '保存谱线'}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
