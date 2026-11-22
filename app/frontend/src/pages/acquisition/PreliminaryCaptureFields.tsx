import { NumericInput } from '../../components/NumericInput'
import type { PreliminaryConditions } from '../../api/system'

export type PreliminaryCaptureProps = {
  kind: 'dispersion' | 'evaporation'
  conditions: PreliminaryConditions
  onCondition: <K extends keyof PreliminaryConditions>(key: K, value: PreliminaryConditions[K]) => void
  name: string
  onName: (name: string) => void
  saveConditions: boolean
  onSaveConditions: (save: boolean) => void
  disabled: boolean
}

export function PreliminaryCaptureFields(props: PreliminaryCaptureProps) {
  const title = props.kind === 'dispersion' ? '色散曲线' : '蒸发曲线'
  return <div className="preliminary-capture-fields">
    <p className="preliminary-caption">设定{title}摄谱工作条件</p>
    <div className="preliminary-condition-grid">
      <label className="field preliminary-pre"><span>预激时间（秒）</span>
        <NumericInput min={1} max={10} step={0.1} value={props.conditions.pre_excitation_seconds} disabled={props.disabled}
          onValueChange={value => props.onCondition('pre_excitation_seconds', value)} /></label>
      <label className="field preliminary-period"><span>采样周期（秒）</span>
        <NumericInput min={1} max={2} step={0.01} value={props.conditions.sampling_period_seconds} disabled={props.disabled}
          onValueChange={value => props.onCondition('sampling_period_seconds', value)} /></label>
      <label className="field preliminary-count"><span>采样次数</span>
        <NumericInput min={1} max={255} value={props.conditions.frame_count} disabled={props.disabled}
          onValueChange={value => props.onCondition('frame_count', value)} /></label>
      <label className="field preliminary-dark"><span>空白次数</span>
        <NumericInput min={0} max={20} value={props.conditions.dark_frame_count} disabled={props.disabled}
          onValueChange={value => props.onCondition('dark_frame_count', value)} /></label>
      <label className="checkbox-row preliminary-save"><input type="checkbox" checked={props.saveConditions}
        disabled={props.disabled} onChange={event => props.onSaveConditions(event.target.checked)} /><span>保存激发条件</span></label>
    </div>
    <label className="field preliminary-name"><span>{title}名</span>
      <input required maxLength={120} value={props.name} disabled={props.disabled} onChange={event => props.onName(event.target.value)} /></label>
  </div>
}
