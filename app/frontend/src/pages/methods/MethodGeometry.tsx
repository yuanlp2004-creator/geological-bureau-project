import { AnalysisUnitSelect } from '../../components/AnalysisUnitSelect'
import {
  Database
} from 'lucide-react'
import {
  api,
  type MethodConditions,
  type MethodOptions
} from '../../api'
import { useEffect, useId, useState } from 'react'
import type { CcdLayoutOption, DispersionOption } from '../../api/methods'
import { NumericInput as EmptyableNumberInput } from '../../components/NumericInput'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  token: string
  hasIssue: (field: string) => boolean
  currentLayout: CcdLayoutOption | undefined
  changeCalibration: (calibrationId: number) => void
  canWrite: boolean
  options: MethodOptions | null
  currentCalibration: DispersionOption | undefined
  setCondition: <K extends keyof MethodConditions>(key: K, value: MethodConditions[K]) => void
  conditions: MethodConditions
}

export function MethodGeometry({
  token,
  hasIssue,
  currentLayout,
  changeCalibration,
  canWrite,
  options,
  currentCalibration,
  setCondition,
  conditions,
}: PanelProps) {
  const [offset, setOffset] = useState<{ wavelength_delta_nm: number; point_delta: number } | null>(null)
  const offsetLabelId = useId()
  useEffect(() => {
    let cancelled = false
    setOffset(null)
    void api.referenceOffset(token, conditions).then((value) => { if (!cancelled) setOffset(value) })
      .catch(() => { if (!cancelled) setOffset(null) })
    return () => { cancelled = true }
  }, [token, conditions])
  return (
    <section
      className={`surface method-section method-geometry ${hasIssue('selected_ccds') || hasIssue('reference_wavelength_nm') || hasIssue('actual_reference_wavelength_nm') ? 'has-errors' : ''}`}
    >
      <div className="surface-heading">
        <div>
          <h2>谱板参数</h2>
        </div>
        <Database size={17} />
      </div>
      <div className="method-field-grid">
        <label className="field span-2">
          <span>色散曲线</span>
          <select
            aria-label="色散曲线"
            value={currentCalibration?.ccd_layout_id === currentLayout?.id && conditions.selected_ccds.length
              ? String(currentCalibration?.id ?? '') : ''}
            onChange={(event) => changeCalibration(Number(event.target.value))}
            disabled={!canWrite}
          >
            <option value="" disabled>请选择色散曲线</option>
            {options?.dispersion_calibrations.map((calibration) => (
              <option key={calibration.id} value={calibration.id}>
                {calibration.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>基线波长 (nm)</span>
          <EmptyableNumberInput
            step={conditions.calculation_profile === 'legacy_2_0_2' ? 'any' : '0.0001'}
            value={conditions.reference_wavelength_nm}
            onValueChange={(value) => setCondition('reference_wavelength_nm', value)}
            disabled={!canWrite}
          />
        </label>
        <label className="field">
          <span>实际基线波长 (nm)</span>
          <EmptyableNumberInput
            step={conditions.calculation_profile === 'legacy_2_0_2' ? 'any' : '0.0001'}
            value={conditions.actual_reference_wavelength_nm}
            onValueChange={(value) => setCondition('actual_reference_wavelength_nm', value)}
            disabled={!canWrite}
          />
        </label>
        <label className="field">
          <span>扫描宽度</span>
          <EmptyableNumberInput
            min="11"
            max="50"
            value={conditions.reference_width_points}
            onValueChange={(value) => setCondition('reference_width_points', value)}
            disabled={!canWrite}
          />
        </label>
        <div className="field">
          <span id={offsetLabelId}>基线偏移</span>
          <div className="field-with-action reference-offset-control">
            <output aria-labelledby={offsetLabelId}>
              {offset ? `${offset.wavelength_delta_nm.toFixed(4)} nm (${offset.point_delta} 点)` : '波长超出有效 CCD 范围'}
            </output>
            <button type="button" className="secondary-button" disabled={!canWrite}
              onClick={() => setCondition('actual_reference_wavelength_nm', conditions.reference_wavelength_nm)}>偏移清零</button>
          </div>
        </div>
        <AnalysisUnitSelect label="分析单位" value={conditions.analysis_unit}
          onChange={(unit) => setCondition('analysis_unit', unit)} disabled={!canWrite} />
      </div>
    </section>
  )
}
